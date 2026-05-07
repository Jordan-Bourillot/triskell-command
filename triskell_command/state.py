"""État global de l'app + persistance des préférences utilisateur.

Stocké dans ~/.triskell-command/settings.json.
Le CRM lui-même reste dans ~/.triskell-prospect/ (géré par Triskell Core).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


APP_DIR = Path.home() / ".triskell-command"
SETTINGS_FILE = APP_DIR / "settings.json"


DEFAULT_SETTINGS: dict[str, Any] = {
    "appearance_mode": "light",         # light | mid | dark (light par défaut, Apple-clear)
    "active_view": "morning",           # vue affichée au lancement
    "ai": {
        "selected_provider": "anthropic",
        "selected_model": "claude-sonnet-4-5",
        "api_keys": {
            "anthropic": "",
            "openai": "",
            "google": "",
            "mistral": "",
            "xai": "",
        },
        "default_mega_prompts": ["01"],  # IDs des méga-prompts pré-cochés
    },
    "outreach": {
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_password": "",
        "from_email": "",
        "from_name": "",
        "imap_host": "",
        "imap_port": 993,
        "imap_user": "",
        "imap_password": "",
        "daily_cap": 40,
        "follow_up_days": 5,
        "mon_prenom": "",
        "signature": "",
    },
    "sources": {
        "youtube_api_key": "",
        "twitch_client_id": "",
        "twitch_client_secret": "",
        "google_places_api_key": "",
    },
    "social": {
        "reseaux_api_url": "https://reseauxapi-production.up.railway.app",
        "reseaux_jwt": "",
    },
    "publish_auto": {
        "enabled": True,
        "cadence": {           # X premiers contacts entre deux drafts
            "linkedin": 10,
            "x": 3,
            "bluesky": 5,
        },
        "daily_cap": {         # Plafond de drafts générés par jour
            "linkedin": 1,
            "x": 5,
            "bluesky": 2,
        },
        "auto_publish": {      # True = publie sans validation, False = draft à valider
            "linkedin": False,
            "x": False,
            "bluesky": False,
        },
        "counters": {          # Compteur de premiers contacts depuis le dernier draft
            "linkedin": 0,
            "x": 0,
            "bluesky": 0,
        },
        "today": {             # Date ISO + drafts générés aujourd'hui par plateforme
            "date": "",
            "linkedin": 0,
            "x": 0,
            "bluesky": 0,
        },
        "next_theme": "",      # Thème pré-sélectionné (vide = aléatoire)
        "angle_index": 0,      # Index rotatif sur la liste d'angles
        "last_prospect": {     # Dernier prospect démarché en 1er contact (pour le draft)
            "metier": "",
            "region": "",
        },
    },
    "ui": {
        "last_window_width": 1280,
        "last_window_height": 820,
    },
}


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    """Charge les préférences avec merge profond sur DEFAULT_SETTINGS."""
    if not SETTINGS_FILE.exists():
        return _deep_copy(DEFAULT_SETTINGS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Échec lecture settings : %s — defaults utilisés", exc)
        return _deep_copy(DEFAULT_SETTINGS)
    if not isinstance(data, dict):
        return _deep_copy(DEFAULT_SETTINGS)
    return _deep_merge(_deep_copy(DEFAULT_SETTINGS), data)


def save_settings(settings: dict[str, Any]) -> None:
    ensure_app_dir()
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(SETTINGS_FILE)


def _deep_copy(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: _deep_copy(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_deep_copy(x) for x in d]
    return d


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Object-style accessor pour les vues (évite de manipuler le dict partout)
# ---------------------------------------------------------------------------
class AppState:
    """Wrapper léger autour des settings + bus d'événements minimal."""

    def __init__(self):
        self.settings: dict[str, Any] = load_settings()
        self._listeners: dict[str, list] = {}

    def get(self, *path: str, default: Any = None) -> Any:
        cur: Any = self.settings
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
        return cur

    def set(self, *path: str, value: Any) -> None:
        if not path:
            raise ValueError("Path requis")
        cur = self.settings
        for key in path[:-1]:
            if key not in cur or not isinstance(cur[key], dict):
                cur[key] = {}
            cur = cur[key]
        cur[path[-1]] = value
        self._emit("change", path, value)

    def save(self) -> None:
        save_settings(self.settings)

    # -------- bus d'événements
    def on(self, event: str, callback) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def _emit(self, event: str, *args, **kwargs) -> None:
        for cb in self._listeners.get(event, []):
            try:
                cb(*args, **kwargs)
            except Exception as exc:
                logger.warning("Listener %s a levé : %s", event, exc)
