"""Reply Responder — génère des draft de réponses + politique d'envoi
(validation manuelle / auto après délai / auto immédiat).

Conception :
- À chaque détection de réponse par replies_poller, on appelle
  ensure_suggested_reply() qui génère un draft IA contextualisé selon la
  classification (interested / not_now / no / unsubscribe / unknown).
- Le draft est stocké dans email_history.extra.suggested_reply avec
  status=pending et send_after = now() + délai selon le mode configuré.
- Mode par catégorie configurable dans shared_settings 'reply_responder' :
    - "manual"     → l'humain valide (UI Réplies)
    - "delay_30m"  → envoi auto 30 min après génération si rien fait
    - "instant"    → envoi immédiat
- Un worker thread daemon scanne toutes les 60s les drafts pending dont
  send_after est dépassé, et envoie via SMTP.
- Tout est best-effort. Si pas d'IA configurée, le draft reste un template
  brut. Si SMTP pas configuré, l'envoi auto est suspendu.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Modes d'envoi par catégorie
MODES = ("manual", "delay_30m", "instant")
DELAY_SECONDS = {
    "manual": None,        # jamais d'auto-envoi
    "delay_30m": 30 * 60,
    "instant": 0,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "global_mode": "manual",  # appliqué si per_category absent pour une catégorie
    "per_category": {
        "interested":  "manual",
        "not_now":     "manual",
        "no":          "manual",
        "unsubscribe": "manual",
        "unknown":     "manual",
    },
    "templates": {
        "interested_product": (
            "Bonjour {name},\n\n"
            "Merci pour votre retour, ravi que ça vous parle.\n\n"
            "Voici le lien direct pour récupérer {product_name} :\n"
            "{product_link}\n\n"
            "Le téléchargement est immédiat après paiement, et vous "
            "récupérez la licence à vie sur cette adresse mail.\n\n"
            "Si une question avant : répondez-moi simplement à ce mail.\n\n"
            "{signature}"
        ),
        "interested_service": (
            "Bonjour {name},\n\n"
            "Merci pour votre retour. Le plus simple pour caler 15 min : "
            "{calendly_link}\n\n"
            "Sinon dites-moi 2 ou 3 créneaux qui vous arrangent et "
            "je m'aligne dessus.\n\n"
            "{signature}"
        ),
        "not_now": (
            "Bonjour {name},\n\n"
            "C'est noté, je vous laisse tranquille pour le moment. "
            "Je reviendrai vers vous dans quelques mois — sauf si "
            "vous me dites stop d'ici là.\n\n"
            "Bonne continuation,\n{signature}"
        ),
        "no": (
            "Bonjour {name},\n\n"
            "Merci pour votre retour clair. Je ne vous recontacte plus "
            "sur ce sujet.\n\n"
            "Bonne continuation,\n{signature}"
        ),
        "unsubscribe": (
            "Bonjour {name},\n\n"
            "C'est noté, vous êtes désinscrit. Vous ne recevrez plus "
            "aucun mail de ma part.\n\n"
            "{signature}"
        ),
        "unknown": (
            "Bonjour {name},\n\n"
            "Merci pour votre message. Pouvez-vous me préciser votre "
            "demande pour que je puisse vous répondre au mieux ?\n\n"
            "{signature}"
        ),
    },
    "links": {
        "products": {
            # ex: {"obelisk": "https://denicheur.triskell-studio.fr",
            #      "pack-elec": "https://pack-elec.triskell-studio.fr"}
        },
        "default_product_key": "",  # produit choisi quand on ne sait pas désambiguïser
        "calendly_default":  "",
    },
    "subject_prefix": "Re: ",
    "signature": "",  # vide = on tente smtp_cfg.from_name
    "worker_enabled": True,
}


WORKER_INTERVAL_SECONDS = 60
INITIAL_DELAY_SECONDS = 45

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


# ---------------------------------------------------------------------------
# Boot / shutdown
# ---------------------------------------------------------------------------
def start_worker(app_state) -> bool:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _WORKER_STOP.clear()
        t = threading.Thread(target=_worker_loop, args=(app_state,),
                              name="ReplyResponderWorker", daemon=True)
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


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def load_config(client) -> dict:
    """Lit shared_settings 'reply_responder' avec merge profond sur DEFAULT."""
    raw = client.get_shared_setting("reply_responder", {}) or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    return _deep_merge(_deep_copy(DEFAULT_CONFIG), raw)


def save_config(client, config: dict) -> None:
    client.set_shared_setting("reply_responder", config)


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


def mode_for_category(config: dict, category: str) -> str:
    pc = (config.get("per_category") or {}).get(category)
    if pc in MODES:
        return pc
    g = config.get("global_mode")
    return g if g in MODES else "manual"


# ---------------------------------------------------------------------------
# Génération de draft
# ---------------------------------------------------------------------------
def ensure_suggested_reply(client, history_row_id: str, *,
                            classification: dict, prospect: dict,
                            reply_subject: str, reply_body: str,
                            in_reply_to: str, app_state) -> dict:
    """Crée un draft suggéré pour cette réponse si pas déjà présent.

    Renvoie {created, mode, send_after, error}.
    """
    out = {"created": False, "mode": "", "send_after": "", "error": ""}
    try:
        sb = client.raw
        res = (sb.table("email_history").select("extra")
               .eq("id", history_row_id).limit(1).execute())
        row = (res.data or [{}])[0]
        extra = row.get("extra") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        if extra.get("suggested_reply"):
            out["error"] = "already_exists"
            return out

        config = load_config(client)
        category = (classification or {}).get("category", "unknown")
        mode = mode_for_category(config, category)
        delay = DELAY_SECONDS.get(mode)
        send_after = ""
        if delay is not None:
            send_after = (datetime.now() + timedelta(seconds=delay)).isoformat(
                timespec="seconds")

        # Génération du body via template + IA si dispo (l'IA polit le
        # template, mais on garde le template comme garde-fou si IA KO).
        subject, body = _build_reply_text(
            config=config, category=category, prospect=prospect,
            reply_subject=reply_subject, reply_body=reply_body,
            app_state=app_state, client=client,
        )

        suggested = {
            "subject": subject,
            "body": body,
            "category": category,
            "mode": mode,
            "send_after": send_after,
            "status": "pending",
            "in_reply_to": in_reply_to,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
        extra["suggested_reply"] = suggested
        sb.table("email_history").update({"extra": extra}).eq(
            "id", history_row_id).execute()
        out.update({"created": True, "mode": mode, "send_after": send_after})
        return out
    except Exception as exc:
        out["error"] = str(exc)
        return out


def _build_reply_text(*, config: dict, category: str, prospect: dict,
                       reply_subject: str, reply_body: str,
                       app_state, client) -> tuple[str, str]:
    """Construit (subject, body) en partant du template + variables.

    Si une clé IA est dispo, on demande à l'IA de polir le draft.
    """
    templates = config.get("templates") or {}
    name = (prospect.get("name") or prospect.get("legal_name")
            or "").strip() or "vous"
    signature = config.get("signature") or app_state.get(
        "outreach", "from_name", default="") or ""

    # Sélection du template
    if category == "interested":
        # Heuristique : si le brief / la dernière offre touche à un service,
        # template service ; sinon template product. Ici on tape simple :
        # si calendly_default existe, on penche service ; sinon product.
        if config.get("links", {}).get("calendly_default"):
            template_key = "interested_service"
        else:
            template_key = "interested_product"
    else:
        template_key = category if category in templates else "unknown"

    tmpl = templates.get(template_key) or templates.get("unknown") or ""

    # Choix du lien produit
    products = (config.get("links") or {}).get("products") or {}
    default_pk = (config.get("links") or {}).get("default_product_key") or ""
    product_link = products.get(default_pk, "") if default_pk else ""
    product_name = default_pk.replace("-", " ").title() if default_pk else "le produit"
    calendly_link = (config.get("links") or {}).get("calendly_default") or ""

    body = tmpl.format(
        name=name,
        product_link=product_link or "(lien à configurer)",
        product_name=product_name,
        calendly_link=calendly_link or "(lien Calendly à configurer)",
        signature=signature,
    )

    prefix = config.get("subject_prefix") or "Re: "
    raw_subject = (reply_subject or "").strip()
    if raw_subject.lower().startswith("re:"):
        subject = raw_subject
    else:
        subject = (prefix + raw_subject).strip(" :")

    # Polish IA optionnel — uniquement pour catégorie 'interested' où la
    # nuance compte le plus. Les autres catégories restent au template
    # exact (plus prévisible et zéro coût IA).
    if category == "interested":
        ai_polished = _polish_with_ai(
            client=client, app_state=app_state,
            base_body=body, prospect_name=name,
            reply_excerpt=(reply_body or "")[:1500],
        )
        if ai_polished:
            body = ai_polished

    return subject, body


def _polish_with_ai(*, client, app_state, base_body: str,
                     prospect_name: str, reply_excerpt: str) -> Optional[str]:
    """Demande à l'IA de polir le brouillon en gardant les liens et le ton.
    Renvoie None si pas d'IA dispo ou erreur."""
    try:
        # Provider + clé : préfère shared_settings, fallback local
        provider = ""
        api_key = ""
        model = ""
        sb_ai = client.get_shared_setting("ai", {}) or {}
        if isinstance(sb_ai, dict):
            provider = sb_ai.get("selected_provider") or ""
            model = sb_ai.get("selected_model") or ""
            api_key = (sb_ai.get("api_keys") or {}).get(provider, "") or ""
        if not provider or not api_key:
            local_ai = app_state.get("ai", default={}) or {}
            provider = provider or local_ai.get("selected_provider", "")
            model = model or local_ai.get("selected_model", "")
            api_key = api_key or (local_ai.get("api_keys") or {}).get(
                provider, "")
        if not provider or not api_key:
            return None
        from triskell_core.ai.providers import send_to_provider, ProviderError
        system = (
            "Tu es l'assistant qui poli un mail de réponse à un prospect "
            "intéressé. Tu PRÉSERVES tous les liens (URLs) du brouillon, "
            "tu PRÉSERVES la signature, tu gardes un ton chaleureux et "
            "direct. Tu ne dépasses pas 8 lignes. Tu réponds UNIQUEMENT "
            "le corps du mail, sans phrase d'intro ni de conclusion."
        )
        user = (
            f"Mail entrant du prospect ({prospect_name}) :\n"
            f"{reply_excerpt}\n\n"
            f"BROUILLON à polir (préserver les liens et la signature) :\n"
            f"{base_body}"
        )
        try:
            prompt = system + "\n\n---\n\n" + user
            api_keys = {provider: api_key}
            text = send_to_provider(provider, model or "", prompt, api_keys)
            text = (text or "").strip()
            # Sanity : le polish doit garder au moins une URL si le brouillon en avait
            import re as _re
            urls_in_base = _re.findall(r"https?://\S+", base_body)
            if urls_in_base:
                if not any(u in text for u in urls_in_base):
                    return None  # IA a perdu les liens → on garde le base
            if 40 <= len(text) <= 4000:
                return text
        except ProviderError:
            return None
    except Exception as exc:
        logger.debug("polish_with_ai: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Worker (auto-envoi des drafts dont send_after est passé)
# ---------------------------------------------------------------------------
def _worker_loop(app_state) -> None:
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        try:
            result = _do_one_cycle(app_state)
            try:
                from . import pulse_bus
                sent = result.get("sent", 0) if isinstance(result, dict) else 0
                err = result.get("error") if isinstance(result, dict) else None
                # Coupures réseau transitoires (Supabase injoignable, socket
                # fermée) : on n'allume pas la LED rouge — le cycle suivant
                # retentera dans 60s.
                transient = isinstance(err, str) and (
                    err == "supabase_unavailable"
                    or err.startswith("fetch:")
                )
                if sent > 0:
                    pulse_bus.report(
                        "responder", "active",
                        text=(f"{sent} draft envoyé"
                              if sent == 1
                              else f"{sent} drafts envoyés"),
                        relative_time="à l'instant",
                    )
                elif err and not transient:
                    pulse_bus.report(
                        "responder", "error",
                        error=str(err),
                    )
                else:
                    # Cycle propre ou erreur transitoire : on remet la LED
                    # en idle pour effacer un état d'erreur précédent.
                    pulse_bus.report("responder", "idle")
            except Exception:
                pass
        except Exception as exc:
            logger.warning("ReplyResponder cycle: %s", exc)
            try:
                from . import pulse_bus
                pulse_bus.report("responder", "error", error=str(exc))
            except Exception:
                pass
        for _ in range(WORKER_INTERVAL_SECONDS // 5):
            if _WORKER_STOP.is_set():
                return
            time.sleep(5)


def _do_one_cycle(app_state) -> dict:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    counters = {"scanned": 0, "sent": 0, "errors": 0, "skipped": 0}
    client = _get_client()
    if client is None:
        counters["error"] = "supabase_unavailable"
        _LAST_RUN_RESULT = counters
        _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
        return counters

    config = load_config(client)
    if not config.get("worker_enabled", True):
        _LAST_RUN_RESULT = counters
        _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
        return counters

    smtp_cfg = _resolve_smtp_config(app_state, client)

    try:
        sb = client.raw
        res = (sb.table("email_history").select("*")
               .eq("kind", "reply_received")
               .order("ts", desc=True).limit(200).execute())
        rows = res.data or []
    except Exception as exc:
        counters["error"] = f"fetch: {exc}"
        _LAST_RUN_RESULT = counters
        _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
        return counters

    now_iso = datetime.now().isoformat(timespec="seconds")
    for row in rows:
        extra = row.get("extra") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        sr = extra.get("suggested_reply")
        if not sr or sr.get("status") != "pending":
            continue
        if sr.get("mode") == "manual":
            continue
        send_after = sr.get("send_after") or ""
        if send_after and send_after > now_iso:
            continue
        counters["scanned"] += 1

        if not smtp_cfg:
            counters["skipped"] += 1
            continue

        # Récupère l'email du prospect
        try:
            pres = (client.raw.table("prospects").select("emails,name,legal_name")
                    .eq("id", row.get("prospect_id")).limit(1).execute())
            prospect = (pres.data or [{}])[0]
        except Exception as exc:
            logger.warning("fetch prospect: %s", exc)
            counters["errors"] += 1
            continue
        emails = prospect.get("emails") or []
        # On préfère l'adresse "From" du mail entrant si dispo
        to = (extra.get("from") or "").strip()
        if not to and emails:
            to = str(emails[0]).strip()
        if not to:
            counters["skipped"] += 1
            continue

        try:
            from triskell_core.prospect.outreach.smtp_sender import (
                send_email, SmtpConfigError,
            )
            in_reply_to = sr.get("in_reply_to") or extra.get("in_reply_to") or ""
            headers = {}
            if in_reply_to:
                headers["In-Reply-To"] = f"<{in_reply_to}>"
                headers["References"] = f"<{in_reply_to}>"
            msg_id = send_email(
                smtp_cfg, to=to,
                subject=sr.get("subject", ""),
                body=sr.get("body", ""),
                custom_headers=headers,
            )
            sr["status"] = "sent"
            sr["sent_at"] = datetime.now().isoformat(timespec="seconds")
            sr["sent_message_id"] = msg_id
            extra["suggested_reply"] = sr
            extra["handled"] = True
            extra["handled_at"] = sr["sent_at"]
            client.raw.table("email_history").update({"extra": extra}).eq(
                "id", row.get("id")).execute()

            # Log de l'envoi en email_history (kind=email_sent) — boucle de
            # traçabilité côté CRM.
            try:
                client.raw.table("email_history").insert({
                    "prospect_id": row.get("prospect_id"),
                    "kind": "email_sent",
                    "ts": sr["sent_at"],
                    "subject": sr.get("subject", "")[:200],
                    "body": sr.get("body", "")[:2000],
                    "message_id": msg_id,
                    "extra": {
                        "auto_response_to": row.get("id"),
                        "category": sr.get("category", ""),
                        "mode": sr.get("mode", ""),
                    },
                    "created_by": client.user_id,
                }).execute()
            except Exception as exc:
                logger.debug("log auto-sent: %s", exc)

            counters["sent"] += 1
        except SmtpConfigError as exc:
            counters["errors"] += 1
            logger.warning("SMTP config: %s", exc)
        except Exception as exc:
            counters["errors"] += 1
            logger.warning("send auto-reply: %s", exc)

    _LAST_RUN_RESULT = counters
    _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
    return counters


def send_now(client, app_state, history_row_id: str) -> dict:
    """Force l'envoi d'un draft suggéré (depuis l'UI). Renvoie {success, error, message_id}."""
    try:
        res = (client.raw.table("email_history").select("*")
               .eq("id", history_row_id).limit(1).execute())
        row = (res.data or [{}])[0]
        if not row:
            return {"success": False, "error": "row_not_found"}
        extra = row.get("extra") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        sr = extra.get("suggested_reply") or {}
        if not sr:
            return {"success": False, "error": "no_suggested_reply"}
        smtp_cfg = _resolve_smtp_config(app_state, client)
        if not smtp_cfg:
            return {"success": False, "error": "smtp_not_configured"}

        # Récupère email destinataire
        pres = (client.raw.table("prospects").select("emails")
                .eq("id", row.get("prospect_id")).limit(1).execute())
        prospect = (pres.data or [{}])[0]
        emails = prospect.get("emails") or []
        to = (extra.get("from") or "").strip()
        if not to and emails:
            to = str(emails[0]).strip()
        if not to:
            return {"success": False, "error": "no_recipient"}

        from triskell_core.prospect.outreach.smtp_sender import send_email
        in_reply_to = sr.get("in_reply_to") or extra.get("in_reply_to") or ""
        headers = {}
        if in_reply_to:
            headers["In-Reply-To"] = f"<{in_reply_to}>"
            headers["References"] = f"<{in_reply_to}>"
        msg_id = send_email(
            smtp_cfg, to=to,
            subject=sr.get("subject", ""),
            body=sr.get("body", ""),
            custom_headers=headers,
        )
        now = datetime.now().isoformat(timespec="seconds")
        sr["status"] = "sent"
        sr["sent_at"] = now
        sr["sent_message_id"] = msg_id
        extra["suggested_reply"] = sr
        extra["handled"] = True
        extra["handled_at"] = now
        client.raw.table("email_history").update({"extra": extra}).eq(
            "id", history_row_id).execute()
        # Log envoi
        try:
            client.raw.table("email_history").insert({
                "prospect_id": row.get("prospect_id"),
                "kind": "email_sent",
                "ts": now,
                "subject": sr.get("subject", "")[:200],
                "body": sr.get("body", "")[:2000],
                "message_id": msg_id,
                "extra": {"auto_response_to": history_row_id,
                            "category": sr.get("category", ""),
                            "mode": "manual_send"},
                "created_by": client.user_id,
            }).execute()
        except Exception:
            pass
        return {"success": True, "message_id": msg_id}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def update_draft(client, history_row_id: str, *, subject: str,
                  body: str) -> dict:
    """Patch le draft suggéré avec un nouveau subject/body (depuis UI)."""
    try:
        res = (client.raw.table("email_history").select("extra")
               .eq("id", history_row_id).limit(1).execute())
        row = (res.data or [{}])[0]
        extra = row.get("extra") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        sr = extra.get("suggested_reply")
        if not sr:
            return {"success": False, "error": "no_suggested_reply"}
        sr["subject"] = subject
        sr["body"] = body
        sr["edited_at"] = datetime.now().isoformat(timespec="seconds")
        # Si le mode était delay_30m / instant et que l'humain édite,
        # on bascule en manual pour éviter qu'un envoi auto pollue les corrections.
        if sr.get("mode") in ("delay_30m", "instant"):
            sr["mode"] = "manual"
            sr["send_after"] = ""
        extra["suggested_reply"] = sr
        client.raw.table("email_history").update({"extra": extra}).eq(
            "id", history_row_id).execute()
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def cancel_draft(client, history_row_id: str) -> dict:
    """Annule un draft pending (status=cancelled)."""
    try:
        res = (client.raw.table("email_history").select("extra")
               .eq("id", history_row_id).limit(1).execute())
        row = (res.data or [{}])[0]
        extra = row.get("extra") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        sr = extra.get("suggested_reply")
        if sr:
            sr["status"] = "cancelled"
            sr["cancelled_at"] = datetime.now().isoformat(timespec="seconds")
            extra["suggested_reply"] = sr
        extra["handled"] = True
        extra["handled_at"] = datetime.now().isoformat(timespec="seconds")
        client.raw.table("email_history").update({"extra": extra}).eq(
            "id", history_row_id).execute()
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Helpers Supabase / SMTP
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
    """Cherche SMTP : shared_settings d'abord, puis settings.json local."""
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
