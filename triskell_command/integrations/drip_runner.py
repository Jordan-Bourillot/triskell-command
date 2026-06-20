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
    # Vouvoiement obligatoire (règle absolue de Jordan) — les anciens
    # textes par défaut tutoyaient.
    # Relances PERSONNALISÉES (nom de l'entreprise via {name}). Vouvoiement.
    # Sans tiret cadratin ni « : » d'annonce (cf. feedback Jordan).
    "templates": {
        "follow_up_7d": (
            "Bonjour,\n\n"
            "Je me permets de revenir vers vous au sujet du site internet "
            "pour {name}. Je vous avais écrit la semaine dernière et je sais "
            "que vous recevez beaucoup de sollicitations.\n\n"
            "Si ce n'est pas le bon moment, dites-le-moi simplement et je "
            "reviendrai vers vous plus tard. Sinon, je reste à votre "
            "disposition.\n\n"
            "{signature}"
        ),
        "follow_up_30d": (
            "Bonjour,\n\n"
            "Dernière relance au sujet du site pour {name}, promis. Si le "
            "sujet peut vous intéresser un jour, je serai ravi d'en parler. "
            "Sinon, je ne vous recontacterai plus.\n\n"
            "Bonne continuation à vous,\n\n"
            "{signature}"
        ),
    },
    "subject_template": "Re: {original_subject}",
}


CYCLE_INTERVAL_SECONDS = 60 * 60     # 1 h
INITIAL_DELAY_SECONDS = 90

# Préparation des relances UNE FOIS PAR JOUR, le matin (et plus à l'heure
# pile de chaque envoi d'origine) : toutes les relances DUES ce jour-là
# arrivent ensemble dans « à valider », marquées « à envoyer aujourd'hui ».
# Le dédoublonnage (brouillon de relance déjà en attente / déjà envoyé) rend
# un éventuel re-passage après redémarrage parfaitement sûr (idempotent).
BATCH_HOUR = 8            # heure locale à partir de laquelle on prépare le jour
_LAST_BATCH_DATE: str = ""  # "AAAA-MM-JJ" du dernier lot préparé (mémoire process)

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


def _initial_sender(sent_row: dict) -> tuple:
    """(adresse, account_id) d'expéditeur du mail initial, d'après sa trace.

    Une relance doit partir de la MÊME adresse que le mail qu'elle suit
    (un « Re: » venu d'une adresse inconnue casse le fil et sent le spam).
    L'autopilote pose extra.from + extra.account_id sur chaque envoi ; les
    vieux envois n'ont rien → ("", "") = comportement historique conservé.
    """
    extra = sent_row.get("extra") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    if not isinstance(extra, dict):
        extra = {}
    return (str(extra.get("from") or "").strip(),
            str(extra.get("account_id") or "").strip())


def run_now(app_state) -> dict:
    # Déclenchement manuel ("Lancer maintenant") : on force, peu importe
    # l'heure ou le lot du jour (le dédoublonnage évite les doublons).
    return _do_one_cycle(app_state, force=True)


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


def _do_one_cycle(app_state, force: bool = False) -> dict:
    global _LAST_RUN_AT, _LAST_RUN_RESULT, _LAST_BATCH_DATE
    counters = {"scanned": 0, "drafts_created": 0,
                "auto_sent": 0, "skipped": 0, "errors": 0}

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

    sb = client.raw
    now = datetime.now()
    today = now.date().isoformat()
    # Une seule préparation par jour, à partir de BATCH_HOUR (sauf "Lancer
    # maintenant" qui force). Les relances du jour arrivent ainsi groupées
    # le matin, et plus à l'heure éparpillée de chaque envoi d'origine.
    if not force:
        if now.hour < BATCH_HOUR:
            counters["skipped_reason"] = f"avant {BATCH_HOUR}h (lot du matin)"
            _set_run(counters)
            return counters
        if _LAST_BATCH_DATE == today:
            counters["skipped_reason"] = "lot du jour déjà préparé"
            _set_run(counters)
            return counters

    for stage in STAGES:
        stage_cfg = (config.get("stages") or {}).get(stage) or {}
        days = int(stage_cfg.get("days") or 0)
        if days <= 0:
            continue
        # Tout ce qui a été envoyé le JOUR situé il y a `days` jours → sa
        # relance est préparée aujourd'hui (fenêtre = la journée entière).
        td = (now - timedelta(days=days)).date()
        day0 = datetime(td.year, td.month, td.day)
        window_start = day0.isoformat(timespec="seconds")
        window_end = (day0 + timedelta(days=1)).isoformat(timespec="seconds")

        try:
            res = (sb.table("email_history").select("*")
                   .eq("kind", "email_sent")
                   .gte("ts", window_start).lt("ts", window_end)
                   .limit(1000).execute())
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

    _LAST_BATCH_DATE = today  # lot du jour préparé → pas de re-passage aujourd'hui
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

    # ANTI-DOUBLON : un brouillon de relance de CE stage est-il DÉJÀ en attente
    # pour ce prospect ? (les anciennes fenêtres ±1h pouvaient en créer 2 ; un
    # re-passage du lot ne doit jamais redoubler non plus.) Bug attrapé par
    # Jordan le 19/06 : 8 relances = 4 prospects × 2.
    try:
        ex = (sb.table("prospect_drafts").select("id")
              .eq("prospect_id", prospect_id).eq("kind", stage)
              .eq("status", "pending").limit(1).execute())
        if ex.data:
            return True
    except Exception:
        pass

    # Status final ? (PS.NO_CONTACT_STATUSES + 'replied' = pas de relance auto)
    try:
        from . import prospect_status as PS
        st = PS.get_status(client, prospect_id)
        if PS.is_no_contact(st) or st == "replied":
            return True
    except Exception:
        pass

    # Anti-doublon cross-runner : un AUTRE envoi est parti vers ce prospect
    # dans les 48h ? OU le destinataire est-il devenu client ?
    # ATTENTION a ne PAS remettre forever=True ici : la memoire a vie
    # matchait le mail INITIAL que la relance est censee suivre -> le drip
    # sautait 100% des prospects et les relances ne partaient JAMAIS
    # (bug constate lors de l'audit du 10/06/2026).
    try:
        from . import prospect_status as PS
        email = ""
        try:
            pres = (sb.table("prospects").select("emails")
                    .eq("id", prospect_id).limit(1).execute())
            emails = (pres.data or [{}])[0].get("emails") or []
            email = str(emails[0]).strip() if emails else ""
        except Exception:
            pass
        recent = PS.has_recent_send(client, prospect_id=prospect_id,
                                    email=email, hours=48,
                                    check_clients=True)
        if recent.get("recent"):
            # Filet : si le seul envoi recent est le mail initial lui-meme
            # (fenetres J+7/J+30 elargies a ±1h, jamais < 48h), on bloque
            # quand meme — un envoi < 48h signifie qu'un autre runner ou un
            # envoi manuel vient de passer.
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
            or "votre entreprise").strip()
    emails = prospect.get("emails") or []
    if not emails:
        out["error"] = "no_email"
        return out
    to = str(emails[0]).strip()

    template = (config.get("templates") or {}).get(stage) or ""
    signature = config.get("signature") or app_state.get(
        "outreach", "from_name", default="") or ""
    # name / soft_hook gardes pour compat avec d'anciens textes custom
    # sauves en reglages ; les textes par defaut n'en utilisent plus.
    body = template.format(name=name, signature=signature,
                           soft_hook="votre activité")
    original_subject = (sent_row.get("subject") or "").strip()
    if original_subject:
        subj_tmpl = config.get("subject_template") or "Re: {original_subject}"
        subject = subj_tmpl.format(original_subject=original_subject)
    else:
        subject = "Petit suivi de mon message"

    # Crée le draft dans prospect_drafts pour qu'il apparaisse dans
    # la vue "Drafts à valider". La relance porte l'adresse d'expéditeur
    # du mail initial (cohérence du fil) — colonne de la migration 46,
    # insertion dégradée si la base ne l'a pas encore.
    initial_from, initial_account = _initial_sender(sent_row)
    _row = {
        "prospect_id": prospect_id,
        "subject": subject[:200],
        "body": body[:8000],
        "kind": stage,
        "status": "pending",
        "created_by": client.user_id,
    }
    try:
        if initial_from:
            try:
                _ext = dict(_row)
                _ext["sender_address"] = initial_from
                sb.table("prospect_drafts").insert(
                    with_workspace(client, _ext)).execute()
            except Exception:
                sb.table("prospect_drafts").insert(
                    with_workspace(client, _row)).execute()
        else:
            sb.table("prospect_drafts").insert(
                with_workspace(client, _row)).execute()
        out["created"] = True
    except Exception as exc:
        out["error"] = f"insert_draft: {exc}"
        return out

    # Envoi auto si mode=instant
    if mode == "instant":
        # Filet anti-variable-oubliee : un texte custom mal sauve ({x} non
        # rempli) ne doit jamais partir tout seul — il reste en brouillon.
        try:
            from . import prospect_status as PS
            safe = PS.mail_is_safe_to_send(subject, body)
            if not safe.get("ok"):
                out["error"] = ("variables non remplies : "
                                + ", ".join(safe.get("unrendered") or []))
                return out
        except Exception:
            pass
        # Cohérence d'expéditeur : la relance part de la MÊME adresse que
        # le mail initial. Compte introuvable → on n'envoie PAS par une
        # autre adresse, le brouillon reste à valider à la main.
        smtp_cfg = None
        if initial_from or initial_account:
            try:
                from . import shared_secrets
                acc = None
                if initial_from:
                    acc = shared_secrets.get_account_by_address(
                        initial_from, client=client, app_state=app_state)
                if acc is None and initial_account:
                    acc = shared_secrets.get_account_by_id(
                        initial_account, client=client, app_state=app_state)
                _required = ("smtp_host", "smtp_user", "smtp_password",
                             "from_email")
                if acc and all(acc.get(k) for k in _required):
                    smtp_cfg = {
                        "smtp_host":     acc.get("smtp_host"),
                        "smtp_port":     int(acc.get("smtp_port") or 587),
                        "smtp_user":     acc.get("smtp_user"),
                        "smtp_password": acc.get("smtp_password"),
                        "from_email":    acc.get("from_email"),
                        "from_name":     acc.get("from_name", ""),
                    }
            except Exception:
                smtp_cfg = None
            if smtp_cfg is None:
                out["error"] = ("compte d'envoi du mail initial introuvable "
                                "-> relance laissée en brouillon")
                return out
        else:
            smtp_cfg = _resolve_smtp_config(app_state, client)
            if not smtp_cfg:
                return out  # draft créé mais pas envoyé : skip
        try:
            from triskell_core.prospect.outreach.smtp_sender import (
                prospection_headers, send_email,
            )
            in_reply_to = (sent_row.get("message_id") or "").strip()
            headers = {}
            if in_reply_to:
                headers["In-Reply-To"] = (
                    in_reply_to if in_reply_to.startswith("<")
                    else f"<{in_reply_to}>"
                )
                headers["References"] = headers["In-Reply-To"]
            # Relance de prospection → en-tête de désinscription obligatoire
            headers = prospection_headers(
                smtp_cfg.get("from_email", ""), extra=headers)
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
                "extra": {"drip_stage": stage, "auto_drip": True,
                          "to": to,
                          "from": smtp_cfg.get("from_email", "")},
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
