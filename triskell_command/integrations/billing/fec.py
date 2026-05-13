"""Export FEC (Fichier des Écritures Comptables).

DESTINATION FINALE :
    Triskell\\triskell-command\\triskell_command\\integrations\\billing\\fec.py

Format légal DGFiP (BOI-CF-IOR-60-40-20). Texte UTF-8 avec BOM, séparateur
pipe `|`, fin de ligne CRLF, 18 colonnes obligatoires.

Pour une micro-entreprise en franchise de TVA, l'export reste obligatoire
en cas de contrôle si on tient une compta. Mieux vaut être prêt dès le
premier euro encaissé. Si la DGFiP ne le demande jamais, c'est un fichier
en plus dans les archives.

Conventions :
- JournalCode = "VTE" pour les ventes (factures et avoirs).
- CompteNum   = "411xxxx" client (411 + 4 chiffres dérivés de l'ID client)
              = "706000"  produit (prestations de services)
              = "445660"  TVA collectée (si applicable)
- Pour chaque facture, on émet 1 écriture (EcritureNum = invoice_number)
  avec N lignes : 1 débit client TTC + 1 crédit produit HT + (si TVA)
  1 crédit TVA collectée.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Iterable

from . import repo

logger = logging.getLogger(__name__)

# Colonnes obligatoires FEC (ordre figé par le BOI)
FEC_HEADERS = [
    "JournalCode", "JournalLib", "EcritureNum", "EcritureDate",
    "CompteNum", "CompteLib", "CompAuxNum", "CompAuxLib",
    "PieceRef", "PieceDate", "EcritureLib", "Debit", "Credit",
    "EcritureLet", "DateLet", "ValidDate", "Montantdevise", "Idevise",
]

ACCOUNT_CLIENT_DEFAULT = "411000"   # Clients - compte général
ACCOUNT_REVENUE = "706000"           # Prestations de services
ACCOUNT_VAT_COLLECTED = "445660"     # TVA collectée


def _fmt_amount(cents: int) -> str:
    """Montant en euros avec virgule, 2 décimales, pas de signe."""
    cents = abs(int(cents or 0))
    return f"{cents // 100},{cents % 100:02d}"


def _fmt_date_yyyymmdd(s: str) -> str:
    """ISO → YYYYMMDD."""
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%Y%m%d")
    except Exception:
        return s.replace("-", "")[:8]


def _client_account(invoice: dict) -> tuple[str, str]:
    """Renvoie (CompAuxNum, CompAuxLib) pour la facture."""
    snap = invoice.get("client_snapshot") or {}
    name = (snap.get("name") or "").strip() or "Client"
    # Un compte auxiliaire stable par client_id si dispo, sinon dérivé du SIRET ou de l'email
    client_id = invoice.get("client_id") or ""
    if client_id:
        suffix = client_id.replace("-", "")[:8].upper()
    else:
        suffix = (snap.get("siret") or snap.get("email") or name)[:8].upper().replace("@", "")
    aux_num = f"411{suffix}"
    return aux_num, name[:60]


def _rows_for_invoice(invoice: dict) -> Iterable[list[str]]:
    """Émet les lignes FEC pour une facture (3 lignes typiquement)."""
    is_credit = invoice.get("is_credit_note", False)
    sign = -1 if is_credit else 1

    issued = _fmt_date_yyyymmdd(invoice.get("issued_at", ""))
    eclib = ("Avoir " if is_credit else "Facture ") + (
        (invoice.get("client_snapshot") or {}).get("name", "")
    )
    piece_ref = invoice.get("invoice_number", "")
    aux_num, aux_lib = _client_account(invoice)

    ttc = sign * int(invoice.get("total_ttc_cents") or 0)
    ht = sign * int(invoice.get("subtotal_ht_cents") or 0)
    vat = sign * int(invoice.get("total_vat_cents") or 0)

    # En FEC, on note Debit OU Credit (l'autre = "0,00"). Pour une vente :
    #   Client (411) : Debit TTC
    #   Produit (706): Credit HT
    #   TVA (44566)  : Credit TVA
    # Pour un avoir, on inverse.
    base = {
        "JournalCode": "VTE",
        "JournalLib": "Journal des ventes",
        "EcritureNum": piece_ref,
        "EcritureDate": issued,
        "PieceRef": piece_ref,
        "PieceDate": issued,
        "EcritureLib": eclib[:200],
        "EcritureLet": "",
        "DateLet": "",
        "ValidDate": issued,
        "Montantdevise": "",
        "Idevise": "",
    }

    def _line(account_num: str, account_lib: str, debit: int, credit: int,
              comp_aux_num: str = "", comp_aux_lib: str = "") -> list[str]:
        row = dict(base)
        row.update({
            "CompteNum": account_num,
            "CompteLib": account_lib,
            "CompAuxNum": comp_aux_num,
            "CompAuxLib": comp_aux_lib,
            "Debit": _fmt_amount(debit if debit > 0 else 0),
            "Credit": _fmt_amount(credit if credit > 0 else 0),
        })
        return [row[h] for h in FEC_HEADERS]

    # Pour un avoir (sign=-1), TTC/HT/VAT sont négatifs. On inverse Debit/Credit.
    if ttc >= 0:
        yield _line(ACCOUNT_CLIENT_DEFAULT, "Clients", debit=ttc, credit=0,
                    comp_aux_num=aux_num, comp_aux_lib=aux_lib)
        yield _line(ACCOUNT_REVENUE, "Prestations de services", debit=0, credit=ht)
        if vat > 0:
            yield _line(ACCOUNT_VAT_COLLECTED, "TVA collectée", debit=0, credit=vat)
    else:
        # Avoir : on annule l'écriture initiale
        yield _line(ACCOUNT_CLIENT_DEFAULT, "Clients", debit=0, credit=-ttc,
                    comp_aux_num=aux_num, comp_aux_lib=aux_lib)
        yield _line(ACCOUNT_REVENUE, "Prestations de services", debit=-ht, credit=0)
        if vat < 0:
            yield _line(ACCOUNT_VAT_COLLECTED, "TVA collectée", debit=-vat, credit=0)


def export(year: int) -> bytes:
    """Renvoie le contenu FEC pour une année, en bytes UTF-8 (avec BOM)."""
    invoices = repo.list_invoices_for_fec(year)
    if not invoices:
        logger.info("FEC %s : aucune facture trouvée.", year)

    buf = io.StringIO()
    buf.write("|".join(FEC_HEADERS) + "\r\n")
    for inv in invoices:
        for row in _rows_for_invoice(inv):
            # Sécurité : pas de pipe dans les libellés (sinon casse le format)
            safe = [str(c).replace("|", "/").replace("\r", " ").replace("\n", " ")
                    for c in row]
            buf.write("|".join(safe) + "\r\n")

    # UTF-8 BOM : la DGFiP accepte avec ou sans, on met avec.
    return "﻿".encode("utf-8") + buf.getvalue().encode("utf-8")
