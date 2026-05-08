"""Bridge Teddy Mail → La Forge du Web.

Ce module fait communiquer les deux apps **à l'intérieur de Triskell
Command** : Teddy détecte un mail "Demande de création de site" reçu
sur la boîte IMAP partagée → on l'extrait, on le parse, on dépose un
row dans `forge_pending_briefs`, et (selon `auto_create_project`) on
crée immédiatement un `forge_projects` qui sera traité plus tard par
le moteur 14 étapes de La Forge.

Conception :
- Poller IMAP indépendant du `replies_poller` (cursor `imap_last_uid_forge`
  séparé pour ne pas se gêner). Cycle 5 min, lecture seule.
- Filtre principal : sujet contenant `Demande de création de site`
  (configurable via shared_settings.forge_intake_config).
- Parsing principal : ligne machine `[TRISKELL-INTAKE-V1] {...}` JSON
  injectée par les netlify functions des sites Triskell. Fallback regex
  sur `Prénom : / Nom : / …` si le marker a été écorné par un MTA.
- Anti-doublon : on dédoublonne sur le Message-ID du mail.
- Idempotent : si un brief existe déjà pour ce Message-ID, no-op.

Lancement : appelé depuis main.py._start_sync_poller (au login Supabase).
"""

from __future__ import annotations

import email
import imaplib
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from . import pulse_bus
from .forge import repo as forge_repo

logger = logging.getLogger(__name__)


POLL_INTERVAL_SECONDS = 300        # 5 min, aligné avec replies_poller
INITIAL_DELAY_SECONDS = 45         # juste après replies_poller (qui a 30 s)

MARKER_RE = re.compile(
    r"\[TRISKELL-INTAKE-V1\]\s*(\{.*\})",
    re.IGNORECASE | re.DOTALL,
)


_POLLER_THREAD: Optional[threading.Thread] = None
_POLLER_STOP = threading.Event()
_POLLER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def start_poller(app_state) -> bool:
    """Lance le bridge en background. Idempotent."""
    global _POLLER_THREAD
    with _POLLER_LOCK:
        if _POLLER_THREAD is not None and _POLLER_THREAD.is_alive():
            return True
        _POLLER_STOP.clear()
        t = threading.Thread(
            target=_poller_loop, args=(app_state,),
            name="TeddyToForgeBridge", daemon=True,
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
    """Force un cycle de poll synchrone (utile pour debug + tests E2E)."""
    return _do_one_poll(app_state)


# ---------------------------------------------------------------------------
# Boucle interne
# ---------------------------------------------------------------------------
def _poller_loop(app_state) -> None:
    if _POLLER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _POLLER_STOP.is_set():
        try:
            result = _do_one_poll(app_state)
            written = (result or {}).get("written", 0)
            err = (result or {}).get("error")
            if written > 0:
                pulse_bus.report(
                    "forge", "active",
                    text=(f"{written} demande de site reçue"
                          if written == 1
                          else f"{written} demandes de site reçues"),
                    relative_time="à l'instant",
                )
            elif err:
                pulse_bus.report("forge", "error", error=str(err))
        except Exception as exc:
            logger.warning("TeddyToForge cycle: %s", exc)
            try:
                pulse_bus.report("forge", "error", error=str(exc))
            except Exception:
                pass
        # Sleep par tranches de 5 s pour permettre stop rapide
        for _ in range(POLL_INTERVAL_SECONDS // 5):
            if _POLLER_STOP.is_set():
                return
            time.sleep(5)


def _do_one_poll(app_state) -> dict:
    """Un cycle complet : IMAP fetch → filter → parse → insert brief."""
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    counters = {"scanned": 0, "matched": 0, "written": 0,
                "skipped": 0, "errors": 0}

    cfg = forge_repo.get_intake_config()
    if not cfg.get("enabled", True):
        counters["error"] = "intake_disabled"
        _LAST_RUN_RESULT = counters
        _LAST_RUN_AT = _now_iso()
        return counters

    client = _get_supabase_client()
    if client is None:
        counters["error"] = "supabase_unavailable"
        _LAST_RUN_RESULT = counters
        _LAST_RUN_AT = _now_iso()
        return counters

    imap_cfg = _resolve_imap_config(app_state, client)
    if not imap_cfg:
        counters["error"] = "imap_not_configured"
        _LAST_RUN_RESULT = counters
        _LAST_RUN_AT = _now_iso()
        return counters

    last_uid = int(client.get_shared_setting("imap_last_uid_forge", 0) or 0)
    subject_prefix = (cfg.get("subject_prefix") or "").strip().lower()
    auto_create = bool(cfg.get("auto_create_project", True))

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

            max_uid_seen = last_uid

            for uid in uids:
                uid_int = int(uid)
                max_uid_seen = max(max_uid_seen, uid_int)
                counters["scanned"] += 1
                try:
                    typ, msg_data = M.uid(
                        "fetch", uid,
                        "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID X-TRISKELL-INTAKE)] BODY.PEEK[TEXT])",
                    )
                    if typ != "OK" or not msg_data:
                        counters["errors"] += 1
                        continue
                    headers, body = _parse_fetch_response(msg_data)
                    subject = (headers.get("Subject") or "").strip()
                    msg_id = _extract_msg_id(headers.get("Message-ID", ""))
                    intake_hdr = (headers.get("X-Triskell-Intake") or "").strip().lower()

                    # Filtre subject + header dédié (l'un OU l'autre suffit)
                    is_intake = (
                        intake_hdr == "site-request"
                        or (subject_prefix and subject_prefix in subject.lower())
                    )
                    if not is_intake:
                        counters["skipped"] += 1
                        continue
                    counters["matched"] += 1

                    # Anti-doublon
                    if msg_id and forge_repo.find_brief_by_message_id(msg_id):
                        counters["skipped"] += 1
                        continue

                    # Parse → payload normalisé
                    payload = _parse_intake_payload(body)
                    if not payload:
                        logger.warning(
                            "Intake détecté (subject='%s') mais payload illisible",
                            subject,
                        )
                        counters["errors"] += 1
                        continue

                    payload["raw_email_subject"] = subject
                    payload["raw_email_message_id"] = msg_id
                    payload["raw_email_excerpt"] = (body or "")[:2000]

                    brief = forge_repo.insert_brief(payload)
                    if not brief:
                        counters["errors"] += 1
                        continue
                    counters["written"] += 1

                    if auto_create:
                        # Mode validation auto jusqu'à l'étape 14 :
                        # on crée tout de suite le projet associé, queued.
                        forge_repo.create_project_from_brief(
                            brief, auto_run=True,
                        )

                except Exception as exc:
                    logger.warning("UID %s: %s", uid_int, exc)
                    counters["errors"] += 1

            if max_uid_seen > last_uid:
                try:
                    client.set_shared_setting(
                        "imap_last_uid_forge", max_uid_seen,
                    )
                except Exception as exc:
                    logger.debug("save imap_last_uid_forge KO: %s", exc)
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
    _LAST_RUN_AT = _now_iso()
    return counters


# ---------------------------------------------------------------------------
# Parsing du payload depuis le mail
# ---------------------------------------------------------------------------
def _parse_intake_payload(body: str) -> Optional[dict]:
    """Tente d'extraire un payload normalisé.

    Stratégie :
      1. Cherche la ligne `[TRISKELL-INTAKE-V1] {...}` → parse JSON.
      2. Fallback : regex sur les labels français du mail (`Prénom : ...`).
    Renvoie un dict aux clés snake_case alignées sur forge_pending_briefs,
    ou None si rien de viable n'a été trouvé.
    """
    if not body:
        return None

    # Stratégie 1 : marker JSON
    m = MARKER_RE.search(body)
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict):
                return _normalize_payload(data)
        except json.JSONDecodeError as exc:
            logger.debug("marker JSON invalide: %s", exc)

    # Stratégie 2 : fallback regex labels
    return _parse_labelled_body(body)


def _normalize_payload(raw: dict) -> dict:
    """Coerce les clés possibles vers le schéma cible."""
    def pick(*keys: str) -> str:
        for k in keys:
            v = raw.get(k)
            if v:
                return str(v).strip()
        return ""

    return {
        "source":       pick("source") or "site-request",
        "first_name":   pick("first_name", "firstName", "prenom"),
        "last_name":    pick("last_name", "lastName", "nom"),
        "email":        pick("email"),
        "phone":        pick("phone", "tel", "telephone"),
        "address":      pick("address", "adresse"),
        "description":  pick("description"),
        "audience":     pick("audience"),
        "tone":         pick("tone", "ton"),
    }


_LABEL_PATTERNS = {
    "first_name":  re.compile(r"^Pr[ée]nom\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE),
    "last_name":   re.compile(r"^Nom\s*:\s*(.+)$",       re.MULTILINE | re.IGNORECASE),
    "email":       re.compile(r"^Email\s*:\s*(\S+@\S+)", re.MULTILINE | re.IGNORECASE),
    "phone":       re.compile(r"^T[ée]l[ée]phone\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE),
    "address":     re.compile(r"^Adresse\s*:\s*(.+)$",   re.MULTILINE | re.IGNORECASE),
}

# Pour les blocs multilignes (Description / Audience / Ton), on prend ce qui
# suit le label jusqu'à la prochaine ligne de label vide ou nouvelle section.
_BLOCK_PATTERNS = {
    "description": re.compile(
        r"Description du site\s*:?\s*\n+(.+?)(?=\n[A-ZÀ-ÿ][^\n]*\s*:\s*\n|\Z)",
        re.IGNORECASE | re.DOTALL),
    "audience": re.compile(
        r"Audience(?: vis[ée]e)?\s*:?\s*\n+(.+?)(?=\n[A-ZÀ-ÿ][^\n]*\s*:\s*\n|\Z)",
        re.IGNORECASE | re.DOTALL),
    "tone": re.compile(
        r"Ton(?: souhait[ée])?\s*:?\s*\n+(.+?)(?=\n[A-ZÀ-ÿ][^\n]*\s*:\s*\n|\Z)",
        re.IGNORECASE | re.DOTALL),
}


def _parse_labelled_body(body: str) -> Optional[dict]:
    out: dict = {"source": "site-request"}
    found = False
    for key, pat in _LABEL_PATTERNS.items():
        m = pat.search(body)
        if m:
            out[key] = m.group(1).strip()
            found = True
    for key, pat in _BLOCK_PATTERNS.items():
        m = pat.search(body)
        if m:
            out[key] = m.group(1).strip()
            found = True
    if not found or not out.get("email"):
        return None
    return _normalize_payload(out)


# ---------------------------------------------------------------------------
# Helpers IMAP / parsing (alignés sur replies_poller)
# ---------------------------------------------------------------------------
def _parse_fetch_response(msg_data) -> tuple[dict, str]:
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
        first = text.lstrip().split(":", 1)[0].lower()
        if first in ("from", "subject", "date", "message-id",
                     "x-triskell-intake"):
            try:
                m = email.message_from_string(text)
                for k in ("From", "Subject", "Date", "Message-ID",
                          "X-Triskell-Intake"):
                    v = m.get(k)
                    if v and k not in headers:
                        headers[k] = v
            except Exception:
                pass
        else:
            body_parts.append(text)
    body = "\n".join(body_parts).strip()
    # Décodage HTML grossier — on garde la version brute pour parsing,
    # mais on enlève les tags si le mail est multi-part HTML.
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+\n", "\n", body)
    body = re.sub(r"[ \t]+", " ", body)
    return headers, body.strip()


def _extract_msg_id(raw: str) -> str:
    if not raw:
        return ""
    m = re.search(r"<([^>]+)>", raw)
    return m.group(1).strip() if m else raw.strip()


# ---------------------------------------------------------------------------
# Helpers Supabase / IMAP config (réutilise la même config que replies_poller)
# ---------------------------------------------------------------------------
def _get_supabase_client():
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


def _resolve_imap_config(app_state, client) -> Optional[dict]:
    """Même config que replies_poller (boîte unique partagée)."""
    sb = client.get_shared_setting("imap_config", None)
    if isinstance(sb, dict):
        host = (sb.get("imap_host") or "").strip()
        user = (sb.get("imap_user") or "").strip()
        password = sb.get("imap_password") or ""
        port = int(sb.get("imap_port") or 993)
        if host and user and password:
            return {"host": host, "port": port,
                    "user": user, "password": password}
    out = app_state.get("outreach", default={}) or {}
    host = (out.get("imap_host") or "").strip()
    user = (out.get("imap_user") or "").strip()
    password = out.get("imap_password") or ""
    port = int(out.get("imap_port") or 993)
    if host and user and password:
        return {"host": host, "port": port,
                "user": user, "password": password}
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
