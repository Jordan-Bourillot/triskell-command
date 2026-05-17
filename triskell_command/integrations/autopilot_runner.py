"""Autopilot Runner — déclencheur nocturne du pipeline de prospection.

Worker thread daemon qui dort la nuit et lance `run_full_pipeline()` à
l'heure programmée si `PipelineConfig.enabled` est vrai. Conçu pour
tourner côté serveur (Coolify), pour que la prospection nocturne marche
même quand Triskell Command desktop n'est pas allumé.

Approche : un cycle de 5 min qui vérifie si on est dans la fenêtre
[3h, 4h] heure Europe/Paris (par défaut) ET que le dernier run de
prospection n'a pas eu lieu aujourd'hui (Paris). Si oui, lance le
pipeline complet et trace la date du run dans shared_settings.

État partagé `shared_settings.autopilot_nightly` :
    {"last_run_date": "YYYY-MM-DD", "last_run_at": "...iso..."}

Pour désactiver la programmation, il suffit de mettre `enabled=False`
dans la config de l'autopilote (Réglages ou bouton mode du cockpit).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


SHARED_KEY = "autopilot_nightly"
DEFAULT_HOUR_PARIS = 3                    # déclenchement à 3h du matin
WINDOW_MINUTES = 60                       # fenêtre [3h, 4h]
CYCLE_INTERVAL_SECONDS = 5 * 60           # check toutes les 5 min
INITIAL_DELAY_SECONDS = 120

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


# ---------------------------------------------------------------------------
def _now_paris() -> datetime:
    """Retourne l'heure actuelle dans le fuseau Europe/Paris."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Paris"))
    except Exception:
        # Fallback : heure locale (peut être UTC sur Coolify, on assume +0h
        # d'écart c'est acceptable, le run partira juste à 3h UTC = 5h Paris
        # en été, mais Jordan le sait via les logs).
        return datetime.now()


def _supabase_client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        return c if c.is_authenticated else None
    except Exception:
        return None


def _read_state() -> dict:
    sb = _supabase_client()
    if sb is None:
        return {}
    try:
        raw = sb.get_shared_setting(SHARED_KEY, {}) or {}
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:
        logger.debug("autopilot_runner read_state: %s", exc)
        return {}


def _write_state(data: dict) -> None:
    sb = _supabase_client()
    if sb is None:
        return
    try:
        sb.set_shared_setting(SHARED_KEY, data)
    except Exception as exc:
        logger.debug("autopilot_runner write_state: %s", exc)


# ---------------------------------------------------------------------------
def start_worker(app_state) -> bool:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _WORKER_STOP.clear()
        t = threading.Thread(target=_loop, args=(app_state,),
                              name="AutopilotRunnerWorker", daemon=True)
        t.start()
        _WORKER_THREAD = t
    return True


def stop_worker() -> None:
    _WORKER_STOP.set()


def get_status() -> dict:
    return {
        "running":         _WORKER_THREAD is not None and _WORKER_THREAD.is_alive(),
        "last_run_at":     _LAST_RUN_AT,
        "last_run_result": dict(_LAST_RUN_RESULT),
    }


# ---------------------------------------------------------------------------
def _loop(app_state) -> None:
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        try:
            _do_one_tick(app_state)
        except Exception as exc:
            logger.exception("autopilot_runner tick a planté")
            _LAST_RUN_RESULT.clear()
            _LAST_RUN_RESULT["error"] = str(exc)
        finally:
            globals()["_LAST_RUN_AT"] = datetime.now().isoformat(timespec="seconds")
        if _WORKER_STOP.wait(CYCLE_INTERVAL_SECONDS):
            return


def _do_one_tick(app_state) -> None:
    """Un seul cycle : décide si on doit lancer le pipeline."""
    # Charge la config de l'autopilote
    try:
        from triskell_core.prospect.pipeline import (
            PipelineConfig, run_full_pipeline,
        )
        cfg = PipelineConfig.load()
    except Exception as exc:
        logger.debug("autopilot_runner load config: %s", exc)
        _LAST_RUN_RESULT.clear()
        _LAST_RUN_RESULT["skipped_reason"] = f"config_unavailable:{exc}"
        return

    if not getattr(cfg, "enabled", False):
        _LAST_RUN_RESULT.clear()
        _LAST_RUN_RESULT["skipped_reason"] = "disabled"
        return

    now = _now_paris()
    if now.hour != DEFAULT_HOUR_PARIS:
        _LAST_RUN_RESULT.clear()
        _LAST_RUN_RESULT["skipped_reason"] = f"outside_window:hour={now.hour}"
        return

    today_iso = now.date().isoformat()
    state = _read_state()
    if state.get("last_run_date") == today_iso:
        _LAST_RUN_RESULT.clear()
        _LAST_RUN_RESULT["skipped_reason"] = "already_ran_today"
        return

    # On y va : trace la tentative AVANT de lancer (anti-double si redémarrage
    # pendant l'exécution).
    _write_state({
        "last_run_date":  today_iso,
        "last_run_at":    now.isoformat(timespec="seconds"),
        "last_run_status": "started",
    })

    log_lines: list[str] = []

    def _progress(msg: str) -> None:
        log_lines.append(msg)
        logger.info("[autopilot_nightly] %s", msg)

    try:
        _progress(f"Lancement nocturne du pipeline (mode {cfg.mode})…")
        stats = run_full_pipeline(cfg, progress=_progress)
        _LAST_RUN_RESULT.clear()
        _LAST_RUN_RESULT.update({
            "searched":         getattr(stats, "searched", 0),
            "enriched":         getattr(stats, "enriched", 0),
            "drafts_sent":      getattr(stats, "drafts_sent", 0),
            "drafts_pending":   getattr(stats, "drafts_pending", 0),
            "replies_detected": getattr(stats, "replies_detected", 0),
            "errors":           list(getattr(stats, "errors", []) or []),
            "log_tail":         log_lines[-20:],
        })
        _write_state({
            "last_run_date":   today_iso,
            "last_run_at":     now.isoformat(timespec="seconds"),
            "last_run_status": "ok",
            "last_run_stats":  dict(_LAST_RUN_RESULT),
        })
    except Exception as exc:
        logger.exception("autopilot_nightly run a échoué")
        _LAST_RUN_RESULT.clear()
        _LAST_RUN_RESULT["error"] = str(exc)
        _LAST_RUN_RESULT["log_tail"] = log_lines[-20:]
        _write_state({
            "last_run_date":   today_iso,
            "last_run_at":     now.isoformat(timespec="seconds"),
            "last_run_status": "failed",
            "last_run_error":  str(exc),
        })
