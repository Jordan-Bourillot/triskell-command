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
import quopri
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

# Deux versions de marker :
#   V1 → payload plat 8 champs (form rapide ou ancien intake auto)
#   V2 → payload complet (wizard détaillé : billing + site.{typeSite,
#        identite, structure, contenu, medias, reseauxSociaux, multilingue})
#
# V1 est plat → `[^{}]*` matche un seul niveau d'objet.
# V2 contient des objets imbriqués (site.identite, site.structure, etc.)
# → on tolère 2 niveaux d'imbrication via une alternation.
#
# Le mail multi-part contient le marker DEUX FOIS (text/plain + text/html
# après strip). MARKER_RE_V1 et MARKER_RE_V2 utilisent une stratégie
# non-greedy + équilibrage limité pour éviter de fusionner les 2 occurrences.
MARKER_RE_V1 = re.compile(
    r"\[TRISKELL-INTAKE-V1\]\s*(\{[^{}]*\})",
    re.IGNORECASE | re.DOTALL,
)
# Pour V2, le payload contient des objets imbriqués. On accepte des `{}`
# imbriqués mais on s'arrête au premier `}` qui ferme l'objet racine —
# implémenté via comptage manuel (cf. _extract_v2_marker).
MARKER_V2_HEAD = re.compile(
    r"\[TRISKELL-INTAKE-V2\]\s*\{",
    re.IGNORECASE,
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

                    # Filtre subject + header dédié (l'un OU l'autre suffit).
                    # V1 : header `site-request` ou subject « Demande de
                    #      création de site … ».
                    # V2 : header `site-request-detailed` ou subject
                    #      « Configuration de site … ».
                    is_intake = (
                        intake_hdr in ("site-request", "site-request-detailed")
                        or (subject_prefix and subject_prefix in subject.lower())
                        or "configuration de site" in subject.lower()
                    )
                    if not is_intake:
                        counters["skipped"] += 1
                        continue
                    counters["matched"] += 1

                    # Anti-doublon
                    if msg_id and forge_repo.find_brief_by_message_id(msg_id):
                        counters["skipped"] += 1
                        continue

                    # Parse → payload normalisé (V1 ou V2)
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
                        # On crée tout de suite le projet associé.
                        # Pour V2, on passe le payload structuré complet
                        # à local_registry pour qu'il pré-remplisse les 14
                        # étapes du wizard La Forge dès l'écriture du
                        # fichier projet (pas d'analyse Claude nécessaire).
                        forge_repo.create_project_from_brief(
                            brief,
                            auto_run=True,
                            v2_payload=payload.get("v2_payload"),
                            client_filled_steps=bool(
                                payload.get("client_filled_steps")
                            ),
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
def _extract_v2_marker(body: str) -> Optional[dict]:
    """Cherche `[TRISKELL-INTAKE-V2] {...}` avec accolades imbriquées
    (V2 contient site.identite, site.structure, etc.).

    On localise le `{` qui suit le marker, puis on compte les accolades
    jusqu'à retrouver l'équilibre — robuste aux objets imbriqués sans
    tenter de matcher tout en regex.
    """
    head = MARKER_V2_HEAD.search(body)
    if not head:
        return None
    start = head.end() - 1   # position du `{` ouvrant
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(body)):
        c = body[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                raw = body[start:i + 1]
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    logger.debug("marker V2 JSON invalide: %s", exc)
                    return None
    return None


def _parse_intake_payload(body: str) -> Optional[dict]:
    """Tente d'extraire un payload normalisé.

    Stratégie :
      1. V2 : `[TRISKELL-INTAKE-V2] {...payload détaillé...}` → parse JSON
         imbriqué. Marqué `client_filled_steps: True`.
      2. V1 : `[TRISKELL-INTAKE-V1] {...payload plat...}` → parse JSON.
      3. Fallback : regex sur les labels français du mail (`Prénom : …`).

    Renvoie un dict aux clés snake_case alignées sur forge_pending_briefs,
    ou None si rien de viable n'a été trouvé. Le dict V2 inclut un champ
    `client_filled_steps: True` et un sous-objet `site` complet à passer
    tel quel à local_registry.
    """
    if not body:
        return None

    # Stratégie 1 : V2 (marker JSON imbriqué)
    v2 = _extract_v2_marker(body)
    if v2 is not None:
        return _normalize_v2_payload(v2)

    # Stratégie 2 : V1 (marker JSON plat)
    m = MARKER_RE_V1.search(body)
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict):
                return _normalize_payload(data)
        except json.JSONDecodeError as exc:
            logger.debug("marker V1 JSON invalide: %s", exc)

    # Stratégie 3 : fallback regex labels
    return _parse_labelled_body(body)


def _normalize_v2_payload(raw: dict) -> dict:
    """Aplati le payload V2 vers les clés forge_pending_briefs + garde le
    sous-objet `site` complet pour local_registry."""
    def s(*keys: str) -> str:
        for k in keys:
            v = raw.get(k)
            if v:
                return str(v).strip()
        return ""

    site = raw.get("site") or {}
    brief = (site.get("brief") if isinstance(site, dict) else None) or {}

    out = {
        "source":       s("source") or "rankus",
        "first_name":   s("first_name"),
        "last_name":    s("last_name"),
        "email":        s("email"),
        "phone":        s("phone"),
        "address":      s("address"),
        "description":  str(raw.get("description") or brief.get("prompt") or "").strip(),
        "audience":     str(raw.get("audience")    or brief.get("audience") or "").strip(),
        "tone":         str(raw.get("tone")        or brief.get("ton") or "").strip(),
        # Marqueurs V2
        "client_filled_steps": True,
        "client_type":  s("client_type") or "particulier",
        "company_name": s("company_name"),
        "siret":        s("siret"),
        "vat_number":   s("vat_number"),
        # Payload structuré complet (typeSite, identite, structure, etc.)
        # Si V2 n'a pas envoyé `site`, on reconstruit minimalement à partir
        # des champs aplatis pour rester compatible avec local_registry.
        "v2_payload":   raw,
    }
    return out


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
# suit le label jusqu'au prochain label connu OU une borne de fin de mail
# (signature `—`, marker JSON, frontière multipart `----`, EOF).
_STOP = (
    r"(?=\n[A-ZÀ-ÿ][^\n]*\s*:\s*\n"   # nouvelle section "Label :\n"
    r"|\n[—–-]\s|"                     # signature "— Envoyé..."
    r"\n\[TRISKELL-INTAKE-V[12]\]|"    # marker machine (V1 ou V2)
    r"\n----|"                          # frontière multipart MIME
    r"\Z)"
)
_BLOCK_PATTERNS = {
    "description": re.compile(
        r"Description du site\s*:?\s*\n+(.+?)" + _STOP,
        re.IGNORECASE | re.DOTALL),
    "audience": re.compile(
        r"Audience(?: vis[ée]e)?\s*:?\s*\n+(.+?)" + _STOP,
        re.IGNORECASE | re.DOTALL),
    "tone": re.compile(
        r"Ton(?: souhait[ée])?\s*:?\s*\n+(.+?)" + _STOP,
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
    """Extrait headers + body texte d'une réponse imaplib.fetch.

    Décode aussi le body si encodé en quoted-printable (cas Resend) — sinon
    les `=\n` soft-line-breaks coupent le marker JSON et les valeurs des
    labels au milieu, ce qui casse le parsing en aval.
    """
    headers: dict = {}
    body_raw_parts: list[bytes] = []
    body_is_qp = False
    for part in msg_data:
        if not isinstance(part, tuple):
            continue
        raw = part[1]
        if not raw:
            continue
        if not isinstance(raw, bytes):
            raw = str(raw).encode("utf-8", errors="ignore")
        text = raw.decode("utf-8", errors="ignore")
        first = text.lstrip().split(":", 1)[0].lower()
        if first in ("from", "subject", "date", "message-id",
                     "x-triskell-intake"):
            try:
                m = email.message_from_string(text)
                for k in ("From", "Subject", "Date", "Message-ID",
                          "X-Triskell-Intake"):
                    v = m.get(k)
                    if v and k not in headers:
                        # decode_header pour les sujets en =?UTF-8?Q?…?=
                        if k == "Subject":
                            try:
                                parts = email.header.decode_header(v)
                                v = "".join(
                                    (s.decode(c or "utf-8", errors="ignore")
                                     if isinstance(s, bytes) else s)
                                    for s, c in parts
                                )
                            except Exception:
                                pass
                        headers[k] = v
            except Exception:
                pass
        else:
            body_raw_parts.append(raw)
            # Heuristique : si le body contient un en-tête CTE quoted-printable
            # quelque part, on saura qu'il faut décoder.
            if b"quoted-printable" in raw.lower():
                body_is_qp = True

    body_blob = b"\n".join(body_raw_parts)

    # Décodage quoted-printable si détecté. Idempotent en pratique :
    # quopri.decodestring conserve les octets non-encodés tels quels.
    if body_is_qp or b"=\r\n" in body_blob or b"=\n" in body_blob:
        try:
            body_blob = quopri.decodestring(body_blob)
        except Exception:
            pass

    body = body_blob.decode("utf-8", errors="ignore")
    # Strip HTML tags (si multi-part avec HTML)
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
