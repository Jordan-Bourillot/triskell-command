"""Garde-fous centraux du systeme de mail.

Source de verite pour repondre a la question : a-t-on le droit d'envoyer un
mail a ce prospect maintenant ?

Centralise :
- les statuts "definitivement plus de mails" (RGPD) : refused, unsubscribed,
  bounced (en plus de won/lost qui sont des fin de cycle business).
- le marquage "unsubscribe" et "bounced" + miroir dans email_history pour
  audit.
- l'anti-doublon : a-t-on deja mail le prospect dans les N dernieres heures
  depuis n'importe quel runner ?
- la verification de variables non remplacees (du style {name}, {{name}})
  dans subject + body avant envoi.

TOUS les runners (convoy, drip, dormant_recycler, multichannel, morning_mailer,
reply_responder) DOIVENT passer par should_contact() avant chaque envoi.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


# --- Statuts qui interdisent definitivement de remailer ---
# - won/lost : cycle business termine
# - refused : prospect a dit "non" ou "stop" explicitement
# - unsubscribed : prospect a demande la desinscription (legal RGPD)
# - bounced : adresse morte, on degrade notre reputation si on continue
NO_CONTACT_STATUSES = frozenset({
    "won", "lost", "refused", "unsubscribed", "bounced",
})

# --- Statuts "a en parle bientot mais pas tout de suite" ---
# 'replied' = a repondu mais on n'a pas encore traite. Les runners
# automatiques NE DOIVENT PAS mailer un prospect "replied" (laisser l'humain
# repondre d'abord). Mais ce n'est pas un statut definitif.
SOFT_PAUSE_STATUSES = frozenset({"replied"})


# Helpers d'auto-detection des bounces (sender + sujet typique de DSN)
BOUNCE_SENDERS = (
    "mailer-daemon@", "postmaster@", "mail-daemon@", "noreply-",
    "bounce@", "bounces@", "delivery@",
)
BOUNCE_SUBJECTS = (
    "delivery status notification",
    "delivery failure",
    "delivery failed",
    "delivery has failed",
    "mail delivery failed",
    "mail delivery failure",
    "mail delivery problem",
    "undelivered mail",
    "undeliverable",
    "returned mail",
    "could not be delivered",
    "ne peut etre delivre",
    "n'a pas pu etre livre",
    "n'a pas pu etre delivre",
    "echec de livraison",
    "echec de remise",
    "echec de la remise",
    "non remis",
    "non distribue",
)
# Regex emails dans le body d'un DSN — on extrait l'adresse de la victime
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Regex variables non remplacees a refuser dans un mail final
# - {name} ou {{name}} : python format / mustache
# - %name% : encore d'autres systemes
# On exclut les caracteres d'espace dans le nom pour eviter de matcher du
# code source ou des accolades JSON valides en HTML.
_UNRENDERED_VAR_RE = re.compile(
    r"(?<!\\)(\{\{?[A-Za-z_][A-Za-z0-9_.]*\}?\}|%[A-Za-z_][A-Za-z0-9_]*%)"
)


# =============================================================================
# Statut prospect : lecture + transitions
# =============================================================================
def get_status(client, prospect_id: str) -> str:
    """Renvoie le statut courant du prospect (lower), ou '' si introuvable."""
    if not prospect_id:
        return ""
    try:
        res = (client.raw.table("prospects").select("status")
               .eq("id", prospect_id).limit(1).execute())
        return ((res.data or [{}])[0].get("status") or "").lower()
    except Exception as exc:
        logger.debug("get_status: %s", exc)
        return ""


def is_no_contact(status: str) -> bool:
    """Faut-il refuser tout nouvel envoi a ce prospect ?"""
    return (status or "").lower() in NO_CONTACT_STATUSES


def mark_unsubscribed(client, prospect_id: str, reason: str = "") -> None:
    """Passe un prospect en 'unsubscribed' definitivement. RGPD."""
    if not prospect_id:
        return
    try:
        client.raw.table("prospects").update({
            "status": "unsubscribed",
            "last_contact_at": datetime.now().isoformat(timespec="seconds"),
            "updated_by": client.user_id,
        }).eq("id", prospect_id).execute()
        _audit("unsubscribed", client, prospect_id, reason)
    except Exception as exc:
        logger.warning("mark_unsubscribed KO: %s", exc)


def mark_refused(client, prospect_id: str, reason: str = "") -> None:
    """Passe en 'refused' (prospect a dit non clairement)."""
    if not prospect_id:
        return
    try:
        client.raw.table("prospects").update({
            "status": "refused",
            "last_contact_at": datetime.now().isoformat(timespec="seconds"),
            "updated_by": client.user_id,
        }).eq("id", prospect_id).execute()
        _audit("refused", client, prospect_id, reason)
    except Exception as exc:
        logger.warning("mark_refused KO: %s", exc)


def mark_bounced(client, prospect_id: str, bounced_address: str = "",
                  reason: str = "") -> None:
    """Passe en 'bounced' : adresse morte, on ne tape plus dedans."""
    if not prospect_id:
        return
    try:
        client.raw.table("prospects").update({
            "status": "bounced",
            "last_contact_at": datetime.now().isoformat(timespec="seconds"),
            "updated_by": client.user_id,
        }).eq("id", prospect_id).execute()
        _audit("bounced", client, prospect_id,
               (reason or "") + (f" addr={bounced_address}" if bounced_address else ""))
    except Exception as exc:
        logger.warning("mark_bounced KO: %s", exc)


def _audit(kind: str, client, prospect_id: str, reason: str) -> None:
    """Trace l'evenement dans email_history (best-effort)."""
    try:
        client.raw.table("email_history").insert({
            "prospect_id": prospect_id,
            "kind": f"status_{kind}",
            "ts": datetime.now().isoformat(timespec="seconds"),
            "subject": f"[auto] prospect marque {kind}",
            "body": "",
            "extra": {"reason": (reason or "")[:500], "auto": True},
            "created_by": client.user_id,
        }).execute()
    except Exception as exc:
        logger.debug("audit %s KO: %s", kind, exc)


# =============================================================================
# Detection des bounces (DSN) dans la boite de reception
# =============================================================================
def looks_like_bounce(from_addr: str, subject: str) -> bool:
    """Heuristique : ce mail entrant est-il un avis de non-delivrance ?"""
    f = (from_addr or "").lower()
    s = (subject or "").lower()
    if any(f.startswith(sender) or f"<{sender}" in f
           for sender in BOUNCE_SENDERS):
        return True
    return any(needle in s for needle in BOUNCE_SUBJECTS)


def extract_bounced_address(body: str, exclude: str = "") -> str:
    """Cherche dans le body du DSN une adresse mail (autre que l'expediteur
    du DSN, generalement nous-meme) qui est la victime du bounce."""
    if not body:
        return ""
    excl = (exclude or "").lower()
    for m in _EMAIL_RE.finditer(body):
        addr = m.group(0).lower()
        if excl and addr == excl:
            continue
        # Skip noreply/postmaster/mailer-daemon dans le body aussi
        if any(addr.startswith(p.replace("@", "")) or p in addr
               for p in BOUNCE_SENDERS):
            continue
        return addr
    return ""


# =============================================================================
# Anti-doublon : a-t-on deja mail ce prospect recemment ?
# =============================================================================
def has_recent_send(client, *, prospect_id: str = "", email: str = "",
                     hours: int = 48) -> dict:
    """Renvoie {"recent": bool, "last_ts": str, "last_kind": str}.

    Considere TOUS les envois (campagnes, drip, dormant, manuels, reponses
    auto) — si un mail est parti vers ce prospect/email dans les `hours`
    dernieres heures, on bloque tout nouvel envoi automatique.
    """
    if not (prospect_id or email):
        return {"recent": False, "last_ts": "", "last_kind": ""}
    sb = client.raw
    threshold = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        q = (sb.table("email_history").select("ts,kind,extra,subject")
             .eq("kind", "email_sent")
             .gte("ts", threshold)
             .order("ts", desc=True).limit(1))
        if prospect_id:
            q = q.eq("prospect_id", prospect_id)
        res = q.execute()
        rows = res.data or []
        # Si on a un prospect_id, on a deja filtre. Sinon, filtrer par email
        # dans extra.to.
        if not prospect_id and email:
            email_low = email.lower()
            filtered = []
            for r in rows:
                extra = r.get("extra") or {}
                if isinstance(extra, str):
                    try:
                        import json as _json
                        extra = _json.loads(extra)
                    except Exception:
                        extra = {}
                tos = extra.get("to") or extra.get("recipients") or []
                if isinstance(tos, str):
                    tos = [tos]
                if any((t or "").lower() == email_low for t in tos):
                    filtered.append(r)
            rows = filtered
        if rows:
            r = rows[0]
            return {"recent": True, "last_ts": r.get("ts", ""),
                    "last_kind": r.get("kind", "")}
    except Exception as exc:
        logger.debug("has_recent_send: %s", exc)
    return {"recent": False, "last_ts": "", "last_kind": ""}


# =============================================================================
# Decision globale : peut-on contacter ce prospect maintenant ?
# =============================================================================
def should_contact(client, prospect_id: str, *, email: str = "",
                    min_hours_between: int = 48,
                    allow_replied: bool = False) -> dict:
    """Decision centrale : OK ou KO pour envoyer un mail ?

    Renvoie : {"ok": bool, "reason": str}.
    - KO si status in NO_CONTACT (refused/unsubscribed/bounced/won/lost)
    - KO si status='replied' et allow_replied=False (sauf reponse manuelle
      qu'on autorise via allow_replied)
    - KO si un envoi vers ce prospect a deja eu lieu dans les min_hours
      dernieres heures
    - OK sinon
    """
    status = get_status(client, prospect_id) if prospect_id else ""
    if is_no_contact(status):
        return {"ok": False, "reason": f"status:{status}"}
    if status in SOFT_PAUSE_STATUSES and not allow_replied:
        return {"ok": False, "reason": f"status:{status}"}
    recent = has_recent_send(client, prospect_id=prospect_id, email=email,
                              hours=min_hours_between)
    if recent.get("recent"):
        return {"ok": False, "reason": f"recent_send:{recent.get('last_ts')}"}
    return {"ok": True, "reason": ""}


# =============================================================================
# Variables non remplacees dans un mail
# =============================================================================
def find_unrendered_vars(*texts: str) -> list[str]:
    """Detecte les marqueurs non remplaces dans subject/body. Renvoie la
    liste des fragments {x}/{{x}}/%x% trouves. Vide = mail propre."""
    found: list[str] = []
    for t in texts:
        if not t:
            continue
        for m in _UNRENDERED_VAR_RE.finditer(t):
            found.append(m.group(0))
    return found


def mail_is_safe_to_send(subject: str, body: str) -> dict:
    """Renvoie {"ok": bool, "unrendered": [...]}.
    Ne PAS envoyer si unrendered non vide."""
    bad = find_unrendered_vars(subject or "", body or "")
    return {"ok": not bad, "unrendered": bad}
