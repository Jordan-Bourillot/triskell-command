"""Implémentation maison de la facturation Triskell.

DESTINATION FINALE :
    Triskell\\triskell-command\\triskell_command\\integrations\\billing\\triskell_native.py

Seule implémentation en service. Toute la logique métier vit ici :
réservation du numéro, calcul des totaux, snapshots figés, rendu PDF,
upload Storage, archivage immuable.

Aucun autre module hors `billing/` ne doit importer ce fichier
directement. Passer par `billing.get_provider()`.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from . import numbering, pdf_renderer, repo
from .interface import (
    BillingProvider, ClientInfo, InvoiceLine, InvoiceRequest, InvoiceResult,
)

logger = logging.getLogger(__name__)

DEFAULT_INVOICE_SERIES = "FA"
DEFAULT_CREDIT_NOTE_SERIES = "AV"


class BillingError(RuntimeError):
    """Erreur métier facturation (manque de config, conflit, etc.)."""


# =====================================================================
# Helpers
# =====================================================================
def _issuer_snapshot_from_config(config: dict) -> dict:
    """Snapshot émetteur figé. Fallback sur les infos Jordan si la config
    Supabase est manquante (mais on log un warning : la migration 10
    aurait dû seed ces valeurs).
    """
    issuer = config.get("issuer") or {}
    if not issuer or not issuer.get("siret"):
        logger.warning("billing_config.issuer manquant — fallback hardcodé. "
                       "Vérifier que la migration 10_billing.sql a bien été exécutée.")
        issuer = {
            "name": "Triskell Studio",
            "legal_form": "Micro-entreprise",
            "siret": "99166857500012",
            "address_line1": "3 rue du Tertre Vert",
            "address_zip": "22190",
            "address_city": "Plérin",
            "address_country": "France",
            "email": "contact@triskell-studio.fr",
            "tva_intra": "",
            "vat_regime": "franchise_293b",
            "vat_exempt_reason": "TVA non applicable, article 293 B du CGI",
        }
    return dict(issuer)


def _compute_totals(lines: list[InvoiceLine]) -> tuple[int, int, int]:
    sub = sum(line.total_ht_cents for line in lines)
    vat = sum(line.total_vat_cents for line in lines)
    return sub, vat, sub + vat


def _resolve_vat_exempt_reason(lines: list[InvoiceLine], issuer: dict) -> str:
    """Si toutes les lignes sont à TVA 0% et que l'émetteur est en
    franchise, on appose la mention art. 293 B.
    """
    if any(line.vat_rate > 0 for line in lines):
        return ""
    return issuer.get("vat_exempt_reason") or ""


# =====================================================================
# Provider
# =====================================================================
class TriskellNativeProvider(BillingProvider):

    def generate_invoice(self, request: InvoiceRequest) -> InvoiceResult:
        config = repo.get_config()
        issuer = _issuer_snapshot_from_config(config)
        series = config.get("invoice_series") or DEFAULT_INVOICE_SERIES
        return self._emit(request, config=config, issuer=issuer,
                          series=series, is_credit_note=False,
                          cancels_invoice_id=None,
                          credit_note_reason="")

    def generate_credit_note(self, invoice_id: str, reason: str) -> InvoiceResult:
        original = repo.get_invoice(invoice_id)
        if not original:
            raise BillingError(f"Facture {invoice_id} introuvable.")
        if original.get("is_credit_note"):
            raise BillingError("Impossible d'émettre un avoir sur un avoir.")
        if original.get("is_cancelled"):
            raise BillingError("Facture déjà annulée.")

        config = repo.get_config()
        issuer = config.get("issuer") or _issuer_snapshot_from_config(config)
        series = config.get("credit_note_series") or DEFAULT_CREDIT_NOTE_SERIES

        # Reconstruction de la requête en négatif depuis le snapshot original
        client_snap = original["client_snapshot"]
        client = ClientInfo(**{
            k: v for k, v in client_snap.items()
            if k in ClientInfo.__dataclass_fields__
        })

        negative_lines = [
            InvoiceLine(
                description=f"Avoir : {l['description']}",
                quantity=l["quantity"],
                unit_price_ht_cents=-int(l["unit_price_ht_cents"]),
                vat_rate=float(l.get("vat_rate", 0.0)),
            )
            for l in original.get("lines", [])
        ]

        request = InvoiceRequest(
            client=client,
            lines=negative_lines,
            payment_method=original.get("payment_method") or "manuel",
            payment_reference=original.get("payment_reference") or "",
            paid_at=datetime.now(timezone.utc),
            service_executed_at=date.today(),
            deal_id=original.get("deal_id"),
            client_id=original.get("client_id"),
            free_text_top=f"Avoir établi en annulation de la facture {original['invoice_number']}.",
        )

        result = self._emit(request, config=config, issuer=issuer,
                            series=series, is_credit_note=True,
                            cancels_invoice_id=invoice_id,
                            credit_note_reason=reason or "Annulation")

        # Marquer la facture originale comme annulée
        repo.update_invoice(invoice_id, {
            "is_cancelled": True,
            "cancellation_reason": reason or f"Annulée par avoir {result.invoice_number}",
        })
        return result

    def get_invoice(self, invoice_id: str) -> Optional[dict]:
        return repo.get_invoice(invoice_id)

    def get_invoice_pdf_url(self, invoice_id: str, *, signed_ttl_seconds: int = 3600) -> str:
        inv = repo.get_invoice(invoice_id)
        if not inv or not inv.get("pdf_path"):
            return ""
        return repo.get_invoice_pdf_signed_url(inv["pdf_path"],
                                                ttl_seconds=signed_ttl_seconds)

    def list_invoices(
        self,
        *,
        client_id: Optional[str] = None,
        client_email: Optional[str] = None,
        year: Optional[int] = None,
        limit: int = 100,
    ) -> list[dict]:
        return repo.list_invoices(client_id=client_id, client_email=client_email,
                                  year=year, limit=limit)

    def export_fec(self, year: int) -> bytes:
        from . import fec
        return fec.export(year)

    # -----------------------------------------------------------------
    # Cœur : émission d'une facture (ou avoir)
    # -----------------------------------------------------------------
    def _emit(
        self,
        request: InvoiceRequest,
        *,
        config: dict,
        issuer: dict,
        series: str,
        is_credit_note: bool,
        cancels_invoice_id: Optional[str],
        credit_note_reason: str,
    ) -> InvoiceResult:
        # 1. Validation amont
        if not request.client.email:
            raise BillingError("Email client requis pour facturer.")
        if not request.lines:
            raise BillingError("Au moins une ligne requise.")

        # 2. Réservation atomique du numéro
        year = numbering.current_year()
        invoice_number = numbering.reserve_number(series, year)
        _, _, sequence = numbering.parse_number(invoice_number)

        # 3. Calcul totaux
        subtotal_ht, total_vat, total_ttc = _compute_totals(request.lines)
        vat_exempt_reason = _resolve_vat_exempt_reason(request.lines, issuer)

        # 4. Dates
        now = datetime.now(timezone.utc)
        issued_at = now
        service_executed_at = request.service_executed_at or now.date()
        if request.due_date:
            due_date = request.due_date
        elif request.paid_at:
            due_date = service_executed_at
        else:
            due_date = service_executed_at + timedelta(days=int(config.get("default_due_days", 30)))

        # 5. Insert ligne invoices
        row = {
            "invoice_number": invoice_number,
            "series": series,
            "year": year,
            "sequence": sequence,
            "deal_id": request.deal_id,
            "client_id": request.client_id,
            "client_snapshot": request.client.to_dict(),
            "issuer_snapshot": issuer,
            "lines": [l.to_dict() for l in request.lines],
            "subtotal_ht_cents": subtotal_ht,
            "total_vat_cents": total_vat,
            "total_ttc_cents": total_ttc,
            "currency": "EUR",
            "vat_exempt_reason": vat_exempt_reason,
            "payment_method": request.payment_method,
            "payment_reference": request.payment_reference or "",
            "paid_at": request.paid_at.isoformat() if request.paid_at else None,
            "due_date": due_date.isoformat(),
            "issued_at": issued_at.isoformat(),
            "service_executed_at": service_executed_at.isoformat(),
            "is_credit_note": is_credit_note,
            "cancels_invoice_id": cancels_invoice_id,
            "credit_note_reason": credit_note_reason,
        }
        inserted = repo.insert_invoice(row)
        if not inserted:
            raise BillingError(
                f"Échec insertion facture {invoice_number}. "
                "ATTENTION : le numéro a été consommé mais la ligne est manquante — "
                "créer une ligne 'annulée par erreur' pour ne pas laisser de trou."
            )

        # 6. Rendu PDF
        # On enrichit la ligne avec un champ pratique pour le template
        invoice_for_template = dict(inserted)
        invoice_for_template["free_text_top"] = request.free_text_top
        invoice_for_template["free_text_bottom"] = request.free_text_bottom

        cancels_number = ""
        if cancels_invoice_id:
            original = repo.get_invoice(cancels_invoice_id)
            cancels_number = (original or {}).get("invoice_number", "")

        pdf_bytes, sha256 = pdf_renderer.render_invoice_pdf(
            invoice=invoice_for_template,
            issuer=issuer,
            client=request.client.to_dict(),
            config=config,
            cancels_invoice_number=cancels_number,
        )

        # 7. Upload Storage
        try:
            pdf_path = repo.upload_invoice_pdf(invoice_number, year, pdf_bytes)
        except Exception as exc:
            # Le numéro est consommé, la ligne existe, mais le PDF n'est pas
            # archivé. On lève — Jordan doit savoir et retenter manuellement.
            raise BillingError(
                f"Facture {invoice_number} créée mais upload PDF échoué : {exc}"
            ) from exc

        # 8. Patch invoice avec pdf_path + sha
        repo.update_invoice(inserted["id"], {
            "pdf_path": pdf_path,
            "pdf_sha256": sha256,
        })

        # 9. Archive immuable
        archived_row = {**inserted, "pdf_path": pdf_path, "pdf_sha256": sha256}
        repo.archive_invoice(archived_row, pdf_sha256=sha256)

        # 10. URL signée pour l'appelant
        signed_url = ""
        try:
            signed_url = repo.get_invoice_pdf_signed_url(pdf_path, ttl_seconds=3600)
        except Exception as exc:
            logger.warning("URL signée indisponible (PDF présent dans Storage) : %s", exc)

        return InvoiceResult(
            invoice_id=inserted["id"],
            invoice_number=invoice_number,
            pdf_url=signed_url,
            pdf_bytes=pdf_bytes,
            pdf_sha256=sha256,
            issued_at=issued_at,
            subtotal_ht_cents=subtotal_ht,
            total_vat_cents=total_vat,
            total_ttc_cents=total_ttc,
        )
