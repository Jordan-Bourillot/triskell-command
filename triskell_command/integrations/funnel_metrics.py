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
    # Nouveaux statuts du systeme de protection mail — exposes pour les
    # jauges de qualite (taux de bounce, taux de desinscription)
    out["stages"]["lost"] = status_counter.get("lost", 0)
    out["stages"]["refused"] = status_counter.get("refused", 0)
    out["stages"]["unsubscribed"] = status_counter.get("unsubscribed", 0)
    out["stages"]["bounced"] = status_counter.get("bounced", 0)
    # Taux de delivrabilite (sain si tres bas)
    total_with_attempt = (sent_targets := 0)  # placeholder, recalc plus bas
    out["health"] = {
        "bounced_rate": 0.0,        # rempli apres le comptage des sent
        "unsubscribe_rate": 0.0,
    }

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
    # Taux de delivrabilite : bounced / sent. Plus c'est haut, plus la
    # reputation d'envoi se degrade. Same pour desinscriptions.
    if sent_count > 0:
        out["health"]["bounced_rate"] = round(
            100.0 * status_counter.get("bounced", 0) / sent_count, 2)
        out["health"]["unsubscribe_rate"] = round(
            100.0 * status_counter.get("unsubscribed", 0) / sent_count, 2)
    out["ok"] = True
    return out


# ---------------------------------------------------------------------------
# Performance par modèle de mail — quel modèle fait répondre ?
# ---------------------------------------------------------------------------
def _template_label(row: dict) -> str:
    """Étiquette lisible du « modèle » d'un envoi (colonne ou extra)."""
    extra = row.get("extra") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    label = (row.get("template_key") or extra.get("template_key")
             or extra.get("offer_name") or "")
    label = str(label).strip()
    if not label:
        if extra.get("drip_stage"):
            return f"relance {extra['drip_stage']}"
        if extra.get("auto_drip"):
            return "relance auto"
        if extra.get("convoy_campaign_id"):
            return "Convoi (libre)"
        return "(génération libre)"
    return label


def aggregate_template_performance(sent_rows: list[dict],
                                    reply_rows: list[dict]) -> list[dict]:
    """Agrégation PURE : envois + réponses → stats par modèle.

    Une réponse est créditée au modèle du DERNIER envoi fait à ce prospect
    AVANT la réponse. Renvoie une liste triée par volume d'envois :
    [{template, sent, replies, interested, reply_rate}].
    """
    # Index des envois par prospect, triés par date
    sends_by_pid: dict[str, list[tuple[str, str]]] = {}
    counts: dict[str, dict] = {}
    for r in sent_rows:
        pid = r.get("prospect_id") or ""
        ts = r.get("ts") or ""
        label = _template_label(r)
        c = counts.setdefault(label, {"sent": 0, "replies": 0,
                                       "interested": 0})
        c["sent"] += 1
        if pid:
            sends_by_pid.setdefault(pid, []).append((ts, label))
    for pid in sends_by_pid:
        sends_by_pid[pid].sort()

    for r in reply_rows:
        pid = r.get("prospect_id") or ""
        ts = r.get("ts") or ""
        sends = sends_by_pid.get(pid) or []
        label = None
        for s_ts, s_label in sends:
            if not ts or s_ts <= ts:
                label = s_label
            else:
                break
        if label is None:
            continue  # réponse sans envoi connu dans la fenêtre
        extra = r.get("extra") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        cat = ((extra.get("classification") or {}).get("category") or "")
        c = counts.setdefault(label, {"sent": 0, "replies": 0,
                                       "interested": 0})
        c["replies"] += 1
        if cat == "interested":
            c["interested"] += 1

    rows = []
    for label, c in counts.items():
        rate = round(100.0 * c["replies"] / c["sent"], 1) if c["sent"] else 0.0
        rows.append({"template": label, "sent": c["sent"],
                     "replies": c["replies"],
                     "interested": c["interested"],
                     "reply_rate": rate})
    rows.sort(key=lambda x: (-x["sent"], x["template"]))
    return rows


def compute_template_performance(period: str = "90d") -> dict[str, Any]:
    """Quel modèle de mail fait répondre ? (envois vs réponses, par modèle).

    C'est la boucle de retour qui manquait : les données dormaient dans
    email_history sans jamais être croisées. Période par défaut : 90 jours
    (la prospection met du temps à répondre).
    """
    out: dict[str, Any] = {"ok": False, "period": period, "rows": [],
                           "error": ""}
    client = _get_client()
    if client is None:
        out["error"] = "supabase_unavailable"
        return out
    period = period if period in PERIODS else "90d"
    since = _period_start(period)
    sb = client.raw
    try:
        sent_res = (sb.table("email_history")
                    .select("prospect_id,ts,template_key,extra")
                    .eq("kind", "email_sent")
                    .gte("ts", since).limit(20000).execute())
        reply_res = (sb.table("email_history")
                     .select("prospect_id,ts,extra")
                     .eq("kind", "reply_received")
                     .gte("ts", since).limit(20000).execute())
    except Exception as exc:
        out["error"] = f"email_history: {exc}"
        return out
    out["rows"] = aggregate_template_performance(
        sent_res.data or [], reply_res.data or [])
    out["ok"] = True
    return out
