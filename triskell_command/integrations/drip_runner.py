"""Drip Runner — relances automatiques J+7 et J+30 sur les emails envoyés
sans réponse.

Conception :
- Worker thread daemon qui scanne toutes les heures :
    1. Cherche email_sent envoyés entre 7j-1h et 7j+1h sans reply_received
       du même prospect → génère un draft "follow_up_7d" si pas déjà fait.
    2. Pareil pour 30j → "follow_up_30d".
- Le draft est stocké en prospect_drafts (kind=follow_up_7d / follow_up_30d)
  pour être visible dans la vue Drafts à valider, ou en suggested_reply
  selon configuration.
- Mode par étape configurable dans shared_settings 'drip_runner' :
    - "manual"     : draft en attente de validation côté Triskell Command
    - "delay_30m"  : envoi auto après 30 min si rien de modifié
    - "instant"    : envoi auto immédiat
- Anti-double : avant de générer un drip, on vérifie qu'aucun email_sent
  postérieur n'existe déjà pour ce prospect (sinon il a déjà été relancé
  manuellement).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from .multi_tenant import with_workspace

logger = logging.getLogger(__name__)


STAGES = ("follow_up_7d", "follow_up_30d")
MODES = ("manual", "delay_30m", "instant")
DELAY_SECONDS = {"manual": None, "delay_30m": 30 * 60, "instant": 0}

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "stages": {
        "follow_up_7d":  {"days": 7,  "mode": "manual"},
        "follow_up_30d": {"days": 30, "mode": "manual"},
    },
    "templates": {
        "follow_up_7d": (
            "Bonjour {name},\n\n"
            "Je relance suite à mon mail de la semaine dernière, "
            "je sais que tu reçois beaucoup de propositions.\n\n"
            "Si le timing n'est pas bon, fais-moi signe et on reprendra "
            "contact plus tard. Sinon je reste à dispo.\n\n"
            "{signature}"
        ),
        "follow_up_30d": (
            "Bonjour {name},\n\n"
            "Dernière relance promis. J'ai pensé à toi en tombant sur "
            "{soft_hook} — peut-être qu'on se reparle ?\n\n"
            "Si non, je te laisse tranquille définitivement.\n\n"
            "{signature}"
        ),
    },
    "subject_template": "Re: {original_subject}",
}


CYCLE_INTERVAL_SECONDS = 60 * 60     # 1 h
INITIAL_DELAY_SECONDS = 90

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


# ---------------------------------------------------------------------------
def start_worker(app_state) -> bool:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _WORKER_STOP.clear()
        t = threading.Thread(target=_loop, args=(app_state,),
                              name="DripRunnerWorker", daemon=True)
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
    raw = client.get_shared_setting("drip_runner", {}) or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    return _deep_merge(_deep_copy(DEFAULT_CONFIG), raw)


def save_config(client, config: dict) -> None:
    client.set_shared_setting("drip_runner", config)


def run_now(app_state) -> dict:
    return _do_one_cycle(app_state)


# ---------------------------------------------------------------------------
def _loop(app_state) -> None:
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        try:
            result = _do_one_cycle(app_state)
            try:
                from . import pulse_bus
                drafts = result.get("drafts_created", 0) if isinstance(result, dict) else 0
                sent = result.get("auto_sent", 0) if isinstance(result, dict) else 0
                err = result.get("error") if isinstance(result, dict) else None
                total = drafts + sent
                if total > 0:
                    parts = []
                    if drafts:
                        parts.append(f"{drafts} relance{'s' if drafts > 1 else ''} préparée{'s' if drafts > 1 else ''}")
                    if sent:
                        parts.append(f"{sent} envoi{'s' if sent > 1 else ''} auto")
                    pulse_bus.report(
                        "drip", "active",
                        text=" + ".join(parts),
                        relative_time="à l'instant",
                    )
                elif err and err != "supabase_unavailable":
                    pulse_bus.report("drip", "error", error=str(err))
            except Exception:
                pass
        except Exception as exc:
            logger.warning("DripRunner cycle: %s", exc)
            try:
                from . import pulse_bus
                pulse_bus.report("drip", "error", error=str(exc))
            except Exception:
                pass
        for _ in range(CYCLE_INTERVAL_SECONDS // 5):
            if _WORKER_STOP.is_set():
                return
            time.sleep(5)


def _do_one_cycle(app_state) -> dict:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    counters = {"scanned": 0, "drafts_created": 0,
                "auto_sent": 0, "skipped": 0, "errors": 0}

    client = _get_client()
    if client is None:
        counters["error"] = "supabase_unavailable"
        _set_run(counters)
        return counters

    config = load_config(client)
    if not config.get("enabled", True):
        _set_run(counters)
        return counters

    sb = client.raw
    now = datetime.now()
    for stage in STAGES:
        stage_cfg = (config.get("stages") or {}).get(stage) or {}
        days = int(stage_cfg.get("days") or 0)
        if days <= 0:
            continue
        target = now - timedelta(days=days)
        # Fenêtre de ±1h pour absorber les décalages de cycles
        window_start = (target - timedelta(hours=1)).isoformat(timespec="seconds")
        window_end = (target + timedelta(hours=1)).isoformat(timespec="seconds")

        try:
            res = (sb.table("email_history").select("*")
                   .eq("kind", "email_sent")
                   .gte("ts", window_start).lt("ts", window_end)
                   .limit(500).execute())
            sent_rows = res.data or []
        except Exception as exc:
            logger.warning("fetch sent for %s: %s", stage, exc)
            counters["errors"] += 1
            continue

        for row in sent_rows:
            counters["scanned"] += 1
            try:
                if _should_skip(client, row, stage):
                    counters["skipped"] += 1
                    continue
                drafted = _create_drip_draft(client, app_state,
                                              row, stage, config)
                if drafted.get("auto_sent"):
                    counters["auto_sent"] += 1
                elif drafted.get("created"):
                    counters["drafts_created"] += 1
                elif drafted.get("error"):
                    counters["errors"] += 1
            except Exception as exc:
                logger.warning("drip stage %s row %s: %s",
                                stage, row.get("id"), exc)
                counters["errors"] += 1

    _set_run(counters)
    return counters


def _should_skip(client, sent_row: dict, stage: str) -> bool:
    """Skippe si :
    - le prospect a répondu (un reply_received existe pour ce prospect_id
      après ce sent)
    - le prospect a déjà reçu ce stage
    - le prospect a un statut "no contact" (won/lost/refused/replied/
      unsubscribed/bounced) — voir prospect_status.NO_CONTACT_STATUSES
    - une autre relance manuelle est partie après ce sent
    - un mail est deja parti vers ce prospect dans les 48h (anti-doublon
      cross-runner)
    """
    prospect_id = sent_row.get("prospect_id")
    if not prospect_id:
        return True
    sb = client.raw
    sent_ts = sent_row.get("ts") or ""

    # Status final ? (PS.NO_CONTACT_STATUSES + 'replied' = pas de relance auto)
    try:
        from . import prospect_status as PS
        st = PS.get_status(client, prospect_id)
        if PS.is_no_contact(st) or st == "replied":
            return True
    except Exception:
        pass

    # Anti-doublon : un mail est deja parti vers ce prospect dans les 48h
    # depuis un autre runner ? On evite la double relance le meme jour.
    try:
        from . import prospect_status as PS
        # hours=None → lit le cooldown configuré (72h par défaut, ou
        # shared_settings.email_cooldown_hours si Jordan l'a personnalisé)
        recent = PS.has_recent_send(client, prospect_id=prospect_id, hours=None)
        if recent.get("recent"):
            return True
    except Exception:
        pass

    # Réponse depuis l'envoi initial ?
    try:
        rres = (sb.table("email_history").select("id")
                .eq("prospect_id", prospect_id)
                .eq("kind", "reply_received")
                .gte("ts", sent_ts).limit(1).execute())
        if rres.data:
            return True
    except Exception:
        pass

    # Déjà ce stage pour ce prospect ?
    try:
        dres = (sb.table("email_history").select("id,extra")
                .eq("prospect_id", prospect_id)
                .eq("kind", "email_sent")
                .order("ts", desc=True).limit(20).execute())
        for r in dres.data or []:
            extra = r.get("extra") or {}
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except Exception:
                    extra = {}
            if extra.get("drip_stage") == stage:
                return True
        # Un envoi humain plus récent que sent_row ?
        if dres.data:
            latest = dres.data[0]
            if (latest.get("id") != sent_row.get("id")
                and (latest.get("ts") or "") > sent_ts):
                # Quelqu'un a déjà relancé manuellement → skip drip
                return True
    except Exception:
        pass

    return False


def _create_drip_draft(client, app_state, sent_row: dict,
                        stage: str, config: dict) -> dict:
    """Crée un draft de relance (kind=stage). Si mode auto et SMTP OK,
    envoie tout de suite (instant) ou planifie via prospect_drafts metadata.

    Implémentation pragmatique : on crée le draft dans prospect_drafts (le
    pipeline drafts existant) avec kind=stage et status=pending. L'envoi
    auto est délégué au reply_responder-like : on push directement le mail
    SMTP si mode=instant, sinon on laisse l'humain valider via la vue
    "Drafts à valider".
    """
    out = {"created": False, "auto_sent": False, "error": ""}
    prospect_id = sent_row.get("prospect_id")
    stage_cfg = (config.get("stages") or {}).get(stage) or {}
    mode = stage_cfg.get("mode", "manual")

    sb = client.raw
    # Prospect emails + nom
    try:
        pres = (sb.table("prospects").select("name,legal_name,emails")
                .eq("id", prospect_id).limit(1).execute())
        prospect = (pres.data or [{}])[0]
    except Exception as exc:
        out["error"] = f"fetch_prospect: {exc}"
        return out

    name = (prospect.get("name") or prospect.get("legal_name")
            or "vous").strip()
    emails = prospect.get("emails") or []
    if not emails:
        out["error"] = "no_email"
        return out
    to = str(emails[0]).strip()

    template = (config.get("templates") or {}).get(stage) or ""
    signature = config.get("signature") or app_state.get(
        "outreach", "from_name", default="") or ""
    body = template.format(name=name, signature=signature, soft_hook="ton sujet")
    original_subject = (sent_row.get("subject") or "").strip()
    subj_tmpl = config.get("subject_template") or "Re: {original_subject}"
    subject = subj_tmpl.format(original_subject=original_subject)

    # Crée le draft dans prospect_drafts pour qu'il apparaisse dans
    # la vue "Drafts à valider".
    try:
        sb.table("prospect_drafts").insert(with_workspace(client, {
            "prospect_id": prospect_id,
            "subject": subject[:200],
            "body": body[:8000],
            "kind": stage,
            "status": "pending",
            "created_by": client.user_id,
        })).execute()
        out["created"] = True
    except Exception as exc:
        out["error"] = f"insert_draft: {exc}"
        return out

    # Envoi auto si mode=instant
    if mode == "instant":
        smtp_cfg = _resolve_smtp_config(app_state, client)
        if not smtp_cfg:
            return out  # draft créé mais pas envoyé : skip
        try:
            from triskell_core.prospect.outreach.smtp_sender import send_email
            in_reply_to = (sent_row.get("message_id") or "").strip()
            headers = {}
            if in_reply_to:
                headers["In-Reply-To"] = (
                    in_reply_to if in_reply_to.startswith("<")
                    else f"<{in_reply_to}>"
                )
                headers["References"] = headers["In-Reply-To"]
            msg_id = send_email(
                smtp_cfg, to=to, subject=subject, body=body,
                custom_headers=headers,
            )
            now = datetime.now().isoformat(timespec="seconds")
            sb.table("email_history").insert(with_workspace(client, {
                "prospect_id": prospect_id,
                "kind": "email_sent",
                "ts": now,
                "subject": subject[:200],
                "body": body[:2000],
                "message_id": msg_id,
                "extra": {"drip_stage": stage, "auto_drip": True},
                "created_by": client.user_id,
            })).execute()
            sb.table("prospects").update({
                "last_contact_at": now,
                "updated_by": client.user_id,
            }).eq("id", prospect_id).execute()
            out["auto_sent"] = True
        except Exception as exc:
            out["error"] = f"smtp_send: {exc}"
    return out


# ---------------------------------------------------------------------------
def _get_client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None
    try:
        client = get_client()
    except SupabaseNotConfigured:
        return None
    if not client.is_authenticated:
        return None
    return client


def _resolve_smtp_config(app_state, client) -> Optional[dict]:
    sb = client.get_shared_setting("smtp_config", None)
    if sb and isinstance(sb, dict):
        host = (sb.get("smtp_host") or "").strip()
        user = (sb.get("smtp_user") or "").strip()
        password = sb.get("smtp_password") or ""
        from_email = sb.get("from_email") or ""
        if host and user and password and from_email:
            return {
                "smtp_host": host,
                "smtp_port": int(sb.get("smtp_port") or 587),
                "smtp_user": user,
                "smtp_password": password,
                "from_email": from_email,
                "from_name": sb.get("from_name") or "",
            }
    out = app_state.get("outreach", default={}) or {}
    host = (out.get("smtp_host") or "").strip()
    user = (out.get("smtp_user") or "").strip()
    password = out.get("smtp_password") or ""
    from_email = out.get("from_email") or ""
    if host and user and password and from_email:
        return {
            "smtp_host": host,
            "smtp_port": int(out.get("smtp_port") or 587),
            "smtp_user": user,
            "smtp_password": password,
            "from_email": from_email,
            "from_name": out.get("from_name") or "",
        }
    return None


def _set_run(counters: dict) -> None:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
    _LAST_RUN_RESULT = counters


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
