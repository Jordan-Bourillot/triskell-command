"""Pont entre les paiements Stripe (abonnement Triskell Command) et la
facturation maison Triskell.

À chaque évènement `invoice.payment_succeeded` reçu de Stripe (paiement
initial OU prélèvement mensuel récurrent), on émet une facture FR conforme
via le module `billing/`, on l'archive, et on l'envoie au workspace par
email avec le PDF en pièce jointe.

L'opération est :
- idempotente : si Stripe rejoue le webhook, on ne re-facture pas
  (clé d'idempotence = id de la facture Stripe `in_XXX`).
- non bloquante : une erreur de facturation ne fait pas échouer le
  webhook (la subscription passe quand même `active`).
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Point d'entrée appelé depuis le webhook
# ---------------------------------------------------------------------------
def emit_from_stripe_invoice(stripe_invoice: dict[str, Any]) -> dict[str, Any]:
    """Émet la facture Triskell + envoie au workspace par mail.

    `stripe_invoice` est l'objet `invoice` reçu dans le webhook
    `invoice.payment_succeeded`.

    Renvoie un dict {ok, idempotent, invoice_number?, error?} pour log.
    Ne lève jamais (toutes les exceptions sont capturées et loguées).
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

    # 1. Idempotence : Stripe peut rejouer le webhook plusieurs fois.
    #    On regarde si une facture Triskell existe déjà avec cette ref.
    existing = _find_existing(billing_repo, stripe_invoice_id)
    if existing:
        logger.info("Stripe invoice %s déjà facturée (Triskell %s) — skip",
                    stripe_invoice_id, existing.get("invoice_number"))
        return {"ok": True, "idempotent": True,
                "invoice_number": existing.get("invoice_number"),
                "invoice_id": existing.get("id")}

    # 2. Construit l'InvoiceRequest depuis l'objet Stripe
    try:
        request = _build_invoice_request(
            stripe_invoice, ClientInfo, InvoiceLine, InvoiceRequest,
        )
    except Exception as exc:
        logger.exception("Construction InvoiceRequest depuis Stripe a échoué")
        return {"ok": False, "error": f"build_request: {exc}"}

    # 3. Émet la facture via le provider maison
    try:
        result = get_provider().generate_invoice(request)
    except Exception as exc:
        logger.exception("generate_invoice a échoué pour Stripe %s",
                         stripe_invoice_id)
        return {"ok": False, "error": f"generate: {exc}"}

    logger.info("Facture Triskell %s émise pour Stripe %s",
                result.invoice_number, stripe_invoice_id)

    # 4. Envoie la facture au workspace par mail (best-effort, non bloquant)
    try:
        _send_invoice_email(
            to_email=request.client.email,
            to_name=request.client.name,
            invoice_number=result.invoice_number,
            total_ttc_cents=result.total_ttc_cents,
            subscription_period=request.subscription_period or "",
            pdf_bytes=result.pdf_bytes,
        )
    except Exception as exc:
        logger.warning("Envoi mail facture %s a échoué : %s",
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
    """Mappe l'objet Stripe `invoice` vers une InvoiceRequest Triskell."""
    # ---- Client ----------------------------------------------------------
    addr = stripe_invoice.get("customer_address") or {}
    tax_ids = stripe_invoice.get("customer_tax_ids") or []
    tva_intra = ""
    siret = ""
    for tid in tax_ids:
        tid_type = (tid.get("type") or "").lower()
        tid_value = tid.get("value") or ""
        if "vat" in tid_type:
            tva_intra = tid_value
        elif "fr_siret" in tid_type or "siret" in tid_type:
            siret = tid_value

    client = ClientInfo(
        name=stripe_invoice.get("customer_name") or "Client",
        email=stripe_invoice.get("customer_email") or "",
        address_line1=addr.get("line1") or "",
        address_line2=addr.get("line2") or "",
        address_zip=addr.get("postal_code") or "",
        address_city=addr.get("city") or "",
        address_country=addr.get("country") or "France",
        siret=siret,
        tva_intra=tva_intra,
    )

    # ---- Lignes ----------------------------------------------------------
    # On reprend les line_items Stripe (chacun = 1 module d'abonnement).
    # Triskell est en franchise TVA 293 B → vat_rate=0 pour toutes les lignes.
    lines: list = []
    stripe_lines = ((stripe_invoice.get("lines") or {}).get("data") or [])

    period_label = _period_label(stripe_invoice)

    for sline in stripe_lines:
        description = sline.get("description") or "Abonnement Triskell Command"
        if period_label and period_label not in description:
            description = f"{description} — {period_label}"
        # On utilise amount (centimes, signé) plutôt que unit_amount
        # pour gérer remises et proratas.
        quantity = sline.get("quantity") or 1
        amount_cents = int(sline.get("amount") or 0)
        if quantity <= 0:
            quantity = 1
        unit_price_ht = int(round(amount_cents / quantity))
        lines.append(InvoiceLine(
            description=description,
            quantity=float(quantity),
            unit_price_ht_cents=unit_price_ht,
            vat_rate=0.0,
        ))

    # Fallback si Stripe n'a pas listé de lignes (cas rare)
    if not lines:
        total = int(stripe_invoice.get("amount_paid")
                    or stripe_invoice.get("total") or 0)
        lines.append(InvoiceLine(
            description=f"Abonnement Triskell Command — {period_label}".strip(" —"),
            quantity=1.0,
            unit_price_ht_cents=total,
            vat_rate=0.0,
        ))

    # ---- Paiement --------------------------------------------------------
    paid_at = _ts_to_dt(stripe_invoice.get("status_transitions", {})
                        .get("paid_at")) or datetime.now(timezone.utc)

    return InvoiceRequest(
        client=client,
        lines=lines,
        payment_method="stripe",
        payment_reference=stripe_invoice.get("id") or "",
        paid_at=paid_at,
        is_subscription=True,
        subscription_period=period_label or None,
        free_text_top=f"Référence Stripe : {stripe_invoice.get('number') or stripe_invoice.get('id')}",
    )


def _period_label(stripe_invoice: dict) -> str:
    """Renvoie 'YYYY-MM' à partir de la période couverte par la facture
    Stripe, ou chaîne vide si introuvable."""
    period_start = stripe_invoice.get("period_start")
    if not period_start:
        # Cherche dans la première ligne
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
# Idempotence
# ---------------------------------------------------------------------------
def _find_existing(billing_repo, payment_reference: str) -> Optional[dict]:
    """Renvoie la facture déjà émise avec ce stripe_invoice_id, ou None."""
    if not payment_reference:
        return None
    sb = billing_repo._sb() if hasattr(billing_repo, "_sb") else None
    if sb is None:
        # Tente l'autre nom (service_sb dans certaines versions)
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


# ---------------------------------------------------------------------------
# Envoi mail avec PDF en pièce jointe
# ---------------------------------------------------------------------------
def _send_invoice_email(*, to_email: str, to_name: str,
                        invoice_number: str, total_ttc_cents: int,
                        subscription_period: str,
                        pdf_bytes: bytes) -> None:
    """Envoie la facture par email avec le PDF attaché.

    Utilise la config SMTP partagée (shared_secrets) — la même que les
    autres flows (post_sale, drip, etc.).
    """
    if not to_email:
        raise RuntimeError("Pas d'email destinataire sur la facture.")

    smtp_cfg = _resolve_smtp()
    if not smtp_cfg:
        raise RuntimeError("Config SMTP Triskell incomplète.")

    total_eur = total_ttc_cents / 100
    period_human = _period_human(subscription_period)
    first_name = (to_name or "").split(" ")[0] or "Bonjour"

    body_text = (
        f"Bonjour {first_name},\n\n"
        f"Voici votre facture {invoice_number} pour votre abonnement "
        f"Triskell Command — {period_human}.\n\n"
        f"Montant prélevé : {total_eur:.2f} €\n\n"
        f"La facture est en pièce jointe (PDF).\n\n"
        f"Pour toute question sur votre abonnement ou votre facturation, "
        f"répondez simplement à cet email.\n\n"
        f"À très vite,\n"
        f"Jordan — Triskell Studio\n"
        f"https://triskell-studio.fr"
    )

    body_html = f"""\
<!doctype html>
<html><body style="font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; color:#222; max-width:600px;">
<p>Bonjour {first_name},</p>
<p>Voici votre facture <strong>{invoice_number}</strong> pour votre abonnement
<strong>Triskell Command — {period_human}</strong>.</p>
<p>Montant prélevé : <strong>{total_eur:.2f} €</strong></p>
<p>La facture est en pièce jointe (PDF).</p>
<p>Pour toute question sur votre abonnement ou votre facturation,
répondez simplement à cet email.</p>
<p>À très vite,<br>
Jordan — Triskell Studio<br>
<a href="https://triskell-studio.fr">triskell-studio.fr</a></p>
</body></html>"""

    msg = EmailMessage()
    from_name = smtp_cfg.get("from_name") or "Triskell Studio"
    from_email = smtp_cfg["from_email"]
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = f"Votre facture Triskell Command {invoice_number} — {period_human}"
    msg["Date"] = formatdate(localtime=True)
    domain = from_email.split("@", 1)[1] if "@" in from_email else "triskell-studio.fr"
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["Reply-To"] = from_email

    msg.set_content(body_text)
    msg.add_alternative(body_html, subtype="html")

    pdf_filename = f"{invoice_number}.pdf"
    if pdf_bytes:
        msg.add_attachment(
            pdf_bytes,
            maintype="application",
            subtype="pdf",
            filename=pdf_filename,
        )

    _smtp_send(msg, smtp_cfg)


def _period_human(period: str) -> str:
    """'2026-05' → 'mai 2026'."""
    if not period or len(period) < 7:
        return period or ""
    try:
        year = int(period[:4])
        month = int(period[5:7])
    except Exception:
        return period
    months = ["janvier", "février", "mars", "avril", "mai", "juin",
             "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    if 1 <= month <= 12:
        return f"{months[month-1]} {year}"
    return period


def _resolve_smtp() -> Optional[dict]:
    """Tente de récupérer la config SMTP Triskell via shared_secrets.
    Fallback : variables d'environnement classiques."""
    try:
        from .. import shared_secrets
        cfg = shared_secrets.resolve_smtp_for_send()
        if cfg:
            return cfg
    except Exception as exc:
        logger.debug("shared_secrets indispo : %s", exc)

    # Fallback env
    import os
    host = os.environ.get("SMTP_HOST", "")
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    from_email = os.environ.get("SMTP_FROM_EMAIL", "")
    if not (host and user and password and from_email):
        return None
    return {
        "smtp_host": host,
        "smtp_port": int(os.environ.get("SMTP_PORT") or 587),
        "smtp_user": user,
        "smtp_password": password,
        "from_email": from_email,
        "from_name": os.environ.get("SMTP_FROM_NAME") or "Triskell Studio",
    }


def _smtp_send(msg: EmailMessage, cfg: dict) -> None:
    """Envoie via SSL/STARTTLS selon le port."""
    host = cfg["smtp_host"]
    port = int(cfg.get("smtp_port") or 587)
    user = cfg["smtp_user"]
    password = cfg["smtp_password"]

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo()
            try:
                s.starttls(context=context)
                s.ehlo()
            except smtplib.SMTPException:
                pass  # serveur sans STARTTLS — rare mais possible en interne
            s.login(user, password)
            s.send_message(msg)
