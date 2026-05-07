"""Funnel metrics — agrège les conversions par segment.

Fonnel par défaut :
  Source → Envoyés → Réponses → Intéressés → Gagnés (status=won)

On considère qu'un "intéressé" est tout email_history.kind=reply_received
avec extra.classification.category=='interested'. Un "won" est un
prospects.status='won'. Un "envoyé" est un email_history.kind='email_sent'.

Segments dispo :
  - "all"      : tout
  - "creators" : prospects.industry contient youtube/twitch/reddit/...
  - "B2B local": prospects.naf_code non vide

Pas de tracking pixel ni UTM — c'est une analyse purement basée sur ce qui
existe en DB. Pour les ouvertures/clics, voir le futur tracking.js Netlify.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


SEGMENTS = ("all", "creators", "b2b_local")
PERIODS = ("7d", "30d", "90d", "all")


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


def _period_start(period: str) -> str:
    today = datetime.now()
    if period == "7d":
        return (today - timedelta(days=7)).isoformat(timespec="seconds")
    if period == "30d":
        return (today - timedelta(days=30)).isoformat(timespec="seconds")
    if period == "90d":
        return (today - timedelta(days=90)).isoformat(timespec="seconds")
    return "1970-01-01T00:00:00"


def _segment_filter(prospects: list[dict], segment: str) -> set:
    """Retourne le set des prospect_ids qui matchent le segment."""
    if segment == "all":
        return {p["id"] for p in prospects if p.get("id")}
    if segment == "creators":
        return {
            p["id"] for p in prospects
            if (p.get("industry") or "").lower()
            in {"youtube", "twitch", "reddit", "bluesky", "mastodon",
                "podcast", "dailymotion", "kick", "github"}
        }
    if segment == "b2b_local":
        return {p["id"] for p in prospects if (p.get("naf_code") or "").strip()}
    return {p["id"] for p in prospects if p.get("id")}


def compute_funnel(period: str = "30d", segment: str = "all") -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "period": period,
        "segment": segment,
        "stages": {
            "prospects": 0,
            "sent": 0,
            "replies": 0,
            "interested": 0,
            "won": 0,
        },
        "by_product": {},
        "by_status": {},
        "by_category": {},
        "error": "",
    }

    client = _get_client()
    if client is None:
        out["error"] = "supabase_unavailable"
        return out

    period = period if period in PERIODS else "30d"
    segment = segment if segment in SEGMENTS else "all"
    since = _period_start(period)

    sb = client.raw

    try:
        prospects_res = (sb.table("prospects")
                         .select("id,industry,naf_code,status,tags")
                         .limit(5000).execute())
        prospects = prospects_res.data or []
    except Exception as exc:
        out["error"] = f"prospects: {exc}"
        return out

    seg_ids = _segment_filter(prospects, segment)
    out["stages"]["prospects"] = len(seg_ids)

    # Compteurs sur les statuts (intéressant pour la jauge)
    status_counter: Counter = Counter()
    for p in prospects:
        if p.get("id") in seg_ids:
            status_counter[p.get("status") or "new"] += 1
    out["by_status"] = dict(status_counter)
    out["stages"]["won"] = status_counter.get("won", 0)

    try:
        hist_res = (sb.table("email_history")
                    .select("prospect_id,kind,ts,extra")
                    .gte("ts", since).limit(20000).execute())
        hist_rows = hist_res.data or []
    except Exception as exc:
        out["error"] = f"email_history: {exc}"
        return out

    by_product: Counter = Counter()
    by_category: Counter = Counter()
    sent_count = 0
    reply_count = 0
    interested_count = 0
    for h in hist_rows:
        pid = h.get("prospect_id")
        if pid not in seg_ids:
            continue
        kind = h.get("kind", "")
        extra = h.get("extra") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        if kind == "email_sent":
            sent_count += 1
            # On essaie d'inférer le produit promu : extra.product OU
            # extra.template_key (heuristique)
            prod = (extra.get("product") or extra.get("template_key")
                    or "").lower().strip()
            if prod:
                by_product[prod] += 1
        elif kind == "reply_received":
            reply_count += 1
            cat = ((extra.get("classification") or {})
                   .get("category") or "unknown")
            by_category[cat] += 1
            if cat == "interested":
                interested_count += 1

    out["stages"]["sent"] = sent_count
    out["stages"]["replies"] = reply_count
    out["stages"]["interested"] = interested_count
    out["by_product"] = dict(by_product.most_common(20))
    out["by_category"] = dict(by_category)
    out["ok"] = True
    return out
