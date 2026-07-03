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
import os
from datetime import datetime
from typing import Any, Optional

from . import repo

logger = logging.getLogger(__name__)


DEFAULT_EMAIL = "contact@triskell-studio.fr"
DEFAULT_USER_ID = "jordan"

# Garde-fou « vrai robot seulement » : le récap quotidien des publications ne
# doit être alimenté/envoyé QUE par un processus de production (serveur web,
# tick GitHub Actions), qui pose PHARE_REAL_RUN=1 au démarrage. Sans ce
# marqueur, on ne touche à RIEN : les batteries de tests et les essais locaux
# parlent à la VRAIE base (machine locale = prod) et ont déjà rempli deux fois
# le récap avec des corrections fictives (mails « 49 » du 02/07 et « 23 » du
# 03/07 — pages de test /realisations). Le stub du smoke ne suffisait pas :
# tout script qui importe l'exécuteur en direct contournait la protection.
REAL_RUN_ENV = "PHARE_REAL_RUN"


def _is_real_run() -> bool:
    return os.environ.get(REAL_RUN_ENV) == "1"

# Récap quotidien des publications automatiques (« publié tout seul ») :
# au lieu d'un mail par correction, on empile les publications du jour dans
# cette clé shared_settings, et le scheduler envoie UN seul mail groupé par
# jour (flush_auto_merged_digest). Plafond pour borner la taille du buffer.
DIGEST_KEY = "phare_automerge_digest"
MAX_DIGEST_ITEMS = 500


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
    except Exception as exc:
        logger.warning("send_email failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    # Log dans l'historique pour apparaître dans la vue « Mails envoyés »
    try:
        from ..email_history_log import log_sent_pipeline_mail
        log_sent_pipeline_mail(
            to=to,
            subject=subject,
            body=body,
            from_email=cfg.get("from_email", "") if isinstance(cfg, dict) else "",
            message_id=message_id or "",
            source="phare_alert",
        )
    except Exception as exc:
        logger.debug("phare.notifications: log_sent_pipeline_mail KO : %s", exc)
    return {"ok": True, "message_id": message_id}


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
# Cas 2 — Publication automatique (« publié tout seul ») → récap quotidien
#
# Avant : 1 push + 1 mail PAR correction publiée → la boîte de Jordan était
# noyée, et chaque mail partait depuis/vers contact@triskell-studio.fr (donc
# comptait dans les « mails envoyés » et grignotait le quota d'envoi de cette
# boîte). Depuis le 18/06/2026 (choix de Jordan) : on empile les publications
# de la journée et le scheduler envoie UN SEUL mail récapitulatif en fin de
# journée (flush_auto_merged_digest). Plus de push individuelle.
# ---------------------------------------------------------------------------
def _read_digest() -> list[dict]:
    """Publications auto en attente de récap (clé shared_settings dédiée)."""
    sb = repo._sb()
    if sb is None:
        return []
    try:
        rows = (sb.table("shared_settings").select("value")
                .eq("key", DIGEST_KEY).limit(1).execute().data)
        if not rows:
            return []
        val = rows[0].get("value") or {}
        items = val.get("items") if isinstance(val, dict) else None
        return items if isinstance(items, list) else []
    except Exception as exc:
        logger.debug("phare digest read: %s", exc)
        return []


def _write_digest(items: list[dict]) -> bool:
    sb = repo._sb()
    if sb is None:
        return False
    try:
        from ..shared_settings_db import upsert_setting
        return upsert_setting(sb, DIGEST_KEY,
                              {"items": items[-MAX_DIGEST_ITEMS:]})
    except Exception as exc:
        logger.debug("phare digest write: %s", exc)
        return False


def notify_auto_merged(*, site: dict, action: dict) -> dict:
    """Empile une publication auto dans le récap quotidien (AUCUN envoi ici).

    Le mail groupé part une fois par jour via flush_auto_merged_digest(),
    déclenché par le scheduler. Jordan reste informé (transparence) sans être
    noyé sous un mail par correction."""
    if not _is_real_run():
        logger.info("notify_auto_merged ignoré (pas un vrai run — "
                    "poser %s=1 pour un robot de production)", REAL_RUN_ENV)
        return {"buffered": False, "skipped": "not_real_run"}
    site_name = site.get("name") or site.get("domain") or "ton site"
    action_title = action.get("title") or "modification SEO"
    try:
        items = _read_digest()
        items.append({
            "site": site_name,
            "title": action_title[:200],
            "at": datetime.now().isoformat(timespec="seconds"),
        })
        _write_digest(items)
        return {"buffered": True, "pending": len(items)}
    except Exception as exc:
        logger.debug("notify_auto_merged buffer: %s", exc)
        return {"buffered": False, "error": str(exc)}


def flush_auto_merged_digest() -> dict:
    """Envoie UN mail récap de toutes les publications auto accumulées, puis
    vide le buffer. Appelé 1×/jour par le scheduler. N'envoie RIEN (et ne
    touche à rien) si le buffer est vide : pas de mail inutile."""
    if not _is_real_run():
        logger.info("flush_auto_merged_digest ignoré (pas un vrai run)")
        return {"ok": True, "sent": False, "reason": "not_real_run"}
    items = _read_digest()
    if not items:
        return {"ok": True, "sent": False, "reason": "empty"}

    n = len(items)
    plural = "s" if n > 1 else ""
    by_site: dict[str, list[str]] = {}
    for it in items:
        by_site.setdefault(it.get("site") or "ton site", []).append(
            it.get("title") or "modification SEO")

    title = f"✅ Le Phare — {n} correction{plural} publiée{plural} aujourd'hui"

    lines = [
        f"Le Phare a publié {n} correction{plural} tout seul aujourd'hui.",
        "=" * 50,
        "",
        "Tu n'as rien à faire : toutes les vérifications sont passées "
        "(vitesse, rendu, liens) et la surveillance reste active 14 jours.",
        "",
    ]
    for site_name in sorted(by_site):
        titles = by_site[site_name]
        s = "s" if len(titles) > 1 else ""
        lines.append(f"{site_name} — {len(titles)} correction{s} :")
        for t in titles:
            lines.append(f"    - {t}")
        lines.append("")
    lines += [
        "---",
        "Le détail est dans l'écran Le Phare, rubrique « Ce qui a été fait ».",
        "https://command.triskell-studio.fr/#phare",
    ]
    body_mail = "\n".join(lines)

    prefs = _prefs()
    mail_wanted = bool(prefs["mail_enabled"] and prefs["email"])
    mail_res = None
    sent = False
    if mail_wanted:
        mail_res = _send_mail(to=prefs["email"], subject=title, body=body_mail)
        sent = bool(mail_res and mail_res.get("ok"))

    # On vide le buffer si le mail est parti, OU si le mail est désactivé
    # (sinon le buffer gonflerait sans fin). En cas d'échec SMTP ponctuel, on
    # garde le buffer pour retenter au prochain passage quotidien.
    if sent or not mail_wanted:
        _write_digest([])

    return {"ok": True, "sent": sent, "count": n, "mail": mail_res}


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
