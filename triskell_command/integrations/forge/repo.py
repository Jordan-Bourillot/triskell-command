"""DAO Supabase pour les tables forge_*.

Wrapper minimal et robuste autour du client Supabase partagé. Toutes les
fonctions retournent une liste vide ou None si Supabase n'est pas configuré
ou pas connecté — pas d'exception qui remonte.

Pattern aligné sur phare/repo.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

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
    return getattr(c, "client", None) or getattr(c, "_client", None) \
        or getattr(c, "raw", None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# forge_pending_briefs
# ---------------------------------------------------------------------------
def list_briefs(status: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Liste les briefs reçus, du plus récent au plus ancien.

    `status` filtre optionnel : 'new', 'imported', 'rejected'.
    """
    sb = _sb()
    if sb is None:
        return []
    try:
        q = (sb.table("forge_pending_briefs")
             .select("*")
             .order("received_at", desc=True)
             .limit(limit))
        if status:
            q = q.eq("status", status)
        return q.execute().data or []
    except Exception as exc:
        logger.warning("forge.list_briefs: %s", exc)
        return []


def get_brief(brief_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        res = (sb.table("forge_pending_briefs")
               .select("*").eq("id", brief_id).limit(1).execute())
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("forge.get_brief: %s", exc)
        return None


def find_brief_by_message_id(message_id: str) -> Optional[dict]:
    """Anti-doublon : un Message-ID = un brief, idempotent."""
    if not message_id:
        return None
    sb = _sb()
    if sb is None:
        return None
    try:
        res = (sb.table("forge_pending_briefs")
               .select("id, status, project_id")
               .eq("raw_email_message_id", message_id)
               .limit(1).execute())
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("forge.find_brief_by_message_id: %s", exc)
        return None


def insert_brief(payload: dict) -> Optional[dict]:
    """Crée un nouveau brief. `payload` doit contenir au moins email + nom.

    Renvoie le row inséré (avec son id) ou None en cas d'échec.
    """
    sb = _sb()
    if sb is None:
        return None
    row = {
        "source":               payload.get("source") or "site-request",
        "received_at":          payload.get("received_at") or _now_iso(),
        "first_name":           (payload.get("first_name") or "")[:120],
        "last_name":            (payload.get("last_name") or "")[:120],
        "email":                (payload.get("email") or "")[:160],
        "phone":                (payload.get("phone") or "")[:60],
        "address":              (payload.get("address") or "")[:300],
        "description":          (payload.get("description") or "")[:4000],
        "audience":             (payload.get("audience") or "")[:1000],
        "tone":                 (payload.get("tone") or "")[:600],
        "raw_email_subject":    (payload.get("raw_email_subject") or "")[:300],
        "raw_email_message_id": (payload.get("raw_email_message_id") or "")[:300],
        "raw_email_excerpt":    (payload.get("raw_email_excerpt") or "")[:2000],
        "status":               "new",
    }
    try:
        ins = sb.table("forge_pending_briefs").insert(row).execute()
        rows = ins.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("forge.insert_brief: %s", exc)
        return None


def mark_brief_imported(brief_id: str, project_id: str) -> bool:
    sb = _sb()
    if sb is None:
        return False
    try:
        sb.table("forge_pending_briefs").update({
            "status": "imported",
            "project_id": project_id,
            "updated_at": _now_iso(),
        }).eq("id", brief_id).execute()
        return True
    except Exception as exc:
        logger.warning("forge.mark_brief_imported: %s", exc)
        return False


def mark_brief_rejected(brief_id: str, note: str = "") -> bool:
    sb = _sb()
    if sb is None:
        return False
    try:
        update = {"status": "rejected", "updated_at": _now_iso()}
        if note:
            update["notes"] = note[:500]
        sb.table("forge_pending_briefs").update(update).eq(
            "id", brief_id).execute()
        return True
    except Exception as exc:
        logger.warning("forge.mark_brief_rejected: %s", exc)
        return False


def count_briefs(status: str = "new") -> int:
    """Pour le badge sidebar ("X briefs en attente d'import")."""
    sb = _sb()
    if sb is None:
        return 0
    try:
        res = (sb.table("forge_pending_briefs")
               .select("id", count="exact")
               .eq("status", status)
               .limit(1).execute())
        return int(res.count or 0)
    except Exception as exc:
        logger.warning("forge.count_briefs: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# forge_projects
# ---------------------------------------------------------------------------
def list_projects(status: Optional[str] = None, limit: int = 50) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = (sb.table("forge_projects")
             .select("*")
             .order("created_at", desc=True)
             .limit(limit))
        if status:
            q = q.eq("status", status)
        return q.execute().data or []
    except Exception as exc:
        logger.warning("forge.list_projects: %s", exc)
        return []


def get_project(project_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        res = (sb.table("forge_projects")
               .select("*").eq("id", project_id).limit(1).execute())
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("forge.get_project: %s", exc)
        return None


def create_project_from_brief(brief: dict, *, auto_run: bool = True) -> Optional[dict]:
    """Crée un projet à partir d'un brief reçu.

    Le brief reste en base ; on copie ses champs dans le projet et on
    pointe brief.project_id vers le projet créé.
    """
    sb = _sb()
    if sb is None:
        return None
    row = {
        "brief_id":           brief.get("id"),
        "client_first_name":  brief.get("first_name") or "",
        "client_last_name":   brief.get("last_name") or "",
        "client_email":       brief.get("email") or "",
        "client_phone":       brief.get("phone") or "",
        "client_address":     brief.get("address") or "",
        "site_description":   brief.get("description") or "",
        "site_audience":      brief.get("audience") or "",
        "site_tone":          brief.get("tone") or "",
        "auto_run":           bool(auto_run),
        "current_step":       0,
        "steps_state":        {},
        "status":             "queued",
    }
    try:
        ins = sb.table("forge_projects").insert(row).execute()
        rows = ins.data or []
        if not rows:
            return None
        project = rows[0]
        # Lien retour brief → project
        if brief.get("id"):
            mark_brief_imported(brief["id"], project["id"])
        return project
    except Exception as exc:
        logger.warning("forge.create_project_from_brief: %s", exc)
        return None


def count_projects(status: str = "queued") -> int:
    sb = _sb()
    if sb is None:
        return 0
    try:
        res = (sb.table("forge_projects")
               .select("id", count="exact")
               .eq("status", status)
               .limit(1).execute())
        return int(res.count or 0)
    except Exception as exc:
        logger.warning("forge.count_projects: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# Config (shared_settings : forge_intake_config)
# ---------------------------------------------------------------------------
def get_intake_config() -> dict:
    """Lit la config d'intake (subject_prefix, marker_tag, enabled, …).

    Fallback hardcodé si la migration 09_forge.sql n'a pas encore été
    exécutée — l'intake reste fonctionnel.
    """
    defaults = {
        "subject_prefix":      "Demande de création de site",
        "marker_tag":          "[TRISKELL-INTAKE-V1]",
        "enabled":             True,
        "auto_create_project": True,
    }
    c = _client()
    if c is None:
        return defaults
    try:
        cfg = c.get_shared_setting("forge_intake_config", None)
        if isinstance(cfg, dict):
            out = dict(defaults)
            out.update(cfg)
            return out
    except Exception as exc:
        logger.debug("forge.get_intake_config: %s", exc)
    return defaults
