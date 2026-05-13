"""Numérotation atomique des factures.

DESTINATION FINALE :
    Triskell\\triskell-command\\triskell_command\\integrations\\billing\\numbering.py

Délègue tout le boulot à la fonction Postgres `reserve_invoice_number(p_series, p_year)`
définie dans la migration `10_billing.sql`. Le verrou pessimiste DB-side garantit
qu'aucun trou ni doublon n'est possible, même sous concurrence.

Si on a besoin d'un jour de plusieurs séries (FA, AV, et plus tard
"AC" pour acomptes par exemple), on les passe simplement en paramètre.
"""
from __future__ import annotations

import logging
from datetime import date

from . import repo

logger = logging.getLogger(__name__)


class InvoiceNumberingError(RuntimeError):
    """Levée si la réservation du numéro échoue."""


def reserve_number(series: str, year: int) -> str:
    """Renvoie le prochain numéro formaté ("FA-2026-0042").

    Implementation : appel RPC vers la fonction Postgres
    `reserve_invoice_number`. Atomique.
    """
    sb = repo._sb()
    if sb is None:
        raise InvoiceNumberingError(
            "Supabase non connecté — impossible de réserver un numéro de facture."
        )
    try:
        resp = sb.rpc("reserve_invoice_number",
                      {"p_series": series, "p_year": year}).execute()
    except Exception as exc:
        raise InvoiceNumberingError(
            f"Échec RPC reserve_invoice_number({series}, {year}) : {exc}"
        ) from exc

    number = resp.data if not isinstance(resp.data, list) else (resp.data[0] if resp.data else None)
    if not number or not isinstance(number, str):
        raise InvoiceNumberingError(
            f"Réponse inattendue de reserve_invoice_number : {resp.data!r}"
        )
    return number


def parse_number(number: str) -> tuple[str, int, int]:
    """Découpe "FA-2026-0042" → ("FA", 2026, 42)."""
    parts = number.split("-")
    if len(parts) != 3:
        raise ValueError(f"Format de numéro invalide : {number}")
    return parts[0], int(parts[1]), int(parts[2])


def current_year() -> int:
    return date.today().year
