"""Sync léger : polling 15s des tables clés pour qu'un changement chez
Jordan apparaisse chez Thomas (et vice-versa) sans rebooter l'app.

Pourquoi du polling et pas le client Realtime Supabase :
- Le client Python `supabase-py` supporte Realtime mais c'est moins
  mature qu'en JS (websocket fragile depuis un Tk mainloop).
- 2 users → 4 polls/min pour 2 personnes = négligeable côté quota
  Supabase (free tier autorise des milliers de requêtes/heure).
- Plus simple à débugger. Si plus tard on a 5+ users, on bascule sur
  Realtime sans changer l'API publique.

Usage : `SyncPoller.start(app, on_change)` au boot. Stoppe automatiquement
si l'app se ferme. L'API publique est volontairement minimale.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)


# Tables à surveiller : (nom, intervalle_seconds)
WATCH_TABLES = {
    "prospects": 30,
    "prospect_drafts": 15,
    "convoy_drafts": 15,
    "convoy_campaigns": 30,
    "email_history": 30,
    "shared_settings": 60,
    "messages": 10,                  # chat 1-à-1 — réactif
}

# Étiquettes lisibles pour la barre de pulsation ("prospect_drafts" →
# "brouillons prospects"). Si une table n'est pas mappée, on retombe
# sur son nom technique.
_TABLE_LABELS = {
    "prospects":        "prospects",
    "prospect_drafts":  "brouillons prospects",
    "convoy_drafts":    "brouillons convoi",
    "convoy_campaigns": "campagnes convoi",
    "email_history":    "historique emails",
    "shared_settings":  "réglages partagés",
    "messages":         "chat",
}


class SyncPoller:
    """Poll Supabase à intervalles, déclenche un callback quand ça a bougé.

    Le callback reçoit `table_name: str` du table qui a changé. À charge
    du consommateur de rafraîchir les vues qui en dépendent.
    """

    def __init__(self, on_change: Callable[[str], None]):
        self._on_change = on_change
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_seen: dict[str, str] = {}    # table → dernier updated_at
        self._client = None

    def start(self) -> bool:
        """Lance le poller. Renvoie False si Supabase pas dispo."""
        try:
            from triskell_core.db import get_client, SupabaseNotConfigured
            try:
                self._client = get_client()
            except SupabaseNotConfigured:
                return False
            if not self._client.is_authenticated:
                return False
        except ImportError:
            return False
        except Exception:
            return False

        # Pré-charge l'état actuel pour ne pas trigger au 1er passage
        for table in WATCH_TABLES:
            self._last_seen[table] = self._fetch_max_updated(table) or ""

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # On poll chaque table à son propre rythme grâce à un compteur de tours
        ticks = {t: 0 for t in WATCH_TABLES}
        while not self._stop.is_set():
            for table, interval in WATCH_TABLES.items():
                ticks[table] += 1
                # 1 tick = 5 secondes ; on ne poll que si ticks * 5 >= interval
                if ticks[table] * 5 < interval:
                    continue
                ticks[table] = 0
                try:
                    cur = self._fetch_max_updated(table) or ""
                    prev = self._last_seen.get(table, "")
                    if cur and cur != prev:
                        self._last_seen[table] = cur
                        try:
                            self._on_change(table)
                        except Exception as exc:
                            logger.debug("on_change(%s) : %s", table, exc)
                        # Pulse worker : changement détecté côté Supabase
                        try:
                            from . import pulse_bus
                            pulse_bus.report(
                                "sync", "active",
                                text=f"{_TABLE_LABELS.get(table, table)} synchronisés",
                                relative_time="à l'instant",
                            )
                        except Exception:
                            pass
                except Exception as exc:
                    logger.debug("Poll %s : %s", table, exc)
            # Sleep court (5s) pour permettre des stops rapides
            for _ in range(5):
                if self._stop.is_set():
                    return
                time.sleep(1)

    def _fetch_max_updated(self, table: str) -> str | None:
        """Récupère le max(updated_at) de la table (ou created_at si pas
        d'updated_at)."""
        if self._client is None:
            return None
        col = "updated_at"
        # `messages` n'a pas d'updated_at — un message envoyé n'est pas
        # modifié, on poll created_at pour détecter les nouveaux.
        if table in ("messages",):
            col = "created_at"
        try:
            res = (self._client.raw.table(table).select(col)
                   .order(col, desc=True).limit(1).execute())
            data = res.data or []
            if data:
                return str(data[0].get(col) or "")
        except Exception as exc:
            logger.debug("fetch_max_updated %s : %s", table, exc)
        return None
