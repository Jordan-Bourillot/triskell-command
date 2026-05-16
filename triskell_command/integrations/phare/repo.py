"""DAO Supabase pour les tables phare_*.

Wrapper minimal et robuste autour du client Supabase partagé. Toutes les
fonctions retournent une liste vide ou None si Supabase n'est pas configuré
ou pas connecté — pas d'exception qui remonte.

Pattern aligné sur clients_repo.py et convoy_runner.py existants.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _client():
    """Renvoie le client Supabase authentifié, ou None."""
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None
    try:
        c = get_client()
    except SupabaseNotConfigured:
        return None
    if not c.is_authenticated:
        return None
    return c


def _sb():
    """Renvoie l'instance supabase-py brute, ou None."""
    c = _client()
    if c is None:
        return None
    return getattr(c, "client", None) or getattr(c, "_client", None)


# ---------------------------------------------------------------------------
# phare_sites
# ---------------------------------------------------------------------------
def list_sites(active_only: bool = True) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("phare_sites").select("*").order("priority", desc=True)
        if active_only:
            q = q.eq("is_active", True)
        return q.execute().data or []
    except Exception as exc:
        logger.warning("phare.list_sites: %s", exc)
        return []


def get_site(site_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = sb.table("phare_sites").select("*").eq("id", site_id).limit(1).execute().data
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("phare.get_site: %s", exc)
        return None


def upsert_site(site: dict) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        site = dict(site)
        site["updated_at"] = datetime.now(timezone.utc).isoformat()
        rows = sb.table("phare_sites").upsert(site, on_conflict="domain").execute().data
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("phare.upsert_site: %s", exc)
        return None


def deactivate_site(site_id: str) -> bool:
    sb = _sb()
    if sb is None:
        return False
    try:
        sb.table("phare_sites").update({"is_active": False}).eq("id", site_id).execute()
        return True
    except Exception as exc:
        logger.warning("phare.deactivate_site: %s", exc)
        return False


# ---------------------------------------------------------------------------
# phare_clients (1:1 avec phare_sites, créé par migration 08)
# ---------------------------------------------------------------------------
def get_client_by_site(site_id: str) -> Optional[dict]:
    """Renvoie la fiche client liée à un site, ou None s'il n'y en a pas."""
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("phare_clients").select("*")
                .eq("site_id", site_id).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("phare.get_client_by_site: %s", exc)
        return None


def upsert_client(client: dict) -> Optional[dict]:
    """Crée ou met à jour la fiche client. La contrainte unique sur
    `site_id` garantit le 1:1 avec phare_sites.
    """
    sb = _sb()
    if sb is None:
        return None
    try:
        client = dict(client)
        client["updated_at"] = datetime.now(timezone.utc).isoformat()
        rows = (sb.table("phare_clients")
                .upsert(client, on_conflict="site_id").execute().data)
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("phare.upsert_client: %s", exc)
        return None


def delete_client(client_id: str) -> bool:
    sb = _sb()
    if sb is None:
        return False
    try:
        sb.table("phare_clients").delete().eq("id", client_id).execute()
        return True
    except Exception as exc:
        logger.warning("phare.delete_client: %s", exc)
        return False


def list_clients_with_cadence(cadence: str) -> list[dict]:
    """Retourne toutes les fiches clients filtrées par cadence
    ('auto_mensuel' ou 'manuel'). Utilisé par le scheduler.
    """
    sb = _sb()
    if sb is None:
        return []
    try:
        return (sb.table("phare_clients").select("*")
                .eq("report_cadence", cadence).execute().data) or []
    except Exception as exc:
        logger.warning("phare.list_clients_with_cadence: %s", exc)
        return []


def mark_report_sent(client_id: str, pdf_path: str = "") -> bool:
    """Met à jour `last_report_sent_at` après envoi réussi d'un rapport."""
    sb = _sb()
    if sb is None:
        return False
    try:
        patch = {
            "last_report_sent_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if pdf_path:
            patch["last_report_pdf_path"] = pdf_path
        sb.table("phare_clients").update(patch).eq("id", client_id).execute()
        return True
    except Exception as exc:
        logger.warning("phare.mark_report_sent: %s", exc)
        return False


# ---------------------------------------------------------------------------
# phare_audits
# ---------------------------------------------------------------------------
def insert_audit(audit: dict) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = sb.table("phare_audits").insert(audit).execute().data
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("phare.insert_audit: %s", exc)
        return None


def latest_audit(site_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("phare_audits").select("*")
                .eq("site_id", site_id)
                .order("ran_at", desc=True).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("phare.latest_audit: %s", exc)
        return None


# ---------------------------------------------------------------------------
# phare_keywords
# ---------------------------------------------------------------------------
def upsert_keywords(site_id: str, keywords: list[dict]) -> int:
    sb = _sb()
    if sb is None or not keywords:
        return 0
    rows = []
    for kw in keywords:
        rows.append({
            "site_id": site_id,
            "keyword": kw["keyword"],
            "volume": int(kw.get("volume") or 0),
            "difficulty": int(kw.get("difficulty") or 0),
            "intent": kw.get("intent") or "informational",
            "target_url": kw.get("target_url") or "",
            "current_position": kw.get("current_position"),
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
        })
    try:
        sb.table("phare_keywords").upsert(rows, on_conflict="site_id,keyword").execute()
        return len(rows)
    except Exception as exc:
        logger.warning("phare.upsert_keywords: %s", exc)
        return 0


def list_keywords(site_id: str, limit: int = 200) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        return (sb.table("phare_keywords").select("*")
                .eq("site_id", site_id)
                .order("volume", desc=True).limit(limit).execute().data) or []
    except Exception as exc:
        logger.warning("phare.list_keywords: %s", exc)
        return []


# ---------------------------------------------------------------------------
# phare_pages
# ---------------------------------------------------------------------------
def upsert_pages(site_id: str, pages: list[dict]) -> int:
    sb = _sb()
    if sb is None or not pages:
        return 0
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for p in pages:
        rows.append({
            "site_id": site_id,
            "url": p["url"],
            "path": p.get("path") or "/",
            "title": p.get("title") or "",
            "meta_description": p.get("meta_description") or "",
            "h1": p.get("h1") or "",
            "h_outline": p.get("h_outline") or [],
            "word_count": int(p.get("word_count") or 0),
            "internal_links": int(p.get("internal_links") or 0),
            "schema_types": p.get("schema_types") or [],
            "last_crawled_at": now,
            "optim_score": p.get("optim_score"),
            "optim_notes": p.get("optim_notes") or "",
        })
    try:
        sb.table("phare_pages").upsert(rows, on_conflict="site_id,path").execute()
        return len(rows)
    except Exception as exc:
        logger.warning("phare.upsert_pages: %s", exc)
        return 0


def list_pages(site_id: str, limit: int = 500) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        return (sb.table("phare_pages").select("*")
                .eq("site_id", site_id)
                .order("last_crawled_at", desc=True).limit(limit).execute().data) or []
    except Exception as exc:
        logger.warning("phare.list_pages: %s", exc)
        return []


# ---------------------------------------------------------------------------
# phare_actions (PRs & recommandations)
# ---------------------------------------------------------------------------
def insert_action(action: dict) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = sb.table("phare_actions").insert(action).execute().data
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("phare.insert_action: %s", exc)
        return None


def update_action(action_id: str, patch: dict) -> bool:
    sb = _sb()
    if sb is None:
        return False
    try:
        sb.table("phare_actions").update(patch).eq("id", action_id).execute()
        return True
    except Exception as exc:
        logger.warning("phare.update_action: %s", exc)
        return False


def list_actions(site_id: Optional[str] = None,
                 status: Optional[str] = None,
                 limit: int = 100) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("phare_actions").select("*").order("created_at", desc=True).limit(limit)
        if site_id:
            q = q.eq("site_id", site_id)
        if status:
            q = q.eq("status", status)
        return q.execute().data or []
    except Exception as exc:
        logger.warning("phare.list_actions: %s", exc)
        return []


def pending_actions_count() -> int:
    sb = _sb()
    if sb is None:
        return 0
    try:
        rows = sb.table("phare_actions").select("id", count="exact").eq("status", "preview").execute()
        return rows.count or 0
    except Exception as exc:
        logger.warning("phare.pending_actions_count: %s", exc)
        return 0


def last_action_by_agent(agent_name: str) -> Optional[dict]:
    """Renvoie la dernière action enregistrée pour un agent donné, ou None."""
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("phare_actions").select("*")
                .eq("agent", agent_name)
                .order("created_at", desc=True).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("phare.last_action_by_agent: %s", exc)
        return None


# ---------------------------------------------------------------------------
# phare_metrics
# ---------------------------------------------------------------------------
def upsert_metrics(site_id: str, day: date, payload: dict, source: str = "gsc") -> bool:
    sb = _sb()
    if sb is None:
        return False
    row = dict(payload)
    row.update({"site_id": site_id, "metric_date": day.isoformat(), "source": source})
    try:
        sb.table("phare_metrics").upsert(row, on_conflict="site_id,metric_date,source").execute()
        return True
    except Exception as exc:
        logger.warning("phare.upsert_metrics: %s", exc)
        return False


def metrics_window(site_id: str, days: int = 30) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        return (sb.table("phare_metrics").select("*")
                .eq("site_id", site_id)
                .order("metric_date", desc=True).limit(days).execute().data) or []
    except Exception as exc:
        logger.warning("phare.metrics_window: %s", exc)
        return []


# ---------------------------------------------------------------------------
# phare_backlinks
# ---------------------------------------------------------------------------
def insert_backlinks(site_id: str, items: list[dict]) -> int:
    sb = _sb()
    if sb is None or not items:
        return 0
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for it in items:
        rows.append({
            "site_id": site_id,
            "source_domain": it["source_domain"],
            "source_url": it.get("source_url") or "",
            "target_url": it.get("target_url") or "",
            "anchor": it.get("anchor") or "",
            "domain_rating": it.get("domain_rating"),
            "is_dofollow": bool(it.get("is_dofollow", True)),
            "kind": it.get("kind") or "existing",
            "opportunity_score": it.get("opportunity_score"),
            "notes": it.get("notes") or "",
            "last_seen_at": now,
        })
    try:
        sb.table("phare_backlinks").insert(rows).execute()
        return len(rows)
    except Exception as exc:
        logger.warning("phare.insert_backlinks: %s", exc)
        return 0


def list_backlinks(site_id: str, kind: Optional[str] = None, limit: int = 200) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("phare_backlinks").select("*").eq("site_id", site_id)
        if kind:
            q = q.eq("kind", kind)
        return q.order("discovered_at", desc=True).limit(limit).execute().data or []
    except Exception as exc:
        logger.warning("phare.list_backlinks: %s", exc)
        return []


# ---------------------------------------------------------------------------
# phare_content_briefs
# ---------------------------------------------------------------------------
def insert_brief(brief: dict) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = sb.table("phare_content_briefs").insert(brief).execute().data
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("phare.insert_brief: %s", exc)
        return None


def list_briefs(site_id: str, status: Optional[str] = None, limit: int = 50) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("phare_content_briefs").select("*").eq("site_id", site_id)
        if status:
            q = q.eq("status", status)
        return q.order("created_at", desc=True).limit(limit).execute().data or []
    except Exception as exc:
        logger.warning("phare.list_briefs: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Configuration partagée (shared_settings.phare_config)
# ---------------------------------------------------------------------------
def get_config() -> dict:
    """Renvoie la config Le Phare (shared_settings.phare_config)."""
    sb = _sb()
    if sb is None:
        return {}
    try:
        rows = (sb.table("shared_settings").select("value")
                .eq("key", "phare_config").limit(1).execute().data)
        if not rows:
            return {}
        return rows[0].get("value") or {}
    except Exception as exc:
        logger.warning("phare.get_config: %s", exc)
        return {}


def update_config(patch: dict) -> bool:
    sb = _sb()
    if sb is None:
        return False
    cur = get_config()
    cur.update(patch)
    try:
        sb.table("shared_settings").upsert({
            "key": "phare_config",
            "value": cur,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="key").execute()
        return True
    except Exception as exc:
        logger.warning("phare.update_config: %s", exc)
        return False
