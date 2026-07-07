"""Veille proactive de Claude.

Toutes les 4 heures (par défaut), interroge claude_advisor en mode "proactive".
Si la réponse a urgency=high (ou medium si activé), pousse un événement
vers l'UI (callback set par main.py au boot) avec :
  - le headline court
  - le conseil complet (mis en cache pour la prochaine ouverture du dialog)

L'UI décide ensuite :
- Si la window est focusée → toast + pastille sidebar
- Sinon → juste pastille sidebar

Configuration via shared_settings.claude_proactive ou settings.json local :
  enabled: bool       (default True)
  interval_minutes    (default 240 — soit toutes les 4h)
  notify_on_medium    (default False — ne notifie que high)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    # 240 (4h) et non 60 : la veille appelait l'IA CHAQUE heure 24/7, soit
    # ~24 appels/jour pour presque rien la plupart du temps. À 4h -> ~6/jour,
    # on divise la note par 4 sans rater les vraies urgences (le chien de
    # garde des robots alerte déjà en direct). Réglable via shared_settings.
    "interval_minutes": 240,
    "notify_on_medium": False,
    "min_seconds_between_notifications": 60 * 60 * 3,  # 3h anti-spam
}

INITIAL_DELAY_SECONDS = 90

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_NOTIFICATION_AT: float = 0.0  # epoch
_PENDING_ADVICE: Optional[dict] = None
_NOTIFY_CALLBACK: Optional[Callable[[dict], None]] = None


def set_notify_callback(cb: Callable[[dict], None]) -> None:
    """L'UI passe ici la fonction qui sera appelée quand Claude veut parler.

    Le callback reçoit le dict de conseil complet et est responsable de
    décider quoi faire (toast, pastille sidebar, son, etc.). Il tourne
    sur le thread Tk si l'appelant l'a souhaité (à charger côté caller via
    self.after(0, ...))."""
    global _NOTIFY_CALLBACK
    _NOTIFY_CALLBACK = cb


def consume_pending_advice() -> Optional[dict]:
    """Pop l'avis en attente (lu une seule fois). Permet à ClaudeDialog
    d'afficher tout de suite la suggestion proactive sans re-appeler l'API."""
    global _PENDING_ADVICE
    advice = _PENDING_ADVICE
    _PENDING_ADVICE = None
    return advice


def get_status() -> dict:
    return {
        "running": _WORKER_THREAD is not None and _WORKER_THREAD.is_alive(),
        "last_run_at": _LAST_RUN_AT,
        "has_pending_advice": _PENDING_ADVICE is not None,
    }


def start_worker(app_state) -> bool:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _WORKER_STOP.clear()
        t = threading.Thread(target=_loop, args=(app_state,),
                              name="ClaudeProactive", daemon=True)
        t.start()
        _WORKER_THREAD = t
    return True


def stop_worker() -> None:
    _WORKER_STOP.set()


def _load_config(app_state) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    # Préfère shared_settings (synchro Jordan/Thomas)
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            client = get_client()
            if client.is_authenticated:
                raw = client.get_shared_setting("claude_proactive", {}) or {}
                if isinstance(raw, dict):
                    cfg.update(raw)
        except SupabaseNotConfigured:
            pass
    except ImportError:
        pass
    # Override par les prefs locales
    local = app_state.get("claude_proactive", default={}) or {}
    if isinstance(local, dict):
        cfg.update(local)
    return cfg


def _loop(app_state) -> None:
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        try:
            _do_one_cycle(app_state)
        except Exception as exc:
            logger.warning("claude_proactive cycle: %s", exc)
        cfg = _load_config(app_state)
        interval = max(15, int(cfg.get("interval_minutes") or 60)) * 60
        for _ in range(interval // 5):
            if _WORKER_STOP.is_set():
                return
            time.sleep(5)


def _do_one_cycle(app_state) -> None:
    global _LAST_RUN_AT, _LAST_NOTIFICATION_AT, _PENDING_ADVICE
    _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")

    cfg = _load_config(app_state)
    if not cfg.get("enabled", True):
        return

    # Anti-spam : si on a notifié il y a moins de min_seconds, on saute
    min_gap = int(cfg.get("min_seconds_between_notifications") or 0)
    now = time.time()
    if min_gap and (now - _LAST_NOTIFICATION_AT) < min_gap:
        return

    try:
        from . import claude_advisor
        advice = claude_advisor.ask_claude(app_state, mode="proactive")
    except Exception as exc:
        logger.debug("claude_advisor: %s", exc)
        return

    if not advice.get("ok"):
        return

    urgency = advice.get("urgency", "low")
    notify = (urgency == "high") or (
        urgency == "medium" and cfg.get("notify_on_medium")
    )
    if not notify:
        return

    _PENDING_ADVICE = advice
    _LAST_NOTIFICATION_AT = now

    if _NOTIFY_CALLBACK is not None:
        try:
            _NOTIFY_CALLBACK(advice)
        except Exception as exc:
            logger.warning("notify callback: %s", exc)
