"""Relance multi-canal — prépare des messages LinkedIn personnalisés
pour les prospects qui n'ont pas répondu à leur(s) mail(s).

Pourquoi pas 100% auto ?
  Les API officielles LinkedIn n'autorisent pas l'envoi de DM
  personnalisés à des inconnus depuis du code tiers (limites API +
  conditions d'utilisation). Les services tiers qui font ça
  (Phantombuster, Waalaxy, La Growth Machine) sont à brancher
  séparément.

Ce que fait ce module :
  - Worker qui tourne en boucle douce (toutes les 30 min)
  - Scanne les prospects avec status="contacted" qui n'ont pas répondu
    depuis ≥ N jours (config)
  - Pour chaque, génère via IA un message LinkedIn court (~60 mots)
  - Sauve dans une "file d'actions à faire" locale
  - Jordan voit la file dans la Matinale, copie le message en 1 clic,
    ouvre le profil LinkedIn du prospect, colle, envoie. ~30 sec/action.

Quand on aura un service LinkedIn DM officiel branché, ce même worker
pourra envoyer directement (cf. `_dispatch_action`).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


ACTIONS_FILE = Path.home() / ".triskell-command" / "multichannel_actions.json"
SHARED_KEY = "multichannel_followup"


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "delay_days": 5,            # relance LinkedIn N jours après le 1er mail sans réponse
    "max_actions_per_day": 10,  # plafond conservateur pour éviter le burn LinkedIn
    "min_pending_in_queue": 0,  # 0 = on génère même si y'en a déjà en queue
    "ai_provider": "google",
    "ai_model": "gemini-2.5-flash",
    "tone_brief": (
        "Message LinkedIn court (60 mots max), tutoiement, ton chaleureux mais "
        "pro. Référence en 1 phrase ce qu'on lui a envoyé par mail "
        "(sans répéter mot à mot), puis demande simplement si elle est ouverte "
        "à un échange. Pas d'emojis, pas de signature (LinkedIn ajoute "
        "automatiquement le nom)."
    ),
}


CYCLE_INTERVAL_SECONDS = 30 * 60          # toutes les 30 min
INITIAL_DELAY_SECONDS = 180

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


# ---------------------------------------------------------------------------
# Worker lifecycle
# ---------------------------------------------------------------------------
def start_worker(app_state) -> bool:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _WORKER_STOP.clear()
        t = threading.Thread(target=_loop, args=(app_state,),
                              name="MultichannelFollowupWorker", daemon=True)
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


def run_now(app_state) -> dict:
    return _do_one_cycle(app_state)


# ---------------------------------------------------------------------------
# Config & actions storage
# ---------------------------------------------------------------------------
def _ensure_dir() -> None:
    ACTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_config(client) -> dict:
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


def save_config(client, config: dict) -> None:
    if client:
        client.set_shared_setting(SHARED_KEY, config)


def load_actions() -> list[dict]:
    if not ACTIONS_FILE.exists():
        return []
    try:
        data = json.loads(ACTIONS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_actions(actions: list[dict]) -> None:
    _ensure_dir()
    ACTIONS_FILE.write_text(
        json.dumps(actions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def mark_done(action_id: str) -> bool:
    actions = load_actions()
    for a in actions:
        if str(a.get("id")) == str(action_id):
            a["done"] = True
            a["done_at"] = datetime.now().isoformat(timespec="seconds")
            save_actions(actions)
            return True
    return False


def discard_action(action_id: str) -> bool:
    actions = load_actions()
    new = [a for a in actions if str(a.get("id")) != str(action_id)]
    if len(new) == len(actions):
        return False
    save_actions(new)
    return True


def list_pending() -> list[dict]:
    return [a for a in load_actions() if not a.get("done")]


def auto_dispatch_to_phantombuster(client) -> dict:
    """Envoie toutes les actions LinkedIn pending au Phantom configuré (si actif).

    Renvoie {ok, launched, remaining, error?}. Marque les actions
    dispatched = True (mais pas done — done quand le Phantom a confirmé
    l'envoi côté LinkedIn, ce qu'on ne sait pas vérifier).
    """
    try:
        from . import phantombuster_client as pb
    except Exception as exc:
        return {"ok": False, "error": f"phantombuster_client: {exc}"}
    cfg = pb.load_config(client)
    if not cfg.get("enabled"):
        return {"ok": False, "error": "Phantombuster désactivé"}
    api_key = cfg.get("api_key", "")
    agent_id = cfg.get("agent_id", "")
    if not api_key or not agent_id:
        return {"ok": False, "error": "Clé API ou agent_id manquant"}

    actions = list_pending()
    # Garde celles avec un platform_url qui ressemble à LinkedIn
    li_actions = [a for a in actions
                   if (a.get("platform_url") or "").lower().find("linkedin") >= 0
                   and not a.get("dispatched")]
    if not li_actions:
        return {"ok": True, "launched": 0, "remaining": 0,
                "note": "Aucune action LinkedIn dispatchable (besoin de platform_url linkedin)"}

    batch = [{"profileUrl": a.get("platform_url"),
              "message":    a.get("message")}
             for a in li_actions[:int(cfg.get("max_per_launch") or 10)]]
    r = pb.send_linkedin_messages(
        api_key, agent_id, batch,
        max_per_launch=int(cfg.get("max_per_launch") or 10),
    )
    if not r.get("ok"):
        return r

    # Marque les actions envoyées au Phantom
    all_actions = load_actions()
    sent_ids = {a.get("id") for a in li_actions[:r.get("launched", 0)]}
    for a in all_actions:
        if a.get("id") in sent_ids:
            a["dispatched"] = True
            a["dispatched_at"] = datetime.now().isoformat(timespec="seconds")
            a["container_id"] = r.get("container_id")
    save_actions(all_actions)

    return {
        "ok": True,
        "launched": r.get("launched", 0),
        "remaining": r.get("remaining_in_queue", 0),
        "container_id": r.get("container_id"),
    }


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------
def _loop(app_state) -> None:
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        try:
            _do_one_cycle(app_state)
        except Exception as exc:
            logger.warning("Multichannel cycle: %s", exc)
        for _ in range(CYCLE_INTERVAL_SECONDS // 5):
            if _WORKER_STOP.is_set():
                return
            time.sleep(5)


def _do_one_cycle(app_state) -> dict:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    counters = {"scanned": 0, "candidates": 0, "drafted": 0, "skipped": 0,
                "errors": 0}

    client = _get_client()
    if client is None:
        counters["error"] = "supabase_unavailable"
        _set_run(counters)
        return counters

    # Anti-double-traitement : si CE process n'est PAS le serveur (ex: app
    # desktop ouverte sur le PC) et que le serveur bat encore, on lui laisse
    # le travail. Si le serveur meurt (>15 min sans battement), ce process
    # reprend automatiquement le relais au cycle suivant.
    from .server_presence import should_defer_to_server
    if should_defer_to_server(client):
        counters["skipped_reason"] = "server_active"
        _set_run(counters)
        return counters

    config = load_config(client)
    if not config.get("enabled", True):
        _set_run(counters)
        return counters

    delay_days = int(config.get("delay_days") or 5)
    max_per_day = int(config.get("max_actions_per_day") or 10)
    sb = client.raw

    # Plafond par jour : compte les actions générées aujourd'hui
    today_iso = datetime.now().date().isoformat()
    pending = load_actions()
    today_count = sum(1 for a in pending
                       if (a.get("created_at") or "").startswith(today_iso))
    if today_count >= max_per_day:
        counters["skipped"] = max_per_day
        _set_run(counters)
        return counters

    cutoff = (datetime.now() - timedelta(days=delay_days)).isoformat(
        timespec="seconds")

    # Récupère les prospects contactés il y a > delay_days et qui n'ont pas
    # répondu (status != "replied")
    try:
        res = (sb.table("prospects").select(
                "id,name,legal_name,emails,city,industry,description,"
                "platform_url,sources,last_contact_at,status")
               .eq("status", "contacted")
               .lt("last_contact_at", cutoff)
               .limit(50).execute())
        candidates = res.data or []
    except Exception as exc:
        counters["error"] = f"fetch: {exc}"
        _set_run(counters)
        return counters

    counters["scanned"] = len(candidates)

    # Filtre : pas déjà une action en file pour ce prospect
    already_pending_ids = {str(a.get("prospect_id")) for a in pending
                            if not a.get("done") and a.get("prospect_id")}

    # Charge clés API IA (depuis la config Core)
    api_keys = _load_ai_keys()
    provider = config.get("ai_provider", "google")
    model = config.get("ai_model", "gemini-2.5-flash")
    if not api_keys.get(provider):
        counters["error"] = f"clé IA '{provider}' manquante"
        _set_run(counters)
        return counters

    new_actions = list(pending)
    quota_left = max_per_day - today_count

    for p in candidates:
        if quota_left <= 0:
            break
        if str(p.get("id")) in already_pending_ids:
            counters["skipped"] += 1
            continue
        try:
            msg = _generate_linkedin_message(
                p, config, provider, model, api_keys)
            if not msg:
                counters["skipped"] += 1
                continue
            action = {
                "id": f"act_{int(time.time())}_{p.get('id', '')[:8]}",
                "prospect_id": p.get("id"),
                "prospect_name": p.get("name") or p.get("legal_name") or "",
                "prospect_city": p.get("city") or "",
                "prospect_industry": p.get("industry") or "",
                "platform_url": p.get("platform_url") or "",
                "channel": "linkedin",
                "message": msg,
                "search_url": _linkedin_search_url(
                    p.get("name") or p.get("legal_name") or "",
                    p.get("city") or "",
                ),
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "done": False,
                "done_at": "",
            }
            new_actions.append(action)
            counters["drafted"] += 1
            quota_left -= 1
        except Exception as exc:
            logger.warning("Multichannel gen for %s: %s", p.get("id"), exc)
            counters["errors"] += 1

    if counters["drafted"] > 0:
        save_actions(new_actions)
    counters["candidates"] = counters["scanned"] - counters["skipped"]

    _set_run(counters)
    return counters


# ---------------------------------------------------------------------------
# IA generation
# ---------------------------------------------------------------------------
def _generate_linkedin_message(prospect: dict, config: dict,
                                provider: str, model: str,
                                api_keys: dict[str, str]) -> str:
    try:
        from triskell_core.ai.providers import send_to_provider
    except ImportError:
        return ""

    name = prospect.get("name") or prospect.get("legal_name") or ""
    city = prospect.get("city") or ""
    industry = prospect.get("industry") or ""
    desc = (prospect.get("description") or "")[:300]
    tone = config.get("tone_brief") or DEFAULT_CONFIG["tone_brief"]

    prompt = f"""Tu es l'auteur d'un message LinkedIn court à un prospect que tu as
déjà contacté par mail (sans réponse). Ton but : rouvrir le dialogue.

Contexte du prospect :
- Nom : {name}
- Ville : {city or '—'}
- Secteur / plateforme : {industry or '—'}
- Description : {desc or '—'}

Consigne : {tone}

Renvoie UNIQUEMENT le texte du message, rien d'autre. Pas de "Bonjour" si
tu commences par une accroche, pas de signature, pas de PS, pas de markdown.
Maximum 60 mots."""

    try:
        text = send_to_provider(provider, model, prompt, api_keys)
        return (text or "").strip()
    except Exception as exc:
        logger.warning("send_to_provider: %s", exc)
        return ""


def _linkedin_search_url(name: str, city: str = "") -> str:
    """URL Google qui cherche le profil LinkedIn du prospect (plus fiable
    qu'une URL LinkedIn directe — LinkedIn bloque les bots)."""
    from urllib.parse import quote_plus
    q = f'site:linkedin.com/in "{name}"'
    if city:
        q += f' "{city}"'
    return f"https://www.google.com/search?q={quote_plus(q)}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None
    try:
        c = get_client()
    except SupabaseNotConfigured:
        return None
    if not c.is_authenticated:
        return None
    return c


def _load_ai_keys() -> dict[str, str]:
    """Délègue à shared_secrets (Supabase prioritaire)."""
    from . import shared_secrets
    return shared_secrets.get_ai_keys(client=_get_client())


def _set_run(counters: dict) -> None:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
    _LAST_RUN_RESULT = counters
