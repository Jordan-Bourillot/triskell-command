"""Appels audio / vidéo (WebRTC) dans le chat Jordan ↔ Thomas.

Ce module ne transporte NI le son NI l'image — une fois l'appel établi,
le flux circule en direct de navigateur à navigateur (peer-to-peer).
Ici on ne gère que la **poignée de main** initiale : les deux PC doivent
s'échanger une « offre » et une « réponse » WebRTC avant de se connecter.

On réutilise exactement le modèle du reste du chat :
- table Supabase `call_signals` = boîte aux lettres éphémère
- chaque navigateur DÉPOSE des signaux pour l'autre (`send_signal`)
- chaque navigateur RELÈVE les siens en pollant (`poll_signals`)

Identité : comme messages.py, on lit l'utilisateur local (jordan/thomas)
posé par web/auth.py sur la session HTTP courante.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Au-delà de cette ancienneté, un signal est considéré périmé (appel
# avorté, onglet fermé en plein milieu…) et purgé à la volée pour garder
# la table propre.
SIGNAL_TTL_SECONDS = 120

# Types de signaux acceptés (garde-fou contre l'insertion de n'importe quoi).
_KINDS = ("offer", "answer", "hangup", "decline", "cancel", "busy", "ringing")


def _supabase():
    """Client Supabase brut si dispo + authentifié, sinon None."""
    try:
        from triskell_core.db import get_client
    except ImportError:
        return None
    try:
        c = get_client()
    except Exception:
        return None
    if not c.is_authenticated:
        return None
    return c


def _me() -> Optional[str]:
    """Identité locale (jordan/thomas) de la requête HTTP en cours."""
    try:
        from ..web.auth import get_current_local_user
        return get_current_local_user()
    except Exception:
        return None


def _opposite(user_id: Optional[str]) -> Optional[str]:
    """L'autre membre du binôme (jordan ↔ thomas)."""
    if user_id == "jordan":
        return "thomas"
    if user_id == "thomas":
        return "jordan"
    return None


def other_user_id() -> Optional[str]:
    """L'identité de la personne qu'on peut appeler (None si pas loggé)."""
    return _opposite(_me())


def send_signal(
    call_id: str,
    kind: str,
    payload: Optional[str] = None,
    mode: Optional[str] = None,
) -> bool:
    """Dépose un signal d'appel à destination de l'autre user.

    - call_id : identifiant de la session d'appel (généré côté navigateur)
    - kind    : offer | answer | hangup | decline | cancel | busy | ringing
    - payload : la description WebRTC sérialisée en JSON (pour offer/answer)
    - mode    : 'audio' ou 'video' (porté par l'offre, pour savoir si la
                caméra est de la partie)

    Renvoie True si l'insertion a réussi.
    """
    me = _me()
    other = _opposite(me)
    c = _supabase()
    if c is None or not me or not other:
        return False
    if kind not in _KINDS or not call_id:
        logger.debug("send_signal: signal invalide kind=%r call_id=%r", kind, call_id)
        return False
    row: dict[str, Any] = {
        "call_id": str(call_id),
        "from_user": me,
        "to_user": other,
        "kind": kind,
    }
    if payload is not None:
        row["payload"] = payload
    if mode:
        row["mode"] = mode
    try:
        c.raw.table("call_signals").insert(row).execute()
    except Exception as exc:
        logger.warning("send_signal: %s", exc)
        return False
    # Une offre = un appel qui démarre. On réveille le destinataire par une
    # notification push, pour que ça sonne même s'il n'a pas le site ouvert.
    if kind == "offer":
        _notify_incoming_call(me, other, mode)
    return True


def _notify_incoming_call(caller_id: str, callee_id: str, mode: Optional[str]) -> None:
    """Réveille le destinataire d'un appel par une notification push, même
    site fermé. Envoyé en tâche de fond pour ne pas ralentir la mise en
    relation. Sans effet (silencieux) si l'autre n'a jamais activé les
    notifications — aucune erreur n'est levée dans ce cas.
    """
    try:
        from ..web.auth import get_display_name
        caller_name = get_display_name(caller_id) or (caller_id or "").capitalize()
    except Exception:
        caller_name = (caller_id or "Quelqu’un").capitalize()
    title = f"📞 {caller_name} t’appelle"
    body = "Appel vidéo" if mode == "video" else "Appel vocal"

    def _go():
        try:
            from ..web.push import send_push
            send_push(
                title, body,
                user_id=callee_id,
                priority="urgent",      # vibration forte + reste affichée
                tag="call",
                tag_group="call",
                url="/",
                extra_data={"type": "call", "mode": mode or "audio"},
            )
        except Exception as exc:
            logger.debug("_notify_incoming_call send: %s", exc)

    try:
        import threading
        threading.Thread(target=_go, name="call-push", daemon=True).start()
    except Exception as exc:
        logger.debug("_notify_incoming_call thread: %s", exc)


def poll_signals() -> list[dict[str, Any]]:
    """Relève les signaux d'appel destinés à l'utilisateur courant.

    Lecture « destructive » atomique : on marque consommés (et on renvoie)
    en UNE requête les signaux non encore lus qui me sont adressés — ça
    évite qu'un poll concurrent ne les retraite. On en profite pour purger
    les vieux signaux périmés (appel avorté).

    Renvoie une liste de dicts {call_id, from_user, kind, mode, payload,
    created_at}, du plus ancien au plus récent.
    """
    me = _me()
    c = _supabase()
    if c is None or not me:
        return []
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    # Housekeeping : on supprime tout signal trop vieux (le mien comme
    # celui de l'autre) pour ne pas laisser la table gonfler.
    try:
        cutoff = (now - timedelta(seconds=SIGNAL_TTL_SECONDS)).isoformat()
        c.raw.table("call_signals").delete().lt("created_at", cutoff).execute()
    except Exception as exc:
        logger.debug("poll_signals housekeeping: %s", exc)
    # Marque consommés + récupère en un seul coup (UPDATE ... RETURNING).
    try:
        res = (c.raw.table("call_signals")
               .update({"consumed_at": now.isoformat()})
               .eq("to_user", me)
               .is_("consumed_at", "null")
               .execute())
        rows = res.data or []
        rows.sort(key=lambda r: r.get("created_at") or "")
        return rows
    except Exception as exc:
        logger.debug("poll_signals: %s", exc)
        return []


def clear_call(call_id: str) -> bool:
    """Supprime tous les signaux d'une session d'appel (nettoyage après
    raccroché). Best-effort — renvoie True si pas d'erreur."""
    c = _supabase()
    if c is None or not call_id:
        return False
    try:
        c.raw.table("call_signals").delete().eq("call_id", str(call_id)).execute()
        return True
    except Exception as exc:
        logger.debug("clear_call: %s", exc)
        return False
