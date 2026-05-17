"""Recyclage des prospects dormants — relance les « pas maintenant ».

Quand un prospect a répondu « pas dispo », « rappelez-moi dans 6 mois »,
ou similaire (catégorie classification = "not_now"), il dort. Ce worker :

  1. Détecte les prospects dont la dernière réponse "not_now" date de
     plus de N mois (config, par défaut 3).
  2. Pour chacun, crée un nouveau brouillon de relance (style
     "ça fait X mois, j'ai pensé à toi car…") via Triskell Core.
  3. Le brouillon arrive dans la file Drafts à valider OU est envoyé
     direct selon le mode global (config).
  4. Idempotent : on marque la trace de réveil dans email_history.extra
     pour ne pas relancer 50 fois la même personne.

Ne touche pas aux "no" / "unsubscribe" / "interested" — uniquement les
"not_now" qui ont passé leur délai.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


SHARED_KEY = "dormant_recycler"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "wake_after_months": 3,        # délai avant de réveiller
    "max_per_day": 5,              # plafond par jour (conservateur)
    "mode": "manual",              # manual | auto — mode d'envoi des relances
    "ai_provider": "google",
    "ai_model": "gemini-2.5-flash",
    "tone_brief": (
        "Mail très court (≤ 8 lignes) à un prospect qui m'avait dit "
        "« pas maintenant » il y a quelques mois. Le ton : léger, sans "
        "pression, on revient juste prendre des nouvelles + glisser une "
        "proposition simple. Tutoiement chaleureux. "
        "Rappelle brièvement (1 phrase) ce dont on avait parlé sans citer "
        "le mail original. Pas d'emojis, pas de jargon."
    ),
    "subject_template": "On reprend là où on s'était arrêtés ?",
}


CYCLE_INTERVAL_SECONDS = 4 * 60 * 60         # toutes les 4h (lent c'est ok)
INITIAL_DELAY_SECONDS = 240

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


def start_worker(app_state) -> bool:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _WORKER_STOP.clear()
        t = threading.Thread(target=_loop, args=(app_state,),
                              name="DormantRecyclerWorker", daemon=True)
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


def run_now(app_state) -> dict:
    return _do_one_cycle(app_state)


# ---------------------------------------------------------------------------
def _loop(app_state) -> None:
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        try:
            _do_one_cycle(app_state)
        except Exception as exc:
            logger.warning("DormantRecycler cycle: %s", exc)
        for _ in range(CYCLE_INTERVAL_SECONDS // 5):
            if _WORKER_STOP.is_set():
                return
            time.sleep(5)


def _do_one_cycle(app_state) -> dict:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    counters = {"scanned": 0, "candidates": 0, "drafted": 0, "auto_sent": 0,
                "skipped": 0, "errors": 0}

    client = _get_client()
    if client is None:
        counters["error"] = "supabase_unavailable"
        _set_run(counters)
        return counters

    config = load_config(client)
    if not config.get("enabled", True):
        _set_run(counters)
        return counters

    months = int(config.get("wake_after_months") or 3)
    max_per_day = int(config.get("max_per_day") or 5)
    cutoff = (datetime.now() - timedelta(days=months * 30))

    sb = client.raw

    # Récupère les "not_now" récents pour avoir le ts de la réponse
    try:
        res = (sb.table("email_history").select(
                "id,prospect_id,ts,subject,extra")
               .eq("kind", "reply_received")
               .order("ts", desc=True).limit(2000).execute())
        rows = res.data or []
    except Exception as exc:
        counters["error"] = f"fetch: {exc}"
        _set_run(counters)
        return counters

    counters["scanned"] = len(rows)

    # Garde le plus récent par prospect, et seulement les "not_now" anciens
    last_by_pid: dict[str, dict] = {}
    for r in rows:
        pid = r.get("prospect_id")
        if not pid:
            continue
        extra = r.get("extra") or {}
        if isinstance(extra, str):
            try: extra = json.loads(extra)
            except Exception: continue
        cls = (extra.get("classification") or {})
        if (cls.get("category") or "").lower() != "not_now":
            continue
        # déjà recyclé ?
        if extra.get("recycled_at"):
            continue
        # Garde le plus ancien match (premier rencontré ici, donc le plus récent)
        if pid not in last_by_pid:
            last_by_pid[pid] = {**r, "extra": extra}

    candidates = []
    for pid, r in last_by_pid.items():
        try:
            ts = datetime.fromisoformat((r.get("ts") or "").replace("Z", "+00:00"))
        except Exception:
            continue
        if ts.replace(tzinfo=None) > cutoff:
            continue
        candidates.append(r)

    counters["candidates"] = len(candidates)

    # Charge prospects pour avoir nom/email
    pids = [c.get("prospect_id") for c in candidates if c.get("prospect_id")]
    prospects: dict[str, dict] = {}
    if pids:
        try:
            pres = (sb.table("prospects").select(
                    "id,name,legal_name,emails,city,industry,description")
                    .in_("id", pids).execute())
            for p in (pres.data or []):
                prospects[p["id"]] = p
        except Exception:
            pass

    # Charge clés API IA
    api_keys = _load_ai_keys()
    provider = config.get("ai_provider", "google")
    model = config.get("ai_model", "gemini-2.5-flash")
    if not api_keys.get(provider):
        counters["error"] = f"clé IA '{provider}' manquante"
        _set_run(counters)
        return counters

    # Plafond journalier
    today_iso = datetime.now().date().isoformat()
    sent_today = sum(1 for r in rows
                      if (r.get("extra") or {}).get("recycled_at", "").startswith(today_iso))
    quota = max_per_day - sent_today
    mode = config.get("mode", "manual")

    from . import task_lock
    me_uid = client.user_id or ""

    from . import prospect_status as PS
    for r in candidates:
        if quota <= 0:
            break
        pid = r.get("prospect_id")
        prospect = prospects.get(pid)
        if not prospect or not (prospect.get("emails") or []):
            counters["skipped"] += 1
            continue
        # Garde-fou central : prospect en no-contact / replied / mail recent ?
        first_email = (prospect.get("emails") or [""])[0]
        guard = PS.should_contact(client, pid, email=first_email,
                                   min_hours_between=48)
        if not guard.get("ok"):
            counters["skipped"] += 1
            continue
        # Verrou doux sur l'email_history pour éviter double recyclage
        if task_lock.is_locked_by_other(client, "email_history",
                                          r.get("id"), user_id=me_uid):
            counters["skipped"] += 1
            continue
        if not task_lock.try_acquire_lock(client, "email_history",
                                            r.get("id"), user_id=me_uid):
            counters["skipped"] += 1
            continue
        try:
            subject, body = _generate_recycle_mail(
                prospect, config, provider, model, api_keys)
            if not subject or not body:
                counters["skipped"] += 1
                continue
            ok = _dispatch(client, sb, app_state, prospect, subject, body, mode)
            if ok == "auto":
                counters["auto_sent"] += 1
            elif ok == "draft":
                counters["drafted"] += 1
            else:
                counters["errors"] += 1
                continue
            # Marque l'email_history original comme recyclé
            extra = r.get("extra") or {}
            extra["recycled_at"] = datetime.now().isoformat(timespec="seconds")
            try:
                sb.table("email_history").update({"extra": extra}).eq(
                    "id", r.get("id")).execute()
            except Exception:
                pass
            quota -= 1
        except Exception as exc:
            logger.warning("dormant recycle for %s: %s", pid, exc)
            counters["errors"] += 1
        finally:
            task_lock.release_lock(client, "email_history",
                                    r.get("id"), user_id=me_uid)

    _set_run(counters)
    return counters


def _generate_recycle_mail(prospect: dict, config: dict,
                            provider: str, model: str,
                            api_keys: dict[str, str]) -> tuple[str, str]:
    from triskell_core.ai.providers import send_to_provider
    name = prospect.get("name") or prospect.get("legal_name") or ""
    city = prospect.get("city") or ""
    industry = prospect.get("industry") or ""
    desc = (prospect.get("description") or "")[:300]
    tone = config.get("tone_brief") or DEFAULT_CONFIG["tone_brief"]
    subject_default = config.get("subject_template") or DEFAULT_CONFIG["subject_template"]

    prompt = f"""Tu réveilles un prospect dormant ("pas maintenant" il y a quelques mois).

Contexte :
- Nom : {name}
- Ville : {city or '—'}
- Secteur : {industry or '—'}
- Description : {desc or '—'}

Consigne : {tone}

Format strict de ta réponse :
OBJET : <objet du mail, court, accrocheur sans être vendeur>

<corps du mail>

Cordialement,

(NE signe pas avec un nom — la signature est ajoutée séparément)"""

    text = send_to_provider(provider, model, prompt, api_keys) or ""
    text = text.strip()
    # Parse OBJET : ... \n\n corps
    subject = subject_default
    body = text
    if text.upper().startswith("OBJET"):
        try:
            first_line, rest = text.split("\n", 1)
            subject = first_line.split(":", 1)[1].strip()
            body = rest.strip()
        except Exception:
            pass
    return subject, body


def _dispatch(client, sb, app_state, prospect: dict,
              subject: str, body: str, mode: str) -> str:
    """Envoie ou crée un draft selon le mode. Renvoie 'auto'|'draft'|'error'."""
    # Toujours créer un draft sur le prospect_drafts pour la traçabilité
    try:
        sb.table("prospect_drafts").insert({
            "prospect_id": prospect["id"],
            "subject": subject[:200],
            "body": body[:8000],
            "kind": "dormant_recycle",
            "status": "pending",
            "created_by": client.user_id,
        }).execute()
    except Exception as exc:
        logger.warning("draft insert: %s", exc)
        return "error"

    if mode != "auto":
        return "draft"

    # Mode auto : envoie SMTP direct
    smtp_cfg = _resolve_smtp_config(app_state, client)
    if not smtp_cfg:
        return "draft"
    to = (prospect.get("emails") or [None])[0]
    if not to:
        return "error"
    try:
        from triskell_core.prospect.outreach.smtp_sender import send_email
        msg_id = send_email(smtp_cfg, to=to, subject=subject, body=body)
        sb.table("email_history").insert({
            "prospect_id": prospect["id"],
            "kind": "email_sent",
            "ts": datetime.now().isoformat(timespec="seconds"),
            "subject": subject[:200],
            "body": body[:2000],
            "message_id": msg_id,
            "extra": {"dormant_recycle": True},
            "created_by": client.user_id,
        }).execute()
        return "auto"
    except Exception as exc:
        logger.warning("dormant smtp: %s", exc)
        return "error"


def _resolve_smtp_config(app_state, client) -> Optional[dict]:
    """Délègue à shared_secrets (source de vérité partagée)."""
    from . import shared_secrets
    return shared_secrets.resolve_smtp_for_send(client=client, app_state=app_state)


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
    """Délègue à shared_secrets (Supabase prioritaire, fallback local + Core)."""
    from . import shared_secrets
    return shared_secrets.get_ai_keys(client=_get_client())


def _set_run(counters: dict) -> None:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
    _LAST_RUN_RESULT = counters
