"""Client minimal de l'API Calendly v2.

Permet à Triskell Command de :
  - Lister les types de RDV configurés (event_types) côté Calendly de Jordan
  - Récupérer les créneaux disponibles sur les N prochains jours
  - Envoyer une invitation par email (single-use scheduling link)

Auth : Personal Access Token (PAT) — créable dans
  https://calendly.com/integrations/api_webhooks
Le PAT est stocké dans shared_settings.calendly.

Pas de webhook Calendly ici — quand un prospect prend RDV, on le détecte
via le mail de confirmation Calendly qui arrive en IMAP (replies_poller).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


SHARED_KEY = "calendly"
BASE = "https://api.calendly.com"


class CalendlyError(Exception):
    pass


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "personal_access_token": "",
    "default_event_type_uri": "",   # URI Calendly de l'event_type par défaut
    "default_event_type_name": "",
    "user_uri": "",                 # cache, rempli au premier appel
}


# ---------------------------------------------------------------------------
def load_config(client=None) -> dict:
    if client:
        try:
            raw = client.get_shared_setting(SHARED_KEY, {}) or {}
            if isinstance(raw, str):
                try: raw = json.loads(raw)
                except Exception: raw = {}
            if isinstance(raw, dict) and raw:
                return {**DEFAULT_CONFIG, **raw}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config: dict, client=None) -> None:
    if client:
        client.set_shared_setting(SHARED_KEY, config)


def _headers(token: str) -> dict[str, str]:
    if not token:
        raise CalendlyError("Personal Access Token Calendly manquant.")
    return {"Authorization": f"Bearer {token}",
            "Content-Type": "application/json"}


def _check(r: requests.Response, action: str) -> dict:
    if r.status_code >= 400:
        try: payload = r.json()
        except Exception: payload = r.text
        msg = f"{action} → HTTP {r.status_code}"
        if isinstance(payload, dict):
            msg += f" : {payload.get('message') or payload.get('title') or payload}"
        raise CalendlyError(msg)
    try:
        return r.json()
    except Exception:
        return {}


# ---------------------------------------------------------------------------
def get_current_user(token: str) -> dict:
    r = requests.get(f"{BASE}/users/me", headers=_headers(token), timeout=10)
    return _check(r, "get_current_user").get("resource") or {}


def list_event_types(token: str, user_uri: str | None = None) -> list[dict]:
    """Liste les types de RDV configurés sur le compte."""
    if not user_uri:
        user_uri = (get_current_user(token) or {}).get("uri", "")
    if not user_uri:
        return []
    r = requests.get(
        f"{BASE}/event_types",
        headers=_headers(token),
        params={"user": user_uri, "active": "true"},
        timeout=10,
    )
    return _check(r, "list_event_types").get("collection") or []


def create_single_use_link(token: str, event_type_uri: str,
                            *, max_event_count: int = 1,
                            owner_type: str = "EventType") -> str:
    """Crée un lien d'invitation à usage unique pour un event_type donné."""
    body = {
        "max_event_count": max_event_count,
        "owner": event_type_uri,
        "owner_type": owner_type,
    }
    r = requests.post(
        f"{BASE}/scheduling_links",
        headers=_headers(token),
        json=body, timeout=10,
    )
    data = _check(r, "create_single_use_link")
    return (data.get("resource") or {}).get("booking_url") or ""


def list_available_times(token: str, event_type_uri: str,
                          days_ahead: int = 14) -> list[str]:
    """Renvoie une liste d'ISO datetimes des créneaux disponibles."""
    start = datetime.utcnow()
    end = start + timedelta(days=days_ahead)
    r = requests.get(
        f"{BASE}/event_type_available_times",
        headers=_headers(token),
        params={
            "event_type": event_type_uri,
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time":   end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        timeout=15,
    )
    coll = _check(r, "list_available_times").get("collection") or []
    return [s.get("start_time") for s in coll if s.get("start_time")]


# ---------------------------------------------------------------------------
def health_check(token: str) -> dict:
    """Vérifie que le PAT est valide en appelant /users/me."""
    try:
        u = get_current_user(token)
        return {
            "ok": True,
            "user_uri": u.get("uri", ""),
            "user_name": u.get("name", ""),
            "user_email": u.get("email", ""),
            "scheduling_url": u.get("scheduling_url", ""),
        }
    except CalendlyError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
