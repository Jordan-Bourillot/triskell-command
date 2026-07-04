"""Relances créateurs — robot de fond du carnet `contacted_creators`.

Conception (purement additif, ne touche RIEN au flux prospection PME) :
- Worker thread daemon, cycle ~30 min. À chaque tour, parcourt le carnet
  (`creators_book.list_all()`) et, fiche par fiche :

  (A) platform == "Email"
      1. `contacted_at` vide → cherche dans le dossier ENVOYÉS un message
         envoyé à l'adresse `handle`. Trouvé → pose `contacted_at` (date du
         mail) et `next_follow_up_at` = +7 j.
      2. `contacted_at` posé → cherche dans INBOX une réponse DE `handle`
         postérieure. Trouvée → vide `next_follow_up_at`, ajoute une note
         « a répondu le … », et NE relance PAS.
      3. `contacted_at` posé, pas de réponse, 7 j passés, pas déjà relancé →
         dépose UN brouillon de relance dans « Brouillons » (réutilise
         l'append IMAP de `creators_make_draft`), mémorise l'id relancé, et
         vide `next_follow_up_at` (une seule relance auto en v1).

  (B) platform ∈ {"Instagram", "TikTok"}
      Le robot ne sait pas lire Instagram/TikTok. Il n'agit que si
      `contacted_at` est posé À LA MAIN et `next_follow_up_at <= now` :
      envoie un push « pense à relancer en DM » puis vide
      `next_follow_up_at` (pour ne pas répéter le rappel).

Robustesse : tout est dans des try/except par fiche (une fiche en erreur ne
casse jamais le cycle) ; sans config IMAP, on ne traite pas les mails (juste
les rappels Instagram) sans planter. L'état (last_check_at + résumé + ids
relancés) est mémorisé dans shared_settings["creator_followup_state"].

Le branchement IMAP (login, dossiers Brouillons candidats, append) reprend
exactement la logique éprouvée de `web/api.py::creators_make_draft` /
`_imap_drafts_candidates` (mailbox quoté, flag `(\\Draft)`, time.time()
passé à append qui gère Time2Internaldate lui-même, parsing LIST par regex).
"""
from __future__ import annotations

import email
import imaplib
import logging
import re
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

STATE_KEY = "creator_followup_state"
RELANCES_KEY = "creator_relances"   # textes de relance personnalisés par id

FOLLOW_UP_DAYS = 7
CYCLE_INTERVAL_SECONDS = 1800        # 30 min
INITIAL_DELAY_SECONDS = 120          # laisse l'app finir son boot

# Dossiers « Envoyés » à essayer (le nom exact varie selon la boîte), même
# esprit que les candidats « Brouillons » de creators_make_draft.
SENT_FOLDER_CANDIDATES = (
    "Sent", "Envoyés", "Sent Items", "INBOX.Sent",
    "INBOX.Sent Items", "INBOX.Envoyés", "Sent Messages",
)

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


# ===========================================================================
# LOGIQUE PURE (testée sans réseau par scripts/smoke_creator_followup.py)
# ===========================================================================
def creator_greet(name: str) -> str:
    """Tire un prénom propre d'un nom de fiche créateur.

    Heuristique simple et raisonnable :
    - Si le nom contient des parenthèses, on prend ce qu'il y a DEDANS puis
      son 1er mot (les fiches notent souvent « pseudo (Prénom Nom) »).
    - Sinon, le 1er mot du nom.
    - Mais on garde un nom de MARQUE entier (ex. « Mamie Crochet ») quand il
      n'y a pas de parenthèses et qu'il ressemble à une marque (≥ 2 mots dont
      aucun n'est un prénom isolé évident) — on s'en tient à un garde-fou
      simple : si le 1er mot est un mot « générique de marque » courant
      (Mamie, Atelier, Studio, Chez, Les, La, Le, Maison, Boutique…), on
      garde le nom entier.
    """
    raw = (name or "").strip()
    if not raw:
        return ""

    # 1) Contenu entre parenthèses prioritaire (« pseudo (Prénom Nom) »).
    m = re.search(r"\(([^)]+)\)", raw)
    if m:
        inside = m.group(1).strip()
        if inside:
            first = inside.split()[0].strip(" .,-")
            if first:
                return first

    parts = raw.split()
    if not parts:
        return ""

    # 2) Marque sans prénom : on garde le nom entier.
    BRAND_LEADS = {
        "mamie", "papy", "papi", "tata", "tonton", "atelier", "studio",
        "chez", "les", "la", "le", "maison", "boutique", "team", "compagnie",
        "cie", "association", "asso", "collectif", "fabrique",
    }
    first_low = parts[0].lower().strip(" .,-")
    if len(parts) >= 2 and first_low in BRAND_LEADS:
        return raw

    # 3) Cas courant : 1er mot = prénom.
    return parts[0].strip(" .,-")


def render_followup_body(greet: str, demo_url: str) -> str:
    """Corps de relance par défaut. Pas de tiret cadratin, pas de « : »
    d'annonce, ton chaleureux qui invite (pas d'impératif, pas d'appel
    téléphonique) — conforme aux règles d'écriture de Jordan."""
    g = (greet or "").strip()
    hello = f"Coucou {g} !" if g else "Coucou !"
    url = (demo_url or "").strip()
    return (
        f"{hello} Je reviens vers toi, au cas où mon premier message "
        f"serait passé à la trappe :) Le club que je t'ai préparé est "
        f"toujours là -> {url}. Si l'idée te branche, dis-moi, je te "
        f"montre tout :)"
    )


def followup_subject() -> str:
    """Sujet court et léger pour la relance."""
    return "Je reviens vers toi :)"


def _norm_platform(platform: str) -> str:
    return (platform or "").strip().lower()


def route_creator(platform: str) -> str:
    """Aiguillage par plateforme : 'email', 'social' (Instagram/TikTok) ou
    'ignore' (tout le reste — le robot ne sait pas quoi en faire)."""
    p = _norm_platform(platform)
    if p == "email":
        return "email"
    if p in ("instagram", "tiktok"):
        return "social"
    return "ignore"


def should_relance(row: dict, now: datetime,
                   relanced_ids: Optional[set] = None) -> bool:
    """Décide s'il faut préparer une relance (étape A3 / B) pour cette fiche.

    Vrai SEULEMENT si :
    - une date de 1er contact est posée (`contacted_at`),
    - une date d'échéance est posée et échue (`next_follow_up_at <= now`),
    - la fiche n'a pas déjà été relancée (id absent de relanced_ids).

    La détection « a déjà répondu » n'est PAS jugée ici : si la personne a
    répondu, l'étape 2 a déjà vidé `next_follow_up_at` (donc next vide = pas
    de relance). Robuste aux dates mal formées (→ pas de relance).
    """
    relanced_ids = relanced_ids or set()
    cid = row.get("id")
    if cid and cid in relanced_ids:
        return False
    contacted = row.get("contacted_at")
    if isinstance(contacted, str):
        contacted = contacted.strip()
    if not contacted:
        return False
    due = _parse_dt(row.get("next_follow_up_at"))
    if due is None:
        return False
    return _as_aware(now) >= due


# ===========================================================================
# Helpers dates
# ===========================================================================
def _as_aware(dt: datetime) -> datetime:
    """Force un datetime en UTC-aware (compare sans planter naïf vs aware)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse une date ISO (ou un datetime) en UTC-aware. None si illisible."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_aware(value)
    s = str(value).strip()
    if not s:
        return None
    # Normalise le suffixe Z et tronque les microsecondes trop longues.
    s2 = s.replace("Z", "+00:00")
    try:
        return _as_aware(datetime.fromisoformat(s2))
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return _as_aware(datetime.strptime(s[:19], fmt))
        except Exception:
            continue
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return _as_aware(dt).isoformat()


# ===========================================================================
# Cycle de vie du worker (calqué sur drip_runner / mission_runner)
# ===========================================================================
def start_worker(app_state) -> bool:
    """Lance le worker en background. Idempotent."""
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _WORKER_STOP.clear()
        t = threading.Thread(target=_loop, args=(app_state,),
                             name="CreatorFollowupWorker", daemon=True)
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
    """Force un cycle synchrone (pour debug/diagnostic)."""
    return _do_one_cycle(app_state)


def _loop(app_state) -> None:
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        try:
            result = _do_one_cycle(app_state)
            # Pulse worker : on ne reporte que du notable (relance/rappel/erreur).
            try:
                from . import pulse_bus
                drafted = result.get("relances_drafted", 0) if isinstance(result, dict) else 0
                pushed = result.get("reminders_pushed", 0) if isinstance(result, dict) else 0
                err = result.get("error") if isinstance(result, dict) else None
                total = drafted + pushed
                if total > 0:
                    parts = []
                    if drafted:
                        parts.append(f"{drafted} relance{'s' if drafted > 1 else ''} préparée{'s' if drafted > 1 else ''}")
                    if pushed:
                        parts.append(f"{pushed} rappel{'s' if pushed > 1 else ''} DM")
                    pulse_bus.report("creator_followup", "active",
                                     text=" + ".join(parts),
                                     relative_time="à l'instant")
                elif err and err != "supabase_unavailable":
                    pulse_bus.report("creator_followup", "error", error=str(err))
            except Exception:
                pass
        except Exception as exc:
            logger.warning("CreatorFollowup cycle: %s", exc)
            try:
                from . import pulse_bus
                pulse_bus.report("creator_followup", "error", error=str(exc))
            except Exception:
                pass
        for _ in range(CYCLE_INTERVAL_SECONDS // 5):
            if _WORKER_STOP.is_set():
                return
            time.sleep(5)


# ===========================================================================
# Accès Supabase / état partagé
# ===========================================================================
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


def _load_state(client) -> dict:
    """État du robot : {last_check_at, summary, relanced_ids:[...]}. Jamais lève."""
    state = {"last_check_at": "", "summary": {}, "relanced_ids": []}
    try:
        raw = client.get_shared_setting(STATE_KEY, {}) or {}
        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        if isinstance(raw, dict):
            state["last_check_at"] = raw.get("last_check_at") or ""
            state["summary"] = raw.get("summary") or {}
            ids = raw.get("relanced_ids") or []
            if isinstance(ids, list):
                state["relanced_ids"] = [str(x) for x in ids if x]
    except Exception as exc:
        logger.debug("creator_followup._load_state: %s", exc)
    return state


def _save_state(client, state: dict) -> None:
    try:
        from .shared_settings_db import upsert_setting
        upsert_setting(client.raw, STATE_KEY, state)
    except Exception as exc:
        logger.debug("creator_followup._save_state: %s", exc)


def _custom_relance_text(client, creator_id: str) -> str:
    """Texte de relance personnalisé pour cette fiche s'il existe dans
    shared_settings["creator_relances"][id], sinon ''. Jamais lève."""
    if not creator_id:
        return ""
    try:
        raw = client.get_shared_setting(RELANCES_KEY, {}) or {}
        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        if isinstance(raw, dict):
            val = raw.get(creator_id)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):  # tolère {"body": "..."} ou {"text": "..."}
                for k in ("body", "text", "message"):
                    if isinstance(val.get(k), str) and val[k].strip():
                        return val[k].strip()
    except Exception as exc:
        logger.debug("creator_followup._custom_relance_text: %s", exc)
    return ""


# ===========================================================================
# Accès IMAP (login + recherche + append brouillon)
# ===========================================================================
def _imap_account(client, app_state) -> Optional[dict]:
    """Renvoie le compte IMAP principal (contact@triskell-studio.fr) avec
    ses identifiants, ou None si pas configuré. Réutilise shared_secrets,
    comme creators_make_draft (account_id='primary')."""
    try:
        from . import shared_secrets
        acc = shared_secrets.get_account_by_id(
            "primary", client=client, app_state=app_state) or {}
    except Exception as exc:
        logger.debug("creator_followup._imap_account: %s", exc)
        return None
    host = (acc.get("imap_host") or "").strip()
    user = (acc.get("imap_user") or "").strip()
    pwd = acc.get("imap_password") or ""
    if not (host and user and pwd):
        return None
    return {
        "host": host,
        "port": int(acc.get("imap_port") or 993),
        "user": user,
        "password": pwd,
        "from_email": (acc.get("from_email") or "").strip(),
        "from_name": (acc.get("from_name") or "").strip(),
    }


def _imap_connect(acc: dict) -> imaplib.IMAP4_SSL:
    ctx = ssl.create_default_context()
    M = imaplib.IMAP4_SSL(acc["host"], acc["port"], ssl_context=ctx)
    M.login(acc["user"], acc["password"])
    return M


def _list_mailboxes(M) -> list[str]:
    """Tous les noms de dossiers IMAP (parse LIST par regex, même pattern
    robuste que _imap_drafts_candidates de api.py)."""
    names: list[str] = []
    try:
        typ, data = M.list()
        if typ == "OK" and data:
            pat = re.compile(
                rb'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+'
                rb'(?:"(?P<q>[^"]*)"|(?P<u>[^\s]+))\s*$')
            for raw in data:
                if not isinstance(raw, (bytes, bytearray)):
                    raw = str(raw).encode("utf-8", "replace")
                m = pat.search(raw)
                if not m:
                    continue
                name = (m.group("q") or m.group("u") or b"").decode(
                    "utf-8", "replace")
                if name:
                    names.append(name)
    except Exception as exc:
        logger.debug("creator_followup._list_mailboxes: %s", exc)
    return names


def _sent_folders(M) -> list[str]:
    """Dossiers « Envoyés » à essayer : ceux marqués \\Sent (parse LIST),
    ceux dont le nom finit par sent/envoyés, puis les noms usuels."""
    found: list[str] = []
    all_names: list[str] = []
    try:
        typ, data = M.list()
        if typ == "OK" and data:
            pat = re.compile(
                rb'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+'
                rb'(?:"(?P<q>[^"]*)"|(?P<u>[^\s]+))\s*$')
            for raw in data:
                if not isinstance(raw, (bytes, bytearray)):
                    raw = str(raw).encode("utf-8", "replace")
                m = pat.search(raw)
                if not m:
                    continue
                name = (m.group("q") or m.group("u") or b"").decode(
                    "utf-8", "replace")
                if name:
                    all_names.append(name)
                if b"\\Sent" in (m.group("flags") or b""):
                    found.append(name)
    except Exception:
        pass
    ordered = (found
               + [x for x in all_names
                  if x.lower().endswith(("sent", "envoyés", "envoyes"))]
               + list(SENT_FOLDER_CANDIDATES))
    out: list[str] = []
    for n in ordered:
        if n and n not in out:
            out.append(n)
    return out


def _imap_message_date(M, uid: bytes) -> Optional[datetime]:
    """Récupère la date d'un message (header Date) par UID. None si KO."""
    try:
        typ, data = M.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (DATE)])")
        if typ != "OK" or not data:
            return None
        raw = ""
        for part in data:
            if isinstance(part, tuple) and part[1]:
                chunk = part[1]
                raw += (chunk.decode("utf-8", "ignore")
                        if isinstance(chunk, bytes) else str(chunk))
        m = re.search(r"Date:\s*(.+)", raw, re.IGNORECASE)
        if not m:
            return None
        dt = email.utils.parsedate_to_datetime(m.group(1).strip())
        return _as_aware(dt) if dt else None
    except Exception as exc:
        logger.debug("creator_followup._imap_message_date: %s", exc)
        return None


def _find_sent_to(M, address: str) -> Optional[datetime]:
    """Cherche dans les dossiers ENVOYÉS un message envoyé À `address`.
    Renvoie la date du PLUS RÉCENT trouvé, ou None."""
    addr = (address or "").strip()
    if not addr:
        return None
    for folder in _sent_folders(M):
        try:
            typ, _ = M.select('"%s"' % folder, readonly=True)
            if typ != "OK":
                continue
        except Exception:
            continue
        try:
            typ, data = M.uid("search", None, "TO", '"%s"' % addr)
            if typ != "OK" or not data or not data[0]:
                continue
            uids = data[0].split()
            if not uids:
                continue
            # Le dernier UID = le plus récent dans ce dossier.
            dt = _imap_message_date(M, uids[-1])
            if dt is not None:
                return dt
        except Exception as exc:
            logger.debug("creator_followup._find_sent_to %s: %s", folder, exc)
            continue
    return None


def _find_reply_from(M, address: str, after: datetime) -> Optional[datetime]:
    """Cherche dans INBOX un message DE `address` daté APRÈS `after`.
    Renvoie la date de la réponse, ou None."""
    addr = (address or "").strip()
    if not addr:
        return None
    try:
        typ, _ = M.select("INBOX", readonly=True)
        if typ != "OK":
            return None
    except Exception:
        return None
    try:
        # SINCE borne au jour (IMAP ne filtre pas l'heure) ; on raffine
        # ensuite sur la vraie date du message.
        since = _as_aware(after).strftime("%d-%b-%Y")
        typ, data = M.uid("search", None, "FROM", '"%s"' % addr,
                          "SINCE", since)
        if typ != "OK" or not data or not data[0]:
            return None
        uids = data[0].split()
        for uid in reversed(uids):   # du plus récent au plus ancien
            dt = _imap_message_date(M, uid)
            if dt is not None and dt > _as_aware(after):
                return dt
    except Exception as exc:
        logger.debug("creator_followup._find_reply_from: %s", exc)
    return None


def _append_draft(M, acc: dict, to_addr: str, subject: str, body: str,
                  candidates_cache: dict) -> bool:
    """Dépose un brouillon dans « Brouillons » via APPEND IMAP — même logique
    que creators_make_draft (mailbox quoté, flag (\\Draft), time.time() passé
    à append qui gère Time2Internaldate). Le 1er dossier candidat qui accepte
    est mémorisé dans candidates_cache['working'] pour les fiches suivantes.

    Renvoie True si déposé."""
    from email.message import EmailMessage
    from email.utils import formatdate, make_msgid

    from_email = acc.get("from_email") or acc.get("user") or ""
    from_name = acc.get("from_name") or from_email
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    try:
        domain = from_email.split("@", 1)[1] if "@" in from_email else None
    except Exception:
        domain = None
    msg["Message-ID"] = make_msgid(domain=domain) if domain else make_msgid()
    if from_email:
        msg["Reply-To"] = from_email
    # Désinscription en 1 clic (en-tête signé + pied cliquable), comme la
    # prospection et les 1ers contacts créateurs. prospect_id vide (pas de
    # fiche prospect pour les créateurs).
    from . import unsubscribe as _unsub
    for _k, _v in _unsub.headers_for(from_email, to_addr).items():
        msg[_k] = _v
    body, _ = _unsub.inject_footer(body, "", to_addr, "")
    msg.set_content(body)
    raw = msg.as_bytes()

    working = candidates_cache.get("working")
    if working:
        try:
            M.append('"%s"' % working, "(\\Draft)", time.time(), raw)
            return True
        except Exception as exc:
            logger.debug("append cached folder %s KO: %s", working, exc)
            candidates_cache["working"] = None  # on retentera la découverte

    cands = candidates_cache.get("candidates")
    if cands is None:
        cands = _drafts_candidates(M)
        candidates_cache["candidates"] = cands
    for f in cands:
        try:
            M.append('"%s"' % f, "(\\Draft)", time.time(), raw)
            candidates_cache["working"] = f
            return True
        except Exception as exc:
            logger.debug("append folder %s KO: %s", f, exc)
            continue
    return False


def _drafts_candidates(M) -> list[str]:
    """Liste ordonnée de dossiers « Brouillons » à essayer (copie de la
    logique _imap_drafts_candidates de api.py : \\Drafts d'abord, puis noms
    finissant par drafts/brouillons, puis noms usuels IONOS/Dovecot)."""
    found: list[str] = []
    names: list[str] = []
    try:
        typ, data = M.list()
        if typ == "OK" and data:
            pat = re.compile(
                rb'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+'
                rb'(?:"(?P<q>[^"]*)"|(?P<u>[^\s]+))\s*$')
            for raw in data:
                if not isinstance(raw, (bytes, bytearray)):
                    raw = str(raw).encode("utf-8", "replace")
                m = pat.search(raw)
                if not m:
                    continue
                name = (m.group("q") or m.group("u") or b"").decode(
                    "utf-8", "replace")
                names.append(name)
                if b"\\Drafts" in (m.group("flags") or b""):
                    found.append(name)
    except Exception:
        pass
    ordered = (found
               + [x for x in names
                  if x.lower().endswith(("drafts", "brouillons"))]
               + ["INBOX.Drafts", "Drafts", "INBOX.Brouillons", "Brouillons"])
    out: list[str] = []
    for n in ordered:
        if n and n not in out:
            out.append(n)
    return out


# ===========================================================================
# Cycle principal
# ===========================================================================
def _do_one_cycle(app_state) -> dict:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    counters = {
        "scanned": 0,
        "contacted_detected": 0,   # A1 : 1er contact détecté dans Envoyés
        "replies_detected": 0,     # A2 : réponse détectée → pas de relance
        "relances_drafted": 0,     # A3 : brouillon de relance déposé
        "reminders_pushed": 0,     # B  : rappel DM Instagram/TikTok
        "skipped": 0,
        "errors": 0,
    }

    client = _get_client()
    if client is None:
        counters["error"] = "supabase_unavailable"
        _set_run(counters)
        return counters

    # Anti-double-traitement serveur/desktop (même garde que les autres
    # workers) : si ce process n'est pas le serveur et que le serveur bat
    # encore, on lui laisse le travail.
    try:
        from .server_presence import should_defer_to_server
        if should_defer_to_server(client):
            counters["skipped_reason"] = "server_active"
            _set_run(counters)
            return counters
    except Exception:
        pass

    try:
        from . import creators_book as book
    except Exception as exc:
        counters["error"] = f"creators_book_import: {exc}"
        _set_run(counters)
        return counters

    try:
        rows = (book.list_all(limit=300).get("rows")) or []
    except Exception as exc:
        counters["error"] = f"list_all: {exc}"
        _set_run(counters)
        return counters

    state = _load_state(client)
    relanced_ids = set(state.get("relanced_ids") or [])

    # Connexion IMAP partagée pour tout le cycle (ouverte une seule fois).
    # Sans config IMAP → on ne traite QUE les rappels Instagram/TikTok.
    acc = _imap_account(client, app_state)
    M = None
    if acc is not None:
        try:
            M = _imap_connect(acc)
        except Exception as exc:
            logger.warning("creator_followup: connexion IMAP KO: %s", exc)
            M = None
            counters["imap_error"] = str(exc)[:200]

    now = _now()
    candidates_cache: dict = {}
    try:
        for row in rows:
            counters["scanned"] += 1
            try:
                kind = route_creator(row.get("platform") or "")
                if kind == "email":
                    if M is None:
                        counters["skipped"] += 1
                        continue
                    _process_email_creator(
                        client, book, M, acc, row, now,
                        relanced_ids, candidates_cache, counters)
                elif kind == "social":
                    _process_social_creator(book, row, now, counters)
                else:
                    counters["skipped"] += 1
            except Exception as exc:
                logger.warning("creator_followup fiche %s: %s",
                               row.get("id"), exc)
                counters["errors"] += 1
    finally:
        if M is not None:
            try:
                M.logout()
            except Exception:
                pass

    # Persiste l'état (ids relancés + résumé + horodatage).
    state["relanced_ids"] = sorted(relanced_ids)
    state["last_check_at"] = _iso(now)
    state["summary"] = {k: counters.get(k, 0) for k in (
        "scanned", "contacted_detected", "replies_detected",
        "relances_drafted", "reminders_pushed")}
    _save_state(client, state)

    _set_run(counters)
    return counters


def _process_email_creator(client, book, M, acc, row, now,
                           relanced_ids, candidates_cache, counters) -> None:
    """Étapes A1 / A2 / A3 pour une fiche dont la plateforme est « Email »."""
    cid = row.get("id")
    handle = (row.get("handle") or "").strip()
    if "@" not in handle:
        counters["skipped"] += 1
        return

    # Créateur désinscrit (a cliqué « se désabonner ») → plus jamais relancé.
    if book.is_unsubscribed(row):
        counters["skipped"] += 1
        return

    contacted_at = (row.get("contacted_at") or "")
    if isinstance(contacted_at, str):
        contacted_at = contacted_at.strip()

    # --- A1 : pas encore de date de 1er contact → la retrouver dans Envoyés.
    if not contacted_at:
        sent_dt = _find_sent_to(M, handle)
        if sent_dt is None:
            counters["skipped"] += 1
            return
        nxt = sent_dt + timedelta(days=FOLLOW_UP_DAYS)
        try:
            book.save({
                "id": cid,
                "contacted_at": _iso(sent_dt),
                "next_follow_up_at": _iso(nxt),
            })
            counters["contacted_detected"] += 1
        except Exception as exc:
            logger.warning("creator_followup A1 save %s: %s", cid, exc)
            counters["errors"] += 1
        return

    contacted_dt = _parse_dt(contacted_at)
    if contacted_dt is None:
        counters["skipped"] += 1
        return

    # --- A2 : a-t-elle répondu depuis le 1er contact ?
    reply_dt = _find_reply_from(M, handle, contacted_dt)
    if reply_dt is not None:
        note = (row.get("notes") or "")
        addition = f" | a répondu le {reply_dt.date().isoformat()}"
        if "a répondu le" not in note:   # ne double pas la note
            note = (note + addition).strip(" |").strip()
        try:
            book.save({
                "id": cid,
                "next_follow_up_at": None,
                "notes": note,
            })
            counters["replies_detected"] += 1
        except Exception as exc:
            logger.warning("creator_followup A2 save %s: %s", cid, exc)
            counters["errors"] += 1
        return

    # --- A3 : 7 j passés, pas de réponse, pas déjà relancée → brouillon.
    if not should_relance(row, now, relanced_ids):
        counters["skipped"] += 1
        return

    greet = creator_greet(row.get("name") or "")
    demo_url = (row.get("demo_url") or "").strip()
    custom = _custom_relance_text(client, cid)
    body = custom if custom else render_followup_body(greet, demo_url)
    subject = followup_subject()

    placed = _append_draft(M, acc, handle, subject, body, candidates_cache)
    if not placed:
        counters["errors"] += 1
        return

    # Une seule relance auto en v1 : on mémorise l'id et on vide l'échéance.
    if cid:
        relanced_ids.add(cid)
    try:
        book.save({"id": cid, "next_follow_up_at": None})
    except Exception as exc:
        logger.debug("creator_followup A3 clear next %s: %s", cid, exc)
    counters["relances_drafted"] += 1


def _process_social_creator(book, row, now, counters) -> None:
    """Étape B pour Instagram / TikTok : push de rappel si échéance posée à la
    main et échue, puis on vide l'échéance pour ne pas répéter."""
    cid = row.get("id")
    if not (row.get("contacted_at") or ""):
        counters["skipped"] += 1
        return
    due = _parse_dt(row.get("next_follow_up_at"))
    if due is None or _as_aware(now) < due:
        counters["skipped"] += 1
        return

    name = (row.get("name") or "ce créateur").strip()
    platform = (row.get("platform") or "").strip()
    try:
        from ..web.push import send_push
        send_push(
            f"⏰ Relance créateur — {name}",
            f"{platform} : 7 jours sans nouvelles. Pense à relancer en DM.",
            user_id="jordan",
            tag_group="creators",
            url="/?view=creators",
        )
        counters["reminders_pushed"] += 1
    except Exception as exc:
        logger.debug("creator_followup push %s: %s", cid, exc)
        counters["errors"] += 1

    # On vide l'échéance pour ne pas re-alerter au prochain cycle.
    try:
        book.save({"id": cid, "next_follow_up_at": None})
    except Exception as exc:
        logger.debug("creator_followup B clear next %s: %s", cid, exc)


def _set_run(counters: dict) -> None:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
    _LAST_RUN_RESULT = counters
