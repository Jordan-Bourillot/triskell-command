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
BUCKET = "brain-attachments"

# Mêmes utilisateurs que command-voice (alias mobile)
USER_ALIASES = {
    "jordan@triskell-studio.fr": "jordan",
    "thomasbourillot@gmail.com": "thomas",
}

ANALYZE_SYSTEM = """Tu traites une note jetée à la volée dans le 'Brain' de Jordan (alias 'BOSS DE L'UNIVERS', user_id=jordan) ou Thomas (alias 'Xi', user_id=thomas).

CONTEXTE CRUCIAL — lis-le avant tout :
Le Brain est une boîte à idées-décharge. L'auteur écrit VITE, BRUT, sans soigner la formulation, pour vider son cerveau. La note peut être un bout de phrase, une faute de frappe, un mot-clé, une idée pas finie. Ce n'est PAS un texte à reformuler joliment, c'est un post-it mental.

Ta tâche : retourner UNIQUEMENT un JSON valide (pas de markdown, pas d'explication) :
{
  "category": "string court (ex: 'Idée produit', 'À faire', 'Pour Xi', 'Question client', 'Tech', 'Marketing', 'Personnel')",
  "summary": "résumé ultra-court et FIDÈLE — voir règles ci-dessous",
  "tags": ["tag1", "tag2"],
  "urgency": 1-5,
  "importance": 1-5,
  "remind_at": "ISO 8601 UTC string OU null. Voir règles ci-dessous.",
  "assigned_to": "'jordan' | 'thomas' | null"
}

RÈGLES POUR `summary` — RELIS À CHAQUE NOTE :
1. SIMPLIFIE, n'invente rien. Reformule en plus court, jamais en plus riche.
2. Reste collé aux mots de la note. Si la note dit 'changer logo', le résumé dit 'Changer le logo', pas 'Refonte de l'identité visuelle'.
3. N'extrapole AUCUN sens : pas de contexte deviné, pas de bénéfice imaginé, pas de produit/projet supposé, pas de jeu de mots, pas de titre 'accrocheur'.
4. Si la note est déjà courte (< 10 mots), tu peux la garder presque telle quelle, juste corriger fautes de frappe / ponctuation.
5. Une phrase max, 12 mots max. Phrase factuelle, pas marketing.
6. Si la note est vraiment incompréhensible, mets le tout début (5-8 mots) tel quel comme summary, ne devine pas.

RÈGLES POUR `urgency` (à quel point ça doit être traité vite) :
- 5 = à faire MAINTENANT / aujourd'hui (urgence client, deadline imminente, problème prod, RDV demain)
- 4 = cette semaine (engagement pris, attendu sous quelques jours)
- 3 = ce mois-ci (à planifier, sans deadline forte)
- 2 = quand il y aura du temps (idée à explorer, amélioration)
- 1 = aucun délai (réflexion, vision long terme, idée pure)

RÈGLES POUR `importance` (à quel point l'impact est grand) :
- 5 = critique pour le business / la vie (chiffre d'affaires, santé, légal, client clé)
- 4 = fort impact (nouveau produit, refonte majeure, relation pro importante)
- 3 = impact normal (amélioration utile, sujet de fond)
- 2 = mineur (petit confort, détail)
- 1 = marginal (curiosité, fun, peu de valeur)

RÈGLES POUR `remind_at` (ordre de priorité) :
1. Si la note mentionne un délai EXPLICITE ('demain', 'dans 3 jours', 'lundi', 'la semaine prochaine') → calcule la date correspondante en UTC ISO 8601 (Z).
2. Sinon → laisse null. Le système calculera automatiquement le rappel à partir de l'urgence.

Catégorie :
- Choisis les catégories naturellement, comme un cerveau humain les classerait
- Si la note est personnelle, préfère 'Personnel'
- Pour remind_at calculé : utilise NOW comme référence (UTC ISO 8601 Z)"""


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
        sb = client.raw
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
        try:
            return client.raw
        except Exception:
            return None
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
             ai_keys: Optional[dict] = None,
             attachments: Optional[list[str]] = None,
             analyze_images: bool = False) -> Optional[dict]:
    """Ajoute une note + analyse IA (catégorie, tags, remind_at).

    Si `attachments` est fourni : les URLs sont stockées avec la note.
    Si `analyze_images=True` : Claude regarde aussi les images pour résumer."""
    sb = _sb(client)
    if sb is None: return None
    content = (content or "").strip()
    atts = [a for a in (attachments or []) if a]
    if not content and not atts: return None
    # Analyse IA (best-effort — si ça échoue, on insère sans métadonnées)
    img_for_analysis = atts if analyze_images else None
    analysis = analyze_note(content or "(image seule)", ai_keys=ai_keys,
                             image_urls=img_for_analysis) or {}
    row = {
        "author": author,
        "content": content,
        "category": analysis.get("category") or None,
        "summary":  analysis.get("summary") or None,
        "tags":     analysis.get("tags") or [],
        "urgency":   analysis.get("urgency"),
        "importance": analysis.get("importance"),
        "remind_at": analysis.get("remind_at"),
        "assigned_to": analysis.get("assigned_to"),
        "replies": [],
        "status": "open",
        "attachments": atts,
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


def edit_content(note_id: str, new_content: str, *, client=None,
                 ai_keys: Optional[dict] = None,
                 attachments: Optional[list[str]] = None,
                 analyze_images: bool = False) -> Optional[dict]:
    """Met à jour le contenu (+ éventuellement attachments) + ré-analyse.

    Si `attachments` est None : on garde celles déjà en base.
    Si `attachments` est une liste : on remplace par cette liste (peut être vide pour tout enlever).
    Si `analyze_images=True` : Claude regarde les images (vision) pour résumer."""
    sb = _sb(client)
    if sb is None or not note_id:
        return None
    new_content = (new_content or "").strip()
    note = get_note(note_id, client=client)
    if note is None:
        return None
    # attachments : on garde l'existant si non précisé
    if attachments is None:
        atts = note.get("attachments") or []
    else:
        atts = [a for a in attachments if a]
    if not new_content and not atts:
        return None
    img_for_analysis = atts if analyze_images else None
    # Re-analyse avec contexte complet (contenu + réponses) si réponses présentes
    replies = note.get("replies") or []
    if replies:
        full = f"Note originale ({note.get('author')}) : {new_content or '(image seule)'}\n\n"
        for r in replies:
            full += f"Réponse ({r.get('author')}) : {r.get('content')}\n\n"
        analysis = analyze_note(full, ai_keys=ai_keys, image_urls=img_for_analysis) or {}
    else:
        analysis = analyze_note(new_content or "(image seule)", ai_keys=ai_keys,
                                 image_urls=img_for_analysis) or {}
    patch = {
        "content":  new_content,
        "attachments": atts,
        "category": analysis.get("category") or note.get("category"),
        "summary":  analysis.get("summary") or None,
        "tags":     analysis.get("tags") or note.get("tags") or [],
        "urgency":   analysis.get("urgency") if analysis else note.get("urgency"),
        "importance": analysis.get("importance") if analysis else note.get("importance"),
        "assigned_to": analysis.get("assigned_to") if analysis else note.get("assigned_to"),
    }
    new_remind = analysis.get("remind_at")
    if new_remind and new_remind != note.get("remind_at"):
        patch["remind_at"] = new_remind
        patch["reminded_at"] = None
    update_note(note_id, patch, client=client)
    return get_note(note_id, client=client)


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
        "urgency":   analysis.get("urgency") if analysis else note.get("urgency"),
        "importance": analysis.get("importance") if analysis else note.get("importance"),
    }
    if analysis.get("remind_at") and analysis.get("remind_at") != note.get("remind_at"):
        patch["remind_at"] = analysis["remind_at"]
        patch["reminded_at"] = None
    update_note(note_id, patch, client=client)
    return get_note(note_id, client=client)


# ---------------------------------------------------------------------------
# Pièces jointes (Supabase Storage)
# ---------------------------------------------------------------------------
import base64 as _b64, mimetypes as _mt
from urllib.request import urlopen as _urlopen


def upload_attachment(file_bytes: bytes, filename: str, *,
                       content_type: Optional[str] = None, client=None) -> Optional[str]:
    """Upload un fichier dans le bucket Storage et renvoie l'URL publique."""
    sb = _sb(client)
    if sb is None or not file_bytes:
        return None
    ct = content_type or _mt.guess_type(filename)[0] or "application/octet-stream"
    ext = (Path(filename).suffix or "").lower() or ".bin"
    # chemin : YYYY/MM/<uuid>.<ext>
    now = datetime.now(timezone.utc)
    key = f"{now.year:04d}/{now.month:02d}/{uuid4().hex}{ext}"
    try:
        sb.storage.from_(BUCKET).upload(
            path=key,
            file=file_bytes,
            file_options={"content-type": ct, "upsert": "false"},
        )
        return sb.storage.from_(BUCKET).get_public_url(key)
    except Exception as exc:
        logger.warning("brain.upload_attachment: %s", exc)
        return None


def _fetch_image_as_base64(url: str) -> Optional[tuple[str, str]]:
    """Récupère une image depuis son URL publique → (media_type, base64). None si échec."""
    try:
        with _urlopen(url, timeout=10) as r:
            data = r.read()
            mt = r.headers.get_content_type() or "image/jpeg"
        if not mt.startswith("image/"):
            return None
        return mt, _b64.b64encode(data).decode("ascii")
    except Exception as exc:
        logger.warning("brain._fetch_image_as_base64 %s: %s", url, exc)
        return None


def process_reminders(client=None, *, dry_run: bool = False) -> dict:
    """Parcourt les notes 'open' dont remind_at est échu (et reminded_at null)
    et envoie une notification push à l'auteur (et l'assigned_to si présent).

    Renvoie {"checked": n, "sent": k, "errors": [...]}.
    Si dry_run=True : ne fait que lister sans pousser ni marquer.
    """
    sb = _sb(client)
    if sb is None:
        return {"checked": 0, "sent": 0, "errors": ["no_supabase"]}
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        rows = (sb.table(TABLE).select("*")
                  .eq("status", "open")
                  .is_("reminded_at", "null")
                  .lte("remind_at", now_iso)
                  .limit(50)
                  .execute().data) or []
    except Exception as exc:
        return {"checked": 0, "sent": 0, "errors": [f"list: {exc}"]}

    sent = 0
    errors: list[str] = []
    # Import push lazy (pas dispo dans tous les environnements)
    try:
        from ..web import push as _push
    except Exception as exc:
        return {"checked": len(rows), "sent": 0, "errors": [f"push_import: {exc}"]}

    for n in rows:
        nid = n.get("id")
        title = "🧠 Rappel Brain"
        u = n.get("urgency")
        if u == 5: title = "🔥 Urgent — Brain"
        elif u == 4: title = "⚡ Bientôt — Brain"
        body = (n.get("summary") or n.get("content") or "")[:200]
        # Cible : assigned_to si défini, sinon auteur, sinon tout le monde
        targets = []
        if n.get("assigned_to"):
            targets.append(n["assigned_to"])
        elif n.get("author"):
            targets.append(n["author"])
        else:
            targets.append(None)
        if dry_run:
            sent += 1
            continue
        try:
            delivered = 0
            for t in targets:
                res = _push.send_push(title, body,
                                user_id=t, tag=f"brain-{nid}",
                                tag_group="brain", priority=("urgent" if u == 5 else "normal"),
                                url="/?view=brain",
                                extra_data={"note_id": nid})
                if isinstance(res, dict):
                    delivered += int(res.get("sent") or 0)
            # On ne marque "rappelée" QUE si au moins une notif est partie.
            # Sinon (pas d'abonnement push, VAPID absent…), on laisse la note
            # active pour que le bandeau in-app dans le navigateur la rattrape.
            if delivered > 0:
                sb.table(TABLE).update({"reminded_at": now_iso}).eq("id", nid).execute()
                sent += 1
        except Exception as exc:
            errors.append(f"{nid}: {exc}")

    return {"checked": len(rows), "sent": sent, "errors": errors}


def _compute_remind_from_urgency(urgency: int) -> Optional[str]:
    """Calcule un remind_at par défaut depuis l'urgence (1-5).
    Renvoie une string ISO 8601 UTC (Z) ou None pour urgency <= 2.

    Règles (heure locale Europe/Paris) :
      - 5 → dans 2 heures
      - 4 → demain 9h00
      - 3 → dans 3 jours, 9h00
      - 1-2 → pas de rappel auto
    """
    from datetime import timedelta
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Paris")
    except Exception:
        tz = timezone.utc
    now = datetime.now(tz)
    if urgency == 5:
        when = now + timedelta(hours=2)
    elif urgency == 4:
        nine = now.replace(hour=9, minute=0, second=0, microsecond=0)
        when = nine + timedelta(days=1) if now >= nine else nine
    elif urgency == 3:
        nine = now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=3)
        when = nine
    else:
        return None
    return when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Analyse IA (Claude)
# ---------------------------------------------------------------------------
def analyze_note(content: str, *, ai_keys: Optional[dict] = None,
                  image_urls: Optional[list[str]] = None) -> Optional[dict]:
    """Appelle Claude pour catégoriser + résumer + extraire tags + détecter rappel.

    Si `image_urls` est fourni, Claude regarde aussi les images (vision)
    et peut s'appuyer sur leur contenu pour résumer."""
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
        # Construit le message user — texte + images si fournies
        user_blocks: list = []
        for url in (image_urls or []):
            img = _fetch_image_as_base64(url)
            if img is None: continue
            mt, b64 = img
            user_blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mt, "data": b64},
            })
        user_blocks.append({"type": "text", "text": content or "(note sans texte, voir images)"})
        resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=400,
            system=[
                {"type": "text", "text": ANALYZE_SYSTEM,
                 "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": f"NOW = {now_iso}"},
            ],
            messages=[{"role": "user", "content": user_blocks}],
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
        # Urgence / Importance (clamp 1-5)
        def _clamp(v):
            try:
                n = int(v)
                return max(1, min(5, n))
            except (TypeError, ValueError):
                return None
        urgency = _clamp(parsed.get("urgency"))
        importance = _clamp(parsed.get("importance"))
        # Si remind_at non explicite, déduit depuis urgency
        if remind is None and urgency is not None and urgency >= 3:
            remind = _compute_remind_from_urgency(urgency)
        return {
            "category": str(parsed.get("category") or "Sans catégorie")[:60],
            "summary":  str(parsed.get("summary") or "")[:200],
            "tags":     [str(t) for t in (parsed.get("tags") or [])][:3],
            "urgency":  urgency,
            "importance": importance,
            "remind_at": remind,
            "assigned_to": assigned,
        }
    except Exception as exc:
        logger.warning("brain.analyze_note Claude: %s", exc)
        return None
