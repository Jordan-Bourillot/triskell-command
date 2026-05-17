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
    "agent_id": "",                # ID du Phantom "LinkedIn Message Sender" (DM)
    "max_per_launch": 10,          # plafond conservateur par exécution
    # Phantoms de DÉCOUVERTE (un par plateforme). À configurer dans
    # PhantomBuster une seule fois, l'ID se colle ici depuis les Réglages.
    "discovery_phantoms": {
        "linkedin": "",   # « LinkedIn Search Export » ou similaire
        "instagram": "",  # « Instagram Hashtag Collector » ou « Instagram Profile Scraper »
        "tiktok": "",     # « TikTok Hashtag Scraper »
    },
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
    """Lance le Phantom avec arguments custom (ex: {messages, sessionCookie}).
    Renvoie {containerId, ...} si tout va bien."""
    body = {
        "id": agent_id,
        "argument": arguments,   # injecté dans l'env du Phantom
    }
    r = requests.post(
        f"{BASE}/agents/launch",
        headers=_headers(api_key), json=body, timeout=20,
    )
    return _check(r, "launch_agent")


# ---------------------------------------------------------------------------
# Suivi d'exécution d'un Phantom (pour les phantoms de découverte qui
# produisent un résultat à récupérer).
# ---------------------------------------------------------------------------
def fetch_container_status(api_key: str, container_id: str) -> dict:
    """Renvoie l'état courant d'un container (running / finished / failed)."""
    r = requests.get(
        f"{BASE}/containers/fetch",
        headers=_headers(api_key),
        params={"id": container_id},
        timeout=15,
    )
    data = _check(r, "fetch_container_status")
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return data or {}


def fetch_container_result(api_key: str, container_id: str) -> dict:
    """Renvoie l'objet de résultat exposé par le Phantom (au format JSON).

    Selon les phantoms, le résultat peut être directement utilisable, ou
    contenir un champ avec une URL S3 vers un fichier CSV/JSON listant les
    profils découverts (clés courantes : `resultObject`, `csvUrl`,
    `jsonUrl`, etc.).
    """
    r = requests.get(
        f"{BASE}/containers/fetch-result-object",
        headers=_headers(api_key),
        params={"id": container_id},
        timeout=20,
    )
    data = _check(r, "fetch_container_result")
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return data or {}


def download_result_file(url: str, *, timeout: int = 60) -> bytes:
    """Télécharge le fichier de résultat (CSV / JSON) depuis l'URL S3
    Phantombuster. Pas d'auth nécessaire, l'URL est signée."""
    if not url:
        raise PhantombusterError("URL de résultat manquante.")
    r = requests.get(url, timeout=timeout)
    if r.status_code >= 400:
        raise PhantombusterError(
            f"download_result_file → HTTP {r.status_code} : {r.text[:200]}")
    return r.content


def parse_result_payload(raw: bytes) -> list[dict]:
    """Parse un payload Phantombuster (JSON ou CSV) en liste de dicts.

    PhantomBuster renvoie typiquement soit un tableau JSON, soit un CSV
    avec en-têtes. On accepte les deux pour rester compatible avec tous
    les phantoms.
    """
    if not raw:
        return []
    text = raw.decode("utf-8", errors="replace").lstrip("﻿")
    text_stripped = text.lstrip()
    # JSON ?
    if text_stripped.startswith("[") or text_stripped.startswith("{"):
        try:
            data = json.loads(text_stripped)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
            if isinstance(data, dict):
                # Certains phantoms enveloppent dans {data: [...]} ou {results: [...]}
                for k in ("data", "results", "items", "profiles"):
                    arr = data.get(k)
                    if isinstance(arr, list):
                        return [d for d in arr if isinstance(d, dict)]
                # Sinon, c'est un dict unique → on en fait une liste
                return [data]
        except Exception as exc:
            logger.debug("parse_result_payload JSON: %s", exc)
    # CSV
    try:
        import csv
        from io import StringIO
        reader = csv.DictReader(StringIO(text))
        rows: list[dict] = []
        for row in reader:
            rows.append({(k or "").strip(): (v.strip() if isinstance(v, str) else v)
                          for k, v in row.items()})
        return rows
    except Exception as exc:
        logger.debug("parse_result_payload CSV: %s", exc)
    return []


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
