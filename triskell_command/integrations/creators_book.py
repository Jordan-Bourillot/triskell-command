"""Carnet des créateurs contactés — table dédiée `public.contacted_creators`.

Volontairement SÉPARÉ du vivier de prospection (`prospects`) : pas de règle
« mail obligatoire », pas de dédoublonnage, pas de relances mail. C'est un
simple carnet manuel des créateurs qu'on démarche par réseaux sociaux.

Réutilise la connexion Supabase d'Obélisk (clé service en prod, sinon session
utilisateur).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from .obelisk.repo import _sb  # même client Supabase que le reste de l'app

logger = logging.getLogger(__name__)

TABLE = "contacted_creators"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(fields: dict) -> dict:
    """Ne garde que les champs connus, nettoyés. Ignore le reste."""
    f = fields or {}
    out: dict = {}
    if "name" in f:
        out["name"] = (f.get("name") or "").strip()[:300]
    for k in ("platform", "handle", "demo_url"):
        if k in f:
            out[k] = (f.get(k) or "").strip()[:2000]
    if "message" in f:
        out["message"] = (f.get("message") or "").strip()[:20000]
    if "notes" in f:
        out["notes"] = (f.get("notes") or "").strip()[:20000]
    for k in ("contacted_at", "next_follow_up_at", "unsubscribed_at"):
        if k in f:
            v = f.get(k)
            if isinstance(v, str):
                out[k] = v.strip() or None
            else:
                out[k] = v or None
    return out


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _emails_in(text: str) -> set[str]:
    return {m.lower() for m in _EMAIL_RE.findall(text or "")}


def is_unsubscribed(row: dict) -> bool:
    """Vrai si ce créateur s'est désinscrit (colonne `unsubscribed_at` posée).
    Faux si la colonne n'existe pas encore (migration 54 non appliquée)."""
    return bool((row or {}).get("unsubscribed_at"))


def mark_unsubscribed_by_email(email: str) -> int:
    """Marque tout créateur du carnet dont l'adresse correspond à `email`
    (le `handle` s'il EST l'adresse, ou une adresse citée dans les notes).

    Idempotent (un déjà-désinscrit n'est pas recompté). TOLÉRANT si la colonne
    `unsubscribed_at` n'existe pas encore (migration 54) : logge et renvoie 0
    sans jamais casser le clic de désinscription. Renvoie le nombre de fiches
    nouvellement marquées.
    """
    sb = _sb()
    if sb is None:
        return 0
    addr = (email or "").strip().lower()
    if "@" not in addr:
        return 0
    try:
        by_handle = (sb.table(TABLE)
                     .select("id,handle,notes,unsubscribed_at")
                     .ilike("handle", addr).execute().data) or []
        by_notes = (sb.table(TABLE)
                    .select("id,handle,notes,unsubscribed_at")
                    .ilike("notes", f"%{addr}%").execute().data) or []
    except Exception as exc:
        logger.warning("creators_book.mark_unsubscribed_by_email search: %s",
                       exc)
        return 0
    seen: set = set()
    count = 0
    for r in (by_handle + by_notes):
        rid = r.get("id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        # Correspondance PRÉCISE : handle == adresse, OU adresse exacte dans
        # les notes (le %like% seul pourrait matcher une sous-chaîne d'une
        # AUTRE adresse — ex. « jo@x.com » dans « bjo@x.com »).
        handle_ok = (r.get("handle") or "").strip().lower() == addr
        notes_ok = addr in _emails_in(r.get("notes") or "")
        if not (handle_ok or notes_ok):
            continue
        if r.get("unsubscribed_at"):
            continue  # déjà désinscrit
        try:
            sb.table(TABLE).update(
                {"unsubscribed_at": _now_iso()}).eq("id", rid).execute()
            count += 1
        except Exception as exc:
            # Colonne absente (migration 54 non appliquée) → dégradé propre.
            logger.warning("creators_book.mark_unsubscribed update %s: %s",
                           rid, exc)
    return count


def list_all(*, relance: bool = False, limit: int = 300) -> dict:
    """Liste les créateurs du carnet.

    relance=True → uniquement ceux « à relancer » : une date de relance est
    posée et elle est échue (<= maintenant). Triés du plus en retard au moins.
    Sinon : les plus récemment ajoutés d'abord.
    """
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Base non connectée", "rows": [], "count": 0}
    try:
        qy = sb.table(TABLE).select("*", count="exact")
        if relance:
            qy = (qy.not_.is_("next_follow_up_at", "null")
                    .lte("next_follow_up_at", _now_iso())
                    .order("next_follow_up_at", desc=False))
        else:
            qy = qy.order("created_at", desc=True)
        res = qy.limit(int(limit)).execute()
        rows = res.data or []
        return {"ok": True, "rows": rows,
                "count": getattr(res, "count", None) or len(rows)}
    except Exception as exc:
        logger.warning("creators_book.list_all: %s", exc)
        return {"ok": False, "error": str(exc), "rows": [], "count": 0}


def get_one(cid: str) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Base non connectée"}
    cid = (cid or "").strip()
    if not cid:
        return {"ok": False, "error": "id requis"}
    try:
        res = sb.table(TABLE).select("*").eq("id", cid).limit(1).execute()
        rows = res.data or []
        if not rows:
            return {"ok": False, "error": "introuvable"}
        return {"ok": True, "row": rows[0]}
    except Exception as exc:
        logger.warning("creators_book.get_one: %s", exc)
        return {"ok": False, "error": str(exc)}


def save(fields: dict) -> dict:
    """Crée (sans id) ou met à jour (avec id) un créateur du carnet."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Base non connectée"}
    f = fields or {}
    cid = (f.get("id") or "").strip()
    data = _clean(f)
    data["updated_at"] = _now_iso()
    try:
        if cid:
            if len(data) <= 1:  # rien à part updated_at
                return {"ok": False, "error": "aucun champ à mettre à jour"}
            sb.table(TABLE).update(data).eq("id", cid).execute()
            return {"ok": True, "id": cid, "action": "updated"}
        if not data.get("name"):
            return {"ok": False, "error": "Le nom est obligatoire."}
        res = sb.table(TABLE).insert(data).execute()
        new_id = (res.data or [{}])[0].get("id", "")
        return {"ok": True, "id": new_id, "action": "created"}
    except Exception as exc:
        logger.warning("creators_book.save: %s", exc)
        return {"ok": False, "error": str(exc)}


def delete(cid: str) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Base non connectée"}
    cid = (cid or "").strip()
    if not cid:
        return {"ok": False, "error": "id requis"}
    try:
        sb.table(TABLE).delete().eq("id", cid).execute()
        return {"ok": True}
    except Exception as exc:
        logger.warning("creators_book.delete: %s", exc)
        return {"ok": False, "error": str(exc)}
