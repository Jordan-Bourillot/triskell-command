"""Chef de gare des missions — worker qui fait avancer la chaîne.

Toutes les 45 s : regarde les missions actives, vérifie où en est leur
chasse, verse les résultats dans la base partagée dès que c'est fini,
puis donne un coup d'épaule à l'Auto-pilote. Voir missions.py pour la
machine à états (pure, testée).

Même patron que les autres robots : thread daemon, statut exposé pour la
page Santé, et retrait automatique côté desktop quand le serveur bat.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

CYCLE_INTERVAL_SECONDS = 45
INITIAL_DELAY_SECONDS = 90

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


def start_worker(app_state) -> bool:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _WORKER_STOP.clear()
        t = threading.Thread(target=_loop, args=(app_state,),
                              name="MissionRunnerWorker", daemon=True)
        t.start()
        _WORKER_THREAD = t
    return True


def stop_worker() -> None:
    _WORKER_STOP.set()


def get_status() -> dict:
    return {
        "running": _WORKER_THREAD is not None and _WORKER_THREAD.is_alive(),
        "last_run_at": _LAST_RUN_AT,
        "last_run_result": dict(_LAST_RUN_RESULT),
    }


def run_now(app_state=None) -> dict:
    return _do_one_cycle(app_state)


def _set_run(result: dict) -> None:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
    _LAST_RUN_RESULT = result


def _loop(app_state) -> None:
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        try:
            _do_one_cycle(app_state)
        except Exception as exc:
            logger.warning("MissionRunner cycle: %s", exc)
        for _ in range(max(1, CYCLE_INTERVAL_SECONDS // 5)):
            if _WORKER_STOP.is_set():
                return
            time.sleep(5)


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


def _do_one_cycle(app_state) -> dict:
    counters = {"scanned": 0, "advanced": 0, "errors": 0}

    client = _get_client()
    if client is None:
        counters["error"] = "supabase_unavailable"
        _set_run(counters)
        return counters

    # Anti-double-traitement : le serveur fait avancer les missions ;
    # le desktop s'efface tant que le serveur bat.
    from .server_presence import should_defer_to_server
    if should_defer_to_server(client):
        counters["skipped_reason"] = "server_active"
        _set_run(counters)
        return counters

    from . import missions
    try:
        result = missions.tick(client)
        counters.update(result)
    except Exception as exc:
        counters["error"] = str(exc)
    _set_run(counters)
    return counters
