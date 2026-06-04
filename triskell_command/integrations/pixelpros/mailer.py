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

# Clés pour le mode auto/manuel d'envoi des mails.
# True = auto (défaut), False = manuel (Jordan déclenche depuis l'UI).
AUTO_KEYS = {
    "paid": "pixelpros_mail_auto_paid",
    "live": "pixelpros_mail_auto_live",
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
        "<html lang=\"fr\"><head><meta charset=\"utf-8\">\n"
        "<link href=\"https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Inter:wght@500;700;800;900&display=swap\" rel=\"stylesheet\">\n"
        "</head>\n"
        "<body style=\"margin:0; padding:0; background:#fff8ed; background-image: radial-gradient(circle at 12% 18%, rgba(14,165,255,0.12) 0%, transparent 38%), radial-gradient(circle at 88% 70%, rgba(250,204,21,0.18) 0%, transparent 42%); font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color:#0b0d1a;\">\n"
        "<div style=\"max-width:560px; margin:0 auto; padding:32px 20px;\">\n"
        "\n"
        "  <!-- Petit logo en-tête -->\n"
        "  <div style=\"text-align:center; margin-bottom:24px;\">\n"
        "    <span style=\"font-family:'Press Start 2P', monospace; font-size:14px; color:#0b0d1a; letter-spacing:0.05em;\">PIXEL</span>\n"
        "    <span style=\"font-family:'Press Start 2P', monospace; font-size:14px; color:#facc15; text-shadow:2px 2px 0 #0b0d1a; letter-spacing:0.05em; margin-left:6px;\">PROS</span>\n"
        "  </div>\n"
        "\n"
        "  <!-- Bandeau pixel -->\n"
        "  <div style=\"background:#facc15; color:#0b0d1a; padding:14px 18px; border:3px solid #0b0d1a; border-radius:10px; box-shadow:6px 6px 0 #0b0d1a; font-family:'Press Start 2P', monospace; font-size:13px; text-align:center; letter-spacing:0.03em; margin-bottom:28px;\">\n"
        "    ✓ PAIEMENT REÇU\n"
        "  </div>\n"
        "\n"
        "  <!-- Carte principale -->\n"
        "  <div style=\"background:#ffffff; border:3px solid #0b0d1a; border-radius:14px; box-shadow:6px 6px 0 #0b0d1a; padding:28px 26px;\">\n"
        "    <p style=\"margin:0 0 14px; font-size:16px;\">Salut <strong>{firstname}</strong>,</p>\n"
        "    <p style=\"margin:0 0 22px; font-size:15px; line-height:1.6;\">On a bien reçu ton paiement, c'est parti pour la fabrication de ton site Pixel Pros{business_html_strong}.</p>\n"
        "\n"
        "    <p style=\"margin:0 0 14px; font-weight:800; font-size:13px; letter-spacing:0.08em; text-transform:uppercase; color:#51546b;\">▶ Voilà ce qui se passe maintenant</p>\n"
        "\n"
        "    <!-- Étapes -->\n"
        "    <div style=\"margin-bottom:8px;\">\n"
        "      <div style=\"display:flex; align-items:flex-start; gap:14px; padding:12px 14px; background:#fff8ed; border:2px solid #0b0d1a; border-radius:10px; margin-bottom:10px;\">\n"
        "        <span style=\"display:inline-block; min-width:30px; height:30px; line-height:26px; text-align:center; background:#0ea5ff; color:#fff; border:2px solid #0b0d1a; border-radius:6px; font-family:'Press Start 2P', monospace; font-size:11px;\">1</span>\n"
        "        <span style=\"font-size:14.5px; line-height:1.5;\">On reprend toutes tes infos et tes photos</span>\n"
        "      </div>\n"
        "      <div style=\"display:flex; align-items:flex-start; gap:14px; padding:12px 14px; background:#fff8ed; border:2px solid #0b0d1a; border-radius:10px; margin-bottom:10px;\">\n"
        "        <span style=\"display:inline-block; min-width:30px; height:30px; line-height:26px; text-align:center; background:#ec4899; color:#fff; border:2px solid #0b0d1a; border-radius:6px; font-family:'Press Start 2P', monospace; font-size:11px;\">2</span>\n"
        "        <span style=\"font-size:14.5px; line-height:1.5;\">On rédige les textes et on monte le site</span>\n"
        "      </div>\n"
        "      <div style=\"display:flex; align-items:flex-start; gap:14px; padding:12px 14px; background:#fff8ed; border:2px solid #0b0d1a; border-radius:10px; margin-bottom:10px;\">\n"
        "        <span style=\"display:inline-block; min-width:30px; height:30px; line-height:26px; text-align:center; background:#22c55e; color:#fff; border:2px solid #0b0d1a; border-radius:6px; font-family:'Press Start 2P', monospace; font-size:11px;\">3</span>\n"
        "        <span style=\"font-size:14.5px; line-height:1.5;\">On le met en ligne sur ton adresse perso</span>\n"
        "      </div>\n"
        "      <div style=\"display:flex; align-items:flex-start; gap:14px; padding:12px 14px; background:#fff8ed; border:2px solid #0b0d1a; border-radius:10px;\">\n"
        "        <span style=\"display:inline-block; min-width:30px; height:30px; line-height:26px; text-align:center; background:#facc15; color:#0b0d1a; border:2px solid #0b0d1a; border-radius:6px; font-family:'Press Start 2P', monospace; font-size:11px;\">4</span>\n"
        "        <span style=\"font-size:14.5px; line-height:1.5;\">Tu reçois un mail dès qu'il est dispo (<strong>sous 24h ouvrées</strong>)</span>\n"
        "      </div>\n"
        "    </div>\n"
        "\n"
        "    <p style=\"margin:24px 0 0; padding:14px 16px; background:#f0f9ff; border-left:4px solid #0ea5ff; border-radius:6px; font-size:14.5px;\">💬 Tu as oublié quelque chose ou tu veux ajouter une info ? <strong>Réponds à ce mail</strong>, on s'en occupe.</p>\n"
        "  </div>\n"
        "\n"
        "  <!-- Signature -->\n"
        "  <div style=\"text-align:center; margin-top:28px; padding-top:20px; border-top:2px dashed #0b0d1a;\">\n"
        "    <p style=\"margin:0 0 6px; font-weight:800; font-size:15px;\">À très vite,</p>\n"
        "    <p style=\"margin:0 0 12px; font-size:14px;\">L'équipe Pixel Pros</p>\n"
        "    <a href=\"https://pixel-pros.fr\" style=\"display:inline-block; font-family:'Press Start 2P', monospace; font-size:10px; color:#0b0d1a; text-decoration:none; padding:8px 14px; border:2px solid #0b0d1a; border-radius:6px; background:#ffffff; box-shadow:3px 3px 0 #0b0d1a;\">pixel-pros.fr</a>\n"
        "  </div>\n"
        "\n"
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
        "⏱ À savoir : cette adresse est PROVISOIRE\n"
        "Notre équipe s'occupe de mettre en place ton adresse définitive dans les 24h :\n"
        "  • Soit un joli sous-domaine sur pixel-pros.fr (offert avec ton abonnement)\n"
        "  • Soit ton propre nom de domaine + adresse mail pro (si tu as pris l'option)\n"
        "Tu reçois un nouveau mail dès que ton adresse définitive est active.\n\n"
        "Quelque chose à modifier (texte, photo, couleur, n'importe quoi) ? Tu réponds à ce mail\n"
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
        "<html lang=\"fr\"><head><meta charset=\"utf-8\">\n"
        "<link href=\"https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Inter:wght@500;700;800;900&display=swap\" rel=\"stylesheet\">\n"
        "</head>\n"
        "<body style=\"margin:0; padding:0; background:#fff8ed; background-image: radial-gradient(circle at 12% 18%, rgba(14,165,255,0.12) 0%, transparent 38%), radial-gradient(circle at 88% 70%, rgba(250,204,21,0.18) 0%, transparent 42%); font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color:#0b0d1a;\">\n"
        "<div style=\"max-width:560px; margin:0 auto; padding:32px 20px;\">\n"
        "\n"
        "  <!-- Petit logo en-tête -->\n"
        "  <div style=\"text-align:center; margin-bottom:24px;\">\n"
        "    <span style=\"font-family:'Press Start 2P', monospace; font-size:14px; color:#0b0d1a; letter-spacing:0.05em;\">PIXEL</span>\n"
        "    <span style=\"font-family:'Press Start 2P', monospace; font-size:14px; color:#facc15; text-shadow:2px 2px 0 #0b0d1a; letter-spacing:0.05em; margin-left:6px;\">PROS</span>\n"
        "  </div>\n"
        "\n"
        "  <!-- Bandeau pixel -->\n"
        "  <div style=\"background:#22c55e; color:#ffffff; padding:14px 18px; border:3px solid #0b0d1a; border-radius:10px; box-shadow:6px 6px 0 #0b0d1a; font-family:'Press Start 2P', monospace; font-size:12px; text-align:center; letter-spacing:0.03em; margin-bottom:28px; line-height:1.6;\">\n"
        "    🎉 TON SITE EST EN LIGNE\n"
        "  </div>\n"
        "\n"
        "  <!-- Carte principale -->\n"
        "  <div style=\"background:#ffffff; border:3px solid #0b0d1a; border-radius:14px; box-shadow:6px 6px 0 #0b0d1a; padding:28px 26px;\">\n"
        "    <p style=\"margin:0 0 14px; font-size:16px;\">Salut <strong>{firstname}</strong>,</p>\n"
        "    <p style=\"margin:0 0 24px; font-size:15px; line-height:1.6;\">Ton site{business_html_strong} est en ligne, tu peux le voir tout de suite :</p>\n"
        "\n"
        "    <!-- CTA principal -->\n"
        "    <p style=\"text-align:center; margin:0 0 14px;\">\n"
        "      <a href=\"{site_url}\" style=\"display:inline-block; background:#facc15; color:#0b0d1a; font-weight:900; padding:16px 32px; border:3px solid #0b0d1a; border-radius:10px; box-shadow:6px 6px 0 #0b0d1a; text-decoration:none; font-size:16px; letter-spacing:0.02em;\">▶ VOIR MON SITE</a>\n"
        "    </p>\n"
        "    <p style=\"margin:0 0 4px; font-size:12px; color:#51546b; text-align:center;\">ou copie-colle l'adresse :</p>\n"
        "    <p style=\"margin:0 0 4px; font-size:13px; text-align:center; line-height:1.5;\"><a href=\"{site_url}\" style=\"display:inline-block; max-width:100%; box-sizing:border-box; word-break:break-all; font-family:'Inter', monospace; color:#0ea5ff; background:#f0f9ff; padding:6px 12px; border-radius:6px; text-decoration:none; border:1px dashed #0ea5ff;\">{site_url}</a></p>\n"
        "\n"
        "    <!-- Encart adresse provisoire -->\n"
        "    <div style=\"background:#eff6ff; border:3px solid #0b0d1a; border-radius:12px; box-shadow:4px 4px 0 #0b0d1a; padding:20px 22px; margin:28px 0 8px;\">\n"
        "      <div style=\"display:inline-block; background:#0ea5ff; color:#fff; font-family:'Press Start 2P', monospace; font-size:9px; padding:5px 10px; border:2px solid #0b0d1a; border-radius:5px; box-shadow:2px 2px 0 #0b0d1a; letter-spacing:0.04em; margin-bottom:12px;\">⏱ À SAVOIR</div>\n"
        "      <p style=\"margin:0 0 10px; font-weight:900; font-size:16px; color:#0b0d1a;\">Cette adresse est provisoire</p>\n"
        "      <p style=\"margin:0 0 12px; font-size:14.5px; line-height:1.6; color:#0b0d1a;\">Notre équipe s'occupe de ton adresse <strong>définitive dans les 24 h</strong> :</p>\n"
        "      <ul style=\"margin:0 0 12px; padding-left:22px; font-size:14px; line-height:1.65; color:#0b0d1a;\">\n"
        "        <li>Soit un joli <strong>sous-domaine sur pixel-pros.fr</strong> (offert avec ton abonnement)</li>\n"
        "        <li>Soit <strong>ton propre nom de domaine</strong> + adresse mail pro (si tu as pris l'option)</li>\n"
        "      </ul>\n"
        "      <p style=\"margin:0; font-size:13.5px; color:#1f5a3c; font-weight:700;\">📧 Tu reçois un nouveau mail dès que ton adresse définitive est active.</p>\n"
        "    </div>\n"
        "\n"
        "    <!-- Encart cadeau Carnet -->\n"
        "    <div style=\"background:#fff8ed; border:3px solid #0b0d1a; border-radius:12px; box-shadow:4px 4px 0 #0b0d1a; padding:22px 22px; margin:32px 0 8px; position:relative;\">\n"
        "      <div style=\"display:inline-block; background:#ec4899; color:#fff; font-family:'Press Start 2P', monospace; font-size:9px; padding:5px 10px; border:2px solid #0b0d1a; border-radius:5px; box-shadow:2px 2px 0 #0b0d1a; letter-spacing:0.04em; margin-bottom:14px;\">🎁 TON CADEAU</div>\n"
        "      <p style=\"margin:0 0 8px; font-weight:900; font-size:18px; color:#0b0d1a;\">Carnet — devis &amp; factures</p>\n"
        "      <p style=\"margin:0 0 16px; font-size:14.5px; line-height:1.6; color:#0b0d1a;\">On t'offre <strong>Carnet</strong>, notre outil pour faire tes devis et factures en 2 clics depuis ton téléphone. <strong>Aucune installation, aucun compte à créer.</strong></p>\n"
        "      <p style=\"text-align:center; margin:0;\">\n"
        "        <a href=\"https://carnet-pro-fr.netlify.app\" style=\"display:inline-block; background:#22c55e; color:#ffffff; font-weight:900; padding:13px 26px; border:3px solid #0b0d1a; border-radius:10px; box-shadow:4px 4px 0 #0b0d1a; text-decoration:none; font-size:14.5px; letter-spacing:0.02em;\">📓 OUVRIR MON CARNET</a>\n"
        "      </p>\n"
        "    </div>\n"
        "\n"
        "    <!-- Conseils -->\n"
        "    <p style=\"margin:28px 0 12px; font-weight:800; font-size:13px; letter-spacing:0.08em; text-transform:uppercase; color:#51546b;\">▶ Quelques conseils pour démarrer</p>\n"
        "    <div>\n"
        "      <div style=\"display:flex; align-items:flex-start; gap:12px; padding:12px 14px; background:#fff8ed; border:2px solid #0b0d1a; border-radius:10px; margin-bottom:8px;\">\n"
        "        <span style=\"font-size:18px; line-height:1; flex-shrink:0;\">📣</span>\n"
        "        <span style=\"font-size:14.5px; line-height:1.5;\">Partage le lien à tes proches et tes clients</span>\n"
        "      </div>\n"
        "      <div style=\"display:flex; align-items:flex-start; gap:12px; padding:12px 14px; background:#fff8ed; border:2px solid #0b0d1a; border-radius:10px; margin-bottom:8px;\">\n"
        "        <span style=\"font-size:18px; line-height:1; flex-shrink:0;\">📍</span>\n"
        "        <span style=\"font-size:14.5px; line-height:1.5;\">Ajoute-le sur Google Business, Instagram, ta signature mail</span>\n"
        "      </div>\n"
        "      <div style=\"display:flex; align-items:flex-start; gap:12px; padding:12px 14px; background:#fff8ed; border:2px solid #0b0d1a; border-radius:10px;\">\n"
        "        <span style=\"font-size:18px; line-height:1; flex-shrink:0;\">🌐</span>\n"
        "        <span style=\"font-size:14.5px; line-height:1.5;\">Pas pris le pack TOUT-EN-UN ? On peut ajouter ton propre nom de domaine quand tu veux.</span>\n"
        "      </div>\n"
        "    </div>\n"
        "\n"
        "    <!-- Modifs -->\n"
        "    <p style=\"margin:24px 0 0; padding:14px 16px; background:#fef2f2; border-left:4px solid #ef4444; border-radius:6px; font-size:14.5px;\">✏️ Quelque chose à modifier (texte, photo, couleur) ? <strong>Réponds à ce mail</strong>, on s'en occupe — les modifs sont incluses dans ton abonnement.</p>\n"
        "  </div>\n"
        "\n"
        "  <!-- Signature -->\n"
        "  <div style=\"text-align:center; margin-top:28px; padding-top:20px; border-top:2px dashed #0b0d1a;\">\n"
        "    <p style=\"margin:0 0 6px; font-weight:800; font-size:15px;\">À très vite,</p>\n"
        "    <p style=\"margin:0 0 12px; font-size:14px;\">L'équipe Pixel Pros</p>\n"
        "    <a href=\"https://pixel-pros.fr\" style=\"display:inline-block; font-family:'Press Start 2P', monospace; font-size:10px; color:#0b0d1a; text-decoration:none; padding:8px 14px; border:2px solid #0b0d1a; border-radius:6px; background:#ffffff; box-shadow:3px 3px 0 #0b0d1a;\">pixel-pros.fr</a>\n"
        "  </div>\n"
        "\n"
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


def is_auto(kind: str) -> bool:
    """True si l'envoi auto est activé pour ce mail (défaut). False si Jordan
    a basculé en mode manuel — dans ce cas l'envoi automatique (webhook Stripe
    ou fin de build) est ignoré, l'envoi se déclenche uniquement via l'UI.
    """
    if kind not in AUTO_KEYS:
        return True
    c = _get_supabase()
    if c is None:
        return True
    try:
        v = c.get_shared_setting(AUTO_KEYS[kind], default=None)
        if v is None:
            return True
        return bool(v)
    except Exception as exc:
        logger.debug("pixelpros.mailer.is_auto: %s", exc)
        return True


def set_auto(kind: str, value: bool) -> tuple[bool, str]:
    """Active/désactive l'envoi auto pour 'paid' ou 'live'."""
    if kind not in AUTO_KEYS:
        return False, f"kind invalide : {kind}"
    c = _get_supabase()
    if c is None:
        return False, "Supabase non configuré ou non authentifié."
    try:
        c.set_shared_setting(AUTO_KEYS[kind], bool(value))
        return True, "Mode mis à jour."
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


def _send_via_smtp(cfg: dict, *, to: str, subject: str, body: str,
                   body_html: str = "", source: str = "", reply_to: str = "") -> bool:
    """Wrapper autour de triskell_core.prospect.outreach.smtp_sender.send_email.

    En cas de succès, logge l'envoi dans `email_history` pour que le mail
    apparaisse dans la vue « Mails envoyés ».

    `reply_to` : adresse de réponse (ex : le visiteur d'un formulaire de
    contact, pour que le client réponde directement en répondant au mail).
    """
    try:
        from triskell_core.prospect.outreach.smtp_sender import send_email
    except ImportError as exc:
        logger.error("pixelpros.mailer: smtp_sender introuvable : %s", exc)
        return False
    try:
        message_id = send_email(cfg, to=to, subject=subject, body=body,
                                body_html=body_html, reply_to=reply_to)
    except Exception as exc:
        logger.warning("pixelpros.mailer envoi KO : %s", exc)
        return False

    # Log dans l'historique (non bloquant)
    try:
        from ..email_history_log import log_sent_pipeline_mail
        log_sent_pipeline_mail(
            to=to,
            subject=subject,
            body=body,
            body_html=body_html,
            from_email=cfg.get("from_email", "") if isinstance(cfg, dict) else "",
            message_id=message_id or "",
            source=source or "pixelpros_pipeline",
        )
    except Exception as exc:
        logger.debug("pixelpros.mailer: log_sent_pipeline_mail KO : %s", exc)
    return True


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
    ok = _send_via_smtp(cfg, to=to, subject=subject, body=body, body_html=body_html,
                        source="pixelpros_paid_mail")
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
    ok = _send_via_smtp(cfg, to=to, subject=subject, body=body, body_html=body_html,
                        source="pixelpros_live_mail")
    return (True, f"Envoyé à {to}") if ok else (False, "Envoi SMTP a échoué (voir logs)")


# ---------------------------------------------------------------------------
# Formulaire de contact d'un site client → mail au client
# ---------------------------------------------------------------------------
def _ops_inbox(cfg: dict) -> str:
    """Adresse de secours : si l'email du client est introuvable, le message
    ne doit JAMAIS être perdu. On retombe sur l'expéditeur configuré (une
    vraie boîte qu'on relève), sinon contact@pixel-pros.fr."""
    box = ""
    if isinstance(cfg, dict):
        box = (cfg.get("from_email") or cfg.get("smtp_user") or "").strip()
    return box or "contact@pixel-pros.fr"


def _contact_html(name: str, visitor_email: str, message: str,
                  business: str, fallback_slug: str = "") -> str:
    n = _html(name)
    em = _html(visitor_email)
    msg_html = _html(message).replace("\n", "<br>")
    biz = (" " + _html(business)) if business else ""
    warn = ""
    if fallback_slug:
        warn = (
            "<p style=\"margin:18px 0 0; padding:12px 14px; background:#fef2f2; "
            "border-left:4px solid #ef4444; border-radius:6px; font-size:13px; color:#7f1d1d;\">"
            "⚠ Destinataire client introuvable pour « " + _html(fallback_slug) +
            " » — message routé vers l'adresse de secours.</p>"
        )
    return (
        "<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\"></head>"
        "<body style=\"margin:0; padding:0; background:#f4f5f7; font-family:-apple-system,"
        "BlinkMacSystemFont,'Segoe UI',sans-serif; color:#0b0d1a;\">"
        "<div style=\"max-width:560px; margin:0 auto; padding:28px 20px;\">"
        "<div style=\"background:#ffffff; border-radius:14px; padding:26px 24px; "
        "box-shadow:0 2px 8px rgba(0,0,0,.06);\">"
        "<p style=\"margin:0 0 4px; font-size:13px; letter-spacing:.06em; "
        "text-transform:uppercase; color:#6b7280; font-weight:700;\">📬 Nouveau message</p>"
        "<h1 style=\"margin:0 0 18px; font-size:20px;\">Un visiteur t'écrit depuis ton site" + biz + "</h1>"
        "<table style=\"width:100%; font-size:14.5px; border-collapse:collapse; margin-bottom:18px;\">"
        "<tr><td style=\"padding:6px 0; color:#6b7280; width:80px;\">De</td>"
        "<td style=\"padding:6px 0; font-weight:700;\">" + n + "</td></tr>"
        "<tr><td style=\"padding:6px 0; color:#6b7280;\">Email</td>"
        "<td style=\"padding:6px 0;\"><a href=\"mailto:" + em + "\" style=\"color:#2563eb;\">" + em + "</a></td></tr>"
        "</table>"
        "<div style=\"padding:16px 18px; background:#f9fafb; border:1px solid #e5e7eb; "
        "border-radius:10px; font-size:15px; line-height:1.6; white-space:normal;\">" + msg_html + "</div>"
        "<p style=\"margin:18px 0 0; font-size:13.5px; color:#6b7280;\">"
        "💬 Pour répondre, réponds simplement à ce mail — ta réponse partira vers " + em + ".</p>"
        + warn +
        "</div>"
        "<p style=\"text-align:center; margin:16px 0 0; font-size:11.5px; color:#9ca3af;\">"
        "Reçu via le formulaire de contact de ton site · Pixel Pros</p>"
        "</div></body></html>"
    )


def _studio_contact_html(name: str, email: str, phone: str,
                         message: str, page_source: str) -> str:
    n = _html(name or "visiteur")
    em = _html(email)
    msg_html = _html(message).replace("\n", "<br>")
    rows = (
        "<tr><td style=\"padding:6px 0; color:#6b7280; width:90px;\">De</td>"
        "<td style=\"padding:6px 0; font-weight:700;\">" + n + "</td></tr>"
        "<tr><td style=\"padding:6px 0; color:#6b7280;\">Email</td>"
        "<td style=\"padding:6px 0;\"><a href=\"mailto:" + em + "\" style=\"color:#2563eb;\">" + em + "</a></td></tr>"
    )
    if phone:
        rows += ("<tr><td style=\"padding:6px 0; color:#6b7280;\">Téléphone</td>"
                 "<td style=\"padding:6px 0;\">" + _html(phone) + "</td></tr>")
    if page_source:
        rows += ("<tr><td style=\"padding:6px 0; color:#6b7280;\">Page</td>"
                 "<td style=\"padding:6px 0; color:#6b7280;\">" + _html(page_source) + "</td></tr>")
    return (
        "<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\"></head>"
        "<body style=\"margin:0; padding:0; background:#f4f5f7; font-family:-apple-system,"
        "BlinkMacSystemFont,'Segoe UI',sans-serif; color:#0b0d1a;\">"
        "<div style=\"max-width:560px; margin:0 auto; padding:28px 20px;\">"
        "<div style=\"background:#ffffff; border-radius:14px; padding:26px 24px; "
        "box-shadow:0 2px 8px rgba(0,0,0,.06);\">"
        "<p style=\"margin:0 0 4px; font-size:13px; letter-spacing:.06em; "
        "text-transform:uppercase; color:#6b7280; font-weight:700;\">📬 Formulaire de contact</p>"
        "<h1 style=\"margin:0 0 18px; font-size:20px;\">Nouveau message depuis pixel-pros.fr</h1>"
        "<table style=\"width:100%; font-size:14.5px; border-collapse:collapse; margin-bottom:18px;\">"
        + rows +
        "</table>"
        "<div style=\"padding:16px 18px; background:#f9fafb; border:1px solid #e5e7eb; "
        "border-radius:10px; font-size:15px; line-height:1.6;\">" + msg_html + "</div>"
        "<p style=\"margin:18px 0 0; font-size:13.5px; color:#6b7280;\">"
        "💬 Pour répondre, réponds simplement à ce mail — ta réponse partira vers " + em + ".</p>"
        "</div>"
        "<p style=\"text-align:center; margin:16px 0 0; font-size:11.5px; color:#9ca3af;\">"
        "Reçu via le formulaire de contact de pixel-pros.fr</p>"
        "</div></body></html>"
    )


def send_studio_contact(*, name: str, email: str, phone: str = "",
                        message: str = "", page_source: str = "") -> tuple[bool, str]:
    """Relaie un message reçu via le formulaire de contact de pixel-pros.fr
    (le site vitrine lui-même, pas un site client) à l'équipe Pixel Pros.

    Destinataire : variable d'env PIXELPROS_CONTACT_TO, sinon l'adresse de
    secours (l'expéditeur configuré, ou contact@pixel-pros.fr).
    Reply-To = email du visiteur, pour répondre en répondant au mail.
    """
    cfg = _load_smtp_config()
    if cfg is None:
        return False, "Config SMTP introuvable (shared_settings.smtp_pixel_pros ou smtp_config)"
    import os
    to = (os.environ.get("PIXELPROS_CONTACT_TO") or "").strip() or _ops_inbox(cfg)
    subject = f"📬 Nouveau message pixel-pros.fr — {name or 'visiteur'}"
    phone_line = f"\nTéléphone : {phone}" if phone else ""
    page_line = f"\nPage : {page_source}" if page_source else ""
    body = (
        "Nouveau message depuis le formulaire de contact de pixel-pros.fr\n\n"
        f"De : {name}\nEmail : {email}{phone_line}{page_line}\n\n"
        f"Message :\n{message}\n"
    )
    body_html = _studio_contact_html(name, email, phone, message, page_source)
    ok = _send_via_smtp(cfg, to=to, subject=subject, body=body,
                        body_html=body_html, source="pixelpros_studio_contact",
                        reply_to=email)
    return (True, f"Envoyé à {to}") if ok else (False, "Envoi SMTP a échoué (voir logs)")


def send_contact_message(intake: Optional[dict], *, slug: str,
                         visitor_name: str, visitor_email: str,
                         visitor_message: str) -> tuple[bool, str]:
    """Envoie au client le message reçu via le formulaire de contact de son site.

    Le destinataire est l'email du client tel qu'enregistré dans son draft
    (résolu en amont par le slug du site). Si on ne le trouve pas, on route
    vers une adresse de secours pour ne JAMAIS perdre un message.
    Reply-To = email du visiteur (le client répond en répondant au mail).
    """
    cfg = _load_smtp_config()
    if cfg is None:
        return False, "Config SMTP introuvable (shared_settings.smtp_pixel_pros ou smtp_config)"

    business = ""
    if isinstance(intake, dict):
        data = intake.get("data") or {}
        if isinstance(data, dict):
            business = (data.get("business_name") or data.get("business-name") or "")
        if not business:
            business = intake.get("business_name") or ""

    to = _resolve_email(intake) if isinstance(intake, dict) else None
    used_fallback = False
    if not to:
        to = _ops_inbox(cfg)
        used_fallback = True
    if not to:
        return False, "Aucun destinataire (ni client ni secours)"

    name = (visitor_name or "Un visiteur").strip()
    subject = f"📬 Nouveau message via ton site{(' ' + business) if business else ''}"
    text_lines = [
        f"Tu as reçu un nouveau message depuis le formulaire de contact de ton site{(' ' + business) if business else ''}.",
        "",
        f"De : {name}",
        f"Email : {visitor_email}",
        "",
        "Message :",
        visitor_message,
        "",
        "— Pour répondre, réponds simplement à ce mail : ta réponse partira vers le visiteur.",
    ]
    if used_fallback:
        text_lines += ["", f"(⚠ Destinataire client introuvable pour « {slug} » — message routé vers l'adresse de secours.)"]
    body = "\n".join(text_lines)
    body_html = _contact_html(name, visitor_email, visitor_message, business,
                              fallback_slug=slug if used_fallback else "")

    ok = _send_via_smtp(cfg, to=to, subject=subject, body=body, body_html=body_html,
                        source="pixelpros_contact_form", reply_to=visitor_email)
    if not ok:
        return False, "Envoi SMTP a échoué (voir logs)"
    return True, f"Envoyé à {to}" + (" (secours)" if used_fallback else "")


# ---------------------------------------------------------------------------
# Mail "lien de connexion affilié" (magic link)
# ---------------------------------------------------------------------------
AFFILIATE_LOGIN_MAIL = {
    "subject": "Ton lien de connexion Pixel Pros Affiliés",
    "body_text": (
        "Salut {firstname},\n\n"
        "Voilà ton lien de connexion à ton espace affilié Pixel Pros :\n"
        "{login_url}\n\n"
        "Ce lien est valable 7 jours et te connecte automatiquement, pas de mot de passe à retenir.\n\n"
        "Si tu n'as pas demandé ce mail, ignore-le simplement.\n\n"
        "L'équipe Pixel Pros\n"
        "https://pixel-pros.fr"
    ),
}


def _build_affiliate_login_mail(firstname: str, token: str) -> tuple[str, str, str]:
    login_url = f"https://pixel-pros.fr/affilie-acces.html?token={token}"
    fn_raw = firstname or "affilié"
    subject = AFFILIATE_LOGIN_MAIL["subject"]
    body_text = (AFFILIATE_LOGIN_MAIL["body_text"]
                 .replace("{firstname}", fn_raw)
                 .replace("{login_url}", login_url))

    fn = _html(fn_raw)
    body_html = (
        "<!doctype html>\n"
        "<html lang=\"fr\"><head><meta charset=\"utf-8\">\n"
        "<link href=\"https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Inter:wght@500;700;800;900&display=swap\" rel=\"stylesheet\">\n"
        "</head>\n"
        "<body style=\"margin:0; padding:0; background:#fff8ed; font-family:'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color:#0b0d1a;\">\n"
        "<div style=\"max-width:560px; margin:0 auto; padding:32px 20px;\">\n"
        "  <div style=\"text-align:center; margin-bottom:24px;\">\n"
        "    <span style=\"font-family:'Press Start 2P', monospace; font-size:14px; color:#0b0d1a; letter-spacing:0.05em;\">PIXEL</span>\n"
        "    <span style=\"font-family:'Press Start 2P', monospace; font-size:14px; color:#facc15; text-shadow:2px 2px 0 #0b0d1a; letter-spacing:0.05em; margin-left:6px;\">PROS</span>\n"
        "  </div>\n"
        "  <div style=\"background:#0ea5ff; color:#fff; padding:14px 18px; border:3px solid #0b0d1a; border-radius:10px; box-shadow:6px 6px 0 #0b0d1a; font-family:'Press Start 2P', monospace; font-size:12px; text-align:center; letter-spacing:0.03em; margin-bottom:28px;\">\n"
        "    ★ ESPACE AFFILIÉ\n"
        "  </div>\n"
        "  <div style=\"background:#ffffff; border:3px solid #0b0d1a; border-radius:14px; box-shadow:6px 6px 0 #0b0d1a; padding:28px 26px;\">\n"
        f"    <p style=\"margin:0 0 14px; font-size:16px;\">Salut <strong>{fn}</strong>,</p>\n"
        "    <p style=\"margin:0 0 22px; font-size:15px; line-height:1.6;\">Voilà ton lien personnel pour te connecter à ton espace affilié Pixel Pros. Un clic et c'est ouvert, pas de mot de passe à retenir.</p>\n"
        f"    <p style=\"text-align:center; margin:22px 0;\"><a href=\"{login_url}\" style=\"display:inline-block; background:#facc15; color:#0b0d1a; padding:14px 28px; border:3px solid #0b0d1a; border-radius:10px; box-shadow:5px 5px 0 #0b0d1a; font-family:'Press Start 2P', monospace; font-size:12px; text-decoration:none; letter-spacing:0.03em;\">▶ OUVRIR MON ESPACE</a></p>\n"
        "    <p style=\"margin:18px 0 0; font-size:13px; color:#51546b; line-height:1.55;\">Ce lien est valable <strong>7 jours</strong>. Si tu n'as pas demandé ce mail, ignore-le.</p>\n"
        "  </div>\n"
        "  <p style=\"text-align:center; margin-top:24px; font-size:12px; color:#51546b;\">Pixel Pros · Tous les pros à égalité</p>\n"
        "</div></body></html>"
    )
    return subject, body_text, body_html


def send_affiliate_login_mail(email: str, token: str, firstname: str = "") -> tuple[bool, str]:
    """Envoie le mail magique de connexion à un affilié."""
    cfg = _load_smtp_config()
    if cfg is None:
        return False, "Config SMTP introuvable"
    to = (email or "").strip()
    if not to:
        return False, "Email destinataire manquant"
    subject, body, body_html = _build_affiliate_login_mail(firstname, token)
    ok = _send_via_smtp(cfg, to=to, subject=subject, body=body, body_html=body_html,
                        source="pixelpros_affiliate_login")
    return (True, f"Envoyé à {to}") if ok else (False, "Envoi SMTP a échoué (voir logs)")
