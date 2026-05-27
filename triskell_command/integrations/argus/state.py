"""État partagé d'une session Argus.

Une session = un run de scraping (toutes sources, un mot-clé, une zone).
À tout moment il n'y a qu'une session active à la fois (singleton global).

L'état est thread-safe (Lock interne) car le scraping tourne dans un thread
daemon pendant que l'UI poll get_status() depuis un thread FastAPI.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Dossier de persistance pour les sessions (état + fichier Excel).
ARGUS_DIR = Path.home() / ".triskell-command" / "argus"
SESSIONS_DIR = ARGUS_DIR / "sessions"
EXPORTS_DIR = ARGUS_DIR / "exports"


@dataclass
class SourceProgress:
    status: str = "pending"   # pending | running | done | error | stopped
    found: int = 0
    visited_pages: int = 0
    message: str = ""


@dataclass
class LogEntry:
    timestamp: float
    level: str                # info | warn | error | success
    source: str
    message: str

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "time": time.strftime("%H:%M:%S", time.localtime(self.timestamp)),
            "level": self.level,
            "source": self.source,
            "message": self.message,
        }


class ArgusState:
    """État global d'une session Argus. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.is_running: bool = False
        self.is_paused: bool = False
        self.should_stop: bool = False

        # Event asyncio utilisé par les coroutines pour respecter la pause.
        # Recréé à chaque session (lié à l'event loop du thread courant).
        self.not_paused_event: Optional[asyncio.Event] = None

        self.emails: set[str] = set()
        self.discovered_sites: set[str] = set()
        self.reference_emails: set[str] = set()

        self.sources: dict[str, SourceProgress] = {}
        self.logs: list[LogEntry] = []

        # Paramètres + métadonnées de la session courante.
        self.params: dict = {}
        self.started_at: float = 0.0
        self.finished_at: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Remet l'état à zéro avant un nouveau run."""
        with self._lock:
            self.is_running = False
            self.is_paused = False
            self.should_stop = False
            self.emails.clear()
            self.discovered_sites.clear()
            self.sources.clear()
            self.logs.clear()
            self.started_at = 0.0
            self.finished_at = 0.0

    def attach_loop_event(self, loop: asyncio.AbstractEventLoop) -> None:
        """Crée l'event asyncio lié à l'event loop du thread courant.
        À appeler depuis le thread daemon une fois l'event loop créé."""
        with self._lock:
            self.not_paused_event = asyncio.Event()
            self.not_paused_event.set()

    # ------------------------------------------------------------------
    # Pause / reprise / stop
    # ------------------------------------------------------------------

    def pause(self) -> None:
        with self._lock:
            self.is_paused = True
            if self.not_paused_event is not None:
                self.not_paused_event.clear()
            self._log("info", "system", "Pause demandée.")

    def resume(self) -> None:
        with self._lock:
            self.is_paused = False
            if self.not_paused_event is not None:
                self.not_paused_event.set()
            self._log("info", "system", "Reprise.")

    def stop(self) -> None:
        with self._lock:
            self.should_stop = True
            # On débloque la pause si on était en pause, pour que les coroutines
            # puissent sortir proprement.
            if self.not_paused_event is not None:
                self.not_paused_event.set()
            self._log("warn", "system", "Arrêt demandé.")

    async def wait_if_paused(self) -> None:
        """À appeler dans chaque scraper entre chaque action."""
        ev = self.not_paused_event
        if ev is not None:
            await ev.wait()

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------

    def log(self, level: str, source: str, message: str) -> None:
        with self._lock:
            self._log(level, source, message)

    def _log(self, level: str, source: str, message: str) -> None:
        """Variante sans lock pour appels internes déjà sous lock."""
        entry = LogEntry(time.time(), level, source, message)
        self.logs.append(entry)
        if len(self.logs) > 5000:
            self.logs = self.logs[-3000:]

    # ------------------------------------------------------------------
    # Sources et résultats
    # ------------------------------------------------------------------

    def init_source(self, source: str) -> None:
        with self._lock:
            self.sources[source] = SourceProgress(status="running")

    def update_source(
        self,
        source: str,
        *,
        status: str | None = None,
        found: int | None = None,
        visited_pages: int | None = None,
        message: str | None = None,
    ) -> None:
        with self._lock:
            sp = self.sources.setdefault(source, SourceProgress())
            if status is not None:
                sp.status = status
            if found is not None:
                sp.found = found
            if visited_pages is not None:
                sp.visited_pages = visited_pages
            if message is not None:
                sp.message = message

    def add_email(self, email: str, source: str) -> bool:
        """Ajoute un email. Retourne True si nouveau, False si doublon."""
        with self._lock:
            if email in self.emails or email in self.reference_emails:
                return False
            self.emails.add(email)
            return True

    def add_site(self, url: str) -> None:
        if not url:
            return
        with self._lock:
            self.discovered_sites.add(url)

    # ------------------------------------------------------------------
    # Snapshot pour l'UI
    # ------------------------------------------------------------------

    def snapshot(self, log_tail: int = 200) -> dict:
        """Renvoie une copie sérialisable de l'état pour l'UI."""
        with self._lock:
            return {
                "is_running": self.is_running,
                "is_paused": self.is_paused,
                "should_stop": self.should_stop,
                "total_emails": len(self.emails),
                "reference_count": len(self.reference_emails),
                "sites_discovered": len(self.discovered_sites),
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "params": dict(self.params),
                "sources": {
                    name: {
                        "status": sp.status,
                        "found": sp.found,
                        "visited_pages": sp.visited_pages,
                        "message": sp.message,
                    }
                    for name, sp in self.sources.items()
                },
                "logs": [e.to_dict() for e in self.logs[-log_tail:]],
            }

    # ------------------------------------------------------------------
    # Persistance JSON minimale (pour survivre à un restart serveur)
    # ------------------------------------------------------------------

    def save_to_disk(self) -> None:
        try:
            SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
            path = SESSIONS_DIR / "current.json"
            with self._lock:
                payload = {
                    "is_running": self.is_running,
                    "is_paused": self.is_paused,
                    "should_stop": self.should_stop,
                    "emails": sorted(self.emails),
                    "params": dict(self.params),
                    "started_at": self.started_at,
                    "finished_at": self.finished_at,
                    "sources": {
                        n: {
                            "status": sp.status,
                            "found": sp.found,
                            "visited_pages": sp.visited_pages,
                            "message": sp.message,
                        }
                        for n, sp in self.sources.items()
                    },
                    "logs": [e.to_dict() for e in self.logs[-500:]],
                }
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            # Persistance best-effort : si ça plante on s'en moque.
            pass

    def load_from_disk(self) -> None:
        """Restaure la dernière session connue (utile au boot du serveur)."""
        try:
            path = SESSIONS_DIR / "current.json"
            if not path.exists():
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            with self._lock:
                self.emails = set(data.get("emails") or [])
                self.params = dict(data.get("params") or {})
                self.started_at = float(data.get("started_at") or 0.0)
                self.finished_at = float(data.get("finished_at") or 0.0)
                # Un run reprenant après un crash : on considère qu'il est terminé.
                self.is_running = False
                self.is_paused = False
                self.should_stop = False
                for name, sp_data in (data.get("sources") or {}).items():
                    sp = SourceProgress(
                        status=sp_data.get("status", "done"),
                        found=int(sp_data.get("found", 0)),
                        visited_pages=int(sp_data.get("visited_pages", 0)),
                        message=sp_data.get("message", ""),
                    )
                    # Si on était au milieu d'un run quand le serveur a planté,
                    # on marque les sources "running" comme arrêtées.
                    if sp.status == "running":
                        sp.status = "stopped"
                    self.sources[name] = sp
                # Reconstruit les logs (pour montrer "session précédente").
                self.logs.clear()
                for entry in (data.get("logs") or []):
                    self.logs.append(LogEntry(
                        timestamp=float(entry.get("timestamp", 0.0)),
                        level=str(entry.get("level", "info")),
                        source=str(entry.get("source", "system")),
                        message=str(entry.get("message", "")),
                    ))
        except Exception:
            pass


# Singleton global.
state = ArgusState()

# Tente de restaurer la dernière session au démarrage du module.
state.load_from_disk()
