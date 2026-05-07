"""Morning Digest — agrégateur des KPIs et alertes de la veille.

Une seule fonction publique : compute_digest(). Elle frappe Supabase pour
agréger en O(1 ou 2 requêtes par bucket) :
  - envois J-1 / J / 7j
  - réponses entrantes J-1 / J par catégorie
  - drafts à valider (prospect + convoy)
  - réponses positives non traitées (file de travail prioritaire)
  - anomalies : campagnes Convoi avec drafts en `failed`

Pas d'IA, pas d'IMAP — c'est juste de la lecture cumulative. Très bon marché.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def _get_client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None
    try:
        client = get_client()
    except SupabaseNotConfigured:
        return None
    if not client.is_authenticated:
        return None
    return client


def _bounds(d: date) -> tuple[str, str]:
    start = datetime.combine(d, datetime.min.time()).isoformat()
    end = datetime.combine(d + timedelta(days=1), datetime.min.time()).isoformat()
    return start, end


def _count_history(client, kind: str, day_start: str, day_end: str) -> int:
    try:
        sb = client.raw
        res = (sb.table("email_history")
               .select("id", count="exact")
               .eq("kind", kind)
               .gte("ts", day_start)
               .lt("ts", day_end)
               .limit(1).execute())
        return int(res.count or 0)
    except Exception as exc:
        logger.debug("count_history(%s): %s", kind, exc)
        return 0


def _replies_breakdown(client, day_start: str, day_end: str) -> dict[str, int]:
    """Répartition des réponses J par catégorie. 1 requête, classification
    extraite côté Python."""
    out = {"interested": 0, "not_now": 0, "no": 0,
           "unsubscribe": 0, "unknown": 0}
    try:
        sb = client.raw
        res = (sb.table("email_history").select("extra")
               .eq("kind", "reply_received")
               .gte("ts", day_start).lt("ts", day_end)
               .limit(500).execute())
        for r in res.data or []:
            extra = r.get("extra") or {}
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except Exception:
                    extra = {}
            cat = ((extra.get("classification") or {}).get("category") or "unknown")
            if cat in out:
                out[cat] += 1
            else:
                out["unknown"] += 1
    except Exception as exc:
        logger.debug("replies_breakdown: %s", exc)
    return out


def _count_pending_prospect_drafts(client) -> int:
    try:
        sb = client.raw
        res = (sb.table("prospect_drafts").select("id", count="exact")
               .eq("status", "pending").limit(1).execute())
        return int(res.count or 0)
    except Exception:
        return 0


def _count_pending_convoy_drafts(client) -> int:
    try:
        sb = client.raw
        res = (sb.table("convoy_drafts").select("id", count="exact")
               .eq("status", "pending").limit(1).execute())
        return int(res.count or 0)
    except Exception:
        return 0


def _count_unhandled_replies(client, *, only_interested: bool = False) -> int:
    """Réponses entrantes pas encore traitées (handled=False).

    On filtre côté Python car le schéma stocke handled dans `extra` JSONB et
    Supabase REST ne permet pas un `extra->>'handled'='true'` proprement.
    """
    try:
        sb = client.raw
        res = (sb.table("email_history").select("extra")
               .eq("kind", "reply_received")
               .order("ts", desc=True).limit(500).execute())
        n = 0
        for r in res.data or []:
            extra = r.get("extra") or {}
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except Exception:
                    extra = {}
            if extra.get("handled"):
                continue
            if only_interested:
                cat = ((extra.get("classification") or {})
                       .get("category") or "unknown")
                if cat != "interested":
                    continue
            n += 1
        return n
    except Exception:
        return 0


def _count_failed_convoy_drafts(client, day_start: str, day_end: str) -> int:
    try:
        sb = client.raw
        res = (sb.table("convoy_drafts").select("id", count="exact")
               .eq("status", "failed")
               .gte("updated_at", day_start).lt("updated_at", day_end)
               .limit(1).execute())
        return int(res.count or 0)
    except Exception:
        return 0


def _count_total_prospects(client) -> int:
    try:
        sb = client.raw
        res = (sb.table("prospects").select("id", count="exact")
               .limit(1).execute())
        return int(res.count or 0)
    except Exception:
        return 0


def compute_digest() -> dict[str, Any]:
    """Renvoie un dict prêt à afficher."""
    out: dict[str, Any] = {
        "ok": False,
        "today": date.today().isoformat(),
        "yesterday": (date.today() - timedelta(days=1)).isoformat(),
        "sent": {"yesterday": 0, "today": 0, "last_7d": 0},
        "replies": {
            "yesterday_total": 0,
            "yesterday_breakdown": {},
            "today_total": 0,
            "today_breakdown": {},
        },
        "queue": {
            "drafts_prospect_pending": 0,
            "drafts_convoy_pending": 0,
            "replies_unhandled_interested": 0,
            "replies_unhandled_total": 0,
        },
        "alerts": {"convoy_failed_yesterday": 0,
                    "convoy_failed_today": 0},
        "totals": {"prospects": 0},
        "error": "",
    }

    client = _get_client()
    if client is None:
        out["error"] = "supabase_unavailable"
        return out

    today = date.today()
    yest = today - timedelta(days=1)
    week_start = today - timedelta(days=7)

    y_start, y_end = _bounds(yest)
    t_start, t_end = _bounds(today)
    w_start, _ = _bounds(week_start)

    out["sent"]["yesterday"] = _count_history(client, "email_sent", y_start, y_end)
    out["sent"]["today"] = _count_history(client, "email_sent", t_start, t_end)
    out["sent"]["last_7d"] = _count_history(client, "email_sent", w_start, t_end)

    out["replies"]["yesterday_total"] = _count_history(
        client, "reply_received", y_start, y_end)
    out["replies"]["yesterday_breakdown"] = _replies_breakdown(
        client, y_start, y_end)
    out["replies"]["today_total"] = _count_history(
        client, "reply_received", t_start, t_end)
    out["replies"]["today_breakdown"] = _replies_breakdown(
        client, t_start, t_end)

    out["queue"]["drafts_prospect_pending"] = _count_pending_prospect_drafts(client)
    out["queue"]["drafts_convoy_pending"] = _count_pending_convoy_drafts(client)
    out["queue"]["replies_unhandled_interested"] = _count_unhandled_replies(
        client, only_interested=True)
    out["queue"]["replies_unhandled_total"] = _count_unhandled_replies(client)

    out["alerts"]["convoy_failed_yesterday"] = _count_failed_convoy_drafts(
        client, y_start, y_end)
    out["alerts"]["convoy_failed_today"] = _count_failed_convoy_drafts(
        client, t_start, t_end)

    out["totals"]["prospects"] = _count_total_prospects(client)

    out["ok"] = True
    return out
