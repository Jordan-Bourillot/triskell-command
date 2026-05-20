"""Envoi des mails transactionnels Pixel Pros.

Deux mails :
- send_paid_mail(intake)  : envoyé juste après que Stripe a confirmé le paiement.
- send_live_mail(intake)  : envoyé quand le site est en ligne sur {slug}.pixel-pros.fr.

Le SMTP est lu depuis shared_settings.smtp_config (la même que morning_mailer) ;
si Jordan a configuré un compte mail dédié Pixel Pros dans shared_settings.smtp_pixel_pros,
on l'utilise en priorité (l'expéditeur du mail sera contact@pixel-pros.fr).

Templates éditables :
- Les mails par défaut sont définis dans ce fichier (DEFAULT_PAID / DEFAULT_LIVE).
- Si Jordan modifie un mail depuis l'UI, l'override est stocké dans
  shared_settings sous les clés `pixelpros_mail_paid` / `pixelpros_mail_live`
  (JSON {subject, body_text, body_html}).
- À l'envoi, on lit l'override en priorité, fallback sur le défaut.
- Placeholders supportés : {firstname}, {business}, {site_url}.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Clés de stockage et templates par défaut
# ---------------------------------------------------------------------------
TEMPLATE_KEYS = {
    "paid": "pixelpros_mail_paid",
    "live": "pixelpros_mail_live",
}

DEFAULT_PAID = {
    "subject": "On a bien reçu ton paiement — ton site Pixel Pros arrive sous 24h",
    "body_text": (
        "Salut {firstname},\n\n"
        "On a bien reçu ton paiement, c'est parti pour la fabrication de ton site Pixel Pros{business_paren}.\n\n"
        "Voilà ce qu'il se passe maintenant :\n"
        "  1. On reprend toutes tes infos et tes photos\n"
        "  2. On rédige les textes et on monte le site\n"
        "  3. On le met en ligne sur ton adresse perso\n"
        "  4. Tu reçois un mail dès qu'il est dispo (sous 24h ouvrées)\n\n"
        "Si tu as oublié quelque chose ou si tu veux ajouter une info, réponds simplement à ce mail.\n\n"
        "À très vite,\n"
        "L'équipe Pixel Pros\n"
        "https://pixel-pros.fr"
    ),
    "body_html": (
        "<!doctype html>\n"
        "<html lang=\"fr\"><body style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height:1.55; color:#1a1a1a; max-width:560px; margin:0 auto; padding:24px;\">\n"
        "<div style=\"background:#facc15; color:#0f172a; padding:18px 22px; border-radius:12px 12px 0 0; font-weight:800; font-size:18px;\">✓ Paiement reçu</div>\n"
        "<div style=\"background:#fff8e1; padding:24px 22px; border-radius:0 0 12px 12px; border:1px solid #facc15; border-top:none;\">\n"
        "  <p style=\"margin:0 0 14px;\">Salut <strong>{firstname}</strong>,</p>\n"
        "  <p style=\"margin:0 0 14px;\">On a bien reçu ton paiement, c'est parti pour la fabrication de ton site Pixel Pros{business_html_strong}.</p>\n"
        "  <p style=\"margin:0 0 8px; font-weight:700;\">Voilà ce qu'il se passe maintenant :</p>\n"
        "  <ol style=\"margin:0 0 14px; padding-left:22px;\">\n"
        "    <li>On reprend toutes tes infos et tes photos</li>\n"
        "    <li>On rédige les textes et on monte le site</li>\n"
        "    <li>On le met en ligne sur ton adresse perso</li>\n"
        "    <li>Tu reçois un mail dès qu'il est dispo (sous 24h ouvrées)</li>\n"
        "  </ol>\n"
        "  <p style=\"margin:0 0 14px;\">Si tu as oublié quelque chose ou si tu veux ajouter une info, réponds simplement à ce mail.</p>\n"
        "  <p style=\"margin:0 0 4px;\">À très vite,</p>\n"
        "  <p style=\"margin:0;\"><strong>L'équipe Pixel Pros</strong><br><a href=\"https://pixel-pros.fr\" style=\"color:#0f172a;\">pixel-pros.fr</a></p>\n"
        "</div>\n"
        "</body></html>"
    ),
}

DEFAULT_LIVE = {
    "subject": "🎉 Ton site Pixel Pros est en ligne !",
    "body_text": (
        "Salut {firstname},\n\n"
        "Ton site{business_space} est en ligne, tu peux le voir tout de suite ici :\n\n"
        "  {site_url}\n\n"
        "Si tu vois un truc à changer (texte, photo, couleur, n'importe quoi), tu réponds à ce mail\n"
        "et on s'en occupe — les modifs sont incluses dans ton abonnement.\n\n"
        "🎁 Petit cadeau de bienvenue : Carnet\n"
        "On t'offre Carnet, notre outil pour faire tes devis et tes factures en deux clics depuis ton téléphone.\n"
        "Aucune installation, aucun compte à créer, c'est dans ton navigateur :\n\n"
        "  https://carnet-pro-fr.netlify.app\n\n"
        "Quelques petits conseils pour démarrer :\n"
        "  • Partage le lien à tes proches et tes clients\n"
        "  • Ajoute-le sur Google Business, Instagram, ta signature mail\n"
        "  • Si tu n'as pas pris le pack TOUT-EN-UN et que tu veux ton propre nom de domaine, on peut l'ajouter à tout moment\n\n"
        "À très vite,\n"
        "L'équipe Pixel Pros\n"
        "https://pixel-pros.fr"
    ),
    "body_html": (
        "<!doctype html>\n"
        "<html lang=\"fr\"><body style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height:1.55; color:#1a1a1a; max-width:560px; margin:0 auto; padding:24px;\">\n"
        "<div style=\"background:#22c55e; color:#fff; padding:18px 22px; border-radius:12px 12px 0 0; font-weight:800; font-size:18px;\">🎉 Ton site est en ligne !</div>\n"
        "<div style=\"background:#fff8e1; padding:24px 22px; border-radius:0 0 12px 12px; border:1px solid #facc15; border-top:none;\">\n"
        "  <p style=\"margin:0 0 14px;\">Salut <strong>{firstname}</strong>,</p>\n"
        "  <p style=\"margin:0 0 18px;\">Ton site{business_html_strong} est en ligne, tu peux le voir tout de suite :</p>\n"
        "  <p style=\"text-align:center; margin:0 0 20px;\">\n"
        "    <a href=\"{site_url}\" style=\"display:inline-block; background:#facc15; color:#0f172a; font-weight:800; padding:14px 28px; border-radius:10px; text-decoration:none; font-size:15px;\">▶ Voir mon site</a>\n"
        "  </p>\n"
        "  <p style=\"margin:0 0 14px; font-size:13px; color:#64748b; text-align:center;\"><code style=\"background:#fff; padding:4px 8px; border-radius:4px;\">{site_url}</code></p>\n"
        "  <div style=\"background:#effaf3; border:1px solid #2d8559; border-radius:12px; padding:18px 20px; margin:18px 0;\">\n"
        "    <p style=\"margin:0 0 8px; font-weight:800; color:#1f5a3c; font-size:15px;\">🎁 Ton cadeau de bienvenue : Carnet</p>\n"
        "    <p style=\"margin:0 0 14px; color:#1f5a3c;\">On t'offre <strong>Carnet</strong>, notre outil pour faire tes <strong>devis et factures</strong> en deux clics depuis ton téléphone. Aucune installation, aucun compte à créer.</p>\n"
        "    <p style=\"text-align:center; margin:0;\">\n"
        "      <a href=\"https://carnet-pro-fr.netlify.app\" style=\"display:inline-block; background:#2d8559; color:#fff; font-weight:700; padding:12px 24px; border-radius:10px; text-decoration:none; font-size:14px;\">📓 Ouvrir mon Carnet</a>\n"
        "    </p>\n"
        "  </div>\n"
        "  <p style=\"margin:0 0 8px; font-weight:700;\">Quelques conseils pour démarrer :</p>\n"
        "  <ul style=\"margin:0 0 14px; padding-left:22px;\">\n"
        "    <li>Partage le lien à tes proches et tes clients</li>\n"
        "    <li>Ajoute-le sur Google Business, Instagram, ta signature mail</li>\n"
        "    <li>Si tu n'as pas pris le pack TOUT-EN-UN et que tu veux ton propre nom de domaine, on peut l'ajouter à tout moment</li>\n"
        "  </ul>\n"
        "  <p style=\"margin:0 0 14px;\">Tu vois un truc à changer (texte, photo, couleur) ? <strong>Tu réponds à ce mail</strong> et on s'en occupe — les modifs sont incluses dans ton abonnement.</p>\n"
        "  <p style=\"margin:0 0 4px;\">À très vite,</p>\n"
        "  <p style=\"margin:0;\"><strong>L'équipe Pixel Pros</strong><br><a href=\"https://pixel-pros.fr\" style=\"color:#0f172a;\">pixel-pros.fr</a></p>\n"
        "</div>\n"
        "</body></html>"
    ),
}

DEFAULTS = {"paid": DEFAULT_PAID, "live": DEFAULT_LIVE}


def _get_supabase():
    """Renvoie le client Supabase authentifié ou None."""
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None
    try:
        c = get_client()
    except SupabaseNotConfigured:
        return None
    if not c.is_authenticated:
        return None
    return c


def load_template(kind: str) -> dict:
    """Renvoie le template pour 'paid' ou 'live'.

    Lit d'abord l'override dans shared_settings, fallback sur le défaut.
    Le dict renvoyé a aussi un champ `is_custom` (bool) pour que l'UI
    sache si Jordan a modifié ou pas.
    """
    if kind not in DEFAULTS:
        raise ValueError(f"kind invalide : {kind}")
    default = dict(DEFAULTS[kind])
    default["is_custom"] = False

    c = _get_supabase()
    if c is None:
        return default

    try:
        override = c.get_shared_setting(TEMPLATE_KEYS[kind], default=None)
    except Exception as exc:
        logger.debug("pixelpros.mailer.load_template: %s", exc)
        return default

    if not isinstance(override, dict):
        return default

    # Champs obligatoires : si l'un manque, on prend la valeur défaut
    out = dict(default)
    out["is_custom"] = True
    for key in ("subject", "body_text", "body_html"):
        if override.get(key):
            out[key] = override[key]
    return out


def save_template(kind: str, subject: str, body_text: str, body_html: str) -> tuple[bool, str]:
    """Enregistre un override dans shared_settings."""
    if kind not in TEMPLATE_KEYS:
        return False, f"kind invalide : {kind}"
    if not subject or not (body_text or body_html):
        return False, "Sujet + au moins un corps (texte ou HTML) requis."
    c = _get_supabase()
    if c is None:
        return False, "Supabase non configuré ou non authentifié."
    try:
        c.set_shared_setting(TEMPLATE_KEYS[kind], {
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
        })
        return True, "Mail sauvegardé."
    except Exception as exc:
        return False, str(exc)


def reset_template(kind: str) -> tuple[bool, str]:
    """Supprime l'override et revient au défaut."""
    if kind not in TEMPLATE_KEYS:
        return False, f"kind invalide : {kind}"
    c = _get_supabase()
    if c is None:
        return False, "Supabase non configuré ou non authentifié."
    try:
        c.set_shared_setting(TEMPLATE_KEYS[kind], None)
        return True, "Mail remis aux valeurs par défaut."
    except Exception as exc:
        return False, str(exc)


def _render_placeholders(template: dict, intake: dict) -> tuple[str, str, str]:
    """Substitue les placeholders dans le template avec les données du draft."""
    data = intake.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    firstname = _firstname_from(data)
    business = data.get("business_name") or data.get("business-name") or ""
    site_url = intake.get("site_url") or ""

    ctx = {
        "firstname": firstname,
        "business": business,
        "business_paren": (" (" + business + ")") if business else "",
        "business_space": (" " + business) if business else "",
        "business_html_strong": (" <strong>" + _html(business) + "</strong>") if business else "",
        "site_url": site_url,
    }

    def _safe_format(s: str, ctx: dict) -> str:
        # str.format échoue si la chaîne contient { } d'usage HTML/CSS. On
        # remplace les placeholders un par un pour éviter le souci.
        out = s or ""
        for k, v in ctx.items():
            out = out.replace("{" + k + "}", str(v))
        return out

    # Pour le HTML, on échappe firstname pour éviter les injections — mais
    # business_html_strong est déjà encapsulé dans son propre <strong>.
    html_ctx = dict(ctx)
    html_ctx["firstname"] = _html(firstname)
    html_ctx["site_url"] = _html(site_url)

    subject = _safe_format(template.get("subject", ""), ctx)
    body_text = _safe_format(template.get("body_text", ""), ctx)
    body_html = _safe_format(template.get("body_html", ""), html_ctx)
    return subject, body_text, body_html


# ---------------------------------------------------------------------------
# SMTP config
# ---------------------------------------------------------------------------
def _load_smtp_config() -> Optional[dict]:
    """Charge la config SMTP. Priorité : smtp_pixel_pros > smtp_config global."""
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None
    try:
        c = get_client()
    except SupabaseNotConfigured:
        return None
    if not c.is_authenticated:
        return None
    # 1. Compte dédié Pixel Pros si configuré
    pp = c.get_shared_setting("smtp_pixel_pros", default=None)
    if isinstance(pp, dict) and pp.get("smtp_host"):
        return pp
    # 2. Fallback : config SMTP générique
    g = c.get_shared_setting("smtp_config", default=None)
    if isinstance(g, dict) and g.get("smtp_host"):
        return g
    return None


def _send_via_smtp(cfg: dict, *, to: str, subject: str, body: str, body_html: str = "") -> bool:
    """Wrapper autour de triskell_core.prospect.outreach.smtp_sender.send_email."""
    try:
        from triskell_core.prospect.outreach.smtp_sender import send_email
    except ImportError as exc:
        logger.error("pixelpros.mailer: smtp_sender introuvable : %s", exc)
        return False
    try:
        send_email(cfg, to=to, subject=subject, body=body, body_html=body_html)
        return True
    except Exception as exc:
        logger.warning("pixelpros.mailer envoi KO : %s", exc)
        return False


# ---------------------------------------------------------------------------
# Construction du contenu des mails
# ---------------------------------------------------------------------------
def _firstname_from(data: dict) -> str:
    """Tente d'extraire un prénom depuis les données du formulaire."""
    name = (data.get("contact_name") or data.get("first_name")
            or data.get("firstname") or data.get("name") or "").strip()
    if name:
        return name.split()[0]
    biz = (data.get("business_name") or data.get("business-name") or "").strip()
    return biz or "vous"


def _build_paid_mail(intake: dict) -> tuple[str, str, str]:
    """Mail de confirmation paiement. Lit le template (override ou défaut)."""
    tpl = load_template("paid")
    return _render_placeholders(tpl, intake)


def _build_live_mail(intake: dict) -> tuple[str, str, str]:
    """Mail 'ton site est en ligne'. Lit le template (override ou défaut)."""
    tpl = load_template("live")
    return _render_placeholders(tpl, intake)


def _html(s: Any) -> str:
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def _resolve_email(intake: dict) -> Optional[str]:
    """Trouve le mail du client dans le draft."""
    data = intake.get("data") or {}
    if isinstance(data, dict):
        for k in ("email", "contact_email", "client_email"):
            if data.get(k):
                return str(data[k]).strip()
    for k in ("contact_email", "email", "stripe_customer_email"):
        if intake.get(k):
            return str(intake[k]).strip()
    return None


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def send_paid_mail(intake: dict) -> tuple[bool, str]:
    cfg = _load_smtp_config()
    if cfg is None:
        return False, "Config SMTP introuvable (shared_settings.smtp_pixel_pros ou smtp_config)"
    to = _resolve_email(intake)
    if not to:
        return False, "Email du client introuvable dans le draft"
    subject, body, body_html = _build_paid_mail(intake)
    ok = _send_via_smtp(cfg, to=to, subject=subject, body=body, body_html=body_html)
    return (True, f"Envoyé à {to}") if ok else (False, "Envoi SMTP a échoué (voir logs)")


def send_live_mail(intake: dict) -> tuple[bool, str]:
    cfg = _load_smtp_config()
    if cfg is None:
        return False, "Config SMTP introuvable (shared_settings.smtp_pixel_pros ou smtp_config)"
    to = _resolve_email(intake)
    if not to:
        return False, "Email du client introuvable dans le draft"
    if not intake.get("site_url"):
        return False, "site_url manquant sur le draft (build pas terminé ?)"
    subject, body, body_html = _build_live_mail(intake)
    ok = _send_via_smtp(cfg, to=to, subject=subject, body=body, body_html=body_html)
    return (True, f"Envoyé à {to}") if ok else (False, "Envoi SMTP a échoué (voir logs)")
