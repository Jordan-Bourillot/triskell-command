"""Présence du serveur — battement de cœur + arbitrage desktop/serveur.

Le problème : les robots de fond (relances, lecture de boîte mail, etc.)
tournent dans le serveur web 24h/24, MAIS AUSSI dans l'application desktop
quand Jordan l'ouvre sur son PC. Deux instances du même robot sur les mêmes
données = double traitement (deux lecteurs IMAP qui se disputent le curseur,
deux moteurs de relances…). Les protections d'idempotence limitent la casse,
mais c'est jouer avec le feu.

La solution : le serveur pose un battement de cœur dans `shared_settings`
toutes les 5 minutes. Les robots qui tournent AILLEURS que sur le serveur
(desktop) vérifient ce battement avant chaque cycle : s'il est frais, ils
s'effacent (skip). Si le serveur meurt (> 15 min sans battement), le desktop
reprend automatiquement le relais — basculement de secours gratuit.

Le serveur se reconnaît via la variable d'environnement TRISKELL_IS_SERVER=1,
posée par http_server au démarrage. Aucun fichier desktop n'est modifié :
tout vit dans le code partagé des integrations.
"""
from __future__ import annotations

import logging
import os
import socket
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "server_heartbeat"
HEARTBEAT_INTERVAL_SEC = 300       # le serveur bat toutes les 5 min
FRESH_MAX_AGE_SEC = 900            # battement plus vieux que 15 min = mort


def is_server_process() -> bool:
    """True si CE process est le serveur web (env posée par http_server)."""
    return os.environ.get("TRISKELL_IS_SERVER", "").strip() == "1"


def mark_server_process() -> None:
    """À appeler une fois au boot du serveur web."""
    os.environ["TRISKELL_IS_SERVER"] = "1"


def beat(client) -> bool:
    """Pose/rafraîchit le battement de cœur. Renvoie True si écrit."""
    if client is None:
        return False
    try:
        client.set_shared_setting(HEARTBEAT_KEY, {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "host": socket.gethostname(),
        })
        return True
    except Exception as exc:
        logger.debug("heartbeat KO : %s", exc)
        return False


def _age_seconds(iso_ts: str) -> float | None:
    if not iso_ts:
        return None
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds()
    except Exception:
        return None


def server_alive(client, *, max_age_sec: int = FRESH_MAX_AGE_SEC) -> bool:
    """True si le serveur a battu récemment."""
    if client is None:
        return False
    try:
        hb = client.get_shared_setting(HEARTBEAT_KEY, None)
    except Exception:
        return False
    if not isinstance(hb, dict):
        return False
    age = _age_seconds(hb.get("at") or "")
    return age is not None and age < max_age_sec


def should_defer_to_server(client) -> bool:
    """True si CE process doit laisser le serveur faire le travail.

    - Sur le serveur lui-même → False (il travaille).
    - Sans accès à la base (client None) → False (comportement historique).
    - Ailleurs (desktop) → True si le serveur est vivant.
    """
    if is_server_process():
        return False
    if client is None:
        return False
    try:
        return server_alive(client)
    except Exception:
        return False
