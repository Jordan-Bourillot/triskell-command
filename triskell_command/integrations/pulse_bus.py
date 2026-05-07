"""Bus d'événements pour la pulsation système.

Découple les workers (sync, replies, drip, etc.) de l'UI (`WorkerPulse`).
Chaque worker appelle `pulse_bus.report(...)` à des moments-clés ; l'UI
s'abonne via `pulse_bus.subscribe(...)` pour recevoir les événements et
les pousser dans la barre de pulsation en bas d'écran.

Si aucun subscriber n'est enregistré (ex : tests, mode CLI, app pas
encore prête) : les `report()` sont des no-op silencieux. Aucun risque
de planter un worker à cause d'un bug d'UI.

Usage côté worker :

    from . import pulse_bus
    pulse_bus.report("sync", "active", text="48 prospects synchros",
                     relative_time="à l'instant")
    # ... travail réel ...
    pulse_bus.report("sync", "idle")

Usage côté UI (une seule fois au boot) :

    pulse_bus.subscribe(lambda evt: app.worker_pulse.update_worker(
        evt["key"], state=evt["state"],
        last_activity_text=evt.get("text", ""),
        relative_time=evt.get("relative_time", ""),
        error_message=evt.get("error", ""),
    ))
"""

from __future__ import annotations

import logging
from threading import Lock
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_lock = Lock()
_subscriber: Optional[Callable[[dict], None]] = None


def subscribe(callback: Callable[[dict], None]) -> None:
    """Enregistre l'unique consommateur (UI). Idempotent — un seul à la fois.

    Le callback peut être invoqué depuis n'importe quel thread (les
    workers tournent en background). C'est à l'implémenteur de
    re-scheduler sur le mainloop Tk via `after(0, ...)` si l'UI a
    besoin de cette garantie.
    """
    global _subscriber
    with _lock:
        _subscriber = callback


def unsubscribe() -> None:
    """Retire le subscriber courant (utile aux tests)."""
    global _subscriber
    with _lock:
        _subscriber = None


def report(
    key: str,
    state: str,
    *,
    text: str = "",
    relative_time: str = "",
    error: str = "",
) -> None:
    """Publie un événement worker. No-op si personne n'écoute.

    `key` doit matcher une des clés dans `widgets/worker_pulse.WORKERS`
    (sync, replies, responder, drip, postsale, phare).

    `state` parmi : "idle", "active", "error", "off".

    Le bus avale silencieusement toute exception du subscriber pour ne
    jamais perturber le worker qui publie.
    """
    sub = _subscriber
    if sub is None:
        return
    try:
        sub({
            "key": key,
            "state": state,
            "text": text,
            "relative_time": relative_time,
            "error": error,
        })
    except Exception as exc:
        logger.debug("pulse_bus subscriber raised: %s", exc)


__all__ = ["subscribe", "unsubscribe", "report"]
