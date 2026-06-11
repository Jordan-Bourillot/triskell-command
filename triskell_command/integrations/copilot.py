"""Le Copilote — la conversation ÉCRITE permanente de Triskell Command Web.

Étape 1 de la vision « copilote omniprésent » (10/06/2026) :
un volet de discussion accessible depuis tous les écrans, qui

  - répond au fil de l'eau (streaming, mot à mot, pas d'attente bloc) ;
  - tient le fil : la conversation est PERSISTÉE côté serveur
    (Supabase shared_settings, un fil par utilisateur jordan/thomas,
    secours fichier local si la base est injoignable) ;
  - a exactement les mêmes pouvoirs que l'assistant vocal :
    il réutilise le protocole [ACTION:{...}] + [CHAT_THOMAS] et la liste
    blanche stricte de claude_advisor.execute_assistant_action ;
  - sait sur quel écran se trouve l'utilisateur (le front passe la vue
    courante à chaque message).

Ce module ne lève JAMAIS vers l'appelant : toute erreur sort sous forme
d'évènement {"type": "error", "error": "<français>"} ou d'un dict {ok: False}.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

# Tout le savoir-faire existant de l'assistant (contexte, actions, clés IA)
# vient de claude_advisor — UNE seule source de vérité pour les pouvoirs.
from . import claude_advisor

# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------
THREAD_SETTING_PREFIX = "copilot_thread_"   # + user_id (jordan / thomas)
MEMORY_SETTING_PREFIX = "copilot_memory_"   # le carnet (mémoire longue durée)
STATE_SETTING_PREFIX = "copilot_state_"     # last_seen / last_briefing
MAX_STORED_MESSAGES = 80      # messages conservés dans le fil persistant
MAX_PROMPT_TURNS = 16         # messages (user+assistant) injectés dans le prompt
MAX_MESSAGE_CHARS = 4000      # tronque les messages monstres
MAX_TOKENS = 2048             # réponses écrites courtes par design
CONTEXT_CACHE_SECONDS = 45    # le snapshot d'app coûte cher → petit cache

MAX_NOTES = 60                # notes du carnet
MAX_NOTE_CHARS = 300
SUMMARY_TRIGGER = MAX_STORED_MESSAGES        # on résume quand le fil déborde
SUMMARY_KEEP_RECENT = 50      # messages gardés tels quels après résumé
MAX_SUMMARY_CHARS = 2200
SUMMARY_MODEL = "claude-haiku-4-5"           # petit cerveau pour condenser
BRIEFING_GAP_HOURS = 8        # pas de nouveau briefing avant ce délai

_LOCAL_FALLBACK_FILE = Path.home() / ".triskell-command" / "copilot_threads.json"
_LOCAL_MEMORY_FILE = Path.home() / ".triskell-command" / "copilot_memory.json"
_LOCAL_STATE_FILE = Path.home() / ".triskell-command" / "copilot_state.json"
_LOCAL_PREFS_FILE = Path.home() / ".triskell-command" / "copilot_prefs.json"

PREFS_SETTING_PREFIX = "copilot_prefs_"
INITIATIVE_LEVELS = ("off", "discret", "normal", "bavard")
DEFAULT_INITIATIVE = "normal"
# kinds connus (sinon: message normal). proposal = carte Confirmer/Annuler,
# habit = carte 💡 « une habitude ? » (étape 5).
MESSAGE_KINDS = ("event", "briefing", "proposal", "habit")

_CTX_CACHE: dict[str, Any] = {"at": 0.0, "text": ""}
_CTX_LOCK = threading.Lock()


class CopilotError(Exception):
    """Erreur d'appel IA côté copilote (réseau, HTTP, format)."""


# ---------------------------------------------------------------------------
# Identité : qui parle au copilote ?
# ---------------------------------------------------------------------------
def current_user_id() -> str:
    """Identité locale (jordan/thomas) posée par le middleware HTTP.
    En mode desktop (pywebview, pas de cookie) : jordan."""
    try:
        from ..web import auth as tcauth
        return tcauth.get_current_local_user() or "jordan"
    except Exception:
        return "jordan"


def _display_name(user_id: str) -> str:
    try:
        from ..web import auth as tcauth
        return tcauth.get_display_name(user_id) or "Jordan"
    except Exception:
        return "Jordan"


# ---------------------------------------------------------------------------
# Persistance du fil (Supabase shared_settings, secours fichier local)
# ---------------------------------------------------------------------------
def _setting_key(user_id: str) -> str:
    safe = "".join(c for c in (user_id or "jordan") if c.isalnum() or c in "-_")
    return THREAD_SETTING_PREFIX + (safe or "jordan")


def _clean_message(msg: Any) -> Optional[dict]:
    """Valide/normalise un message {role, content[, at, kind, nav]}.
    None si invalide. kind/nav (messages d'évènement, briefing) ne sont
    gardés que s'ils sont sains."""
    if not isinstance(msg, dict):
        return None
    role = str(msg.get("role") or "").strip().lower()
    if role not in ("user", "assistant"):
        return None
    content = str(msg.get("content") or "").strip()
    if not content:
        return None
    out = {
        "role": role,
        "content": content[:MAX_MESSAGE_CHARS],
        "at": str(msg.get("at") or datetime.now().isoformat(timespec="seconds")),
    }
    kind = str(msg.get("kind") or "").strip().lower()
    if kind in MESSAGE_KINDS:
        out["kind"] = kind
    nav = str(msg.get("nav") or "").strip()
    if nav and nav.isidentifier() and len(nav) <= 40:
        out["nav"] = nav
    # pid : l'identifiant de la proposition liée (carte Confirmer/Annuler)
    pid = str(msg.get("pid") or "").strip().lower()
    if pid and len(pid) <= 16 and all(c in "0123456789abcdef" for c in pid):
        out["pid"] = pid
    # hid : l'identifiant du motif d'habitude lié (carte 💡)
    hid = str(msg.get("hid") or "").strip().lower()
    if hid and len(hid) <= 16 and all(c in "0123456789abcdef" for c in hid):
        out["hid"] = hid
    return out


# Un seul écrivain à la fois sur les documents persistés (le résumé en
# arrière-plan et le tour suivant peuvent se chevaucher).
_PERSIST_LOCK = threading.Lock()


def _local_read_doc(path: Path, user_id: str) -> Optional[dict]:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                doc = data.get(user_id)
                return doc if isinstance(doc, dict) else None
    except Exception as exc:
        logger.debug("copilot local read %s: %s", path.name, exc)
    return None


def _local_write_doc(path: Path, user_id: str, payload: dict) -> None:
    try:
        data = {}
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
            except Exception:
                data = {}
        data[user_id] = payload
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False),
                        encoding="utf-8")
    except Exception as exc:
        logger.debug("copilot local write %s: %s", path.name, exc)


def _doc_read(setting_key: str, local_file: Path, user_id: str) -> Optional[dict]:
    """Lit un document {clé: dict} : Supabase d'abord, fichier local sinon."""
    client = claude_advisor._client()
    if client is not None:
        try:
            raw = client.get_shared_setting(setting_key, None)
            if isinstance(raw, dict):
                return raw
        except Exception as exc:
            logger.debug("copilot read %s: %s", setting_key, exc)
    return _local_read_doc(local_file, user_id)


def _doc_write(setting_key: str, local_file: Path, user_id: str,
               payload: dict) -> None:
    payload = dict(payload)
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    client = claude_advisor._client()
    if client is not None:
        try:
            client.set_shared_setting(setting_key, payload)
            return
        except Exception as exc:
            logger.debug("copilot write %s: %s", setting_key, exc)
    _local_write_doc(local_file, user_id, payload)


def _load_thread_doc(user_id: str) -> dict:
    """Le document complet du fil : {messages: [...], summary: str}."""
    user_id = user_id or "jordan"
    raw = _doc_read(_setting_key(user_id), _LOCAL_FALLBACK_FILE, user_id) or {}
    msgs = raw.get("messages") if isinstance(raw, dict) else None
    out: list[dict] = []
    for m in (msgs or []):
        cm = _clean_message(m)
        if cm:
            out.append(cm)
    summary = raw.get("summary") if isinstance(raw, dict) else ""
    return {
        "messages": out[-MAX_STORED_MESSAGES:],
        "summary": str(summary or "")[:MAX_SUMMARY_CHARS],
    }


def load_thread(user_id: str) -> list[dict]:
    """Le fil de discussion persisté (du plus ancien au plus récent).
    Jamais d'exception : au pire, liste vide."""
    return _load_thread_doc(user_id)["messages"]


def load_summary(user_id: str) -> str:
    """Le résumé des échanges plus anciens (peut être vide)."""
    return _load_thread_doc(user_id)["summary"]


def save_thread(user_id: str, messages: list[dict],
                summary: Optional[str] = None) -> None:
    """Écrit le fil (tronqué). summary=None → conserve le résumé existant."""
    user_id = user_id or "jordan"
    if summary is None:
        summary = load_summary(user_id)
    _doc_write(_setting_key(user_id), _LOCAL_FALLBACK_FILE, user_id, {
        "messages": messages[-MAX_STORED_MESSAGES:],
        "summary": str(summary or "")[:MAX_SUMMARY_CHARS],
    })


def append_messages(user_id: str, new_messages: list[Any]) -> int:
    """Ajoute des messages au fil (tour de chat, tours vocaux reversés…).
    Si le fil déborde, les plus anciens partent se faire condenser en
    arrière-plan dans le résumé (au lieu d'être jetés). Renvoie le nombre
    de messages réellement ajoutés."""
    cleaned = []
    for m in (new_messages or [])[:20]:
        cm = _clean_message(m)
        if cm:
            cleaned.append(cm)
    if not cleaned:
        return 0
    user_id = user_id or "jordan"
    with _PERSIST_LOCK:
        doc = _load_thread_doc(user_id)
        thread = doc["messages"] + cleaned
        overflow: list[dict] = []
        if len(thread) > SUMMARY_TRIGGER:
            overflow = thread[:-SUMMARY_KEEP_RECENT]
            thread = thread[-SUMMARY_KEEP_RECENT:]
        save_thread(user_id, thread, summary=doc["summary"])
    if overflow:
        _schedule_condense(user_id, doc["summary"], overflow)
    return len(cleaned)


def append_turn(user_id: str, question: str, answer: str) -> None:
    append_messages(user_id, [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ])


def clear_thread(user_id: str) -> None:
    """Nouvelle discussion : vide le fil ET le résumé. (Le carnet, lui,
    survit — c'est sa raison d'être.)"""
    with _PERSIST_LOCK:
        save_thread(user_id, [], summary="")


# ---------------------------------------------------------------------------
# Condensation : les vieux tours deviennent un résumé (rien ne se perd)
# ---------------------------------------------------------------------------
def _summarize_with_ai(app_state, prev_summary: str,
                       old_messages: list[dict]) -> str:
    """Condense (résumé précédent + vieux messages) en un nouveau résumé.
    Petit modèle, appel bloc. Lève en cas d'échec (l'appelant décide)."""
    from triskell_core.ai.providers import call_anthropic

    ai = claude_advisor._resolve_ai(app_state)
    if not ai.get("api_key") or ai.get("provider") != "anthropic":
        raise CopilotError("pas de clé Anthropic pour condenser")
    convo = "\n".join(
        f"{'U' if m['role'] == 'user' else 'C'} : {m['content'][:500]}"
        for m in old_messages
    )
    prompt = (
        "Tu condenses l'historique d'une conversation entre un utilisateur "
        "(U) et son copilote (C) dans une app de pilotage d'agence web.\n"
        "RÉSUMÉ EXISTANT DES ÉCHANGES ENCORE PLUS ANCIENS (à conserver et "
        "fusionner) :\n" + (prev_summary or "(aucun)") + "\n\n"
        "NOUVEAUX ÉCHANGES À INTÉGRER :\n" + convo + "\n\n"
        "Écris le NOUVEAU résumé fusionné : uniquement les faits, décisions, "
        "préférences et sujets en cours UTILES pour la suite de la "
        "conversation. Français, puces courtes, 15 lignes max, pas de "
        "politesse. Réponds par le résumé seul."
    )
    text = call_anthropic(prompt, SUMMARY_MODEL, ai["api_key"])
    return (text or "").strip()[:MAX_SUMMARY_CHARS]


def _condense_now(app_state, user_id: str, prev_summary: str,
                  overflow: list[dict]) -> bool:
    """Fait la condensation et range le nouveau résumé. True si OK."""
    try:
        new_summary = _summarize_with_ai(app_state, prev_summary, overflow)
    except Exception as exc:
        logger.debug("copilot condense: %s", exc)
        return False
    if not new_summary:
        return False
    with _PERSIST_LOCK:
        doc = _load_thread_doc(user_id)
        save_thread(user_id, doc["messages"], summary=new_summary)
    return True


_CONDENSE_APP_STATE = None  # posé par stream_reply (le worker en a besoin)


def _schedule_condense(user_id: str, prev_summary: str,
                       overflow: list[dict]) -> None:
    """Lance la condensation dans un fil d'arrière-plan : le tour de chat
    qui a fait déborder le fil ne doit pas attendre 3 s de plus."""
    app_state = _CONDENSE_APP_STATE
    if app_state is None:
        return  # pas d'app_state connu (tests…) : on tronque comme avant
    t = threading.Thread(
        target=_condense_now, args=(app_state, user_id, prev_summary,
                                    overflow),
        name="copilot-condense", daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Le carnet — mémoire longue durée (préférences, décisions, faits)
# ---------------------------------------------------------------------------
def _memory_key(user_id: str) -> str:
    safe = "".join(c for c in (user_id or "jordan") if c.isalnum() or c in "-_")
    return MEMORY_SETTING_PREFIX + (safe or "jordan")


def load_memory(user_id: str) -> list[dict]:
    """Les notes du carnet : [{id, text, at}], de la plus ancienne à la
    plus récente. Jamais d'exception."""
    user_id = user_id or "jordan"
    raw = _doc_read(_memory_key(user_id), _LOCAL_MEMORY_FILE, user_id) or {}
    notes = raw.get("notes") if isinstance(raw, dict) else None
    out: list[dict] = []
    for n in (notes or []):
        if not isinstance(n, dict):
            continue
        text = str(n.get("text") or "").strip()
        nid = str(n.get("id") or "").strip()
        if text and nid:
            out.append({"id": nid, "text": text[:MAX_NOTE_CHARS],
                        "at": str(n.get("at") or "")})
    return out[-MAX_NOTES:]


def save_memory(user_id: str, notes: list[dict]) -> None:
    _doc_write(_memory_key(user_id), _LOCAL_MEMORY_FILE, user_id,
               {"notes": notes[-MAX_NOTES:]})


def add_note(user_id: str, text: str) -> Optional[dict]:
    """Ajoute une note au carnet (dédoublonnée). Renvoie la note ou None."""
    import uuid
    text = " ".join(str(text or "").split()).strip()
    if not text:
        return None
    text = text[:MAX_NOTE_CHARS]
    notes = load_memory(user_id)
    low = text.lower()
    for n in notes:
        if n["text"].lower() == low:
            return n  # déjà connue — pas de doublon
    note = {"id": uuid.uuid4().hex[:8], "text": text,
            "at": datetime.now().isoformat(timespec="seconds")}
    notes.append(note)
    save_memory(user_id, notes)
    return note


def delete_note(user_id: str, note_id: str) -> bool:
    notes = load_memory(user_id)
    kept = [n for n in notes if n["id"] != str(note_id or "")]
    if len(kept) == len(notes):
        return False
    save_memory(user_id, kept)
    return True


def memory_for_ui(user_id: str) -> dict:
    return {"ok": True, "notes": load_memory(user_id or "jordan")}


# ---------------------------------------------------------------------------
# État léger : dernier passage, dernier briefing
# ---------------------------------------------------------------------------
def _state_key(user_id: str) -> str:
    safe = "".join(c for c in (user_id or "jordan") if c.isalnum() or c in "-_")
    return STATE_SETTING_PREFIX + (safe or "jordan")


def load_state(user_id: str) -> dict:
    raw = _doc_read(_state_key(user_id), _LOCAL_STATE_FILE,
                    user_id or "jordan") or {}
    try:
        unseen = max(0, int(raw.get("unseen") or 0))
    except Exception:
        unseen = 0
    return {
        "last_seen_at": str(raw.get("last_seen_at") or ""),
        "last_briefing_at": str(raw.get("last_briefing_at") or ""),
        "unseen": unseen,
    }


def save_state(user_id: str, **fields: Any) -> None:
    st = load_state(user_id)
    st.update({k: v for k, v in fields.items() if k in st})
    _doc_write(_state_key(user_id), _LOCAL_STATE_FILE,
               user_id or "jordan", st)


def get_unseen(user_id: str) -> int:
    """Messages du copilote déposés depuis la dernière ouverture du volet
    (pour la pastille 💬 de la barre-guide)."""
    return load_state(user_id)["unseen"]


# ---------------------------------------------------------------------------
# Préférences : niveau d'initiative + curseur de confiance par famille
# ---------------------------------------------------------------------------
def _prefs_key(user_id: str) -> str:
    safe = "".join(c for c in (user_id or "jordan") if c.isalnum() or c in "-_")
    return PREFS_SETTING_PREFIX + (safe or "jordan")


def get_prefs(user_id: str) -> dict:
    from . import copilot_actions
    raw = _doc_read(_prefs_key(user_id), _LOCAL_PREFS_FILE,
                    user_id or "jordan") or {}
    lvl = str(raw.get("initiative") or "").strip().lower()
    if lvl not in INITIATIVE_LEVELS:
        lvl = DEFAULT_INITIATIVE
    return {"initiative": lvl,
            "trust": copilot_actions.clean_trust(raw.get("trust"))}


def set_prefs(user_id: str, initiative: Optional[str] = None,
              trust: Optional[dict] = None) -> dict:
    """Met à jour le niveau d'initiative et/ou le curseur de confiance
    (trust peut être partiel : {"mails": "never"}). Les deux réglages
    cohabitent dans le même document — on fusionne, jamais d'écrasement."""
    from . import copilot_actions
    current = get_prefs(user_id)

    if initiative is not None:
        lvl = str(initiative or "").strip().lower()
        if lvl not in INITIATIVE_LEVELS:
            return {"ok": False,
                    "error": "Niveau inconnu (off, discret, normal ou "
                             "bavard)."}
        current["initiative"] = lvl

    if trust is not None:
        if not isinstance(trust, dict):
            return {"ok": False, "error": "Réglage de confiance invalide."}
        merged = dict(current["trust"])
        for fam, value in trust.items():
            fam = str(fam or "").strip().lower()
            value = str(value or "").strip().lower()
            if fam not in copilot_actions.FAMILIES:
                return {"ok": False,
                        "error": f"Famille inconnue ({fam})."}
            if value not in copilot_actions.TRUST_LEVELS:
                return {"ok": False,
                        "error": "Niveau inconnu (solo, ask ou never)."}
            if fam == "mails" and value == "solo":
                # Plafond non négociable : les envois de mails ne passent
                # JAMAIS en « il fait seul ».
                return {"ok": False,
                        "error": "Les envois de mails restent sous ta "
                                 "validation — « il fait seul » n'existe "
                                 "pas pour cette famille."}
            merged[fam] = value
        current["trust"] = copilot_actions.clean_trust(merged)

    _doc_write(_prefs_key(user_id), _LOCAL_PREFS_FILE, user_id or "jordan",
               current)
    return {"ok": True, **current}


# ---------------------------------------------------------------------------
# Dépôt d'évènements : le copilote vient vers l'utilisateur
# ---------------------------------------------------------------------------
def deposit_event_message(user_id: str, text: str, nav: str = "") -> bool:
    """Dépose un message d'évènement dans le fil (rédigé par des règles,
    pas par l'IA) et allume la pastille. Jamais d'exception."""
    try:
        text = str(text or "").strip()
        if not text:
            return False
        added = append_messages(user_id, [{
            "role": "assistant", "content": text[:600],
            "kind": "event", "nav": nav,
        }])
        if added:
            save_state(user_id, unseen=get_unseen(user_id) + 1)
        return bool(added)
    except Exception as exc:
        logger.debug("copilot deposit: %s", exc)
        return False


def deposit_habit_message(user_id: str, motif: dict) -> bool:
    """Dépose la carte 💡 « une habitude ? » dans le fil (étape 5).
    Pas de pastille : elle apparaît à l'ouverture du volet, l'utilisateur
    est déjà là. Jamais d'exception."""
    try:
        motif = motif or {}
        hid = str(motif.get("id") or "").strip()
        label = str(motif.get("label") or "").strip()
        if not hid or not label:
            return False
        added = append_messages(user_id, [{
            "role": "assistant",
            "content": ("💡 Une habitude ? " + label)[:600],
            "kind": "habit", "hid": hid,
        }])
        return bool(added)
    except Exception as exc:
        logger.debug("copilot deposit habit: %s", exc)
        return False


def deposit_proposal_message(user_id: str, prop: dict,
                             bump: bool = True) -> bool:
    """Dépose la carte « à confirmer » d'une proposition dans le fil.
    bump=True allume la pastille (utile quand Jordan n'est pas dans le
    volet : tour vocal, veille). Jamais d'exception."""
    try:
        prop = prop or {}
        pid = str(prop.get("id") or "").strip()
        title = str(prop.get("title") or "une action").strip()
        if not pid:
            return False
        added = append_messages(user_id, [{
            "role": "assistant",
            "content": ("✋ À confirmer : " + title)[:600],
            "kind": "proposal", "pid": pid,
        }])
        if added and bump:
            save_state(user_id, unseen=get_unseen(user_id) + 1)
        return bool(added)
    except Exception as exc:
        logger.debug("copilot deposit proposal: %s", exc)
        return False


def _hours_since(iso: str) -> float:
    if not iso:
        return 1e9
    try:
        then = datetime.fromisoformat(iso)
        return max(0.0, (datetime.now() - then).total_seconds() / 3600.0)
    except Exception:
        return 1e9


def briefing_due(user_id: str) -> bool:
    """Un point du jour est-il dû ? (jamais fait, ou il date de plus de
    BRIEFING_GAP_HOURS heures)."""
    st = load_state(user_id)
    return _hours_since(st["last_briefing_at"]) >= BRIEFING_GAP_HOURS


def thread_for_ui(user_id: str) -> dict:
    """Le fil prêt à afficher dans le volet (+ signale si un point du
    jour est dû — le front le déclenche alors en streaming).
    Embarque aussi les propositions (cartes Confirmer/Annuler), le
    curseur de confiance, les raccourcis (barre ⚡) et l'état des cartes
    💡 habitude, pour que le volet peigne l'état réel."""
    from . import copilot_actions, copilot_habits
    user_id = user_id or "jordan"
    prefs = get_prefs(user_id)

    # Étape 5 : si une habitude est mûre, sa carte 💡 rejoint le fil
    # MAINTENANT (à l'ouverture du volet — le bon moment, sans pastille).
    try:
        ripe = copilot_habits.ripe_motif(user_id)
        if ripe and deposit_habit_message(user_id, ripe):
            copilot_habits.mark_proposed(user_id, ripe["id"])
    except Exception as exc:
        logger.debug("copilot habit suggest: %s", exc)

    messages = load_thread(user_id)[-60:]

    # L'état des cartes 💡 encore visibles dans le fil (rendu des boutons)
    habits: dict[str, dict] = {}
    try:
        for m in messages:
            hid = m.get("hid")
            if hid and hid not in habits:
                habits[hid] = copilot_habits.habit_card_state(user_id, hid)
    except Exception as exc:
        logger.debug("copilot habit states: %s", exc)

    out = {
        "ok": True,
        "user": user_id,
        "display_name": _display_name(user_id),
        "messages": messages,
        "briefing_due": briefing_due(user_id),
        "initiative": prefs["initiative"],
        "trust": prefs["trust"],
        "proposals": copilot_actions.list_proposals(user_id),
        "shortcuts": copilot_habits.list_shortcuts(user_id),
        "habits": habits,
    }
    # Volet ouvert : tout est vu → la pastille s'éteint.
    save_state(user_id, last_seen_at=datetime.now().isoformat(
        timespec="seconds"), unseen=0)
    return out


# ---------------------------------------------------------------------------
# Prompt système — la voix ÉCRITE du copilote
# ---------------------------------------------------------------------------
COPILOT_SYSTEM_PROMPT = """Tu es Claude, le copilote de {PRENOM} dans Triskell Command (l'app de pilotage de Studio Triskell, agence web bretonne fondée par Jordan et Thomas).

Tu vis dans un VOLET DE DISCUSSION ÉCRIT, ouvrable depuis n'importe quel écran de l'app. {PRENOM} t'écrit, tu réponds par écrit. La conversation est conservée d'une session à l'autre : tu peux faire référence aux échanges précédents du fil.

═══════════════════════════════════════════════════════════════
TU AS ACCÈS À TOUTE L'APP TRISKELL COMMAND EN DIRECT
═══════════════════════════════════════════════════════════════
Plus bas, tu reçois un bloc JSON « ÉTAT DE TOUTE L'APP TRISKELL COMMAND EN DIRECT » : snapshot live (cockpit prospection, envois, réponses par catégorie, file de travail, workers, config, catalogue, clients, projets, Pixel Pros, Lagriffe, Obélisk, Phare/SEO, GEO — bloc geo : audits « être cité par les IA », surveillance, auto-pilote ; ses sites (geo.sites) ne sont PAS ceux de Phare —, Convoi, Forge, factures, funnel 30 j) + les missions de prospection récentes.

⇒ Pour toute question business (« combien de réponses aujourd'hui ? », « où en est ma chasse ? », « ça donne quoi Pixel Pros ce mois-ci ? »…), tu pioches les VRAIS chiffres et les VRAIS noms dans ce JSON. Tu n'as PAS le droit de répondre « je n'ai pas accès » : tu as le JSON, sers-t'en.
⇒ Si une donnée précise n'y est pas, tu le dis honnêtement et tu indiques l'écran de l'app où elle se trouve (tu peux proposer d'y aller).

Le champ active_view du JSON (et la ligne « Écran actuellement ouvert ») te dit OÙ se trouve {PRENOM} dans l'app en ce moment. Sers-t'en pour des réponses situées (« le bouton est en haut à droite de cet écran ») et pour proposer la navigation quand la réponse vit ailleurs.

QUAND NE PAS DÉROULER LE JSON : si {PRENOM} parle d'autre chose que son business (question générale, papote, idée), réponds normalement sans ramener l'app sur le tapis. Pas de bilan spontané à chaque « salut ». EXCEPTION : un truc VRAIMENT critique visible dans le JSON (envois cassés en boucle, réponses intéressées qui moisissent, config IA absente) → tu peux le signaler en une phrase en fin de réponse.

═══════════════════════════════════════════════════════════════
TON ET FORMAT (ÉCRIT)
═══════════════════════════════════════════════════════════════
- Tu parles comme un associé : direct, chaleureux, tutoiement, zéro flatterie, zéro « Excellente question ! ».
- ESPRIT CRITIQUE OBLIGATOIRE : si {PRENOM} s'apprête à faire une erreur ou qu'il existe une meilleure approche, tu le dis franchement, avec UN argument concret, AVANT d'exécuter quoi que ce soit.
- Réponses COURTES par défaut : 1 à 5 lignes. Tu développes seulement si on te demande du détail.
- Markdown LÉGER autorisé : **gras** pour les chiffres/mots-clés, listes à puces courtes (- ) quand tu énumères 2 éléments ou plus. JAMAIS de titres #, jamais de tableaux, jamais de blocs de code.
- JAMAIS de jargon technique : pas de noms de fichiers, d'endpoints, de termes anglais techniques. Tu parles comme à quelqu'un de non-technique.
- Si tu ne comprends pas la demande, pose UNE question de clarification, courte.
- N'invente JAMAIS un chiffre ou un fait : tout vient du JSON ou du fil de la conversation.
- Quand tu viens d'AGIR (action exécutée), ne promets rien que le système ne fait pas : décris ce qui va réellement se passer.
"""

# Le carnet : comment le copilote retient (et oublie) — bloc fixe du prompt.
MEMORY_RULES_BLOCK = """═══════════════════════════════════════════════════════════════
TON CARNET — TU RETIENS CE QUI COMPTE, SANS QU'ON TE LE REDISE
═══════════════════════════════════════════════════════════════
Tu reçois plus bas ton CARNET : les notes que tu as prises au fil du temps (numérotées). Elles sont vraies jusqu'à preuve du contraire — appuie-toi dessus, ne refais pas répéter ce qui y est déjà.

NOTER : quand {PRENOM} exprime une PRÉFÉRENCE durable (« écris-moi plus court », « jamais de mails le week-end »), une DÉCISION (« on laisse tomber les avocats », « objectif du mois : 10 ventes »), ou un FAIT stable et utile (« Thomas gère le SEO », « le client X est susceptible »), termine ta réponse par UNE ligne invisible :
[MEMOIRE:{"note":"<la note, formulée courte et claire, max 200 caractères>"}]

OUBLIER : si {PRENOM} te demande d'oublier quelque chose ou te corrige (« c'est plus le cas », « oublie ça »), termine par :
[OUBLIE:{"n":<numéro de la note dans le carnet>}]

RÈGLES DU CARNET (non négociables) :
- Une seule note prise OU oubliée par tour, en toute fin de réponse, JSON valide.
- Tu notes l'utile DURABLE. Jamais l'éphémère (« il est fatigué aujourd'hui »), jamais ce que l'app sait déjà (les chiffres du JSON), JAMAIS un mot de passe, une clé ou une donnée sensible.
- Pas de note « au cas où » à chaque tour : un carnet utile est un carnet court.
- Tu n'annonces pas le tag — si tu veux le dire, dis simplement « C'est noté. ».
- Si une note du carnet contredit ce que {PRENOM} dit MAINTENANT : ce qu'il dit maintenant gagne, et tu mets le carnet à jour (note corrigée = [OUBLIE] de l'ancienne ce tour-ci, puis nouvelle [MEMOIRE] au tour suivant si besoin).
"""

# Bloc « messages à Thomas » : pertinent seulement quand c'est Jordan qui écrit.
CHAT_THOMAS_BLOCK = """═══════════════════════════════════════════════════════════════
ENVOYER UN MESSAGE À THOMAS DANS LE CHAT
═══════════════════════════════════════════════════════════════
Tu peux poster un message à Thomas dans le chat interne de Triskell Command, UNIQUEMENT quand Jordan te le demande explicitement (« dis à Thomas… », « préviens Thomas… »). Tu n'écris pas au nom de Jordan : tu écris en tant que Claude, le messager (« Salut Thomas, Jordan m'a chargé de te dire que… »). Tutoiement, ton naturel.

Pour envoyer, place le contenu EXACT entre ces balises, seules sur leurs lignes :
[CHAT_THOMAS]
Le message ici.
[/CHAT_THOMAS]
Une seule paire de balises par tour, rien d'autre à l'intérieur. Avant les balises, donne à Jordan une confirmation écrite très courte (« C'est envoyé. »).
"""


def _context_block(app_state) -> str:
    """Le snapshot JSON de toute l'app + missions récentes, avec un petit
    cache (le calcul fait beaucoup d'allers-retours base)."""
    now = time.time()
    with _CTX_LOCK:
        if _CTX_CACHE["text"] and (now - _CTX_CACHE["at"]) < CONTEXT_CACHE_SECONDS:
            return _CTX_CACHE["text"]
    try:
        context = claude_advisor.gather_voice_context(app_state)
        block = (
            "ÉTAT DE TOUTE L'APP TRISKELL COMMAND EN DIRECT "
            "(JSON, snapshot pris à l'instant) :\n"
            + json.dumps(context, ensure_ascii=False, indent=2, default=str)
        )
    except Exception as exc:
        logger.debug("copilot gather context: %s", exc)
        block = "ÉTAT DE L'APP EN DIRECT : (indisponible pour ce tour)"
    try:
        from . import missions as _mi
        _lst = sorted(_mi.load_missions(),
                      key=lambda m: m.get("created_at") or "",
                      reverse=True)[:6]
        if _lst:
            block += ("\n\nMISSIONS DE PROSPECTION (récentes → anciennes) :\n"
                      + json.dumps(_lst, ensure_ascii=False, default=str))
    except Exception as exc:
        logger.debug("copilot missions context: %s", exc)
    with _CTX_LOCK:
        _CTX_CACHE["at"] = now
        _CTX_CACHE["text"] = block
    return block


def _memory_block(user_id: str, name: str) -> str:
    """Le carnet, numéroté pour permettre [OUBLIE:{"n":…}]."""
    notes = load_memory(user_id)
    if not notes:
        return (f"TON CARNET SUR {name.upper()} : (vide pour l'instant — "
                "il se remplira au fil des discussions)")
    lines = [f"{i + 1}. {n['text']}" for i, n in enumerate(notes)]
    return (f"TON CARNET SUR {name.upper()} (notes numérotées, des plus "
            "anciennes aux plus récentes) :\n" + "\n".join(lines))


def build_prompt(app_state, user_id: str, thread: list[dict],
                 question: str, view: str = "") -> str:
    """Assemble le prompt complet d'un tour de copilote."""
    name = _display_name(user_id)
    system = COPILOT_SYSTEM_PROMPT.replace("{PRENOM}", name)

    blocks: list[str] = [system]
    blocks.append(MEMORY_RULES_BLOCK.replace("{PRENOM}", name))
    if (user_id or "jordan") == "jordan":
        blocks.append(CHAT_THOMAS_BLOCK)
    # Le catalogue d'actions est GÉNÉRÉ depuis le registre central :
    # toujours fidèle aux pouvoirs réels ET au curseur de confiance.
    from . import copilot_actions
    blocks.append(copilot_actions.build_actions_prompt(user_id)
                  .replace("{PRENOM}", name))
    blocks.append(_memory_block(user_id, name))
    summary = load_summary(user_id)
    if summary:
        blocks.append("RÉSUMÉ DES ÉCHANGES PLUS ANCIENS (le fil ci-dessous "
                      "ne montre que la fin) :\n" + summary)
    blocks.append(_context_block(app_state))
    if view:
        blocks.append(f"Écran actuellement ouvert devant {name} : {view}")

    convo: list[str] = []
    for turn in thread[-MAX_PROMPT_TURNS:]:
        speaker = name if turn["role"] == "user" else "Claude"
        convo.append(f"{speaker} : {turn['content']}")
    convo.append(f"{name} : {question.strip()}")
    convo.append("Claude :")
    blocks.append("FIL DE LA CONVERSATION :\n" + "\n\n".join(convo))

    return "\n\n---\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Anti-fuite : masque les tags de commande pendant le stream
# ---------------------------------------------------------------------------
_TAG_MARKERS = ("[ACTION:", "[CHAT_THOMAS]", "[MEMOIRE:", "[OUBLIE:")


class TagScrubber:
    """Filtre un flux de texte : tout ce qui suit le début d'un tag de
    commande est retenu (les tags arrivent en fin de réponse par règle).
    Le texte final propre est de toute façon recalculé hors stream."""

    def __init__(self) -> None:
        self._tail = ""
        self._muted = False

    def push(self, chunk: str) -> str:
        if self._muted:
            return ""
        buf = self._tail + (chunk or "")
        upper = buf.upper()
        hits = [upper.find(m) for m in _TAG_MARKERS]
        hits = [h for h in hits if h != -1]
        if hits:
            cut = min(hits)
            self._muted = True
            self._tail = ""
            return buf[:cut]
        # Retient le plus long suffixe qui pourrait être un début de tag
        keep = 0
        max_probe = min(len(buf), max(len(m) for m in _TAG_MARKERS) - 1)
        for k in range(max_probe, 0, -1):
            suffix = upper[-k:]
            if any(m.startswith(suffix) for m in _TAG_MARKERS):
                keep = k
                break
        if keep:
            self._tail = buf[-keep:]
            return buf[:-keep]
        self._tail = ""
        return buf


# ---------------------------------------------------------------------------
# Appel Anthropic en streaming (SSE)
# ---------------------------------------------------------------------------
def _stream_anthropic(prompt: str, model: str, api_key: str) -> Iterator[str]:
    """Yield les morceaux de texte au fil de l'eau. Lève CopilotError."""
    import requests

    payload = {
        "model": model or "claude-sonnet-4-5",
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
            stream=True,
            timeout=(10, 120),
        )
    except requests.RequestException as exc:
        raise CopilotError(f"erreur réseau ({exc})") from exc

    if r.status_code >= 400:
        try:
            body = r.json()
            detail = ((body.get("error") or {}).get("message")
                      or json.dumps(body)[:200])
        except Exception:
            detail = (r.text or "")[:200]
        r.close()
        raise CopilotError(f"HTTP {r.status_code} : {detail}")

    try:
        for raw_line in r.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", "ignore") \
                if isinstance(raw_line, bytes) else str(raw_line)
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data:
                continue
            try:
                evt = json.loads(data)
            except Exception:
                continue
            etype = evt.get("type")
            if etype == "content_block_delta":
                delta = evt.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield delta["text"]
            elif etype == "error":
                msg = ((evt.get("error") or {}).get("message")
                       or "erreur inconnue")
                raise CopilotError(msg)
            elif etype == "message_stop":
                break
    finally:
        try:
            r.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Fin de tour : extraire/exécuter les commandes, nettoyer le texte
# ---------------------------------------------------------------------------
_MEMOIRE_RE = re.compile(r"\[MEMOIRE:\s*(\{.*?\})\s*\]",
                         re.DOTALL | re.IGNORECASE)
_OUBLIE_RE = re.compile(r"\[OUBLIE:\s*(\{.*?\})\s*\]",
                        re.DOTALL | re.IGNORECASE)


def _extract_json_tag(raw: str, regex: re.Pattern) -> tuple[str, Optional[dict]]:
    """Détache le dernier tag JSON du texte. JSON cassé → ignoré proprement."""
    matches = list(regex.finditer(raw or ""))
    if not matches:
        return raw, None
    m = matches[-1]
    cleaned = (raw[:m.start()] + raw[m.end():]).strip()
    try:
        data = json.loads(m.group(1))
        return cleaned, data if isinstance(data, dict) else None
    except Exception:
        return cleaned, None


def _apply_memory_tags(user_id: str, text: str) -> tuple[str, dict]:
    """Traite [MEMOIRE:{note}] et [OUBLIE:{n}]. Renvoie (texte nettoyé,
    {memorized?: str, forgotten?: bool})."""
    out: dict[str, Any] = {}
    text, mem = _extract_json_tag(text, _MEMOIRE_RE)
    if mem is not None:
        note = add_note(user_id, str(mem.get("note") or ""))
        if note:
            out["memorized"] = note["text"]
    text, forget = _extract_json_tag(text, _OUBLIE_RE)
    if forget is not None:
        try:
            n = int(forget.get("n"))
        except Exception:
            n = 0
        notes = load_memory(user_id)
        if 1 <= n <= len(notes):
            if delete_note(user_id, notes[n - 1]["id"]):
                out["forgotten"] = True
    return text, out


def _finalize_reply(raw: str, *, user_id: str = "jordan",
                    execute=None) -> dict:
    """À partir du texte BRUT complet du modèle : poste l'éventuel message à
    Thomas, route l'éventuelle action (registre central : exécution directe
    OU proposition à confirmer, selon le curseur de confiance), range les
    notes du carnet. Renvoie {text, navigate, action_done, sent_to_thomas,
    proposed?, memorized?, forgotten?}."""
    if execute is None:
        from . import copilot_actions

        def execute(a):  # canal écrit : le curseur s'applique ici
            return copilot_actions.execute_action(
                a, user_id=user_id, channel="copilot")
    text, sent_thomas = claude_advisor._extract_chat_to_thomas(raw or "")
    text, action = claude_advisor._extract_action(text)
    text, mem_out = _apply_memory_tags(user_id, text)
    out: dict[str, Any] = {
        "text": (text or "").strip(),
        "navigate": "",
        "action_done": None,
        "sent_to_thomas": bool(sent_thomas),
    }
    out.update(mem_out)
    if action is not None:
        try:
            result = execute(action) or {}
        except Exception as exc:  # ceinture : execute ne lève normalement pas
            result = {"ok": False, "summary": f"L'action a échoué : {exc}"}
        prop = result.get("proposed")
        if prop:
            # Rien n'est exécuté : la carte Confirmer/Annuler suit la
            # réponse (déposée par l'appelant, APRÈS le tour, pour que
            # le fil garde l'ordre réponse → carte).
            out["proposed"] = prop
            if not out["text"]:
                out["text"] = "Je te l'ai préparé — confirme ci-dessous."
        else:
            summary = (result.get("summary") or "").strip()
            if summary:
                out["text"] = (out["text"] + ("\n\n" if out["text"] else "")
                               + summary).strip()
            if result.get("navigate"):
                out["navigate"] = result["navigate"]
            out["action_done"] = bool(result.get("ok"))
    if not out["text"]:
        out["text"] = "…"
    return out


# ---------------------------------------------------------------------------
# LE tour de conversation (générateur d'évènements)
# ---------------------------------------------------------------------------
def stream_reply(app_state, user_id: str, question: str,
                 view: str = "") -> Iterator[dict]:
    """Un tour complet de copilote, streamé.

    Yield des dicts :
      {"type": "delta", "text": "..."}   — morceau de réponse à afficher
      {"type": "done",  "text": "...", "navigate"?, "action_done"?,
                        "sent_to_thomas"?}
      {"type": "error", "error": "<message en français>"}
    """
    user_id = (user_id or "jordan").strip() or "jordan"
    question = (question or "").strip()
    if not question:
        yield {"type": "error", "error": "Message vide — écris-moi quelque chose !"}
        return
    question = question[:MAX_MESSAGE_CHARS]
    view = str(view or "").strip()[:60]

    # La condensation d'arrière-plan aura besoin d'un app_state
    global _CONDENSE_APP_STATE
    _CONDENSE_APP_STATE = app_state

    # L'écran courant : utile au prompt ET aux autres modes (vocal, veille)
    if view:
        try:
            app_state.set("active_view", value=view)
        except Exception:
            pass

    ai = claude_advisor._resolve_ai(app_state)
    if not ai.get("api_key"):
        yield {"type": "error",
               "error": "L'IA n'est pas configurée — ajoute ta clé dans "
                        "Réglages, et je serai là."}
        return
    if ai.get("provider") != "anthropic":
        # Le streaming copilote est branché Anthropic (comme le vocal).
        yield {"type": "error",
               "error": "Le copilote a besoin d'une clé Anthropic (Réglages → IA)."}
        return

    thread = load_thread(user_id)
    prompt = build_prompt(app_state, user_id, thread, question, view)

    scrub = TagScrubber()
    pieces: list[str] = []
    try:
        for piece in _stream_anthropic(prompt, ai.get("model") or "",
                                       ai["api_key"]):
            pieces.append(piece)
            visible = scrub.push(piece)
            if visible:
                yield {"type": "delta", "text": visible}
    except CopilotError as exc:
        logger.warning("copilot stream: %s", exc)
        yield {"type": "error",
               "error": f"Je n'ai pas réussi à répondre ({exc}). Réessaie."}
        return
    except Exception as exc:
        logger.warning("copilot stream inattendu: %s", exc)
        yield {"type": "error",
               "error": "Je n'ai pas réussi à répondre cette fois. Réessaie."}
        return

    raw = "".join(pieces).strip()
    if not raw:
        yield {"type": "error",
               "error": "Réponse vide de l'IA — réessaie dans un instant."}
        return

    final = _finalize_reply(raw, user_id=user_id)
    append_turn(user_id, question, final["text"])

    # Étape 5 : une question d'information répétée (sans action derrière)
    # nourrit le compteur d'habitudes → bouton d'un clic proposé un jour.
    if final.get("action_done") is None and not final.get("proposed"):
        try:
            from . import copilot_habits
            copilot_habits.record_question(user_id, question)
        except Exception as exc:
            logger.debug("copilot habit question: %s", exc)

    done: dict[str, Any] = {"type": "done", "text": final["text"]}
    prop = final.get("proposed")
    if prop:
        # La carte suit la réponse dans le fil (ordre : réponse → carte).
        # Pas de pastille : l'utilisateur est déjà dans le volet.
        deposit_proposal_message(user_id, prop, bump=False)
        done["proposed"] = {
            "id": prop.get("id") or "",
            "do": prop.get("do") or "",
            "title": prop.get("title") or "",
            "preview": prop.get("preview"),
            "status": prop.get("status") or "pending",
            "created_at": prop.get("created_at") or "",
            "result_summary": "",
        }
    if final.get("navigate"):
        done["navigate"] = final["navigate"]
    if final.get("action_done") is not None:
        done["action_done"] = final["action_done"]
    if final.get("sent_to_thomas"):
        done["sent_to_thomas"] = True
    if final.get("memorized"):
        done["memorized"] = final["memorized"]
    if final.get("forgotten"):
        done["forgotten"] = True
    yield done


# ---------------------------------------------------------------------------
# Le point du jour (briefing) — à l'ouverture du volet, si c'est l'heure
# ---------------------------------------------------------------------------
BRIEFING_INSTRUCTION = """MISSION DE CE TOUR : fais LE POINT pour {PRENOM} (il vient d'ouvrir le volet, il ne t'a rien demandé — c'est ton accueil du jour).

Structure attendue, en 5 à 10 lignes, markdown léger :
1. Ce qui a BOUGÉ depuis son dernier passage (réel, tiré du JSON : réponses arrivées, missions finies, envois, sites…). S'il s'est passé peu de choses, une ligne suffit.
2. Les 2-3 choses qui COMPTENT maintenant, triées par impact business (réponses intéressées à traiter > brouillons à valider > robot en panne > relancer la machine). Chiffres réels à l'appui.
3. Si tout est calme et à jour : dis-le franchement en deux lignes, sans inventer de l'urgence.

Interdits pour CE tour : les tags [ACTION:…], [MEMOIRE:…], [OUBLIE:…], [CHAT_THOMAS]. Tu informes, tu ne lances rien.
Commence directement par le contenu (pas de « Salut » — l'en-tête est déjà posé)."""


def stream_briefing(app_state, user_id: str, view: str = "") -> Iterator[dict]:
    """Le point du jour, streamé comme un tour normal, persisté dans le fil.
    Mêmes évènements que stream_reply."""
    user_id = (user_id or "jordan").strip() or "jordan"
    ai = claude_advisor._resolve_ai(app_state)
    if not ai.get("api_key") or ai.get("provider") != "anthropic":
        yield {"type": "error",
               "error": "L'IA n'est pas configurée — ajoute ta clé Anthropic "
                        "dans Réglages."}
        return

    # Posé AVANT le stream : si le volet est rouvert pendant la génération,
    # pas de second briefing en parallèle.
    save_state(user_id, last_briefing_at=datetime.now().isoformat(
        timespec="seconds"))

    name = _display_name(user_id)
    st = load_state(user_id)
    hours = _hours_since(st["last_seen_at"])
    since = ("(premier passage enregistré)" if hours > 24 * 365 else
             f"dernier passage il y a environ {max(1, int(round(hours)))} h")

    blocks = [
        COPILOT_SYSTEM_PROMPT.replace("{PRENOM}", name),
        _memory_block(user_id, name),
    ]
    summary = load_summary(user_id)
    if summary:
        blocks.append("RÉSUMÉ DES ÉCHANGES PLUS ANCIENS :\n" + summary)
    blocks.append(_context_block(app_state))
    if view:
        blocks.append(f"Écran actuellement ouvert devant {name} : {view}")
    blocks.append(f"Repère temporel : {since}.")
    blocks.append(BRIEFING_INSTRUCTION.replace("{PRENOM}", name))
    prompt = "\n\n---\n\n".join(blocks)

    scrub = TagScrubber()
    header = "☀️ **Le point**\n"
    yield {"type": "delta", "text": header}
    pieces: list[str] = []
    try:
        for piece in _stream_anthropic(prompt, ai.get("model") or "",
                                       ai["api_key"]):
            pieces.append(piece)
            visible = scrub.push(piece)
            if visible:
                yield {"type": "delta", "text": visible}
    except CopilotError as exc:
        logger.warning("copilot briefing: %s", exc)
        yield {"type": "error",
               "error": f"Le point du jour n'a pas pu se faire ({exc})."}
        return
    except Exception as exc:
        logger.warning("copilot briefing inattendu: %s", exc)
        yield {"type": "error",
               "error": "Le point du jour n'a pas pu se faire. Réessaie."}
        return

    raw = "".join(pieces).strip()
    if not raw:
        yield {"type": "error", "error": "Point du jour vide — réessaie."}
        return

    # Pas d'action au briefing : on retire les tags sans RIEN exécuter.
    text, _ = claude_advisor._extract_action(raw)
    text, _ = _extract_json_tag(text, _MEMOIRE_RE)
    text, _ = _extract_json_tag(text, _OUBLIE_RE)
    text = (header + text).strip()
    append_messages(user_id, [{"role": "assistant", "content": text,
                               "kind": "briefing"}])
    yield {"type": "done", "text": text}


def send_blocking(app_state, user_id: str, question: str,
                  view: str = "", briefing: bool = False) -> dict:
    """Version « réponse en bloc » (secours quand le navigateur ne peut pas
    streamer, et chemin naturel du mode desktop)."""
    if briefing:
        gen = stream_briefing(app_state, user_id, view=view)
    else:
        gen = stream_reply(app_state, user_id, question, view=view)
    final: Optional[dict] = None
    for evt in gen:
        if evt.get("type") == "error":
            return {"ok": False, "text": "", "error": evt.get("error") or "erreur"}
        if evt.get("type") == "done":
            final = evt
    if not final:
        return {"ok": False, "text": "", "error": "Réponse vide de l'IA."}
    out = {"ok": True, "text": final.get("text") or ""}
    for k in ("navigate", "action_done", "sent_to_thomas", "memorized",
              "forgotten", "proposed"):
        if k in final:
            out[k] = final[k]
    return out
