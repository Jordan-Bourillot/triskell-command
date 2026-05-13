"""Rendu PDF des factures (WeasyPrint).

DESTINATION FINALE :
    Triskell\\triskell-command\\triskell_command\\integrations\\billing\\pdf_renderer.py

Charge le template Jinja2 `templates/invoice.html` et le rend en PDF via
WeasyPrint. Si WeasyPrint n'est pas dispo sur la machine, lève une
exception explicite — pas de fallback silencieux (une facture sans PDF
n'a aucune valeur légale).

Helpers de formatage centralisés ici : montants en euros (FR), dates,
taux TVA, etc.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


# ---------------------------------------------------------------------------
# Formatage FR
# ---------------------------------------------------------------------------
_MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin",
              "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def fmt_money(cents: int) -> str:
    """123456 → "1 234,56 €" (négatifs préservés pour les avoirs)."""
    if cents is None:
        return "—"
    negative = cents < 0
    cents = abs(int(cents))
    euros, c = divmod(cents, 100)
    # séparateur de milliers : espace insécable (NBSP)
    euros_str = f"{euros:,}".replace(",", " ")
    sign = "-" if negative else ""
    return f"{sign}{euros_str},{c:02d} €"


def fmt_date(d: Any) -> str:
    """date | datetime | str ISO → "12 mai 2026"."""
    if d is None:
        return "—"
    if isinstance(d, str):
        try:
            d = datetime.fromisoformat(d.replace("Z", "+00:00"))
        except ValueError:
            try:
                d = date.fromisoformat(d)
            except ValueError:
                return d
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.day} {_MONTHS_FR[d.month - 1]} {d.year}"


def fmt_qty(q: float) -> str:
    """Quantité : entier sans virgule, sinon 2 décimales."""
    if q == int(q):
        return str(int(q))
    return f"{q:.2f}".replace(".", ",")


def fmt_vat_rate(rate: float) -> str:
    """0.20 → "20 %" ; 0.0 → "—"."""
    if not rate:
        return "—"
    pct = round(rate * 100, 2)
    if pct == int(pct):
        return f"{int(pct)} %"
    return f"{pct:.2f}".replace(".", ",") + " %"


_PAYMENT_LABELS = {
    "stripe": "carte bancaire (Stripe)",
    "carte": "carte bancaire",
    "sepa": "virement SEPA",
    "virement": "virement bancaire",
    "manuel": "paiement manuel",
    "espece": "espèces",
    "cheque": "chèque",
}


def payment_label(method: str) -> str:
    return _PAYMENT_LABELS.get((method or "").lower(), method or "—")


# ---------------------------------------------------------------------------
# Rendu
# ---------------------------------------------------------------------------
def render_html(
    invoice: dict,
    issuer: dict,
    client: dict,
    config: dict,
    *,
    cancels_invoice_number: str = "",
) -> str:
    """Rend le HTML final via Jinja2. `invoice` est la ligne DB (avec
    `lines` déjà déserialisé en liste de dicts). `issuer`, `client`,
    `config` sont les snapshots / config courante.
    """
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except ImportError as exc:
        raise RuntimeError(
            "Jinja2 requis pour le rendu de facture. "
            "Installer avec : pip install jinja2"
        ) from exc

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("invoice.html")

    doc_title = "AVOIR" if invoice.get("is_credit_note") else "FACTURE"

    return template.render(
        invoice=invoice,
        issuer=issuer,
        client=client,
        config=config,
        doc_title=doc_title,
        cancels_invoice_number=cancels_invoice_number,
        payment_label=payment_label(invoice.get("payment_method", "")),
        fmt_money=fmt_money,
        fmt_date=fmt_date,
        fmt_qty=fmt_qty,
        fmt_vat_rate=fmt_vat_rate,
    )


def html_to_pdf(html: str) -> bytes:
    """HTML → bytes PDF. WeasyPrint obligatoire."""
    try:
        from weasyprint import HTML
    except ImportError as exc:
        raise RuntimeError(
            "WeasyPrint requis pour la génération PDF. "
            "Installer avec : pip install weasyprint "
            "(Windows : prévoir aussi GTK runtime, voir doc WeasyPrint)."
        ) from exc

    return HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf()


def render_invoice_pdf(
    invoice: dict,
    issuer: dict,
    client: dict,
    config: dict,
    *,
    cancels_invoice_number: str = "",
) -> tuple[bytes, str]:
    """Renvoie (pdf_bytes, sha256_hex). Pas de side-effect."""
    html = render_html(invoice, issuer, client, config,
                       cancels_invoice_number=cancels_invoice_number)
    pdf_bytes = html_to_pdf(html)
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    return pdf_bytes, sha
