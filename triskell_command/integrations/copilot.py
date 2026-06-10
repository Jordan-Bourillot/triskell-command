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
MAX_STORED_MESSAGES = 80      # messages conservés dans le fil persistant
MAX_PROMPT_TURNS = 16         # messages (user+assistant) injectés dans le prompt
MAX_MESSAGE_CHARS = 4000      # tronque les messages monstres
MAX_TOKENS = 2048             # réponses écrites courtes par design
CONTEXT_CACHE_SECONDS = 45    # le snapshot d'app coûte cher → petit cache

_LOCAL_FALLBACK_FILE = Path.home() / ".triskell-command" / "copilot_threads.json"

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
    """Valide/normalise un message {role, content[, at]}. None si invalide."""
    if not isinstance(msg, dict):
        return None
    role = str(msg.get("role") or "").strip().lower()
    if role not in ("user", "assistant"):
        return None
    content = str(msg.get("content") or "").strip()
    if not content:
        return None
    return {
        "role": role,
        "content": content[:MAX_MESSAGE_CHARS],
        "at": str(msg.get("at") or datetime.now().isoformat(timespec="seconds")),
    }


def _read_local_threads() -> dict:
    try:
        if _LOCAL_FALLBACK_FILE.is_file():
            data = json.loads(_LOCAL_FALLBACK_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.debug("copilot fallback read: %s", exc)
    return {}


def _write_local_thread(user_id: str, messages: list[dict]) -> None:
    try:
        data = _read_local_threads()
        data[user_id] = {
            "messages": messages,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        _LOCAL_FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LOCAL_FALLBACK_FILE.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.debug("copilot fallback write: %s", exc)


def load_thread(user_id: str) -> list[dict]:
    """Le fil de discussion persisté (liste de messages, du plus ancien au
    plus récent). Jamais d'exception : au pire, liste vide."""
    user_id = user_id or "jordan"
    raw = None
    client = claude_advisor._client()
    if client is not None:
        try:
            raw = client.get_shared_setting(_setting_key(user_id), None)
        except Exception as exc:
            logger.debug("copilot load supabase: %s", exc)
            raw = None
    if raw is None:
        raw = _read_local_threads().get(user_id)
    msgs = (raw or {}).get("messages") if isinstance(raw, dict) else None
    out: list[dict] = []
    for m in (msgs or []):
        cm = _clean_message(m)
        if cm:
            out.append(cm)
    return out[-MAX_STORED_MESSAGES:]


def save_thread(user_id: str, messages: list[dict]) -> None:
    """Écrit le fil (tronqué). Supabase d'abord, fichier local en secours."""
    user_id = user_id or "jordan"
    messages = messages[-MAX_STORED_MESSAGES:]
    payload = {
        "messages": messages,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    client = claude_advisor._client()
    if client is not None:
        try:
            client.set_shared_setting(_setting_key(user_id), payload)
            return
        except Exception as exc:
            logger.debug("copilot save supabase: %s", exc)
    _write_local_thread(user_id, messages)


def append_messages(user_id: str, new_messages: list[Any]) -> int:
    """Ajoute des messages au fil (ex : tours du mode vocal reversés à la
    fin d'un appel). Renvoie le nombre réellement ajouté."""
    cleaned = []
    for m in (new_messages or [])[:20]:
        cm = _clean_message(m)
        if cm:
            cleaned.append(cm)
    if not cleaned:
        return 0
    thread = load_thread(user_id)
    thread.extend(cleaned)
    save_thread(user_id, thread)
    return len(cleaned)


def append_turn(user_id: str, question: str, answer: str) -> None:
    append_messages(user_id, [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ])


def clear_thread(user_id: str) -> None:
    save_thread(user_id, [])


def thread_for_ui(user_id: str) -> dict:
    """Le fil prêt à afficher dans le volet."""
    user_id = user_id or "jordan"
    return {
        "ok": True,
        "user": user_id,
        "display_name": _display_name(user_id),
        "messages": load_thread(user_id)[-60:],
    }


# ---------------------------------------------------------------------------
# Prompt système — la voix ÉCRITE du copilote
# ---------------------------------------------------------------------------
COPILOT_SYSTEM_PROMPT = """Tu es Claude, le copilote de {PRENOM} dans Triskell Command (l'app de pilotage de Studio Triskell, agence web bretonne fondée par Jordan et Thomas).

Tu vis dans un VOLET DE DISCUSSION ÉCRIT, ouvrable depuis n'importe quel écran de l'app. {PRENOM} t'écrit, tu réponds par écrit. La conversation est conservée d'une session à l'autre : tu peux faire référence aux échanges précédents du fil.

═══════════════════════════════════════════════════════════════
TU AS ACCÈS À TOUTE L'APP TRISKELL COMMAND EN DIRECT
═══════════════════════════════════════════════════════════════
Plus bas, tu reçois un bloc JSON « ÉTAT DE TOUTE L'APP TRISKELL COMMAND EN DIRECT » : snapshot live (cockpit prospection, envois, réponses par catégorie, file de travail, workers, config, catalogue, clients, projets, Pixel Pros, Lagriffe, Obélisk, Phare/SEO, Convoi, Forge, factures, funnel 30 j) + les missions de prospection récentes.

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


def build_prompt(app_state, user_id: str, thread: list[dict],
                 question: str, view: str = "") -> str:
    """Assemble le prompt complet d'un tour de copilote."""
    name = _display_name(user_id)
    system = COPILOT_SYSTEM_PROMPT.replace("{PRENOM}", name)

    blocks: list[str] = [system]
    if (user_id or "jordan") == "jordan":
        blocks.append(CHAT_THOMAS_BLOCK)
    blocks.append(claude_advisor.ASSISTANT_ACTIONS_PROMPT)
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
# Anti-fuite : masque les tags [ACTION:…] / [CHAT_THOMAS] pendant le stream
# ---------------------------------------------------------------------------
_TAG_MARKERS = ("[ACTION:", "[CHAT_THOMAS]")


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
def _finalize_reply(raw: str, *, execute=None) -> dict:
    """À partir du texte BRUT complet du modèle : poste l'éventuel message à
    Thomas, exécute l'éventuelle action (liste blanche stricte), renvoie
    {text, navigate, action_done, sent_to_thomas}."""
    execute = execute or claude_advisor.execute_assistant_action
    text, sent_thomas = claude_advisor._extract_chat_to_thomas(raw or "")
    text, action = claude_advisor._extract_action(text)
    out: dict[str, Any] = {
        "text": (text or "").strip(),
        "navigate": "",
        "action_done": None,
        "sent_to_thomas": bool(sent_thomas),
    }
    if action is not None:
        try:
            result = execute(action) or {}
        except Exception as exc:  # ceinture : execute ne lève normalement pas
            result = {"ok": False, "summary": f"L'action a échoué : {exc}"}
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

    final = _finalize_reply(raw)
    append_turn(user_id, question, final["text"])

    done: dict[str, Any] = {"type": "done", "text": final["text"]}
    if final.get("navigate"):
        done["navigate"] = final["navigate"]
    if final.get("action_done") is not None:
        done["action_done"] = final["action_done"]
    if final.get("sent_to_thomas"):
        done["sent_to_thomas"] = True
    yield done


def send_blocking(app_state, user_id: str, question: str,
                  view: str = "") -> dict:
    """Version « réponse en bloc » (secours quand le navigateur ne peut pas
    streamer, et chemin naturel du mode desktop)."""
    final: Optional[dict] = None
    for evt in stream_reply(app_state, user_id, question, view=view):
        if evt.get("type") == "error":
            return {"ok": False, "text": "", "error": evt.get("error") or "erreur"}
        if evt.get("type") == "done":
            final = evt
    if not final:
        return {"ok": False, "text": "", "error": "Réponse vide de l'IA."}
    out = {"ok": True, "text": final.get("text") or ""}
    for k in ("navigate", "action_done", "sent_to_thomas"):
        if k in final:
            out[k] = final[k]
    return out
