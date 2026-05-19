"""Envoi des mails transactionnels Pixel Pros.

Deux mails :
- send_paid_mail(intake)  : envoyé juste après que Stripe a confirmé le paiement.
- send_live_mail(intake)  : envoyé quand le site est en ligne sur {slug}.pixel-pros.fr.

Le SMTP est lu depuis shared_settings.smtp_config (la même que morning_mailer) ;
si Jordan a configuré un compte mail dédié Pixel Pros dans shared_settings.smtp_pixel_pros,
on l'utilise en priorité (l'expéditeur du mail sera contact@pixel-pros.fr).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


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
    """Renvoie (subject, body_text, body_html) pour le mail de confirmation paiement."""
    data = intake.get("data") or {}
    if not isinstance(data, dict): data = {}
    firstname = _firstname_from(data)
    business = data.get("business_name") or data.get("business-name") or ""

    subject = f"On a bien reçu ton paiement — ton site Pixel Pros arrive sous 24h"

    body_text = (
        f"Salut {firstname},\n\n"
        f"On a bien reçu ton paiement, c'est parti pour la fabrication de ton site Pixel Pros{' (' + business + ')' if business else ''}.\n\n"
        f"Voilà ce qu'il se passe maintenant :\n"
        f"  1. On reprend toutes tes infos et tes photos\n"
        f"  2. On rédige les textes et on monte le site\n"
        f"  3. On le met en ligne sur ton adresse perso\n"
        f"  4. Tu reçois un mail dès qu'il est dispo (sous 24h ouvrées)\n\n"
        f"Si tu as oublié quelque chose ou si tu veux ajouter une info, réponds simplement à ce mail.\n\n"
        f"À très vite,\n"
        f"L'équipe Pixel Pros\n"
        f"https://pixel-pros.fr"
    )

    body_html = f"""<!doctype html>
<html lang="fr"><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height:1.55; color:#1a1a1a; max-width:560px; margin:0 auto; padding:24px;">
<div style="background:#facc15; color:#0f172a; padding:18px 22px; border-radius:12px 12px 0 0; font-weight:800; font-size:18px;">✓ Paiement reçu</div>
<div style="background:#fff8e1; padding:24px 22px; border-radius:0 0 12px 12px; border:1px solid #facc15; border-top:none;">
  <p style="margin:0 0 14px;">Salut <strong>{_html(firstname)}</strong>,</p>
  <p style="margin:0 0 14px;">On a bien reçu ton paiement, c'est parti pour la fabrication de ton site Pixel Pros{(' <strong>' + _html(business) + '</strong>') if business else ''}.</p>
  <p style="margin:0 0 8px; font-weight:700;">Voilà ce qu'il se passe maintenant :</p>
  <ol style="margin:0 0 14px; padding-left:22px;">
    <li>On reprend toutes tes infos et tes photos</li>
    <li>On rédige les textes et on monte le site</li>
    <li>On le met en ligne sur ton adresse perso</li>
    <li>Tu reçois un mail dès qu'il est dispo (sous 24h ouvrées)</li>
  </ol>
  <p style="margin:0 0 14px;">Si tu as oublié quelque chose ou si tu veux ajouter une info, réponds simplement à ce mail.</p>
  <p style="margin:0 0 4px;">À très vite,</p>
  <p style="margin:0;"><strong>L'équipe Pixel Pros</strong><br><a href="https://pixel-pros.fr" style="color:#0f172a;">pixel-pros.fr</a></p>
</div>
</body></html>"""

    return subject, body_text, body_html


def _build_live_mail(intake: dict) -> tuple[str, str, str]:
    """Renvoie (subject, body_text, body_html) pour le mail 'ton site est en ligne'."""
    data = intake.get("data") or {}
    if not isinstance(data, dict): data = {}
    firstname = _firstname_from(data)
    business = data.get("business_name") or data.get("business-name") or ""
    site_url = intake.get("site_url") or ""

    subject = f"🎉 Ton site Pixel Pros est en ligne !"

    body_text = (
        f"Salut {firstname},\n\n"
        f"Ton site{' ' + business if business else ''} est en ligne, tu peux le voir tout de suite ici :\n\n"
        f"  {site_url}\n\n"
        f"Si tu vois un truc à changer (texte, photo, couleur, n'importe quoi), tu réponds à ce mail\n"
        f"et on s'en occupe — les modifs sont incluses dans ton abonnement.\n\n"
        f"Quelques petits conseils pour démarrer :\n"
        f"  • Partage le lien à tes proches et tes clients\n"
        f"  • Ajoute-le sur Google Business, Instagram, ta signature mail\n"
        f"  • Si tu n'as pas pris le pack TOUT-EN-UN et que tu veux ton propre nom de domaine, on peut l'ajouter à tout moment\n\n"
        f"À très vite,\n"
        f"L'équipe Pixel Pros\n"
        f"https://pixel-pros.fr"
    )

    body_html = f"""<!doctype html>
<html lang="fr"><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height:1.55; color:#1a1a1a; max-width:560px; margin:0 auto; padding:24px;">
<div style="background:#22c55e; color:#fff; padding:18px 22px; border-radius:12px 12px 0 0; font-weight:800; font-size:18px;">🎉 Ton site est en ligne !</div>
<div style="background:#fff8e1; padding:24px 22px; border-radius:0 0 12px 12px; border:1px solid #facc15; border-top:none;">
  <p style="margin:0 0 14px;">Salut <strong>{_html(firstname)}</strong>,</p>
  <p style="margin:0 0 18px;">Ton site{(' <strong>' + _html(business) + '</strong>') if business else ''} est en ligne, tu peux le voir tout de suite :</p>
  <p style="text-align:center; margin:0 0 20px;">
    <a href="{_html(site_url)}" style="display:inline-block; background:#facc15; color:#0f172a; font-weight:800; padding:14px 28px; border-radius:10px; text-decoration:none; font-size:15px;">▶ Voir mon site</a>
  </p>
  <p style="margin:0 0 14px; font-size:13px; color:#64748b; text-align:center;"><code style="background:#fff; padding:4px 8px; border-radius:4px;">{_html(site_url)}</code></p>
  <p style="margin:0 0 8px; font-weight:700;">Quelques conseils pour démarrer :</p>
  <ul style="margin:0 0 14px; padding-left:22px;">
    <li>Partage le lien à tes proches et tes clients</li>
    <li>Ajoute-le sur Google Business, Instagram, ta signature mail</li>
    <li>Si tu n'as pas pris le pack TOUT-EN-UN et que tu veux ton propre nom de domaine, on peut l'ajouter à tout moment</li>
  </ul>
  <p style="margin:0 0 14px;">Tu vois un truc à changer (texte, photo, couleur) ? <strong>Tu réponds à ce mail</strong> et on s'en occupe — les modifs sont incluses dans ton abonnement.</p>
  <p style="margin:0 0 4px;">À très vite,</p>
  <p style="margin:0;"><strong>L'équipe Pixel Pros</strong><br><a href="https://pixel-pros.fr" style="color:#0f172a;">pixel-pros.fr</a></p>
</div>
</body></html>"""

    return subject, body_text, body_html


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
