"""DAO Supabase pour Obelisk (prospection créateurs).

Lit/écrit dans la table partagée `public.prospects` (déjà alimentée par
l'app standalone Obelisk via son module RemoteCRM). Triskell Command
devient simplement un consommateur de plus de cette table.

Tables touchées :
  - public.prospects               (schéma : supabase/01_schema.sql)
  - public.obelisk_search_jobs     (créée par migration 21_obelisk_jobs.sql)
  - public.obelisk_user_config     (créée par migration 21_obelisk_jobs.sql)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SERVICE_CLIENT = None
_SERVICE_CLIENT_TRIED = False


# ---------------------------------------------------------------------------
# Connexion Supabase (même pattern que lagriffe/repo.py)
# ---------------------------------------------------------------------------
def _load_service_config() -> Optional[dict]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
    if url and key:
        return {"url": url, "service_role_key": key}
    p = Path.home() / ".triskell-command" / "settings.json"
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            sb = d.get("supabase") or {}
            url = sb.get("url") or ""
            key = sb.get("service_role_key") or sb.get("service_key") or ""
            if url and key:
                return {"url": url, "service_role_key": key}
        except Exception as exc:
            logger.debug("obelisk._load_service_config: %s", exc)
    return None


def _service_sb():
    global _SERVICE_CLIENT, _SERVICE_CLIENT_TRIED
    if _SERVICE_CLIENT is not None:
        return _SERVICE_CLIENT
    if _SERVICE_CLIENT_TRIED:
        return None
    _SERVICE_CLIENT_TRIED = True
    cfg = _load_service_config()
    if cfg is None:
        return None
    try:
        from supabase import create_client
    except ImportError:
        logger.warning("supabase-py introuvable — pip install supabase")
        return None
    try:
        _SERVICE_CLIENT = create_client(cfg["url"], cfg["service_role_key"])
    except Exception as exc:
        logger.warning("obelisk._service_sb: %s", exc)
        return None
    return _SERVICE_CLIENT


def _user_sb():
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
    return getattr(c, "client", None) or getattr(c, "_client", None)


def _sb():
    return _service_sb() or _user_sb()


# ---------------------------------------------------------------------------
# Liste des créateurs (lecture)
# ---------------------------------------------------------------------------
ALLOWED_STATUSES = ("new", "qualified", "contacted", "replied", "refused", "won", "lost")


def list_creators(*,
                  platform: str = "",
                  status: str = "",
                  min_score: int = 0,
                  city: str = "",
                  q: str = "",
                  has_email: Optional[bool] = None,
                  country: str = "",
                  limit: int = 100,
                  offset: int = 0) -> dict:
    """Retourne une page de prospects + le count total filtré.

    Filtres :
      - platform   : 'youtube', 'twitch', 'bluesky', etc. (matche dans
                     sources[*].name OU platform_url)
      - status     : status CRM exact ('new', 'qualified', ...)
      - min_score  : score minimal (inclusif)
      - city       : préfixe ville (ilike)
      - q          : texte libre (matche name / handle / website / description)
      - has_email  : True → uniquement avec emails non vides ; False → uniquement sans ;
                     None (défaut) → tout
      - country    : "FR" → uniquement France ;
                     "OTHERS" → tous SAUF France (vide ou autre code) ;
                     "" → pas de filtre
    """
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré", "rows": [], "count": 0}
    try:
        qy = (sb.table("prospects")
                .select("id, name, handle, legal_name, emails, phones, website, "
                        "city, postal_code, country, industry, description, "
                        "monetized, monetization_reasons, score, score_label, "
                        "subscribers, platform_url, status, tags, notes, "
                        "last_contact_at, sources, created_at, updated_at",
                        count="exact"))
        if status and status in ALLOWED_STATUSES:
            qy = qy.eq("status", status)
        if min_score and min_score > 0:
            qy = qy.gte("score", int(min_score))
        if city:
            qy = qy.ilike("city", f"{city}%")
        if q:
            # Recherche textuelle multi-colonnes (or_ supabase)
            term = q.replace("%", "")[:80]
            qy = qy.or_(
                f"name.ilike.%{term}%,"
                f"handle.ilike.%{term}%,"
                f"website.ilike.%{term}%,"
                f"description.ilike.%{term}%,"
                f"legal_name.ilike.%{term}%"
            )
        if has_email is True:
            qy = qy.neq("emails", "[]")
        elif has_email is False:
            qy = qy.eq("emails", "[]")
        if platform:
            # platform_url contient youtube.com / twitch.tv / etc. selon source
            p = platform.lower()
            qy = qy.ilike("platform_url", f"%{p}%")
        if country:
            cu = country.strip().upper()
            if cu == "FR":
                qy = qy.eq("country", "FR")
            elif cu == "OTHERS":
                qy = qy.neq("country", "FR")
            else:
                # Pays explicite : on filtre dessus
                qy = qy.eq("country", cu)
        qy = qy.order("score", desc=True).order("updated_at", desc=True)
        qy = qy.range(offset, offset + max(0, limit - 1))
        res = qy.execute()
        return {"ok": True, "rows": res.data or [], "count": getattr(res, "count", None) or len(res.data or [])}
    except Exception as exc:
        logger.warning("obelisk.list_creators: %s", exc)
        return {"ok": False, "error": str(exc), "rows": [], "count": 0}


def get_creator(prospect_id: str) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        rows = (sb.table("prospects").select("*")
                  .eq("id", prospect_id).limit(1).execute().data or [])
        if not rows:
            return {"ok": False, "error": "introuvable"}
        return {"ok": True, "prospect": rows[0]}
    except Exception as exc:
        logger.warning("obelisk.get_creator: %s", exc)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Stats globales pour le bandeau du haut
# ---------------------------------------------------------------------------
def stats() -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        out: dict[str, int] = {"total": 0, "with_email": 0, "qualified": 0,
                                "contacted": 0, "replied": 0, "won": 0}
        # total
        r = sb.table("prospects").select("id", count="exact").limit(1).execute()
        out["total"] = getattr(r, "count", None) or 0
        # with_email (emails != '[]')
        r = sb.table("prospects").select("id", count="exact").neq("emails", "[]").limit(1).execute()
        out["with_email"] = getattr(r, "count", None) or 0
        for s in ("qualified", "contacted", "replied", "won"):
            r = sb.table("prospects").select("id", count="exact").eq("status", s).limit(1).execute()
            out[s] = getattr(r, "count", None) or 0
        return {"ok": True, "stats": out}
    except Exception as exc:
        logger.warning("obelisk.stats: %s", exc)
        return {"ok": False, "error": str(exc), "stats": {}}


# ---------------------------------------------------------------------------
# Update CRM (statut, tags, notes)
# ---------------------------------------------------------------------------
def update_creator(prospect_id: str, fields: dict) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    ALLOWED = ("status", "tags", "notes", "last_contact_at")
    payload: dict = {}
    for k in ALLOWED:
        if k in fields:
            payload[k] = fields[k]
    if "status" in payload and payload["status"] not in ALLOWED_STATUSES:
        return {"ok": False, "error": "status invalide"}
    if "notes" in payload and isinstance(payload["notes"], str):
        payload["notes"] = payload["notes"][:10_000]
    if not payload:
        return {"ok": False, "error": "aucun champ à mettre à jour"}
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("prospects").update(payload).eq("id", prospect_id).execute()
        return {"ok": True, "prospect_id": prospect_id}
    except Exception as exc:
        logger.warning("obelisk.update_creator: %s", exc)
        return {"ok": False, "error": str(exc)}


def delete_creator(prospect_id: str) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        sb.table("prospects").delete().eq("id", prospect_id).execute()
        return {"ok": True}
    except Exception as exc:
        logger.warning("obelisk.delete_creator: %s", exc)
        return {"ok": False, "error": str(exc)}


def delete_creators_bulk(prospect_ids: list[str]) -> dict:
    """Supprime plusieurs créateurs d'un coup. Renvoie le nombre supprimé."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré", "deleted": 0}
    ids = [str(i).strip() for i in (prospect_ids or []) if i]
    if not ids:
        return {"ok": True, "deleted": 0}
    try:
        # Le client Supabase Python ne supporte pas always le batch in_().
        # On chunke par 50 pour rester sous la limite d'URL.
        deleted = 0
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            sb.table("prospects").delete().in_("id", chunk).execute()
            deleted += len(chunk)
        return {"ok": True, "deleted": deleted}
    except Exception as exc:
        logger.warning("obelisk.delete_creators_bulk: %s", exc)
        return {"ok": False, "error": str(exc), "deleted": 0}


def delete_creators_filtered(*,
                              platform: str = "",
                              status: str = "",
                              min_score: int = 0,
                              city: str = "",
                              q: str = "",
                              has_email: Optional[bool] = None) -> dict:
    """Supprime tous les créateurs qui matchent les filtres donnés.
    Réutilise list_creators pour récupérer les IDs, puis delete_bulk.

    Renvoie {ok, deleted, matched}.
    """
    # On récupère par paquets jusqu'à épuisement
    ids_total: list[str] = []
    offset = 0
    page_size = 200
    while True:
        page = list_creators(platform=platform, status=status,
                              min_score=min_score, city=city, q=q,
                              has_email=has_email,
                              limit=page_size, offset=offset)
        rows = (page or {}).get("rows") or []
        if not rows:
            break
        ids_total.extend(r["id"] for r in rows if r.get("id"))
        if len(rows) < page_size:
            break
        offset += page_size
        if offset > 10_000:   # garde-fou
            break
    if not ids_total:
        return {"ok": True, "deleted": 0, "matched": 0}
    res = delete_creators_bulk(ids_total)
    return {"ok": res.get("ok", False),
            "deleted": res.get("deleted", 0),
            "matched": len(ids_total),
            "error":   res.get("error", "")}


def delete_all_creators() -> dict:
    """Supprime TOUS les créateurs (table prospects). Garde-fou côté API :
    cette méthode doit être appelée seulement après double confirmation
    utilisateur. La table est purgée intégralement (workspace-scoped via
    les RLS Supabase normalement)."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré", "deleted": 0}
    try:
        # Count avant pour les stats
        c = sb.table("prospects").select("id", count="exact").limit(1).execute()
        before = int(c.count or 0)
        # Delete all avec un filtre toujours vrai (id n'est jamais vide)
        sb.table("prospects").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        return {"ok": True, "deleted": before}
    except Exception as exc:
        logger.warning("obelisk.delete_all_creators: %s", exc)
        return {"ok": False, "error": str(exc), "deleted": 0}


# ---------------------------------------------------------------------------
# Config Obelisk par user (clés API, IA, préférences, catalogue d'offres)
# Stockée dans une table dédiée pour rester user-scoped propre.
# ---------------------------------------------------------------------------
def get_user_config(user_email: str = "") -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": True, "config": _default_config(), "fallback": True}
    try:
        q = sb.table("obelisk_user_config").select("*").limit(1)
        if user_email:
            q = q.eq("user_email", user_email)
        rows = q.execute().data or []
        if not rows:
            return {"ok": True, "config": _default_config()}
        row = rows[0]
        cfg = row.get("config") or {}
        # Fusionne avec les défauts pour ne jamais renvoyer d'objet incomplet
        merged = {**_default_config(), **(cfg if isinstance(cfg, dict) else {})}
        return {"ok": True, "config": merged, "updated_at": row.get("updated_at")}
    except Exception as exc:
        logger.warning("obelisk.get_user_config: %s", exc)
        return {"ok": True, "config": _default_config(), "error": str(exc), "fallback": True}


def save_user_config(user_email: str, config: dict) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    if not isinstance(config, dict):
        return {"ok": False, "error": "config doit être un objet"}
    # Filtre les clés sensibles pour ne pas écrire n'importe quoi
    ALLOWED = (
        "niche", "platforms", "max_per_platform", "only_unmonetized",
        "enrich_web", "daily_cap",
        "ai_provider", "ai_model", "ai_mega_prompts",
        "catalog", "product_override",
        # API keys (chiffrement géré côté Supabase par RLS, pas de chiffrement
        # local supplémentaire à ce stade — TODO sécurité niveau 2 si besoin)
        "youtube_api_key", "twitch_client_id", "twitch_client_secret",
        "github_token", "mastodon_instances",
        "apple_podcasts_country", "apple_podcasts_lang",
        "ai_api_keys",
    )
    clean = {k: v for k, v in config.items() if k in ALLOWED}
    try:
        sb.table("obelisk_user_config").upsert({
            "user_email": user_email or "_default_",
            "config": clean,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="user_email").execute()
        return {"ok": True}
    except Exception as exc:
        logger.warning("obelisk.save_user_config: %s", exc)
        return {"ok": False, "error": str(exc)}


def _default_config() -> dict:
    return {
        "niche": "",
        "platforms": ["youtube", "reddit"],
        "max_per_platform": 30,
        "only_unmonetized": True,
        "enrich_web": True,
        "daily_cap": 20,
        "ai_provider": "google",
        "ai_model": "gemini-2.5-flash",
        "ai_mega_prompts": ["16", "06", "07"],
        "catalog": "",
        "product_override": "",
        "youtube_api_key": "",
        "twitch_client_id": "",
        "twitch_client_secret": "",
        "github_token": "",
        "mastodon_instances": [],
        "apple_podcasts_country": "fr",
        "apple_podcasts_lang": "fr_fr",
        "ai_api_keys": {},
    }


# ---------------------------------------------------------------------------
# Search jobs : queue partagée pour lancer une recherche depuis Triskell
# Command alors qu'Obelisk standalone tourne (à terme : le runner web prend
# la main directement).
# ---------------------------------------------------------------------------
def create_search_job(user_email: str, niche: str, platforms: list[str],
                      max_per_platform: int = 30) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    if not niche:
        return {"ok": False, "error": "niche requise"}
    try:
        row = {
            "user_email": user_email or "_default_",
            "niche": niche[:200],
            "platforms": platforms or ["youtube"],
            "max_per_platform": int(max_per_platform or 30),
            "status": "pending",  # pending → running → done | failed
            "progress": [],
            "stats": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        res = sb.table("obelisk_search_jobs").insert(row).select("id").execute()
        data = res.data or []
        job_id = data[0].get("id") if data else None
        return {"ok": True, "job_id": job_id}
    except Exception as exc:
        logger.warning("obelisk.create_search_job: %s", exc)
        return {"ok": False, "error": str(exc)}


def get_search_job(job_id: str) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        rows = (sb.table("obelisk_search_jobs").select("*")
                  .eq("id", job_id).limit(1).execute().data or [])
        if not rows:
            return {"ok": False, "error": "introuvable"}
        return {"ok": True, "job": rows[0]}
    except Exception as exc:
        logger.warning("obelisk.get_search_job: %s", exc)
        return {"ok": False, "error": str(exc)}


def list_recent_jobs(user_email: str = "", limit: int = 10) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": True, "jobs": [], "fallback": True}
    try:
        q = (sb.table("obelisk_search_jobs")
               .select("id, niche, platforms, status, stats, created_at, finished_at")
               .order("created_at", desc=True).limit(limit))
        if user_email:
            q = q.eq("user_email", user_email)
        return {"ok": True, "jobs": q.execute().data or []}
    except Exception as exc:
        logger.warning("obelisk.list_recent_jobs: %s", exc)
        return {"ok": True, "jobs": [], "error": str(exc)}
