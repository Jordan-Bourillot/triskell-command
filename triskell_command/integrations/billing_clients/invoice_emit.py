"""Pont entre les paiements Stripe d'un client final et la facturation maison.

À chaque évènement `invoice.payment_succeeded` reçu de Stripe AVEC une
metadata `client_subscription_id` (= abonnement d'un client de Triskell,
pas du SaaS Command), on émet une facture FR conforme via le module
`billing/`, on l'archive, et on l'envoie au client par email avec le
PDF en pièce jointe.

L'opération est :
- idempotente : si Stripe rejoue le webhook, on ne re-facture pas
  (clé d'idempotence = id de la facture Stripe `in_XXX`).
- non bloquante : une erreur n'empêche pas la mise à jour de status.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Point d'entrée appelé depuis le webhook
# ---------------------------------------------------------------------------
def emit_from_stripe_invoice(stripe_invoice: dict[str, Any]) -> dict[str, Any]:
    """Émet la facture Triskell + envoie au client par mail.

    `stripe_invoice` est l'objet `invoice` reçu dans le webhook
    `invoice.payment_succeeded`.

    Renvoie un dict {ok, idempotent, invoice_number?, error?} pour log.
    Ne lève jamais.
    """
    try:
        from triskell_command.integrations.billing import (
            ClientInfo, InvoiceLine, InvoiceRequest, get_provider,
        )
        from triskell_command.integrations.billing import repo as billing_repo
    except Exception as exc:
        logger.warning("billing module indisponible : %s", exc)
        return {"ok": False, "error": f"billing import: {exc}"}

    stripe_invoice_id = stripe_invoice.get("id") or ""
    if not stripe_invoice_id:
        return {"ok": False, "error": "stripe invoice sans id"}

    # 1. Idempotence
    existing = _find_existing(billing_repo, stripe_invoice_id)
    if existing:
        logger.info("Stripe invoice %s déjà facturée (Triskell %s) — skip",
                    stripe_invoice_id, existing.get("invoice_number"))
        _update_subscription_last_invoice(stripe_invoice, existing)
        return {"ok": True, "idempotent": True,
                "invoice_number": existing.get("invoice_number"),
                "invoice_id": existing.get("id")}

    # 2. Construit l'InvoiceRequest depuis Stripe + DB
    try:
        request, client_subscription_id = _build_invoice_request(
            stripe_invoice, ClientInfo, InvoiceLine, InvoiceRequest,
        )
    except Exception as exc:
        logger.exception("Construction InvoiceRequest depuis Stripe a échoué")
        return {"ok": False, "error": f"build_request: {exc}"}

    # 3. Émission
    try:
        result = get_provider().generate_invoice(request)
    except Exception as exc:
        logger.exception("generate_invoice a échoué pour Stripe %s",
                         stripe_invoice_id)
        return {"ok": False, "error": f"generate: {exc}"}

    logger.info("Facture client Triskell %s émise pour Stripe %s (sub %s)",
                result.invoice_number, stripe_invoice_id,
                client_subscription_id)

    # 4. Met à jour client_subscriptions (last_invoice_id, last_invoice_at)
    _patch_subscription(client_subscription_id, {
        "last_invoice_id": result.invoice_id,
        "last_invoice_at": datetime.now(timezone.utc).isoformat(),
    })

    # 5. Mail au client (best-effort)
    try:
        # Réutilise l'envoi SMTP de billing_saas (même config, même style)
        from ..billing_saas.invoice_emit import _send_invoice_email
        _send_invoice_email(
            to_email=request.client.email,
            to_name=request.client.name,
            invoice_number=result.invoice_number,
            total_ttc_cents=result.total_ttc_cents,
            subscription_period=request.subscription_period or "",
            pdf_bytes=result.pdf_bytes,
        )
    except Exception as exc:
        logger.warning("Envoi mail facture client %s a échoué : %s",
                       result.invoice_number, exc)
        return {"ok": True, "idempotent": False,
                "invoice_number": result.invoice_number,
                "invoice_id": result.invoice_id,
                "mail_error": str(exc)}

    return {"ok": True, "idempotent": False,
            "invoice_number": result.invoice_number,
            "invoice_id": result.invoice_id}


# ---------------------------------------------------------------------------
# Construction de l'InvoiceRequest
# ---------------------------------------------------------------------------
def _build_invoice_request(stripe_invoice: dict, ClientInfo, InvoiceLine,
                            InvoiceRequest):
    """Renvoie (InvoiceRequest, client_subscription_id)."""
    # ---- Sous-quel client_subscription ? --------------------------------
    metadata = _gather_metadata(stripe_invoice)
    client_subscription_id = metadata.get("client_subscription_id") or ""
    client_id = metadata.get("client_id") or ""

    # ---- Description côté facture ---------------------------------------
    # On préfère la description stockée côté DB (= ce que Jordan a saisi
    # à la création de l'abonnement) plutôt que celle générée par Stripe.
    description = "Abonnement mensuel"
    sub_row = _get_subscription_row(client_subscription_id)
    if sub_row:
        description = sub_row.get("description") or description
        if not client_id:
            client_id = sub_row.get("client_id") or ""

    # ---- Client : on préfère la fiche Triskell (à jour) -----------------
    client_row = _get_client_row(client_id) if client_id else None
    if client_row:
        client = ClientInfo(
            name=_full_name(client_row),
            email=client_row.get("email") or "",
            address_line1=client_row.get("address_line1") or "",
            address_line2=client_row.get("address_line2") or "",
            address_zip=client_row.get("address_zip") or "",
            address_city=client_row.get("address_city") or "",
            address_country=client_row.get("address_country") or "France",
            siret=client_row.get("siret") or "",
            tva_intra=client_row.get("vat_number") or "",
        )
    else:
        # Fallback : on prend ce que Stripe a (billing_address au checkout)
        addr = stripe_invoice.get("customer_address") or {}
        client = ClientInfo(
            name=stripe_invoice.get("customer_name") or "Client",
            email=stripe_invoice.get("customer_email") or "",
            address_line1=addr.get("line1") or "",
            address_line2=addr.get("line2") or "",
            address_zip=addr.get("postal_code") or "",
            address_city=addr.get("city") or "",
            address_country=addr.get("country") or "France",
        )

    # ---- Lignes ---------------------------------------------------------
    period_label = _period_label(stripe_invoice)
    lines: list = []
    stripe_lines = ((stripe_invoice.get("lines") or {}).get("data") or [])
    for sline in stripe_lines:
        line_desc = description
        if period_label and period_label not in line_desc:
            line_desc = f"{line_desc} — {period_label}"
        quantity = sline.get("quantity") or 1
        amount_cents = int(sline.get("amount") or 0)
        if quantity <= 0:
            quantity = 1
        unit_price = int(round(amount_cents / quantity))
        lines.append(InvoiceLine(
            description=line_desc,
            quantity=float(quantity),
            unit_price_ht_cents=unit_price,
            vat_rate=0.0,  # franchise TVA art. 293 B
        ))
    if not lines:
        total = int(stripe_invoice.get("amount_paid")
                    or stripe_invoice.get("total") or 0)
        lines.append(InvoiceLine(
            description=f"{description} — {period_label}".strip(" —"),
            quantity=1.0,
            unit_price_ht_cents=total,
            vat_rate=0.0,
        ))

    paid_at = _ts_to_dt((stripe_invoice.get("status_transitions") or {})
                        .get("paid_at")) or datetime.now(timezone.utc)

    request = InvoiceRequest(
        client=client,
        lines=lines,
        payment_method="stripe",
        payment_reference=stripe_invoice.get("id") or "",
        paid_at=paid_at,
        client_id=client_id or None,
        is_subscription=True,
        subscription_period=period_label or None,
        free_text_top=f"Référence Stripe : {stripe_invoice.get('number') or stripe_invoice.get('id')}",
    )
    return request, client_subscription_id


def _gather_metadata(stripe_invoice: dict) -> dict:
    """Cherche client_id / client_subscription_id dans plusieurs endroits
    de l'objet Stripe (invoice, subscription nested, lines)."""
    metadata = dict(stripe_invoice.get("metadata") or {})
    sub = stripe_invoice.get("subscription_details") or {}
    if isinstance(sub.get("metadata"), dict):
        for k, v in sub["metadata"].items():
            metadata.setdefault(k, v)
    # Fallback : 1ère ligne
    sline = (((stripe_invoice.get("lines") or {}).get("data") or [{}])[0])
    line_meta = sline.get("metadata") or {}
    for k, v in line_meta.items():
        metadata.setdefault(k, v)
    return metadata


def _full_name(client_row: dict) -> str:
    parts = []
    fn = (client_row.get("first_name") or "").strip()
    ln = (client_row.get("last_name") or "").strip()
    if fn or ln:
        parts.append(" ".join(filter(None, [fn, ln])).strip())
    cn = (client_row.get("company_name") or "").strip()
    if cn:
        # Si on a une personne ET une boite, on facture à la boîte
        # avec la personne en libellé (cas typique B2B).
        return cn
    if parts:
        return parts[0]
    return "Client"


def _period_label(stripe_invoice: dict) -> str:
    """Renvoie 'YYYY-MM' à partir de la période couverte par la facture."""
    period_start = stripe_invoice.get("period_start")
    if not period_start:
        sline = (((stripe_invoice.get("lines") or {}).get("data") or [{}])[0])
        period_start = (sline.get("period") or {}).get("start")
    if not period_start:
        return datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        dt = datetime.fromtimestamp(int(period_start), tz=timezone.utc)
        return dt.strftime("%Y-%m")
    except Exception:
        return ""


def _ts_to_dt(ts) -> Optional[datetime]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers Supabase
# ---------------------------------------------------------------------------
def _sb():
    try:
        from ..billing import repo as billing_repo
        return billing_repo._sb()
    except Exception:
        return None


def _get_subscription_row(client_subscription_id: str) -> Optional[dict]:
    if not client_subscription_id:
        return None
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("client_subscriptions").select("*")
                .eq("id", client_subscription_id).limit(1).execute().data) or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.debug("_get_subscription_row: %s", exc)
        return None


def _get_client_row(client_id: str) -> Optional[dict]:
    if not client_id:
        return None
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("clients").select("*")
                .eq("id", client_id).limit(1).execute().data) or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.debug("_get_client_row: %s", exc)
        return None


def _patch_subscription(client_subscription_id: str, patch: dict) -> None:
    if not client_subscription_id:
        return
    sb = _sb()
    if sb is None:
        return
    try:
        sb.table("client_subscriptions").update(patch).eq(
            "id", client_subscription_id
        ).execute()
    except Exception as exc:
        logger.debug("_patch_subscription: %s", exc)


def _update_subscription_last_invoice(stripe_invoice: dict,
                                       existing_triskell_invoice: dict) -> None:
    """Met à jour la ligne subscription même en cas d'idempotence
    (au cas où le mois précédent n'a pas eu son patch)."""
    metadata = _gather_metadata(stripe_invoice)
    sid = metadata.get("client_subscription_id") or ""
    if not sid:
        return
    _patch_subscription(sid, {
        "last_invoice_id": existing_triskell_invoice.get("id"),
        "last_invoice_at": existing_triskell_invoice.get("issued_at"),
    })


def _find_existing(billing_repo, payment_reference: str) -> Optional[dict]:
    if not payment_reference:
        return None
    sb = billing_repo._sb() if hasattr(billing_repo, "_sb") else None
    if sb is None:
        sb = (billing_repo._service_sb()
              if hasattr(billing_repo, "_service_sb") else None)
    if sb is None:
        return None
    try:
        rows = (sb.table("invoices").select("*")
                .eq("payment_reference", payment_reference)
                .eq("is_credit_note", False)
                .limit(1).execute().data) or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.debug("_find_existing: %s", exc)
        return None
