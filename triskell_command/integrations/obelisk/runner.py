"""Runner Obelisk : lance les recherches en arrière-plan.

Quand l'utilisateur clique sur "Nouvelle recherche" dans la vue Obelisk de
Triskell Command :
  1. on crée un search job (table obelisk_search_jobs, status=pending)
  2. on spawn un thread daemon qui exécute la recherche :
     - plateformes natives (YouTube/Twitch/Reddit/Bluesky/Mastodon/
       Podcasts/Dailymotion/Kick/GitHub) → triskell_core.prospect
       .creators_pipeline.run_creators_pipeline
     - plateformes PhantomBuster (LinkedIn/Instagram/TikTok) →
       phantom_discovery.discover_profiles (un appel par plateforme,
       en séquence pour rester gentil avec les quotas)
  3. à chaque progression, on met à jour le job (status, progress, stats)
  4. le frontend poll get_search_job(job_id) toutes les 2 s

Les profils trouvés atterrissent dans la table partagée `public.prospects`,
peu importe la source.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from . import repo

logger = logging.getLogger(__name__)


# Plateformes qui passent par PhantomBuster (découverte). Toutes les autres
# sont gérées par run_creators_pipeline (sources natives : YouTube etc.).
PHANTOM_PLATFORMS = ("linkedin", "instagram", "tiktok")

# job_id → Thread (pour pouvoir savoir si une recherche tourne encore localement)
_RUNNING: dict[str, threading.Thread] = {}


def start_search(user_email: str, niche: str, platforms: list[str],
                 max_per_platform: int = 30,
                 config_overrides: Optional[dict] = None) -> dict:
    """Crée le job en base, le lance dans un thread daemon, renvoie le job_id.

    config_overrides : permet d'override la config user (utile pour les tests).
    """
    if not niche or not niche.strip():
        return {"ok": False, "error": "niche requise"}
    if not platforms:
        return {"ok": False, "error": "au moins une plateforme requise"}

    created = repo.create_search_job(user_email, niche.strip(), platforms, max_per_platform)
    if not created.get("ok"):
        return created
    job_id = created.get("job_id")
    if not job_id:
        return {"ok": False, "error": "job sans id"}

    t = threading.Thread(
        target=_run_thread,
        args=(job_id, user_email, niche, platforms, max_per_platform, config_overrides or {}),
        daemon=True,
        name=f"obelisk-search-{job_id[:8]}",
    )
    _RUNNING[job_id] = t
    t.start()
    return {"ok": True, "job_id": job_id}


def is_running(job_id: str) -> bool:
    t = _RUNNING.get(job_id)
    return bool(t and t.is_alive())


def _update_job(job_id: str, **fields) -> None:
    """Best-effort : met à jour le job (silencieux si erreur)."""
    sb = repo._sb()
    if sb is None:
        return
    try:
        sb.table("obelisk_search_jobs").update(fields).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning("obelisk._update_job(%s): %s", job_id, exc)


def _run_thread(job_id: str, user_email: str, niche: str, platforms: list[str],
                max_per_platform: int, overrides: dict) -> None:
    """Exécute le pipeline dans un thread. Toujours catch global pour
    ne jamais crash le worker."""
    progress_lines: list[str] = []

    def log(msg: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        progress_lines.append(line)
        # Tronque pour éviter d'écrire un blob jsonb géant
        trimmed = progress_lines[-200:]
        _update_job(job_id, progress=trimmed)

    _update_job(job_id, status="running",
                started_at=datetime.now(timezone.utc).isoformat())
    try:
        # Charge la config user (fusionnée avec defaults) + applique overrides
        cfg_res = repo.get_user_config(user_email)
        ucfg = cfg_res.get("config") or {}
        ucfg.update(overrides)
        ucfg["niche"] = niche
        ucfg["platforms"] = platforms
        ucfg["max_per_platform"] = max_per_platform

        # Import paresseux pour ne pas alourdir le boot de Command
        try:
            from triskell_core.prospect.creators_pipeline import (
                AutopilotConfig, run_creators_pipeline,
            )
        except Exception as exc:
            log(f"⚠ triskell_core.prospect.creators_pipeline introuvable : {exc}")
            _update_job(job_id, status="failed", error=str(exc),
                        finished_at=datetime.now(timezone.utc).isoformat())
            return

        # Construit la dataclass AutopilotConfig depuis le dict, en ignorant
        # les clés qu'elle ne connaît pas.
        try:
            allowed = AutopilotConfig.__dataclass_fields__.keys()
        except Exception:
            allowed = set()
        cfg_kwargs = {k: v for k, v in ucfg.items() if k in allowed}
        try:
            cfg = AutopilotConfig(**cfg_kwargs)
        except Exception as exc:
            log(f"⚠ AutopilotConfig invalide : {exc}")
            cfg = AutopilotConfig()
            cfg.niche = niche
            cfg.platforms = platforms
            cfg.max_per_platform = max_per_platform

        # Sépare plateformes natives (creators_pipeline) vs PhantomBuster.
        native_platforms = [p for p in platforms if p not in PHANTOM_PLATFORMS]
        phantom_platforms = [p for p in platforms if p in PHANTOM_PLATFORMS]

        agg_stats: dict[str, Any] = {
            "found": 0, "enriched": 0, "drafts": 0,
            "phantom_inserted": 0, "phantom_skipped": 0,
            "per_platform": {},
        }

        # 1) Pipeline natif (YouTube, Twitch, Reddit, etc.)
        if native_platforms:
            cfg.platforms = native_platforms
            log(f"Démarrage recherche natives '{niche}' sur "
                f"{', '.join(native_platforms)}…")
            stats = run_creators_pipeline(cfg, progress=log) or {}
            agg_stats["found"]    += int(stats.get("found", 0) or 0)
            agg_stats["enriched"] += int(stats.get("enriched", 0) or 0)
            agg_stats["drafts"]   += int(stats.get("drafts", 0) or 0)
            agg_stats["per_platform"]["_native"] = stats

        # 2) Phantoms (LinkedIn / Instagram / TikTok)
        if phantom_platforms:
            _run_phantom_platforms(
                niche=niche,
                platforms=phantom_platforms,
                max_per_platform=max_per_platform,
                log=log,
                agg_stats=agg_stats,
            )

        log(f"Terminé : {agg_stats['found']} trouvés, "
            f"{agg_stats['enriched']} enrichis, "
            f"{agg_stats['drafts']} drafts, "
            f"{agg_stats['phantom_inserted']} via PhantomBuster.")
        _update_job(job_id, status="done", stats=agg_stats,
                    finished_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        logger.exception("obelisk._run_thread crashed: %s", exc)
        log(f"💥 Erreur : {exc}")
        _update_job(job_id, status="failed", error=str(exc),
                    finished_at=datetime.now(timezone.utc).isoformat())
    finally:
        _RUNNING.pop(job_id, None)


# ---------------------------------------------------------------------------
# Helpers PhantomBuster (discovery)
# ---------------------------------------------------------------------------
def _run_phantom_platforms(*, niche: str, platforms: list[str],
                            max_per_platform: int,
                            log,
                            agg_stats: dict) -> None:
    """Exécute la découverte PhantomBuster pour chaque plateforme demandée,
    en séquence. Met à jour agg_stats en place.

    Les phantoms sont lents (10-30 min chacun) — on log régulièrement
    pour que l'UI affiche un signe de vie.
    """
    try:
        from .. import phantombuster_client, phantom_discovery
    except Exception as exc:
        log(f"⚠ PhantomBuster indisponible : {exc}")
        return

    sb = repo._sb()
    if sb is None:
        log("⚠ Supabase non joignable : impossible d'insérer les profils.")
        return

    triskell_client = None
    try:
        from triskell_core.db import get_client as _gc, SupabaseNotConfigured
        try:
            tc = _gc()
            if tc.is_authenticated:
                triskell_client = tc
        except SupabaseNotConfigured:
            pass
    except Exception:
        pass
    pb_cfg = phantombuster_client.load_config(triskell_client)
    api_key = (pb_cfg or {}).get("api_key") or ""
    phantoms = (pb_cfg or {}).get("discovery_phantoms") or {}
    if not api_key:
        log("⚠ Clé API PhantomBuster manquante (Réglages → Intégrations).")
        return

    for platform in platforms:
        phantom_id = (phantoms or {}).get(platform) or ""
        if not phantom_id:
            log(f"⚠ Phantom {platform} non configuré (Réglages → PhantomBuster).")
            continue
        log(f"════════ {platform.upper()} ════════")
        try:
            res = phantom_discovery.discover_profiles(
                sb=sb,
                api_key=api_key,
                platform=platform,
                phantom_id=phantom_id,
                niche=niche,
                max_results=max_per_platform,
                progress=log,
            )
        except Exception as exc:
            log(f"💥 {platform} : {exc}")
            continue
        if not res.get("ok"):
            log(f"⚠ {platform} : {res.get('error') or 'échec'}")
            continue
        agg_stats["phantom_inserted"] += int(res.get("inserted", 0) or 0)
        agg_stats["phantom_skipped"]  += int(res.get("skipped",  0) or 0)
        agg_stats["found"]            += int(res.get("profiles_found", 0) or 0)
        agg_stats["per_platform"][platform] = {
            "profiles_found": res.get("profiles_found", 0),
            "inserted":       res.get("inserted", 0),
            "skipped":        res.get("skipped", 0),
            "errors":         res.get("errors", 0),
        }
