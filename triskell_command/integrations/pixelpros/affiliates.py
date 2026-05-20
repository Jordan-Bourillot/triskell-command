"""DAO Supabase pour le programme d'affiliation Pixel Pros.

Pattern aligné sur `repo.py` mais dédié aux tables `pp_affiliates`,
`pp_affiliate_clicks`, `pp_affiliate_sales`.

Workflow d'une vente attribuée à un affilié :
    pending     → la vente vient d'être enregistrée (cooldown 30 jours)
    available   → versable, sera incluse dans le prochain paiement
    paid        → versée à l'affilié
    cancelled   → remboursement Stripe, commission annulée

Lifecycle automatique :
- Insertion via `pp_mark_paid` (RPC côté DB) au moment du paiement Stripe.
- Passage pending → available : à exécuter par un cron mensuel
  (`promote_pending_sales`).
- Passage available → paid : déclenché manuellement par Jordan
  depuis l'UI Triskell Command (`mark_sales_paid`).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# On réutilise le même client Supabase que le repo principal pour profiter
# du même chargement de config + cache.
from .repo import _sb, TABLE as DRAFTS_TABLE  # noqa: E402

T_AFFILIATES = "pp_affiliates"
T_CLICKS     = "pp_affiliate_clicks"
T_SALES      = "pp_affiliate_sales"


# ---------------------------------------------------------------------------
# Affiliés — lecture
# ---------------------------------------------------------------------------
def list_affiliates(*, status: Optional[str] = None, limit: int = 100) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = (sb.table(T_AFFILIATES)
             .select("id,email,firstname,lastname,ref_code,payout_method,status,created_at,email_validated_at")
             .order("created_at", desc=True)
             .limit(limit))
        if status:
            q = q.eq("status", status)
        return q.execute().data or []
    except Exception as exc:
        logger.warning("affiliates.list_affiliates: %s", exc)
        return []


def get_affiliate(affiliate_id: str) -> Optional[dict]:
    """Détail d'un affilié (toutes les colonnes sauf login_token)."""
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table(T_AFFILIATES)
                .select("id,email,firstname,lastname,ref_code,payout_method,"
                        "iban,bic,account_holder,paypal_email,promotion_method,"
                        "status,email_validated_at,terms_accepted_at,"
                        "created_at,updated_at")
                .eq("id", affiliate_id).limit(1)
                .execute().data)
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("affiliates.get_affiliate: %s", exc)
        return None


def count_by_status() -> dict[str, int]:
    keys = ["active", "pending", "paused", "banned"]
    out = {k: 0 for k in keys}
    sb = _sb()
    if sb is None:
        return out
    try:
        for k in keys:
            r = (sb.table(T_AFFILIATES).select("id", count="exact", head=True)
                 .eq("status", k).execute())
            out[k] = int(getattr(r, "count", 0) or 0)
    except Exception as exc:
        logger.warning("affiliates.count_by_status: %s", exc)
    return out


def affiliate_stats(affiliate_id: str) -> dict:
    """Compteurs détaillés pour un affilié : clics + ventes par status + commissions."""
    sb = _sb()
    if sb is None:
        return {}
    out = {
        "clicks_total": 0,
        "sales_pending": 0,
        "sales_available": 0,
        "sales_paid": 0,
        "sales_cancelled": 0,
        "commission_pending_cents": 0,
        "commission_available_cents": 0,
        "commission_paid_cents": 0,
    }
    try:
        # Le ref_code est nécessaire pour compter les clics
        aff = get_affiliate(affiliate_id)
        if aff is None:
            return out
        rc = aff.get("ref_code") or ""

        if rc:
            r = (sb.table(T_CLICKS).select("id", count="exact", head=True)
                 .eq("ref_code", rc).execute())
            out["clicks_total"] = int(getattr(r, "count", 0) or 0)

        rows = (sb.table(T_SALES)
                .select("payout_status,commission_cents")
                .eq("affiliate_id", affiliate_id).execute().data) or []
        for row in rows:
            st = row.get("payout_status") or ""
            cents = int(row.get("commission_cents") or 0)
            if st in ("pending", "available", "paid", "cancelled"):
                out[f"sales_{st}"] = out.get(f"sales_{st}", 0) + 1
                out[f"commission_{st}_cents"] = out.get(f"commission_{st}_cents", 0) + cents
    except Exception as exc:
        logger.warning("affiliates.affiliate_stats: %s", exc)
    return out


# ---------------------------------------------------------------------------
# Affiliés — écriture (status, pause/ban)
# ---------------------------------------------------------------------------
def set_affiliate_status(affiliate_id: str, new_status: str) -> tuple[bool, str]:
    if new_status not in ("active", "paused", "banned"):
        return False, "Status invalide."
    sb = _sb()
    if sb is None:
        return False, "Supabase non configuré."
    try:
        sb.table(T_AFFILIATES).update({"status": new_status}).eq("id", affiliate_id).execute()
        return True, f"Status mis à {new_status}."
    except Exception as exc:
        logger.warning("affiliates.set_affiliate_status: %s", exc)
        return False, str(exc)


# ---------------------------------------------------------------------------
# Ventes — lecture
# ---------------------------------------------------------------------------
def list_sales(*, affiliate_id: Optional[str] = None,
               payout_status: Optional[str] = None,
               limit: int = 200) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = (sb.table(T_SALES).select("*").order("created_at", desc=True).limit(limit))
        if affiliate_id:
            q = q.eq("affiliate_id", affiliate_id)
        if payout_status:
            q = q.eq("payout_status", payout_status)
        return q.execute().data or []
    except Exception as exc:
        logger.warning("affiliates.list_sales: %s", exc)
        return []


def list_sales_with_affiliate(*, payout_status: Optional[str] = None,
                              limit: int = 200) -> list[dict]:
    """Liste des ventes enrichies des infos de l'affilié (jointure manuelle)."""
    sales = list_sales(payout_status=payout_status, limit=limit)
    if not sales:
        return []
    aff_ids = list({s.get("affiliate_id") for s in sales if s.get("affiliate_id")})
    sb = _sb()
    if sb is None:
        return sales
    try:
        rows = (sb.table(T_AFFILIATES)
                .select("id,email,firstname,lastname,ref_code,payout_method,iban,paypal_email,account_holder")
                .in_("id", aff_ids).execute().data) or []
        by_id = {r["id"]: r for r in rows}
        for s in sales:
            a = by_id.get(s.get("affiliate_id")) or {}
            s["_affiliate"] = a
        return sales
    except Exception as exc:
        logger.warning("affiliates.list_sales_with_affiliate: %s", exc)
        return sales


# ---------------------------------------------------------------------------
# Ventes — écriture (transitions de statut)
# ---------------------------------------------------------------------------
def promote_pending_sales(*, min_age_days: int = 30) -> int:
    """Passe en 'available' toutes les ventes 'pending' dont la vente a plus
    de `min_age_days` jours.

    À appeler depuis un cron mensuel (le 1er du mois par exemple).
    Renvoie le nombre de lignes mises à jour.
    """
    sb = _sb()
    if sb is None:
        return 0
    threshold = (datetime.now(timezone.utc) - timedelta(days=min_age_days)).isoformat()
    try:
        r = (sb.table(T_SALES)
             .update({"payout_status": "available",
                      "updated_at": datetime.now(timezone.utc).isoformat()})
             .eq("payout_status", "pending")
             .lt("created_at", threshold)
             .execute())
        return len(r.data or [])
    except Exception as exc:
        logger.warning("affiliates.promote_pending_sales: %s", exc)
        return 0


def mark_sales_paid(sale_ids: list[str], *, batch_ref: str = "") -> tuple[int, str]:
    """Marque des ventes comme payées. Retourne (nb_mises_à_jour, message)."""
    if not sale_ids:
        return 0, "Aucune vente sélectionnée."
    sb = _sb()
    if sb is None:
        return 0, "Supabase non configuré."
    now = datetime.now(timezone.utc).isoformat()
    patch: dict[str, Any] = {
        "payout_status": "paid",
        "paid_at": now,
        "updated_at": now,
    }
    if batch_ref:
        patch["paid_batch_ref"] = batch_ref
    try:
        r = sb.table(T_SALES).update(patch).in_("id", sale_ids).execute()
        n = len(r.data or [])
        return n, f"{n} vente(s) marquée(s) comme payée(s)."
    except Exception as exc:
        logger.warning("affiliates.mark_sales_paid: %s", exc)
        return 0, str(exc)


def cancel_sale(sale_id: str, *, reason: str = "") -> tuple[bool, str]:
    """Annule une commission (ex: remboursement Stripe)."""
    sb = _sb()
    if sb is None:
        return False, "Supabase non configuré."
    try:
        now = datetime.now(timezone.utc).isoformat()
        sb.table(T_SALES).update({
            "payout_status": "cancelled",
            "paid_batch_ref": reason or "cancelled",
            "updated_at": now,
        }).eq("id", sale_id).execute()
        return True, "Commission annulée."
    except Exception as exc:
        logger.warning("affiliates.cancel_sale: %s", exc)
        return False, str(exc)


# ---------------------------------------------------------------------------
# Préparation des paiements du mois
# ---------------------------------------------------------------------------
def prepare_monthly_payouts() -> list[dict]:
    """Pour chaque affilié ayant des commissions 'available', regroupe ses
    commissions et calcule le total à verser. Retourne une liste de payouts
    prêts à utiliser pour des virements groupés.

    AUTO-PROMOTION : avant de calculer, on promeut automatiquement en
    'available' toutes les commissions 'pending' de plus de 30 jours. Ça
    évite d'avoir besoin d'un cron mensuel séparé — le simple fait que
    Jordan ouvre son onglet "Affiliés" met les commissions à jour.

    Format de sortie (1 entrée par affilié) :
    {
      "affiliate_id", "firstname", "lastname", "email", "payout_method",
      "iban", "paypal_email", "account_holder",
      "total_cents", "sale_ids": [...]
    }
    """
    # Promotion automatique des commissions de plus de 30 jours
    try:
        promote_pending_sales(min_age_days=30)
    except Exception as exc:
        logger.warning("affiliates.prepare_monthly_payouts: promote auto a échoué : %s", exc)

    sales = list_sales(payout_status="available", limit=1000)
    if not sales:
        return []
    by_aff: dict[str, dict] = {}
    for s in sales:
        aid = s.get("affiliate_id")
        if not aid:
            continue
        b = by_aff.setdefault(aid, {"affiliate_id": aid, "total_cents": 0, "sale_ids": []})
        b["total_cents"] += int(s.get("commission_cents") or 0)
        b["sale_ids"].append(s["id"])

    # Enrichit avec les infos de l'affilié
    sb = _sb()
    if sb is None:
        return []
    try:
        rows = (sb.table(T_AFFILIATES)
                .select("id,email,firstname,lastname,payout_method,iban,bic,"
                        "account_holder,paypal_email")
                .in_("id", list(by_aff.keys())).execute().data) or []
        by_id = {r["id"]: r for r in rows}
    except Exception as exc:
        logger.warning("affiliates.prepare_monthly_payouts: %s", exc)
        return []

    out = []
    for aid, b in by_aff.items():
        a = by_id.get(aid) or {}
        # Seuil de 50 € : on saute les payouts trop petits
        if b["total_cents"] < 5000:
            continue
        b.update({
            "email": a.get("email"),
            "firstname": a.get("firstname"),
            "lastname": a.get("lastname"),
            "payout_method": a.get("payout_method"),
            "iban": a.get("iban"),
            "bic": a.get("bic"),
            "account_holder": a.get("account_holder"),
            "paypal_email": a.get("paypal_email"),
        })
        out.append(b)
    # Tri par montant décroissant
    out.sort(key=lambda x: -x["total_cents"])
    return out
