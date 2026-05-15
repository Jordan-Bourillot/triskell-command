"""Brain — boîte à idées partagée Jordan/Thomas (alimente la table
`command_voice_brain` Supabase, déjà créée par l'app mobile command-voice).

Workflow type :
  1. Utilisateur ajoute une note rapide (texte libre)
  2. Claude analyse : catégorie, résumé court, tags, date de rappel éventuelle
  3. Note enregistrée avec ces métadonnées
  4. Liste consultable groupée par catégorie
  5. Marquer fait / archiver / supprimer / répondre (avec ré-analyse)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

TABLE = "command_voice_brain"

# Mêmes utilisateurs que command-voice (alias mobile)
USER_ALIASES = {
    "jordan@triskell-studio.fr": "jordan",
    "thomasbourillot@gmail.com": "thomas",
}

ANALYZE_SYSTEM = """Tu analyses une note rapide écrite par Jordan (alias 'BOSS DE L'UNIVERS', user_id=jordan) ou Thomas (alias 'Xi', user_id=thomas) dans leur 'Brain' — un cerveau commun où ils jettent idées, tâches, réflexions, infos en vrac.

Ta tâche : retourner UNIQUEMENT un JSON valide avec ces champs (pas de markdown, pas d'explication) :
{
  "category": "string court (ex: 'Idée produit', 'À faire', 'Pour Xi', 'Question client', 'Tech', 'Marketing', 'Personnel')",
  "summary": "string courte (1 phrase max) qui résume l'essentiel de la note",
  "tags": ["tag1", "tag2"],
  "remind_at": "ISO 8601 string OU null. Si la note mentionne explicitement un délai (ex 'dans 3 jours', 'demain', 'la semaine prochaine', 'lundi'), calcule la date correspondante depuis NOW. Sinon null.",
  "assigned_to": "'jordan' | 'thomas' | null"
}

Conseils :
- Choisis les catégories naturellement, comme un cerveau humain les classerait
- Si la note est personnelle, préfère 'Personnel'
- Pour remind_at : utilise NOW comme référence et calcule UTC ISO 8601 (Z)"""


# ---------------------------------------------------------------------------
# Connexion Supabase (service-role)
# ---------------------------------------------------------------------------
_SERVICE_CLIENT = None
_SERVICE_TRIED = False


def _service_sb():
    global _SERVICE_CLIENT, _SERVICE_TRIED
    if _SERVICE_CLIENT is not None:
        return _SERVICE_CLIENT
    if _SERVICE_TRIED:
        return None
    _SERVICE_TRIED = True
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not (url and key):
        cfg = Path.home() / ".triskell-command" / "settings.json"
        if cfg.exists():
            try:
                d = json.loads(cfg.read_text(encoding="utf-8"))
                sb = d.get("supabase") or {}
                url = url or sb.get("url", "")
                key = key or sb.get("service_role_key") or sb.get("service_key", "")
            except Exception: pass
    if not (url and key):
        return None
    try:
        from supabase import create_client
        _SERVICE_CLIENT = create_client(url, key)
    except Exception as exc:
        logger.warning("brain._service_sb: %s", exc)
    return _SERVICE_CLIENT


def _user_alias(client) -> str:
    """Devine l'alias (jordan / thomas) depuis le user authentifié."""
    if client is None:
        return "jordan"
    try:
        sb = getattr(client, "client", None) or getattr(client, "_client", None)
        if sb:
            user = sb.auth.get_user()
            email = getattr(getattr(user, "user", None) or user, "email", "") or ""
            return USER_ALIASES.get(email.lower(), "jordan")
    except Exception: pass
    return "jordan"


def _sb(client=None):
    """Renvoie un client Supabase brut (raw) — préfère service-role."""
    s = _service_sb()
    if s is not None:
        return s
    if client is not None:
        return getattr(client, "client", None) or getattr(client, "_client", None)
    return None


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def list_notes(*, status: Optional[str] = None, category: Optional[str] = None,
                limit: int = 100, client=None) -> list[dict]:
    sb = _sb(client)
    if sb is None: return []
    try:
        q = sb.table(TABLE).select("*").order("created_at", desc=True).limit(limit)
        if status:   q = q.eq("status", status)
        if category: q = q.eq("category", category)
        return q.execute().data or []
    except Exception as exc:
        logger.warning("brain.list_notes: %s", exc)
        return []


def list_by_category(client=None) -> list[dict]:
    """Renvoie [{category, count, notes}] trié par count desc."""
    notes = list_notes(status="open", limit=200, client=client)
    by_cat: dict[str, list[dict]] = {}
    for n in notes:
        cat = n.get("category") or "Sans catégorie"
        by_cat.setdefault(cat, []).append(n)
    out = [{"category": c, "count": len(ns), "notes": ns}
           for c, ns in by_cat.items()]
    out.sort(key=lambda g: -g["count"])
    return out


def get_note(note_id: str, client=None) -> Optional[dict]:
    sb = _sb(client)
    if sb is None: return None
    try:
        rows = sb.table(TABLE).select("*").eq("id", note_id).limit(1).execute().data
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("brain.get_note: %s", exc)
        return None


def add_note(content: str, *, author: str = "jordan", client=None,
             ai_keys: Optional[dict] = None) -> Optional[dict]:
    """Ajoute une note + analyse IA (catégorie, tags, remind_at)."""
    sb = _sb(client)
    if sb is None: return None
    content = (content or "").strip()
    if not content: return None
    # Analyse IA (best-effort — si ça échoue, on insère sans métadonnées)
    analysis = analyze_note(content, ai_keys=ai_keys) or {}
    row = {
        "author": author,
        "content": content,
        "category": analysis.get("category") or None,
        "summary":  analysis.get("summary") or None,
        "tags":     analysis.get("tags") or [],
        "remind_at": analysis.get("remind_at"),
        "assigned_to": analysis.get("assigned_to"),
        "replies": [],
        "status": "open",
    }
    try:
        ins = sb.table(TABLE).insert(row).execute()
        return (ins.data or [None])[0]
    except Exception as exc:
        logger.warning("brain.add_note: %s", exc)
        return None


def update_note(note_id: str, patch: dict, client=None) -> bool:
    sb = _sb(client)
    if sb is None or not note_id: return False
    patch = dict(patch or {})
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        sb.table(TABLE).update(patch).eq("id", note_id).execute()
        return True
    except Exception as exc:
        logger.warning("brain.update_note: %s", exc)
        return False


def delete_note(note_id: str, client=None) -> bool:
    sb = _sb(client)
    if sb is None or not note_id: return False
    try:
        sb.table(TABLE).delete().eq("id", note_id).execute()
        return True
    except Exception as exc:
        logger.warning("brain.delete_note: %s", exc)
        return False


def add_reply(note_id: str, reply_content: str, *, author: str = "jordan",
              client=None, ai_keys: Optional[dict] = None) -> Optional[dict]:
    """Ajoute une réponse à une note + ré-analyse avec le contexte complet."""
    note = get_note(note_id, client=client)
    if note is None: return None
    new_reply = {
        "id": str(uuid4()),
        "author": author,
        "content": (reply_content or "").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    replies = list(note.get("replies") or []) + [new_reply]
    full_text = f"Note originale ({note.get('author')}) : {note.get('content')}\n\n"
    for r in replies:
        full_text += f"Réponse ({r.get('author')}) : {r.get('content')}\n\n"
    analysis = analyze_note(full_text, ai_keys=ai_keys) or {}
    patch = {
        "replies": replies,
        "category": analysis.get("category") or note.get("category"),
        "summary":  analysis.get("summary") or note.get("summary"),
        "tags":     analysis.get("tags") or note.get("tags"),
    }
    if analysis.get("remind_at") and analysis.get("remind_at") != note.get("remind_at"):
        patch["remind_at"] = analysis["remind_at"]
        patch["reminded_at"] = None
    update_note(note_id, patch, client=client)
    return get_note(note_id, client=client)


# ---------------------------------------------------------------------------
# Analyse IA (Claude)
# ---------------------------------------------------------------------------
def analyze_note(content: str, *, ai_keys: Optional[dict] = None) -> Optional[dict]:
    """Appelle Claude pour catégoriser + résumer + extraire tags + détecter rappel."""
    api_key = (ai_keys or {}).get("anthropic", "") if ai_keys else ""
    if not api_key:
        # Fallback : lit settings.json local
        try:
            cfg = json.loads((Path.home() / ".triskell-command" / "settings.json")
                              .read_text(encoding="utf-8"))
            api_key = (cfg.get("ai") or {}).get("api_keys", {}).get("anthropic", "")
        except Exception: pass
    if not api_key:
        logger.debug("brain.analyze_note: clé Anthropic manquante")
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        logger.warning("anthropic SDK manquant — pip install anthropic")
        return None
    try:
        client = Anthropic(api_key=api_key)
        now_iso = datetime.now(timezone.utc).isoformat()
        resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=400,
            system=[
                {"type": "text", "text": ANALYZE_SYSTEM,
                 "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": f"NOW = {now_iso}"},
            ],
            messages=[{"role": "user", "content": content}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(text)
        assigned = parsed.get("assigned_to")
        if assigned not in ("jordan", "thomas"):
            assigned = None
        remind = parsed.get("remind_at")
        if not (isinstance(remind, str) and len(remind) >= 10 and remind[:4].isdigit()):
            remind = None
        return {
            "category": str(parsed.get("category") or "Sans catégorie")[:60],
            "summary":  str(parsed.get("summary") or "")[:200],
            "tags":     [str(t) for t in (parsed.get("tags") or [])][:3],
            "remind_at": remind,
            "assigned_to": assigned,
        }
    except Exception as exc:
        logger.warning("brain.analyze_note Claude: %s", exc)
        return None
