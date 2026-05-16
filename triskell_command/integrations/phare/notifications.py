"""Notifications Le Phare — mail + push web pour Jordan.

Branché dans `orchestrator.py` après l'insertion d'actions importantes :
  - run_analyst        → bulletin matinal de l'Analyste
  - run_onpage_optim   → modif HTML soumise en validation
  - merge_action       → modif refusée (notif si rejet automatique)

Canaux :
  - Push web (VAPID) via triskell_command.web.push.send_push
  - Mail SMTP via triskell_core.prospect.outreach.smtp_sender.send_email

Préférences lues dans `shared_settings.phare_config` :
  - notify_push_enabled (bool, défaut True)
  - notify_mail_enabled (bool, défaut True)
  - notify_email        (str, défaut jordan@triskell-studio.fr)
  - notify_user_id      (str, défaut "jordan" — utilisé pour cibler les
                         subscriptions push)

Tout échoue gracieusement : aucune notif ne casse jamais le tick scheduler.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from . import repo

logger = logging.getLogger(__name__)


DEFAULT_EMAIL = "contact@triskell-studio.fr"
DEFAULT_USER_ID = "jordan"


def _prefs() -> dict:
    """Renvoie les préférences notif (avec valeurs par défaut)."""
    cfg = repo.get_config() or {}
    return {
        "push_enabled": bool(cfg.get("notify_push_enabled", True)),
        "mail_enabled": bool(cfg.get("notify_mail_enabled", True)),
        "email": (cfg.get("notify_email") or DEFAULT_EMAIL).strip(),
        "user_id": (cfg.get("notify_user_id") or DEFAULT_USER_ID).strip(),
    }


# ---------------------------------------------------------------------------
# Canal 1 : push web
# ---------------------------------------------------------------------------
def _send_push(title: str, body: str, *, url: str, tag_group: str,
               priority: str = "normal", user_id: str = DEFAULT_USER_ID) -> dict:
    try:
        from triskell_command.web import push
    except ImportError as exc:
        logger.debug("push module unavailable: %s", exc)
        return {"sent": 0, "error": "push_unavailable"}
    try:
        return push.send_push(
            title=title, body=body,
            user_id=user_id, url=url,
            tag_group=tag_group, priority=priority,
        )
    except Exception as exc:
        logger.warning("send_push failed: %s", exc)
        return {"sent": 0, "error": str(exc)}


# ---------------------------------------------------------------------------
# Canal 2 : mail SMTP
# ---------------------------------------------------------------------------
def _send_mail(to: str, subject: str, body: str) -> dict:
    """Envoie un mail simple via le compte SMTP partagé Supabase."""
    sb = repo._sb()
    if sb is None:
        return {"ok": False, "error": "supabase_unavailable"}
    try:
        # Lit la config SMTP depuis shared_settings
        rows = (sb.table("shared_settings").select("value")
                .eq("key", "outreach").limit(1).execute().data)
        if not rows:
            return {"ok": False, "error": "smtp_config_missing"}
        cfg = rows[0].get("value") or {}
        # Vérifie les champs critiques
        for k in ("smtp_host", "smtp_user", "smtp_password", "from_email"):
            if not cfg.get(k):
                return {"ok": False, "error": f"smtp_missing_{k}"}
    except Exception as exc:
        logger.warning("read smtp config: %s", exc)
        return {"ok": False, "error": str(exc)}

    try:
        from triskell_core.prospect.outreach.smtp_sender import send_email
    except ImportError as exc:
        return {"ok": False, "error": f"smtp_sender_unavailable: {exc}"}

    try:
        message_id = send_email(cfg, to=to, subject=subject, body=body)
        return {"ok": True, "message_id": message_id}
    except Exception as exc:
        logger.warning("send_email failed: %s", exc)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Helper : envoi sur les 2 canaux
# ---------------------------------------------------------------------------
def _notify(*, title: str, body_short: str, body_mail: str,
            url_path: str, tag_group: str, priority: str = "normal") -> dict:
    """Envoie push + mail selon les préférences. Renvoie un récap dict."""
    prefs = _prefs()
    result: dict[str, Any] = {"push": None, "mail": None}

    if prefs["push_enabled"]:
        result["push"] = _send_push(
            title=title, body=body_short,
            url=url_path, tag_group=tag_group,
            priority=priority, user_id=prefs["user_id"],
        )

    if prefs["mail_enabled"] and prefs["email"]:
        result["mail"] = _send_mail(
            to=prefs["email"],
            subject=title,
            body=body_mail,
        )

    return result


# ---------------------------------------------------------------------------
# Cas 1 — Bulletin de l'Analyste
# ---------------------------------------------------------------------------
def notify_bulletin(*, site: dict, bulletin: dict) -> dict:
    """Appelée après run_analyst quand un nouveau bulletin est produit."""
    site_name = site.get("name") or site.get("domain") or "ton site"
    trend = bulletin.get("trend") or ""
    summary = (bulletin.get("trend_summary_md") or "").strip()
    delta_clicks = bulletin.get("delta_clicks_30d_abs")
    delta_pct = bulletin.get("delta_clicks_30d_pct")

    # Titre court
    arrow = {"hausse": "↑", "baisse": "↓", "plateau": "→"}.get(trend, "•")
    title = f"📰 Bulletin {site_name} {arrow}"

    # Body push : 1-2 phrases
    if delta_clicks is not None:
        try:
            body_short = f"{delta_clicks:+d} clics sur 30 jours"
            if delta_pct is not None:
                body_short += f" ({delta_pct:+.0f}%)"
        except (TypeError, ValueError):
            body_short = summary[:140] if summary else "Nouveau bulletin disponible."
    else:
        body_short = summary[:140] if summary else "Nouveau bulletin disponible."

    # Body mail : version longue
    reco = bulletin.get("next_week_recommendation")
    reco_str = ""
    if isinstance(reco, dict):
        reco_str = reco.get("action") or ""
    elif isinstance(reco, str):
        reco_str = reco

    body_mail = (
        f"Bulletin SEO — {site_name}\n"
        f"{'=' * 50}\n\n"
        f"Tendance : {trend or 'inconnue'}\n"
    )
    if delta_clicks is not None:
        try:
            body_mail += f"Delta clics 30j : {delta_clicks:+d}"
            if delta_pct is not None:
                body_mail += f" ({delta_pct:+.0f}%)"
            body_mail += "\n"
        except Exception:
            pass
    body_mail += f"\n{summary}\n"
    if reco_str:
        body_mail += f"\nRecommandation : {reco_str}\n"
    body_mail += (
        "\n---\n"
        "Lire le bulletin complet sur :\n"
        "https://command.triskell-studio.fr/#phare\n"
    )

    return _notify(
        title=title,
        body_short=body_short,
        body_mail=body_mail,
        url_path="https://command.triskell-studio.fr/#phare",
        tag_group="phare-bulletin",
        priority="low",   # bulletin matinal = pas urgent
    )


# ---------------------------------------------------------------------------
# Cas 2 — Modification en attente de validation
# ---------------------------------------------------------------------------
def notify_pending_action(*, site: dict, action: dict) -> dict:
    """Appelée quand une modification est soumise et attend validation manuelle."""
    site_name = site.get("name") or site.get("domain") or "ton site"
    kind = action.get("kind") or "modification"
    action_title = action.get("title") or kind

    title = f"⚠️ Modif à valider — {site_name}"
    body_short = action_title[:140]

    body_mail = (
        f"Une modification attend ta validation\n"
        f"{'=' * 50}\n\n"
        f"Site    : {site_name}\n"
        f"Type    : {kind}\n"
        f"Détail  : {action_title}\n\n"
        f"{(action.get('detail_md') or '').strip()}\n\n"
        "---\n"
        "Valider ou refuser sur :\n"
        "https://command.triskell-studio.fr/#phare → À valider\n"
    )

    return _notify(
        title=title,
        body_short=body_short,
        body_mail=body_mail,
        url_path="https://command.triskell-studio.fr/#phare",
        tag_group="phare-pending",
        priority="normal",
    )
