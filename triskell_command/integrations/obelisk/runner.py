"""Runner Obelisk : lance run_creators_pipeline en arrière-plan.

Quand l'utilisateur clique sur "Nouvelle recherche" dans la vue Obelisk de
Triskell Command :
  1. on crée un search job (table obelisk_search_jobs, status=pending)
  2. on spawn un thread daemon qui exécute le pipeline créateurs
     (via triskell_core.prospect.creators_pipeline.run_creators_pipeline)
  3. à chaque progression, on met à jour le job (status, progress, stats)
  4. le frontend poll get_search_job(job_id) toutes les 2 s

Le pipeline pousse les prospects trouvés dans la table `prospects` via
le RemoteCRM (déjà branché dans triskell_core.prospect.core.crm).
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from . import repo

logger = logging.getLogger(__name__)

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

        log(f"Démarrage recherche '{niche}' sur {', '.join(platforms)}…")
        stats = run_creators_pipeline(cfg, progress=log)
        log(f"Terminé : {stats.get('found', 0)} trouvés, "
            f"{stats.get('enriched', 0)} enrichis, "
            f"{stats.get('drafts', 0)} drafts.")
        _update_job(job_id, status="done", stats=stats,
                    finished_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        logger.exception("obelisk._run_thread crashed: %s", exc)
        log(f"💥 Erreur : {exc}")
        _update_job(job_id, status="failed", error=str(exc),
                    finished_at=datetime.now(timezone.utc).isoformat())
    finally:
        _RUNNING.pop(job_id, None)
