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


_ADMIN_SB_CACHE: Any = None


def _sb():
    """Renvoie l'instance supabase-py brute, ou None.

    Ordre de résolution :
    1. Session utilisateur authentifiée (cas normal : app desktop / web)
    2. Fallback CI/cron : variables d'env SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
       (utilisé par scripts/phare_tick.py et le workflow GitHub Actions)
    """
    c = _client()
    if c is not None:
        # c.raw force l'init du SDK ; le getattr "_client" restait None en
        # mode service_role tant que rien d'autre n'avait touché le client.
        try:
            return c.raw
        except Exception:
            pass
    # ----- Fallback service_role pour exécution en CI / batch -----
    global _ADMIN_SB_CACHE
    if _ADMIN_SB_CACHE is not None:
        return _ADMIN_SB_CACHE
    import os
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        _ADMIN_SB_CACHE = create_client(url, key)
        logger.info("phare.repo : utilisation du fallback service_role (CI/batch)")
        return _ADMIN_SB_CACHE
    except Exception as exc:
        logger.warning("phare._sb fallback service_role: %s", exc)
        return None


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
            "best_position": kw.get("best_position"),
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
    seen_paths: set[str] = set()
    now = datetime.now(timezone.utc).isoformat()
    for p in pages:
        path = p.get("path") or "/"
        # Le crawler retire la query string : « /configurer?option=seo » et
        # « /configurer?option=combo » donnent le même path. Deux lignes
        # identiques dans le MÊME upsert → Postgres rejette TOUT le lot
        # (21000, « cannot affect row a second time ») et la table restait
        # vide en silence (vécu sur Pixel Pros le 12/06/2026 : 50 pages
        # crawlées, 0 écrites → l'Exécuteur travaillait à l'aveugle).
        if path in seen_paths:
            continue
        seen_paths.add(path)
        rows.append({
            "site_id": site_id,
            "url": p["url"],
            "path": path,
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
        # Filet : une seule ligne pourrie ne doit plus emporter tout le lot
        logger.warning("phare.upsert_pages (lot): %s — reprise ligne à ligne", exc)
        ok = 0
        for row in rows:
            try:
                sb.table("phare_pages").upsert(row, on_conflict="site_id,path").execute()
                ok += 1
            except Exception as exc2:
                logger.warning("phare.upsert_pages (%s): %s", row.get("path"), exc2)
        return ok


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
# Colonnes ajoutées par la migration 48 — si elle n'est pas encore appliquée,
# l'insert est retenté sans elles (mode dégradé propre, même esprit que 45/46).
_ACTION_OPTIONAL_COLS = ("simple_md", "apply_state", "apply_error",
                         "apply_requested_at")


def insert_action(action: dict, *, dedup: bool = True) -> Optional[dict]:
    """Insère une action — en refusant les doublons.

    Avant d'écrire, on regarde si une action « équivalente » existe déjà
    pour ce site (ouverte, refusée < 60 j ou validée < 14 j) : si oui, on
    renvoie l'existante avec un marqueur `_dedup` au lieu d'en créer une
    deuxième. Règle posée par Jordan le 12/06/2026 : plus jamais de cartes
    en double dans « À toi de jouer ».
    """
    sb = _sb()
    if sb is None:
        return None
    if dedup:
        try:
            from . import dedup as _dedup
            existing = (sb.table("phare_actions").select("*")
                        .eq("site_id", action.get("site_id"))
                        .order("created_at", desc=True)
                        .limit(400).execute().data) or []
            twin = _dedup.find_blocking_duplicate(existing, action)
            if twin is not None:
                logger.info("phare.insert_action: doublon évité « %s » (≈ %s)",
                            (action.get("title") or "")[:80],
                            (twin.get("title") or "")[:80])
                return {**twin, "_dedup": True}
        except Exception as exc:
            logger.debug("phare.insert_action dedup KO (on insère quand même): %s", exc)
    try:
        rows = sb.table("phare_actions").insert(action).execute().data
        return rows[0] if rows else None
    except Exception as exc:
        # Migration 48 pas appliquée → retente sans les colonnes optionnelles
        msg = str(exc)
        slim = {k: v for k, v in action.items() if k not in _ACTION_OPTIONAL_COLS}
        if len(slim) != len(action) and ("column" in msg.lower()
                                          or "PGRST204" in msg):
            try:
                rows = sb.table("phare_actions").insert(slim).execute().data
                return rows[0] if rows else None
            except Exception as exc2:
                logger.warning("phare.insert_action (retry sans cols 48): %s", exc2)
                return None
        logger.warning("phare.insert_action: %s", exc)
        return None


def expire_open_actions(site_id: str, *, agent: str, title_prefix: str,
                        reason: str = "Remplacée par une version plus récente") -> int:
    """Expire les actions ouvertes d'un agent dont le titre commence par
    `title_prefix` (bulletins quotidiens, plans du mois… : périssables —
    une nouvelle édition rend l'ancienne obsolète).
    """
    sb = _sb()
    if sb is None:
        return 0
    try:
        from . import dedup as _dedup
        rows = (sb.table("phare_actions").select("id,title,status")
                .eq("site_id", site_id).eq("agent", agent)
                .like("title", f"{title_prefix}%")
                .in_("status", list(_dedup.OPEN_STATUSES))
                .execute().data) or []
        for r in rows:
            sb.table("phare_actions").update({
                "status": "expired",
                "rejected_reason": reason,
            }).eq("id", r["id"]).execute()
        return len(rows)
    except Exception as exc:
        logger.warning("phare.expire_open_actions: %s", exc)
        return 0


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
    # PK composite (workspace_id, key) depuis la migration 20 : l'ancien
    # upsert on_conflict="key" plantait en 42P10 et la config ne
    # s'écrivait PLUS (scheduler_log figé → missions globales re-exécutées
    # à chaque tick). L'idiome robuste vit dans shared_settings_db.
    from ..shared_settings_db import upsert_setting
    return upsert_setting(sb, "phare_config", cur)
