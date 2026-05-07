"""Client minimal de l'API Phantombuster.

Phantombuster est un service tiers (~70 €/mois) qui pilote LinkedIn
(et autres réseaux) via du scraping headless authentifié au sessionCookie
du compte de l'utilisateur. C'est le standard de l'industrie pour
automatiser des DM LinkedIn (l'API officielle LinkedIn ne le permet pas).

Triskell Command utilise ici le « LinkedIn Message Sender » Phantom :
https://phantombuster.com/automations/linkedin/3389/linkedin-message-sender

Comment ça marche :
  1. L'utilisateur configure son agent Phantom (cookie LinkedIn,
     spreadsheet d'inputs, etc.) une fois pour toutes côté Phantombuster.
  2. Triskell Command envoie au Phantom une liste {profileUrl, message}
     via API → le Phantom les exécute (rate-limité à ~25 DM/jour pour
     éviter le ban LinkedIn).

Auth : API key Phantombuster (X-Phantombuster-Key header).
Stockage de la clé : shared_settings.phantombuster.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


SHARED_KEY = "phantombuster"
BASE = "https://api.phantombuster.com/api/v2"


class PhantombusterError(Exception):
    pass


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "api_key": "",
    "agent_id": "",                # ID du Phantom "LinkedIn Message Sender"
    "max_per_launch": 10,          # plafond conservateur par exécution
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


def _headers(api_key: str) -> dict[str, str]:
    if not api_key:
        raise PhantombusterError("Clé API Phantombuster manquante.")
    return {"X-Phantombuster-Key-1": api_key,
            "Content-Type": "application/json"}


def _check(r: requests.Response, action: str) -> dict:
    if r.status_code >= 400:
        try: payload = r.json()
        except Exception: payload = r.text
        raise PhantombusterError(f"{action} → HTTP {r.status_code} : {payload}")
    try: return r.json()
    except Exception: return {}


# ---------------------------------------------------------------------------
def list_agents(api_key: str) -> list[dict]:
    """Liste les Phantoms (agents) configurés."""
    r = requests.get(
        f"{BASE}/agents/fetch-all",
        headers=_headers(api_key), timeout=15,
    )
    data = _check(r, "list_agents")
    if isinstance(data, list):
        return data
    return data.get("data") or []


def launch_agent(api_key: str, agent_id: str,
                  arguments: dict[str, Any]) -> dict:
    """Lance le Phantom avec arguments custom (ex: {messages, sessionCookie})."""
    body = {
        "id": agent_id,
        "argument": arguments,   # injecté dans l'env du Phantom
    }
    r = requests.post(
        f"{BASE}/agents/launch",
        headers=_headers(api_key), json=body, timeout=20,
    )
    return _check(r, "launch_agent")


def health_check(api_key: str) -> dict:
    try:
        agents = list_agents(api_key)
        return {"ok": True, "agents_count": len(agents),
                "agents": [{"id": a.get("id"), "name": a.get("name")}
                           for a in agents[:20]]}
    except PhantombusterError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
def send_linkedin_messages(api_key: str, agent_id: str,
                            actions: list[dict],
                            *, max_per_launch: int = 10) -> dict:
    """Envoie une vague de DMs LinkedIn via le Phantom configuré.

    actions = [
      {"profileUrl": "https://linkedin.com/in/xxx", "message": "..."},
      ...
    ]

    Le Phantom va lire ces inputs et les distribuer (rate-limité côté
    Phantombuster pour éviter le ban LinkedIn).
    """
    if not actions:
        return {"ok": True, "launched": 0}
    if not agent_id:
        return {"ok": False, "error": "agent_id manquant"}
    batch = actions[:max_per_launch]
    arguments = {"messages": batch}
    try:
        r = launch_agent(api_key, agent_id, arguments)
        return {"ok": True, "launched": len(batch),
                "container_id": r.get("containerId"),
                "remaining_in_queue": max(0, len(actions) - max_per_launch)}
    except PhantombusterError as exc:
        return {"ok": False, "error": str(exc)}
