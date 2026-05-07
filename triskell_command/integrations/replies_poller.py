"""Poller IMAP des réponses prospects + classification IA + persistance Supabase.

Conception :
- Tourne en thread daemon, poll IMAP toutes les 5 min (configurable).
- Pour chaque mail nouveau :
    1. Match au prospect (par Message-ID référencé OU par From)
    2. Classification IA en 5 catégories : interested / not_now / no /
       unsubscribe / unknown
    3. Écrit un row email_history avec kind='reply_received' + extra =
       {classification, body_excerpt, from, in_reply_to, handled: false}
    4. Met à jour prospects.status → 'replied' (si pas déjà won/lost)
- Idempotent : last_uid IMAP stocké dans shared_settings ("imap_last_uid").
- Pas de Supabase configuré ou pas de config IMAP → no-op silencieux.

Pourquoi un poller dédié à Triskell Command et pas l'imap_listener de Triskell
Core : Core écrit dans le CRM JSON local et n'a pas de classification IA.
Ici on veut Supabase + classification dès la 1re détection pour que la vue
"Réponses" soit utile sans pré-traitement humain.
"""

from __future__ import annotations

import email
import imaplib
import json
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Catégories de classification — alignées avec ce que l'UI attendra
CATEGORIES = ("interested", "not_now", "no", "unsubscribe", "unknown")

POLL_INTERVAL_SECONDS = 300  # 5 min
INITIAL_DELAY_SECONDS = 30   # laisse l'app finir son boot


_POLLER_THREAD: Optional[threading.Thread] = None
_POLLER_STOP = threading.Event()
_POLLER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


def start_poller(app_state) -> bool:
    """Lance le poller en background. Idempotent."""
    global _POLLER_THREAD
    with _POLLER_LOCK:
        if _POLLER_THREAD is not None and _POLLER_THREAD.is_alive():
            return True
        _POLLER_STOP.clear()
        t = threading.Thread(
            target=_poller_loop, args=(app_state,),
            name="RepliesPoller", daemon=True,
        )
        t.start()
        _POLLER_THREAD = t
    return True


def stop_poller() -> None:
    _POLLER_STOP.set()


def get_status() -> dict:
    return {
        "running": _POLLER_THREAD is not None and _POLLER_THREAD.is_alive(),
        "last_run_at": _LAST_RUN_AT,
        "last_run_result": dict(_LAST_RUN_RESULT),
    }


def poll_now(app_state) -> dict:
    """Force un cycle de poll synchrone et renvoie le résultat."""
    return _do_one_poll(app_state)


# ---------------------------------------------------------------------------
# Boucle interne
# ---------------------------------------------------------------------------
def _poller_loop(app_state) -> None:
    # Délai initial pour ne pas bloquer le boot UI
    if _POLLER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _POLLER_STOP.is_set():
        try:
            _do_one_poll(app_state)
        except Exception as exc:
            logger.warning("RepliesPoller cycle: %s", exc)
        # Sleep par tranches de 5s pour permettre stop rapide
        for _ in range(POLL_INTERVAL_SECONDS // 5):
            if _POLLER_STOP.is_set():
                return
            time.sleep(5)


def _do_one_poll(app_state) -> dict:
    """Un cycle complet : IMAP fetch → classify → write Supabase."""
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    counters = {"scanned": 0, "matched": 0, "classified": 0,
                "written": 0, "errors": 0, "skipped": 0}

    client = _get_supabase_client()
    if client is None:
        counters["error"] = "supabase_unavailable"
        _LAST_RUN_RESULT = counters
        _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
        return counters

    imap_cfg = _resolve_imap_config(app_state, client)
    if not imap_cfg:
        counters["error"] = "imap_not_configured"
        _LAST_RUN_RESULT = counters
        _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
        return counters

    # last_uid : on le persiste dans shared_settings pour partager entre Jordan et Thomas
    last_uid = int(client.get_shared_setting("imap_last_uid", 0) or 0)

    try:
        M = imaplib.IMAP4_SSL(imap_cfg["host"], imap_cfg["port"])
        try:
            M.login(imap_cfg["user"], imap_cfg["password"])
            M.select("INBOX", readonly=True)

            criteria = f"UID {last_uid + 1}:*" if last_uid else "ALL"
            typ, data = M.uid("search", None, criteria)
            if typ != "OK":
                counters["error"] = f"imap_search_{typ}"
                return counters
            uids = data[0].split() if data and data[0] else []
            if not uids:
                return counters

            # Index prospects pour matching
            msgid_to_prospect, from_to_prospect = _build_prospect_index(client)
            ai_settings = _resolve_ai_settings(app_state, client)
            max_uid_seen = last_uid

            for uid in uids:
                uid_int = int(uid)
                max_uid_seen = max(max_uid_seen, uid_int)
                counters["scanned"] += 1
                try:
                    typ, msg_data = M.uid(
                        "fetch", uid,
                        "(BODY.PEEK[HEADER.FIELDS (FROM IN-REPLY-TO REFERENCES SUBJECT DATE)] BODY.PEEK[TEXT])",
                    )
                    if typ != "OK" or not msg_data:
                        counters["errors"] += 1
                        continue
                    headers, body = _parse_fetch_response(msg_data)
                    in_reply_to = _extract_msg_id(headers.get("In-Reply-To", ""))
                    references = headers.get("References", "") or ""
                    from_addr = _from_address(headers.get("From", ""))
                    subject = (headers.get("Subject") or "").strip()

                    # Match précis puis flou
                    prospect_id = None
                    for cand in [in_reply_to] + [
                        _extract_msg_id(r) for r in references.split()
                    ]:
                        if cand and cand in msgid_to_prospect:
                            prospect_id = msgid_to_prospect[cand]
                            break
                    if prospect_id is None and from_addr:
                        prospect_id = from_to_prospect.get(from_addr.lower())
                    if prospect_id is None:
                        counters["skipped"] += 1
                        continue
                    counters["matched"] += 1

                    # Anti-doublon : si on a déjà un reply_received avec ce
                    # message_id pour ce prospect, on saute.
                    if _already_logged(client, prospect_id, in_reply_to,
                                        from_addr, subject):
                        counters["skipped"] += 1
                        continue

                    # Classification IA (best-effort)
                    classification = _classify_reply(
                        ai_settings, subject=subject, body=body, from_addr=from_addr,
                    )
                    counters["classified"] += 1

                    # Écriture email_history
                    extra = {
                        "classification": classification,
                        "body_excerpt": (body or "")[:1500],
                        "from": from_addr,
                        "in_reply_to": in_reply_to,
                        "handled": False,
                    }
                    row = {
                        "prospect_id": prospect_id,
                        "kind": "reply_received",
                        "ts": datetime.now().isoformat(timespec="seconds"),
                        "subject": subject[:200],
                        "body": "",  # body excerpt va dans extra
                        "extra": extra,
                        "created_by": client.user_id,
                    }
                    try:
                        ins = client.raw.table("email_history").insert(row).execute()
                        counters["written"] += 1
                        history_row_id = (ins.data or [{}])[0].get("id", "")
                    except Exception as exc:
                        logger.warning("insert email_history KO: %s", exc)
                        counters["errors"] += 1
                        continue

                    # Génère un draft de réponse suggéré (best-effort)
                    if history_row_id:
                        try:
                            from . import reply_responder
                            # Récupère le prospect pour personnalisation
                            pres = (client.raw.table("prospects")
                                    .select("name,legal_name,emails")
                                    .eq("id", prospect_id).limit(1).execute())
                            prospect = (pres.data or [{}])[0]
                            reply_responder.ensure_suggested_reply(
                                client, history_row_id,
                                classification=classification,
                                prospect=prospect,
                                reply_subject=subject,
                                reply_body=body,
                                in_reply_to=in_reply_to,
                                app_state=app_state,
                            )
                        except Exception as exc:
                            logger.debug("ensure_suggested_reply: %s", exc)

                    # Mise à jour status prospect
                    try:
                        # On ne dégrade pas un status final (won/lost/refused)
                        sb = client.raw
                        cur = (sb.table("prospects").select("status")
                               .eq("id", prospect_id).limit(1).execute())
                        cur_status = ((cur.data or [{}])[0].get("status") or "").lower()
                        if cur_status not in ("won", "lost", "refused", "replied"):
                            sb.table("prospects").update({
                                "status": "replied",
                                "last_contact_at": datetime.now().isoformat(timespec="seconds"),
                                "updated_by": client.user_id,
                            }).eq("id", prospect_id).execute()
                    except Exception as exc:
                        logger.debug("update status KO: %s", exc)

                except Exception as exc:
                    logger.warning("UID %s: %s", uid_int, exc)
                    counters["errors"] += 1

            # Persiste le dernier UID vu
            if max_uid_seen > last_uid:
                try:
                    client.set_shared_setting("imap_last_uid", max_uid_seen)
                except Exception as exc:
                    logger.debug("save last_uid KO: %s", exc)
        finally:
            try:
                M.logout()
            except Exception:
                pass
    except imaplib.IMAP4.error as exc:
        counters["error"] = f"imap_login_{exc}"
    except Exception as exc:
        counters["error"] = str(exc)

    _LAST_RUN_RESULT = counters
    _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
    return counters


# ---------------------------------------------------------------------------
# Helpers IMAP / parsing
# ---------------------------------------------------------------------------
def _parse_fetch_response(msg_data) -> tuple[dict, str]:
    """Renvoie (dict_headers, str_body_text). Robuste aux réponses imaplib
    multi-tuple (cas Office365 / certains serveurs)."""
    headers: dict = {}
    body_parts: list[str] = []
    for part in msg_data:
        if not isinstance(part, tuple):
            continue
        raw = part[1]
        if isinstance(raw, bytes):
            text = raw.decode("utf-8", errors="ignore")
        else:
            text = str(raw or "")
        if not text:
            continue
        # Heuristique : si ça commence par un header connu, c'est l'en-tête,
        # sinon c'est du body (text/plain).
        first = text.lstrip().split(":", 1)[0].lower()
        if first in ("from", "in-reply-to", "references", "subject", "date"):
            try:
                m = email.message_from_string(text)
                for k in ("From", "In-Reply-To", "References", "Subject", "Date"):
                    v = m.get(k)
                    if v and k not in headers:
                        headers[k] = v
            except Exception:
                pass
        else:
            body_parts.append(text)
    body = "\n".join(body_parts).strip()
    # Body sans HTML grossier — on enlève les balises pour rester lisible
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+\n", "\n", body)
    body = re.sub(r"[ \t]+", " ", body).strip()
    return headers, body


def _extract_msg_id(raw: str) -> str:
    if not raw:
        return ""
    m = re.search(r"<([^>]+)>", raw)
    return m.group(1).strip() if m else raw.strip()


def _from_address(raw: str) -> str:
    if not raw:
        return ""
    addr = email.utils.parseaddr(raw)
    return (addr[1] or "").lower().strip()


# ---------------------------------------------------------------------------
# Helpers Supabase
# ---------------------------------------------------------------------------
def _get_supabase_client():
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


def _resolve_imap_config(app_state, client) -> Optional[dict]:
    """Cherche IMAP config : shared_settings d'abord, settings.json local sinon."""
    sb = client.get_shared_setting("imap_config", None)
    if sb and isinstance(sb, dict):
        host = (sb.get("imap_host") or "").strip()
        user = (sb.get("imap_user") or "").strip()
        password = sb.get("imap_password") or ""
        port = int(sb.get("imap_port") or 993)
        if host and user and password:
            return {"host": host, "port": port, "user": user, "password": password}
    # Fallback : settings.json local
    out = app_state.get("outreach", default={}) or {}
    host = (out.get("imap_host") or "").strip()
    user = (out.get("imap_user") or "").strip()
    password = out.get("imap_password") or ""
    port = int(out.get("imap_port") or 993)
    if host and user and password:
        return {"host": host, "port": port, "user": user, "password": password}
    return None


def _resolve_ai_settings(app_state, client) -> dict:
    """Provider + clé pour la classification. Préfère shared_settings."""
    out: dict = {"provider": "", "model": "", "api_key": ""}
    sb = client.get_shared_setting("ai", None)
    if sb and isinstance(sb, dict):
        out["provider"] = sb.get("selected_provider", "") or ""
        out["model"] = sb.get("selected_model", "") or ""
        keys = sb.get("api_keys") or {}
        if out["provider"]:
            out["api_key"] = keys.get(out["provider"], "") or ""
    if not out["provider"] or not out["api_key"]:
        ai = app_state.get("ai", default={}) or {}
        out["provider"] = ai.get("selected_provider", "") or out["provider"]
        out["model"] = ai.get("selected_model", "") or out["model"]
        keys = ai.get("api_keys") or {}
        if out["provider"]:
            out["api_key"] = keys.get(out["provider"], "") or out["api_key"]
    return out


def _build_prospect_index(client) -> tuple[dict, dict]:
    """Renvoie (msgid → prospect_id, from_email → prospect_id) en lisant
    prospects + email_history (kind=email_sent)."""
    msgid_to: dict = {}
    from_to: dict = {}
    sb = client.raw
    try:
        # Tous les prospects (id + emails)
        res = sb.table("prospects").select("id,emails").execute()
        for row in res.data or []:
            pid = row.get("id")
            emails = row.get("emails") or []
            for em in emails:
                if em:
                    from_to[str(em).lower().strip()] = pid
        # Tous les message_id envoyés
        res2 = (sb.table("email_history").select("prospect_id,message_id")
                .eq("kind", "email_sent").execute())
        for row in res2.data or []:
            mid = (row.get("message_id") or "").strip()
            pid = row.get("prospect_id")
            if mid and pid:
                clean = _extract_msg_id(mid)
                if clean:
                    msgid_to[clean] = pid
    except Exception as exc:
        logger.warning("build_prospect_index: %s", exc)
    return msgid_to, from_to


def _already_logged(client, prospect_id: str, in_reply_to: str,
                     from_addr: str, subject: str) -> bool:
    """Évite d'écrire 2x la même réponse si le poller refait un cycle après crash."""
    try:
        sb = client.raw
        # Check par message_id (in_reply_to stocké dans extra) — limite aux 50
        # derniers reply_received pour ce prospect.
        res = (sb.table("email_history")
               .select("subject,extra")
               .eq("prospect_id", prospect_id)
               .eq("kind", "reply_received")
               .order("ts", desc=True).limit(50).execute())
        for row in res.data or []:
            extra = row.get("extra") or {}
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except Exception:
                    extra = {}
            same_thread = (in_reply_to and
                            extra.get("in_reply_to") == in_reply_to)
            same_subject_from = (
                subject and from_addr
                and (row.get("subject") or "").strip()[:200] == subject[:200]
                and (extra.get("from") or "").lower() == from_addr.lower()
            )
            if same_thread or same_subject_from:
                return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Classification IA
# ---------------------------------------------------------------------------
CLASSIFY_PROMPT = (
    "Classe ce mail entrant en UNE catégorie parmi : "
    "interested, not_now, no, unsubscribe, unknown.\n"
    "- interested = montre un intérêt clair (veut en savoir plus, demande RDV, "
    "  prix, démo, échange).\n"
    "- not_now = poli mais reporte (pas le bon moment, recontactez plus tard, "
    "  en vacances, en réunion, etc).\n"
    "- no = refus net (pas intéressé, pas pour nous, on a déjà, merci non).\n"
    "- unsubscribe = demande explicite de désinscription / arrêter les mails / "
    "  RGPD / spam.\n"
    "- unknown = auto-réponse, hors-sujet, contenu vide, ou impossible à classer.\n"
    "\n"
    "RÉPONDS UNIQUEMENT par un JSON valide : "
    '{\"category\": \"interested\", \"confidence\": 0.85, \"reason\": "..."}\n'
    "Aucun autre texte avant ou après le JSON."
)


def _classify_reply(ai: dict, *, subject: str, body: str,
                     from_addr: str) -> dict:
    """Renvoie {category, confidence, reason}. Fallback unknown si pas d'IA."""
    out = {"category": "unknown", "confidence": 0.0, "reason": "no_ai_configured"}
    provider = (ai.get("provider") or "").strip()
    api_key = (ai.get("api_key") or "").strip()
    model = (ai.get("model") or "").strip()
    if not provider or not api_key:
        return out
    try:
        from triskell_core.ai.providers import send_to_provider, ProviderError
    except ImportError:
        return out
    user_msg = (
        f"De : {from_addr}\nObjet : {subject}\n\n"
        f"Corps :\n{(body or '')[:4000]}"
    )
    try:
        prompt = CLASSIFY_PROMPT + "\n\n---\n\n" + user_msg
        api_keys = {provider: api_key}
        text = send_to_provider(provider, model or "", prompt, api_keys)
        text = (text or "").strip()
        # Extrait le 1er JSON
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
                cat = (data.get("category") or "").strip().lower()
                if cat in CATEGORIES:
                    return {
                        "category": cat,
                        "confidence": float(data.get("confidence", 0.0) or 0.0),
                        "reason": (data.get("reason") or "")[:300],
                    }
            except Exception:
                pass
        # Fallback : essaye keyword match sur la réponse brute
        low = text.lower()
        for cat in CATEGORIES:
            if cat in low:
                return {"category": cat, "confidence": 0.4,
                        "reason": "keyword_fallback"}
    except ProviderError as exc:
        return {"category": "unknown", "confidence": 0.0,
                "reason": f"ai_error: {exc}"[:300]}
    except Exception as exc:
        return {"category": "unknown", "confidence": 0.0,
                "reason": f"ai_exc: {exc}"[:300]}
    return out
