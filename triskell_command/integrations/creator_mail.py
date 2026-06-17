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


def render(name: str, demo_url: str, accent: str = "#6366F1",
           accent2: str = "#4F46E5", tu: bool = True, angle: str = "") -> str:
    """Retourne le corps HTML du mail pour un créateur."""
    base = (demo_url or "").rstrip("/")
    name = _esc(name)
    acc = accent or "#6366F1"
    acc2 = accent2 or "#4F46E5"
    url_accueil = base + "/accueil.html"
    url_quiz = base + "/quiz.html"
    img_avatar = base + "/brand_avatar.jpg"
    img_assistant = base + "/_mail_assistant.png"
    img_quiz = base + "/_mail_quiz.png"

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
            "d3": ("💰 &nbsp;<b>De quoi monétiser ton audience</b>, avec un "
                   "abonnement pour ta communauté dont tu touches une part"),
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
            "d3": ("💰 &nbsp;<b>De quoi monétiser votre audience</b>, avec un "
                   "abonnement pour votre communauté dont vous touchez une "
                   "part"),
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
        <td style="padding-right:13px;"><img src="{img_avatar}" width="52" height="52" alt="" style="border-radius:50%;display:block;border:2px solid {acc};"></td>
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
                angle: str = "") -> str:
    """Version TEXTE BRUT du mail (secours `text/plain`), cohérente avec le
    rendu HTML et sans tic d'IA (pas de « : » d'annonce, pas de tiret
    cadratin, pas de « sans pression »). `angle` remplace la 3e ligne pour
    les créateurs qui vendent déjà (pitch complémentaire)."""
    base = (demo_url or "").rstrip("/")
    url = base + "/accueil.html"
    angle = (angle or "").strip()
    if tu:
        d3 = angle or ("De quoi monétiser ton audience, avec un abonnement "
                       "pour ta communauté dont tu touches une part")
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
    d3 = angle or ("De quoi monétiser votre audience, avec un abonnement "
                   "pour votre communauté dont vous touchez une part")
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
