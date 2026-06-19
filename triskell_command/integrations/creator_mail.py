"""Génère le mail HTML « riche » envoyé aux créateurs (validé par Jordan 17/06).

Structure : accroche globale → aperçu de l'assistant → le détail (quiz, analyse,
monétisation) → aperçu du quiz → bouton → offre. Deux aperçus images pour
intriguer. Gère tutoiement / vouvoiement. Style « zéro tic d'IA » : pas de
deux-points d'annonce, pas de tiret cadratin, pas de « sans pression »
(cf. feedback Jordan).

Les images (avatar + 2 aperçus) sont servies depuis le site du créateur :
  <demo_url>/brand_avatar.jpg, /_mail_assistant.png, /_mail_quiz.png
(elles doivent y être déployées — voir scripts/… côté Operateur-Croissance).
"""
from __future__ import annotations

import html as _html


def _esc(s: str) -> str:
    return _html.escape(str(s or ""))


def _nowidow(s: str) -> str:
    """Évite la « veuve » (un mot seul en fin de ligne) en reliant les deux
    derniers mots par un espace insécable. Pour le HTML uniquement."""
    s = (s or "").rstrip()
    i = s.rfind(" ")
    return s[:i] + "&nbsp;" + s[i + 1:] if i > 0 else s


def _initials(name: str) -> str:
    """Initiales du créateur pour la pastille du mail (l'avatar image n'est pas
    déployé sur tous les sites → on évite le rond vide)."""
    import re
    n = re.sub(r"\(.*?\)", " ", name or "")
    stop = {"de", "des", "du", "la", "le", "les", "et", "d", "l", "un", "une"}
    parts = [p for p in re.split(r"[\s\-]+", n) if p and p.lower() not in stop]
    if not parts:
        return "★"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


# Badge Triskell (logo hébergé) affiché dans le rond de l'en-tête. Asset public
# stable, dans le bucket Supabase déjà utilisé pour les aperçus. Choix de Jordan
# (19/06/2026) : un logo Triskell constant plutôt que les initiales du créateur
# (le rond, c'est l'expéditeur — « préparé par Triskell Studio »).
TRISKELL_BADGE_URL = (
    "https://rmaafrrseafghptlsgdz.supabase.co/storage/v1/object/public/"
    "pp-client-photos/brand/triskell_badge.png")


def _badge_html() -> str:
    """Rond d'en-tête : le logo Triskell hébergé, sur un fond sombre de repli
    (si l'image ne charge pas, on a un rond sombre à la marque, jamais un rond
    cassé ni des initiales qui ne sont pas celles du créateur)."""
    return (
        '<div style="width:52px;height:52px;border-radius:50%;'
        'background:#0B0B14;overflow:hidden;line-height:0;">'
        f'<img src="{TRISKELL_BADGE_URL}" width="52" height="52" '
        'alt="Triskell Studio" style="display:block;width:52px;height:52px;'
        'border:0;outline:none;"></div>')


def kind_for(platform: str = "", notes: str = "", demo_url: str = "") -> str:
    """« kit » pour les créateurs TikTok (boutique + cours + cadeau), « club »
    pour les créateurs Instagram à qui on propose un club mensuel à leur marque
    (offre récente), « assistant » sinon (offre YouTube historique)."""
    p = (platform or "").lower()
    n = (notes or "").lower()
    d = (demo_url or "").lower()
    if (p == "tiktok" or "cible tiktok" in n
            or "kit de monétisation" in n or "kit de monetisation" in n):
        return "kit"
    # Club : repéré par les notes (« (club) », « Piste A/B ») ou par l'adresse
    # du site (les démos de club vivent sur des sous-domaines « club-… »).
    host = d.split("//", 1)[-1]
    if "club" in n or host.startswith("club-") or "/club-" in d:
        return "club"
    return "assistant"


def _render_kit(name: str, badge: str, acc: str, acc2: str,
                url_accueil: str, tu: bool, preview_url: str = "") -> str:
    """Mail « boutique » pour un créateur TikTok (boutique + cours + cadeau).
    `preview_url` = vraie capture de SA boutique en ligne (aperçu fidèle)."""
    if tu:
        hello = "Salut " + name + " 👋"
        h1b = "j'ai préparé une boutique à ta marque."
        cap = "Ta boutique, à ta marque, déjà en ligne."
        intro = ("J'ai regardé ton compte, et je t'ai préparé de quoi "
                 "<b>transformer ton audience en revenus</b>, sans que tu aies "
                 "rien à gérer. Le plus simple, c'est d'aller y jeter un œil.")
        b1 = ("🏪 &nbsp;<b>Une petite boutique à ta marque</b>, le lien à "
              "mettre dans ta bio")
        b2 = ("💸 &nbsp;<b>Un produit prêt à vendre</b>, un cours et un guide "
              "tirés de ton contenu")
        b3 = ("🎁 &nbsp;<b>Un cadeau gratuit</b> qui transforme tes vues en "
              "e-mails à toi")
        cta = "Découvrir ta boutique →"
        offer = ("Tout est déjà prêt, à ta marque, fait à partir de ton "
                 "contenu. Toi tu crées, je m'occupe du reste. Si l'idée te "
                 "plaît, je t'explique tout avec plaisir.")
    else:
        hello = "Bonjour " + name + " 👋"
        h1b = "j'ai préparé une boutique à votre marque."
        cap = "Votre boutique, à votre marque, déjà en ligne."
        intro = ("J'ai regardé votre compte, et je vous ai préparé de quoi "
                 "<b>transformer votre audience en revenus</b>, sans que vous "
                 "ayez rien à gérer. Le plus simple, c'est d'aller y jeter un "
                 "œil.")
        b1 = ("🏪 &nbsp;<b>Une petite boutique à votre marque</b>, le lien à "
              "mettre dans votre bio")
        b2 = ("💸 &nbsp;<b>Un produit prêt à vendre</b>, un cours et un guide "
              "tirés de votre contenu")
        b3 = ("🎁 &nbsp;<b>Un cadeau gratuit</b> qui transforme vos vues en "
              "e-mails à vous")
        cta = "Découvrir votre boutique →"
        offer = ("Tout est déjà prêt, à votre marque, fait à partir de votre "
                 "contenu. Vous créez, je m'occupe du reste. Si l'idée vous "
                 "plaît, je vous explique tout avec plaisir.")
    h1b = _nowidow(h1b); intro = _nowidow(intro)
    b1 = _nowidow(b1); b2 = _nowidow(b2); b3 = _nowidow(b3); offer = _nowidow(offer)
    img_row = ""
    if preview_url:
        img_row = (
            '<tr><td style="padding:22px 38px 0;">'
            f'<a href="{url_accueil}" style="text-decoration:none;">'
            f'<img src="{preview_url}" width="524" alt="" style="width:100%;'
            'display:block;border-radius:12px;border:1px solid #e5e7eb;"></a>'
            '<p style="margin:12px 0 0;font-size:13px;color:#6b7280;'
            f'text-align:center;">{cap}</p></td></tr>')
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#eef1f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#eef1f5;">
<tr><td align="center" style="padding:30px 12px;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" style="max-width:600px;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 10px 34px rgba(15,23,42,.10);">
    <tr><td style="padding:34px 38px 6px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="padding-right:13px;">{badge}</td>
        <td style="font-size:14px;color:#6b7280;line-height:1.3;">Préparé pour vous par<br><b style="color:#111827;font-size:15px;">Triskell Studio</b></td>
      </tr></table>
      <h1 style="margin:22px 0 10px;font-size:25px;line-height:1.25;color:#0f172a;">{hello}<br>{h1b}</h1>
      <p style="margin:0;font-size:16px;line-height:1.6;color:#374151;">{intro}</p>
    </td></tr>
    {img_row}
    <tr><td style="padding:16px 38px 0;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
        <tr><td style="padding:9px 0;font-size:15px;color:#374151;line-height:1.5;">{b1}</td></tr>
        <tr><td style="padding:9px 0;font-size:15px;color:#374151;line-height:1.5;">{b2}</td></tr>
        <tr><td style="padding:9px 0;font-size:15px;color:#374151;line-height:1.5;">{b3}</td></tr>
      </table>
    </td></tr>
    <tr><td align="center" style="padding:26px 38px 6px;">
      <a href="{url_accueil}" style="display:inline-block;background:linear-gradient(135deg,{acc},{acc2});color:#fff;padding:15px 30px;border-radius:10px;text-decoration:none;font-weight:800;font-size:16px;">{cta}</a>
    </td></tr>
    <tr><td style="padding:20px 38px 34px;">
      <p style="margin:0;font-size:14.5px;line-height:1.6;color:#6b7280;">{offer}</p>
      <p style="margin:16px 0 0;font-size:14.5px;color:#374151;">Au plaisir,<br><b>Triskell Studio</b></p>
    </td></tr>
  </table>
</td></tr>
</table>
</body></html>"""


def _render_club(name: str, badge: str, acc: str, acc2: str,
                 url_club: str, preview_url: str, tu: bool) -> str:
    """Mail « club » pour un créateur Instagram : un club mensuel à sa marque
    (rendez-vous mensuel + direct + communauté + abonnement). L'aperçu est une
    vraie capture de SON site de club (preview_url), jamais une image absente."""
    if tu:
        hello = "Salut " + name + " 👋"
        h1b = "j'ai préparé ton club, à ta marque."
        intro = ("J'ai regardé ton compte, et j'ai préparé un moyen de "
                 "<b>transformer ton audience en revenus réguliers</b>, sans "
                 "que tu aies rien à gérer. Le plus simple, c'est de te montrer "
                 "ça directement.")
        cap = "Ton club, à ta marque, déjà en ligne."
        detail = "Voilà ce qu'il y a dedans."
        d1 = ("🗓️ &nbsp;<b>Un rendez-vous chaque mois</b>, un cours filmé "
              "étape par étape")
        d2 = ("🔴 &nbsp;<b>Un direct avec toi</b>, où ta communauté pose ses "
              "questions")
        d3 = ("👥 &nbsp;<b>Une communauté</b> qui partage ses projets et "
              "avance avec toi")
        d4 = ("💰 &nbsp;<b>Un abonnement</b>, où ta communauté te reverse "
              "chaque mois, pendant que je m'occupe de tout le reste")
        cta = "Découvrir ton club →"
        offer = ("Tout est déjà prêt, à ta marque, fait à partir de ton "
                 "contenu. Toi tu crées, je m'occupe du reste. Si l'idée te "
                 "plaît, je t'explique tout avec plaisir.")
    else:
        hello = "Bonjour " + name + " 👋"
        h1b = "j'ai préparé votre club, à votre marque."
        intro = ("J'ai regardé votre compte, et j'ai préparé un moyen de "
                 "<b>transformer votre audience en revenus réguliers</b>, sans "
                 "que vous ayez rien à gérer. Le plus simple, c'est de vous "
                 "montrer ça directement.")
        cap = "Votre club, à votre marque, déjà en ligne."
        detail = "Voilà ce qu'il y a dedans."
        d1 = ("🗓️ &nbsp;<b>Un rendez-vous chaque mois</b>, un cours filmé "
              "étape par étape")
        d2 = ("🔴 &nbsp;<b>Un direct avec vous</b>, où votre communauté pose "
              "ses questions")
        d3 = ("👥 &nbsp;<b>Une communauté</b> qui partage ses projets et "
              "avance avec vous")
        d4 = ("💰 &nbsp;<b>Un abonnement</b>, où votre communauté vous reverse "
              "chaque mois, pendant que je m'occupe de tout le reste")
        cta = "Découvrir votre club →"
        offer = ("Tout est déjà prêt, à votre marque, fait à partir de votre "
                 "contenu. Vous créez, je m'occupe du reste. Si l'idée vous "
                 "plaît, je vous explique tout avec plaisir.")
    h1b = _nowidow(h1b); intro = _nowidow(intro); detail = _nowidow(detail)
    d1 = _nowidow(d1); d2 = _nowidow(d2); d3 = _nowidow(d3); d4 = _nowidow(d4)
    offer = _nowidow(offer)
    img_row = ""
    if preview_url:
        img_row = (
            '<tr><td style="padding:24px 38px 0;">'
            f'<a href="{url_club}" style="text-decoration:none;">'
            f'<img src="{preview_url}" width="524" alt="" style="width:100%;'
            'display:block;border-radius:12px;border:1px solid #e5e7eb;"></a>'
            '<p style="margin:12px 0 0;font-size:13px;color:#6b7280;'
            f'text-align:center;">{cap}</p></td></tr>')
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#eef1f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#eef1f5;">
<tr><td align="center" style="padding:30px 12px;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" style="max-width:600px;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 10px 34px rgba(15,23,42,.10);">
    <tr><td style="padding:34px 38px 6px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="padding-right:13px;">{badge}</td>
        <td style="font-size:14px;color:#6b7280;line-height:1.3;">Préparé pour vous par<br><b style="color:#111827;font-size:15px;">Triskell Studio</b></td>
      </tr></table>
      <h1 style="margin:22px 0 10px;font-size:25px;line-height:1.25;color:#0f172a;">{hello}<br>{h1b}</h1>
      <p style="margin:0;font-size:16px;line-height:1.6;color:#374151;">{intro}</p>
    </td></tr>
    {img_row}
    <tr><td style="padding:22px 38px 0;">
      <p style="margin:0 0 12px;font-size:15.5px;color:#0f172a;font-weight:700;">{detail}</p>
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
        <tr><td style="padding:9px 0;font-size:15px;color:#374151;line-height:1.5;">{d1}</td></tr>
        <tr><td style="padding:9px 0;font-size:15px;color:#374151;line-height:1.5;">{d2}</td></tr>
        <tr><td style="padding:9px 0;font-size:15px;color:#374151;line-height:1.5;">{d3}</td></tr>
        <tr><td style="padding:9px 0;font-size:15px;color:#374151;line-height:1.5;">{d4}</td></tr>
      </table>
    </td></tr>
    <tr><td align="center" style="padding:28px 38px 6px;">
      <a href="{url_club}" style="display:inline-block;background:linear-gradient(135deg,{acc},{acc2});color:#fff;padding:15px 30px;border-radius:10px;text-decoration:none;font-weight:800;font-size:16px;">{cta}</a>
    </td></tr>
    <tr><td style="padding:18px 38px 34px;">
      <p style="margin:0;font-size:14.5px;line-height:1.6;color:#6b7280;">{offer}</p>
      <p style="margin:16px 0 0;font-size:14.5px;color:#374151;">Au plaisir,<br><b>Triskell Studio</b></p>
    </td></tr>
  </table>
</td></tr>
</table>
</body></html>"""


def render(name: str, demo_url: str, accent: str = "#6366F1",
           accent2: str = "#4F46E5", tu: bool = True, angle: str = "",
           kind: str = "assistant", preview_url: str = "") -> str:
    """Retourne le corps HTML du mail pour un créateur. `kind`='kit' (TikTok :
    boutique + cours + cadeau), 'club' (Instagram : club mensuel à la marque),
    'assistant' sinon (YouTube : assistant IA + quiz). `preview_url` (clubs) =
    image hébergée de la 1re vue du VRAI site du créateur (aperçu fidèle)."""
    base = (demo_url or "").rstrip("/")
    badge = _badge_html()
    name = _esc(name)
    acc = accent or "#6366F1"
    acc2 = accent2 or "#4F46E5"
    url_accueil = base + "/accueil.html"
    url_quiz = base + "/quiz.html"
    img_assistant = base + "/_mail_assistant.png"
    img_quiz = base + "/_mail_quiz.png"

    if kind == "kit":
        return _render_kit(name, badge, acc, acc2, url_accueil, tu, preview_url)
    if kind == "club":
        return _render_club(name, badge, acc, acc2, base, preview_url, tu)

    if tu:
        t = {
            "hello": "Salut " + name + " 👋",
            "h1b": "j'ai construit tout un espace à ta marque.",
            "intro": ("J'ai regardé ta chaîne, et j'ai préparé un moyen de "
                      "<b>transformer ton audience en revenus</b>, sans que tu "
                      "aies rien à gérer. Le plus simple, c'est de te montrer "
                      "ça en images."),
            "hero": ("<b>Ton assistant IA, à ta marque.</b> Il répond à ta "
                     "communauté <b>24h/24</b>, avec ta méthode, tirée de tes "
                     "vidéos."),
            "detail": "Et autour, j'ai aussi préparé tout ça pour toi.",
            "d1": ("🎮 &nbsp;<b>Un quiz</b> « teste ton niveau » qui amuse ta "
                   "communauté et la ramène vers toi"),
            "d2": ("🔍 &nbsp;<b>Une analyse de ta chaîne</b> et <b>10 idées de "
                   "vidéos</b>, offertes, rien que pour toi"),
            "d3": ("💰 &nbsp;<b>Un revenu récurrent presque passif</b>, où ta "
                   "communauté s'abonne et te reverse une part, pendant que je "
                   "m'occupe de tout le reste"),
            "quizcap": ("Un aperçu du quiz, à ta marque, avec tes vraies "
                        "vidéos et tes couleurs."),
            "cta": "Découvrir tout ton espace →",
            "offer": ("Tout est déjà prêt, à ta marque, fait à partir de tes "
                      "vidéos. Toi tu fais ton contenu, je m'occupe du reste. "
                      "Si l'idée te plaît, je t'explique tout avec plaisir."),
        }
    else:
        t = {
            "hello": "Bonjour " + name + " 👋",
            "h1b": "j'ai construit tout un espace à votre marque.",
            "intro": ("J'ai regardé votre chaîne, et j'ai préparé un moyen de "
                      "<b>transformer votre audience en revenus</b>, sans que "
                      "vous ayez rien à gérer. Le plus simple, c'est de vous "
                      "montrer ça en images."),
            "hero": ("<b>Votre assistant IA, à votre marque.</b> Il répond à "
                     "votre communauté <b>24h/24</b>, avec votre méthode, "
                     "tirée de vos vidéos."),
            "detail": "Et autour, j'ai aussi préparé tout ça pour vous.",
            "d1": ("🎮 &nbsp;<b>Un quiz</b> « testez votre niveau » qui amuse "
                   "votre communauté et la ramène vers vous"),
            "d2": ("🔍 &nbsp;<b>Une analyse de votre chaîne</b> et <b>10 idées "
                   "de vidéos</b>, offertes, rien que pour vous"),
            "d3": ("💰 &nbsp;<b>Un revenu récurrent presque passif</b>, où "
                   "votre communauté s'abonne et vous reverse une part, "
                   "pendant que je m'occupe de tout le reste"),
            "quizcap": ("Un aperçu du quiz, à votre marque, avec vos vraies "
                        "vidéos et vos couleurs."),
            "cta": "Découvrir tout votre espace →",
            "offer": ("Tout est déjà prêt, à votre marque, fait à partir de "
                      "vos vidéos. Vous faites votre contenu, je m'occupe du "
                      "reste. Si l'idée vous plaît, je vous explique tout avec "
                      "plaisir."),
        }

    angle = (angle or "").strip()
    if angle:
        t["d3"] = "💰 &nbsp;" + _esc(angle)

    for _k in ("h1b", "intro", "hero", "detail", "d1", "d2", "d3",
               "quizcap", "offer"):
        if t.get(_k):
            t[_k] = _nowidow(t[_k])

    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#eef1f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#eef1f5;">
<tr><td align="center" style="padding:30px 12px;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" style="max-width:600px;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 10px 34px rgba(15,23,42,.10);">
    <tr><td style="padding:34px 38px 6px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="padding-right:13px;">{badge}</td>
        <td style="font-size:14px;color:#6b7280;line-height:1.3;">Préparé pour vous par<br><b style="color:#111827;font-size:15px;">Triskell Studio</b></td>
      </tr></table>
      <h1 style="margin:22px 0 10px;font-size:25px;line-height:1.25;color:#0f172a;">{t['hello']}<br>{t['h1b']}</h1>
      <p style="margin:0;font-size:16px;line-height:1.6;color:#374151;">{t['intro']}</p>
    </td></tr>
    <tr><td style="padding:24px 38px 0;">
      <a href="{url_accueil}" style="text-decoration:none;"><img src="{img_assistant}" width="524" alt="" style="width:100%;display:block;border-radius:12px;border:1px solid #e5e7eb;"></a>
      <p style="margin:14px 0 0;font-size:15.5px;line-height:1.55;color:#374151;">{t['hero']}</p>
    </td></tr>
    <tr><td style="padding:22px 38px 0;">
      <p style="margin:0 0 12px;font-size:15.5px;color:#0f172a;font-weight:700;">{t['detail']}</p>
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
        <tr><td style="padding:9px 0;font-size:15px;color:#374151;line-height:1.5;">{t['d1']}</td></tr>
        <tr><td style="padding:9px 0;font-size:15px;color:#374151;line-height:1.5;">{t['d2']}</td></tr>
        <tr><td style="padding:9px 0;font-size:15px;color:#374151;line-height:1.5;">{t['d3']}</td></tr>
      </table>
    </td></tr>
    <tr><td style="padding:18px 38px 0;">
      <a href="{url_quiz}" style="text-decoration:none;"><img src="{img_quiz}" width="524" alt="" style="width:100%;display:block;border-radius:12px;border:1px solid #e5e7eb;"></a>
      <p style="margin:10px 0 0;font-size:13px;color:#6b7280;text-align:center;">{t['quizcap']}</p>
    </td></tr>
    <tr><td align="center" style="padding:28px 38px 6px;">
      <a href="{url_accueil}" style="display:inline-block;background:linear-gradient(135deg,{acc},{acc2});color:#fff;padding:15px 30px;border-radius:10px;text-decoration:none;font-weight:800;font-size:16px;">{t['cta']}</a>
    </td></tr>
    <tr><td style="padding:18px 38px 34px;">
      <p style="margin:0;font-size:14.5px;line-height:1.6;color:#6b7280;">{t['offer']}</p>
      <p style="margin:16px 0 0;font-size:14.5px;color:#374151;">Au plaisir,<br><b>Triskell Studio</b></p>
    </td></tr>
  </table>
</td></tr>
</table>
</body></html>"""


def render_text(name: str, demo_url: str, tu: bool = True,
                angle: str = "", kind: str = "assistant") -> str:
    """Version TEXTE BRUT du mail (secours `text/plain`), cohérente avec le
    rendu HTML et sans tic d'IA (pas de « : » d'annonce, pas de tiret
    cadratin, pas de « sans pression »). `angle` remplace la 3e ligne pour
    les créateurs qui vendent déjà (pitch complémentaire). `kind`='kit' pour
    les créateurs TikTok (offre boutique)."""
    base = (demo_url or "").rstrip("/")
    url = base + "/accueil.html"
    angle = (angle or "").strip()
    if kind == "kit":
        if tu:
            return (
                f"Salut {name},\n\n"
                "J'ai regardé ton compte et je t'ai préparé une petite "
                "boutique à ta marque, pour transformer ton audience en "
                "revenus sans que tu aies rien à gérer.\n\n"
                "Voici ce qu'il y a dedans.\n"
                "- Une petite boutique à ta marque, le lien à mettre dans ta "
                "bio\n"
                "- Un produit prêt à vendre, un cours et un guide tirés de ton "
                "contenu\n"
                "- Un cadeau gratuit qui transforme tes vues en e-mails à "
                "toi\n\n"
                "Tu peux tout découvrir ici.\n"
                f"{url}\n\n"
                "Tout est déjà prêt, à ta marque. Toi tu crées, je m'occupe du "
                "reste. Si l'idée te plaît, je t'explique tout avec plaisir.\n\n"
                "Au plaisir,\nTriskell Studio"
            )
        return (
            f"Bonjour {name},\n\n"
            "J'ai regardé votre compte et je vous ai préparé une petite "
            "boutique à votre marque, pour transformer votre audience en "
            "revenus sans que vous ayez rien à gérer.\n\n"
            "Voici ce qu'il y a dedans.\n"
            "- Une petite boutique à votre marque, le lien à mettre dans votre "
            "bio\n"
            "- Un produit prêt à vendre, un cours et un guide tirés de votre "
            "contenu\n"
            "- Un cadeau gratuit qui transforme vos vues en e-mails à vous\n\n"
            "Vous pouvez tout découvrir ici.\n"
            f"{url}\n\n"
            "Tout est déjà prêt, à votre marque. Vous créez, je m'occupe du "
            "reste. Si l'idée vous plaît, je vous explique tout avec "
            "plaisir.\n\n"
            "Au plaisir,\nTriskell Studio"
        )
    if kind == "club":
        if tu:
            return (
                f"Salut {name},\n\n"
                "J'ai regardé ton compte et je t'ai préparé un club mensuel à "
                "ta marque, pour transformer ton audience en revenus réguliers "
                "sans que tu aies rien à gérer.\n\n"
                "Voici ce qu'il y a dedans.\n"
                "- Un rendez-vous chaque mois, un cours filmé étape par étape\n"
                "- Un direct avec toi, où ta communauté pose ses questions\n"
                "- Une communauté qui partage ses projets et avance avec toi\n"
                "- Un abonnement, où ta communauté te reverse chaque mois, "
                "pendant que je m'occupe de tout le reste\n\n"
                "Tu peux tout découvrir ici.\n"
                f"{base}\n\n"
                "Tout est déjà prêt, à ta marque. Toi tu crées, je m'occupe du "
                "reste. Si l'idée te plaît, je t'explique tout avec plaisir.\n\n"
                "Au plaisir,\nTriskell Studio"
            )
        return (
            f"Bonjour {name},\n\n"
            "J'ai regardé votre compte et je vous ai préparé un club mensuel à "
            "votre marque, pour transformer votre audience en revenus réguliers "
            "sans que vous ayez rien à gérer.\n\n"
            "Voici ce qu'il y a dedans.\n"
            "- Un rendez-vous chaque mois, un cours filmé étape par étape\n"
            "- Un direct avec vous, où votre communauté pose ses questions\n"
            "- Une communauté qui partage ses projets et avance avec vous\n"
            "- Un abonnement, où votre communauté vous reverse chaque mois, "
            "pendant que je m'occupe de tout le reste\n\n"
            "Vous pouvez tout découvrir ici.\n"
            f"{base}\n\n"
            "Tout est déjà prêt, à votre marque. Vous créez, je m'occupe du "
            "reste. Si l'idée vous plaît, je vous explique tout avec plaisir.\n\n"
            "Au plaisir,\nTriskell Studio"
        )
    if tu:
        d3 = angle or ("Un revenu récurrent presque passif, où ta communauté "
                       "s'abonne et te reverse une part, pendant que je "
                       "m'occupe de tout le reste")
        return (
            f"Salut {name},\n\n"
            "J'ai regardé ta chaîne et j'ai préparé tout un espace à ta "
            "marque, pour transformer ton audience en revenus sans que tu "
            "aies rien à gérer.\n\n"
            "Le cœur, c'est un assistant IA à ta marque. Il répond à ta "
            "communauté 24h/24, avec ta méthode tirée de tes vidéos.\n\n"
            "Et autour, j'ai aussi préparé tout ça pour toi.\n"
            "- Un quiz « teste ton niveau » qui amuse ta communauté et la "
            "ramène vers toi\n"
            "- Une analyse de ta chaîne et 10 idées de vidéos, offertes\n"
            "- " + d3 + "\n\n"
            "Tu peux tout découvrir ici.\n"
            f"{url}\n\n"
            "Tout est déjà prêt, à ta marque, fait à partir de tes vidéos. "
            "Toi tu fais ton contenu, je m'occupe du reste. Si l'idée te "
            "plaît, je t'explique tout avec plaisir.\n\n"
            "Au plaisir,\nTriskell Studio"
        )
    d3 = angle or ("Un revenu récurrent presque passif, où votre communauté "
                   "s'abonne et vous reverse une part, pendant que je "
                   "m'occupe de tout le reste")
    return (
        f"Bonjour {name},\n\n"
        "J'ai regardé votre chaîne et j'ai préparé tout un espace à votre "
        "marque, pour transformer votre audience en revenus sans que vous "
        "ayez rien à gérer.\n\n"
        "Le cœur, c'est un assistant IA à votre marque. Il répond à votre "
        "communauté 24h/24, avec votre méthode tirée de vos vidéos.\n\n"
        "Et autour, j'ai aussi préparé tout ça pour vous.\n"
        "- Un quiz « testez votre niveau » qui amuse votre communauté et la "
        "ramène vers vous\n"
        "- Une analyse de votre chaîne et 10 idées de vidéos, offertes\n"
        "- " + d3 + "\n\n"
        "Vous pouvez tout découvrir ici.\n"
        f"{url}\n\n"
        "Tout est déjà prêt, à votre marque, fait à partir de vos vidéos. "
        "Vous faites votre contenu, je m'occupe du reste. Si l'idée vous "
        "plaît, je vous explique tout avec plaisir.\n\n"
        "Au plaisir,\nTriskell Studio"
    )


def accent_from_notes(notes: str):
    """Couleurs de marque rangées dans les notes de la fiche créateur, au
    format `[brand:#22B8CF,#0E8C9E]`. Retourne ("", "") si absent."""
    import re
    m = re.search(r"\[brand:(#[0-9A-Fa-f]{3,8}),\s*(#[0-9A-Fa-f]{3,8})\]",
                  notes or "")
    return (m.group(1), m.group(2)) if m else ("", "")


def angle_from_notes(notes: str) -> str:
    """Phrase d'angle personnalisée rangée dans les notes de la fiche, au
    format `[angle: ...]` (jusqu'au `]`). Retourne "" si absent."""
    import re
    m = re.search(r"\[angle:\s*(.+?)\]", notes or "", re.DOTALL)
    return m.group(1).strip() if m else ""


def default_pitch(tu: bool = True) -> str:
    """Phrase de monétisation standard (la 3e ligne du mail), en texte brut.
    Sert de base à la 2e IA pour noter / peaufiner le pitch des créateurs qui
    n'ont pas d'angle propre."""
    if tu:
        return ("Un revenu récurrent presque passif, où ta communauté "
                "s'abonne et te reverse une part, pendant que je m'occupe de "
                "tout le reste")
    return ("Un revenu récurrent presque passif, où votre communauté "
            "s'abonne et vous reverse une part, pendant que je m'occupe de "
            "tout le reste")
