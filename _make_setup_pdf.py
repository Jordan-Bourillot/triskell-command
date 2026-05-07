"""Génère le PDF de consignes pour le frère de Jordan."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


OUT = Path(r"C:\Users\jorda\OneDrive\Bureau\Triskell Studio\Triskell Command\Configuration_Triskell_Command.pdf")


# ── JWT AlphaCast — long-lived (1 an, expire fin avril 2027) ────────
# Lié au compte partagé Triskell Studio (contact@triskell-studio.fr).
# Jordan + Thomas utilisent le même token, même identité côté API.
ALPHACAST_JWT = (
    "eyJhbGciOiJSUzI1NiIsImNhdCI6ImNsX0I3ZDRQRDIyMkFBQSIsImtpZCI6Imluc18zREg1MGswTHVMa"
    "DJUR2dvTFNBMDI3Um1CZU0iLCJ0eXAiOiJKV1QifQ.eyJleHAiOjE4MDk1MjkzNDIsImlhdCI6MTc3Nzk"
    "5MzM0MiwiaXNzIjoiaHR0cHM6Ly9pbW1lbnNlLXlhay0yLmNsZXJrLmFjY291bnRzLmRldiIsImp0aSI6"
    "ImIyYmZkYTBlOThiNTI0MDY3MzBhIiwibmJmIjoxNzc3OTkzMzM3LCJzdWIiOiJ1c2VyXzNESDY2ZFN6Z"
    "zFHaEtIY0FEaENWWmFUajk3VSJ9.jEyP4ATI2_j3miVWUMmcfK5FW86V2GWR8-YBBJ8VSaU4xJeeVK-1w"
    "p3Lb_B2tMRYaLJOSvNpXbTna0QSOE9Z06-i8L2XWXbO1tAfdArTs5OuP7W-ROt_01WWgrP8f2lZ-eVz7t"
    "sp1tIL_030PLwLkqEqiFnL6tJDPMTRUAPHV1QghuMCCtuIkLtcmP-W0BQWiprAV5lLYJvCqbmgcIvkIGV"
    "Tw5qdtyo9IP1wSQCqIMACnuD9S4mnsagpnXzVbO72hk_iGBQ5pSIGVYPpOAXrdJTvA1AFE_gsskNgVoi1"
    "ON8FTRTXTybU21KpQ69OO4FXjRnb4IBYsslS7KK_kH-XUA"
)


# ── Palette Triskell-ish ────────────────────────────────────────────
INDIGO = colors.HexColor("#4F46E5")
INK = colors.HexColor("#0F172A")
MUTED = colors.HexColor("#64748B")
PANEL = colors.HexColor("#F1F5F9")
BORDER = colors.HexColor("#CBD5E1")


# ── Styles ──────────────────────────────────────────────────────────
base = getSampleStyleSheet()

title_style = ParagraphStyle(
    "title",
    parent=base["Title"],
    fontName="Helvetica-Bold",
    fontSize=22,
    leading=26,
    textColor=INDIGO,
    alignment=TA_LEFT,
    spaceAfter=6,
)
subtitle_style = ParagraphStyle(
    "subtitle",
    parent=base["Normal"],
    fontName="Helvetica",
    fontSize=11,
    leading=14,
    textColor=MUTED,
    spaceAfter=18,
)
h1_style = ParagraphStyle(
    "h1",
    parent=base["Heading1"],
    fontName="Helvetica-Bold",
    fontSize=15,
    leading=18,
    textColor=INDIGO,
    spaceBefore=14,
    spaceAfter=6,
)
h2_style = ParagraphStyle(
    "h2",
    parent=base["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=12,
    leading=15,
    textColor=INK,
    spaceBefore=10,
    spaceAfter=4,
)
body_style = ParagraphStyle(
    "body",
    parent=base["Normal"],
    fontName="Helvetica",
    fontSize=10.5,
    leading=14,
    textColor=INK,
    spaceAfter=6,
)
small_style = ParagraphStyle(
    "small",
    parent=base["Normal"],
    fontName="Helvetica",
    fontSize=9.5,
    leading=12,
    textColor=MUTED,
    spaceAfter=4,
)
mono_style = ParagraphStyle(
    "mono",
    parent=base["Normal"],
    fontName="Courier",
    fontSize=9,
    leading=12,
    textColor=INK,
    spaceAfter=4,
)
mono_jwt_style = ParagraphStyle(
    "mono_jwt",
    parent=base["Normal"],
    fontName="Courier",
    fontSize=6.5,
    leading=8,
    textColor=INK,
    spaceAfter=4,
    wordWrap="CJK",  # casse au caractère, pas au mot — pour les longs tokens
)
warn_style = ParagraphStyle(
    "warn",
    parent=base["Normal"],
    fontName="Helvetica-Bold",
    fontSize=10,
    leading=13,
    textColor=colors.HexColor("#B91C1C"),
    backColor=colors.HexColor("#FEE2E2"),
    borderColor=colors.HexColor("#FCA5A5"),
    borderWidth=1,
    borderPadding=8,
    spaceAfter=10,
)


def bullets(items, style=body_style):
    """Crée une liste à puces."""
    return ListFlowable(
        [ListItem(Paragraph(it, style), leftIndent=4) for it in items],
        bulletType="bullet",
        start="•",
        leftIndent=14,
        bulletFontSize=8,
        spaceBefore=2,
        spaceAfter=8,
    )


def kv_table(rows: list[tuple[str, str]]) -> Table:
    """Tableau clé/valeur stylé pour les paramètres SMTP."""
    data = [[Paragraph(f"<b>{k}</b>", body_style), Paragraph(v, mono_style)]
            for k, v in rows]
    t = Table(data, colWidths=[5.5 * cm, 11 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


# ── Contenu ─────────────────────────────────────────────────────────
def build_story():
    s = []

    s.append(Paragraph("Configuration Triskell Command", title_style))
    s.append(Paragraph(
        "Guide d'installation et de paramétrage pas à pas — "
        "à lire en entier avant de cliquer quoi que ce soit.",
        subtitle_style,
    ))

    s.append(Paragraph(
        "⚠ CONFIDENTIEL — Ce document contient un JWT d'accès à l'API "
        "Triskell Studio (compte partagé). Ne le partage avec personne d'autre, "
        "ne le mets pas dans Drive/Dropbox/Slack public. Supprime-le quand t'as "
        "fini la config.",
        warn_style,
    ))

    # ── 1. Avant de commencer ─────────────────────────────────────
    s.append(Paragraph("1.  Avant de commencer", h1_style))
    s.append(Paragraph(
        "Avant de te lancer, prépare les éléments suivants. Si tu n'as pas tout, "
        "rassemble-les d'abord — ça t'évitera d'aller-retour dans les Réglages :",
        body_style,
    ))
    s.append(bullets([
        "<b>L'installateur</b> <font name='Courier'>TriskellCommand_Setup.exe</font> que Jordan t'a transmis.",
        "<b>Tes identifiants email</b> (Gmail recommandé) — tu auras besoin d'un <i>mot de passe d'application</i>, pas ton mot de passe Google habituel (procédure à l'étape 3).",
        "<b>Une clé API IA</b> — Anthropic recommandé. Tu peux la créer sur "
        "<font color='#4F46E5'>console.anthropic.com/settings/keys</font> "
        "(prévois un budget de 5–10 € pour démarrer, ça dure plusieurs semaines).",
        "<b>Le JWT AlphaCast</b> — déjà fourni dans ce document (section 3.3). "
        "C'est ce qui te connecte au compte Triskell Studio partagé avec Jordan.",
    ]))

    # ── 2. Installation ───────────────────────────────────────────
    s.append(Paragraph("2.  Installation", h1_style))
    s.append(Paragraph(
        "Rien de sorcier — l'installateur est un classique Windows :",
        body_style,
    ))
    s.append(bullets([
        "Double-clique sur <font name='Courier'>TriskellCommand_Setup.exe</font>.",
        "Suis l'assistant (Suivant → Suivant → Installer). Si Windows demande "
        "des droits admin, accepte ; sinon il s'installe dans ton "
        "<font name='Courier'>%LOCALAPPDATA%</font> sans privilèges.",
        "Lance l'app depuis le raccourci Bureau ou le menu Démarrer.",
    ]))

    # ── 3. Configuration ──────────────────────────────────────────
    s.append(Paragraph("3.  Configuration des Réglages", h1_style))
    s.append(Paragraph(
        "Dans la sidebar gauche, clique sur <b>Réglages</b> (en bas, icône engrenage). "
        "Tout se passe dans cette vue. Quand t'as fini de remplir : <b>« Enregistrer »</b> "
        "en haut à droite.",
        body_style,
    ))

    s.append(Paragraph("3.1  Services IA", h2_style))
    s.append(Paragraph(
        "Colle au minimum ta clé Anthropic. Les autres providers sont optionnels.",
        body_style,
    ))
    s.append(bullets([
        "<b>Anthropic (Claude)</b> — clé sur "
        "<font color='#4F46E5'>console.anthropic.com/settings/keys</font>. "
        "Format : commence par <font name='Courier'>sk-ant-…</font>",
        "Les autres (OpenAI, Google, Mistral, xAI) — tu peux les ajouter plus tard si besoin.",
    ]))

    s.append(Paragraph("3.2  Email & Outreach (SMTP / IMAP)", h2_style))
    s.append(Paragraph(
        "C'est ce qui te permet d'envoyer des prospections et de détecter les réponses. "
        "<b>Étape critique pour Gmail</b> : tu dois créer un <b>mot de passe d'application</b> "
        "(16 caractères) — Google refuse ton mot de passe habituel pour des raisons de sécurité.",
        body_style,
    ))
    s.append(Paragraph(
        "<b>Comment générer un mot de passe d'application Gmail :</b>",
        body_style,
    ))
    s.append(bullets([
        "Va sur <font color='#4F46E5'>myaccount.google.com/apppasswords</font> "
        "(connecté avec ton compte).",
        "Si la page demande la double authentification, active-la — c'est obligatoire.",
        "Crée un mot de passe nommé « Triskell Command ». Google te donne 16 caractères. "
        "<b>Copie-les sans les espaces.</b>",
        "Tu ne pourras jamais le revoir — si tu le perds, tu en regénères un nouveau.",
    ]))
    s.append(Paragraph("Champs à remplir dans Réglages > Email & Outreach :", body_style))
    s.append(kv_table([
        ("SMTP host", "smtp.gmail.com"),
        ("SMTP port", "587"),
        ("SMTP user", "ton.adresse@gmail.com"),
        ("SMTP password", "le mot de passe d'application 16 car. (sans espaces)"),
        ("IMAP host", "imap.gmail.com"),
        ("IMAP port", "993"),
        ("IMAP user", "ton.adresse@gmail.com"),
        ("IMAP password", "le même mot de passe d'application"),
        ("From email", "ton.adresse@gmail.com"),
        ("From name", "Prénom Nom"),
        ("Mon prénom", "Prénom"),
        ("Signature", "ta signature mail (multi-lignes OK)"),
        ("Daily cap", "40"),
        ("Follow-up days", "5"),
    ]))

    s.append(Paragraph("3.3  Service AlphaCast (ex-Réseaux)", h2_style))
    s.append(Paragraph(
        "C'est le moteur derrière la vue <b>Publier</b> — il génère et publie sur "
        "LinkedIn / X / Bluesky de Triskell Studio. L'URL est déjà bonne par défaut, "
        "tu colles juste le JWT ci-dessous.",
        body_style,
    ))
    s.append(Paragraph(
        "<b>Compte partagé :</b> ce JWT t'identifie comme "
        "<font name='Courier'>contact@triskell-studio.fr</font> — donc Jordan et toi "
        "voyez le même workspace, les mêmes drafts, les mêmes statistiques. "
        "Les posts générés vont sur les comptes sociaux de Triskell Studio (pas tes "
        "comptes perso). C'est voulu : vous bossez sur la même image de marque.",
        small_style,
    ))
    s.append(Paragraph("URL de l'API :", body_style))
    s.append(Paragraph("https://reseauxapi-production.up.railway.app", mono_style))
    s.append(Paragraph("JWT Clerk (valide 1 an, expire fin avril 2027) :", body_style))
    s.append(Paragraph(ALPHACAST_JWT, mono_jwt_style))
    s.append(Paragraph(
        "<b>Comment le copier :</b> sélectionne tout le bloc ci-dessus (Ctrl+A "
        "marche dans la plupart des lecteurs PDF, sinon clic-glisse du début à la "
        "fin), Ctrl+C, puis colle dans Triskell Command. Vérifie qu'il n'y a pas "
        "d'espace ou de retour-ligne avant/après.",
        small_style,
    ))

    s.append(Paragraph("3.4  Sources (optionnel)", h2_style))
    s.append(bullets([
        "<b>Google Places API key</b> — uniquement si tu veux chercher des commerces "
        "locaux via la vue Prospects. Sinon, ignore : Sirene fonctionne sans clé.",
        "<b>YouTube / Twitch</b> — pareil, optionnels, ne touche pas si tu ne cherches "
        "pas de créateurs.",
    ]))

    s.append(Paragraph(
        "<b>Quand tu as tout rempli</b> → clique « <b>Enregistrer</b> » en haut. "
        "Tu verras une confirmation verte.",
        body_style,
    ))

    # ── 4. Premier test ───────────────────────────────────────────
    s.append(Paragraph("4.  Premier test", h1_style))
    s.append(Paragraph(
        "Avant de lancer une vraie campagne, vérifie que tout marche :",
        body_style,
    ))
    s.append(bullets([
        "<b>Vue Prospects</b> → clique « Nouvelle recherche » → choisis « Sirene » → "
        "entre un département (ex: 35) et un code NAF (ex: 56.10A pour la restauration), "
        "limite à 20 résultats. Tu devrais voir des prospects apparaître dans la table.",
        "<b>Vue Campagnes</b> → coche <b>« Dry-run »</b>, choisis le template "
        "<font name='Courier'>tpe_intro</font>, limite à 1 envoi, lance. Aucun mail n'est "
        "réellement envoyé en dry-run, mais tu vois le rendu.",
        "Si le dry-run passe vert, décoche dry-run et envoie 1 vrai email à toi-même "
        "pour vérifier le rendu côté destinataire.",
        "<b>Vue Publier</b> → clique « Tester la connexion ». Tu dois voir "
        "« ✅ AlphaCast : connecté ». Sinon, vérifie ton JWT.",
    ]))

    # ── 5. Auto-publish ───────────────────────────────────────────
    s.append(Paragraph("5.  Auto-publish réseaux sociaux", h1_style))
    s.append(Paragraph(
        "Triskell Command génère automatiquement des posts LinkedIn / X / Bluesky "
        "à partir de ton activité de prospection. Le principe :",
        body_style,
    ))
    s.append(bullets([
        "Quand tu envoies un <b>premier contact</b> depuis Campagnes (mode intro, "
        "pas relance), un compteur monte sur chaque plateforme.",
        "Au <b>seuil</b>, un draft de post sort tout seul dans la vue Publier. "
        "Cadences par défaut : <b>LinkedIn = 10</b>, <b>X = 3</b>, <b>Bluesky = 5</b> envois.",
        "Le draft mentionne discrètement le métier et la région du dernier prospect "
        "démarché — totalement anonymisé, jamais de nom ni d'adresse.",
        "Tu peux <b>relire et publier à la main</b>, ou activer le toggle "
        "« <b>Auto-publier</b> » dans la carte de chaque plateforme pour publier "
        "automatiquement.",
        "En haut de la vue Publier : <b>6 thèmes-boutons</b> (Avant/Après, Témoignage, "
        "Pourquoi un site, Mon process, Tarif transparent, Coulisses). Clique en un "
        "pour décider du ton du prochain draft, ou laisse en mode Aléatoire.",
        "<b>Plafonds quotidiens</b> évitent le sur-postage : LinkedIn = 1/jour, "
        "X = 5/jour, Bluesky = 2/jour. Réglable dans Réglages.",
    ]))
    s.append(Paragraph(
        "<i>Si tu veux un draft maintenant sans attendre le compteur, chaque carte "
        "plateforme a un bouton « Générer maintenant ».</i>",
        small_style,
    ))

    # ── 6. Si ça marche pas ───────────────────────────────────────
    s.append(Paragraph("6.  Si quelque chose ne marche pas", h1_style))

    s.append(Paragraph("« AlphaCast injoignable »", h2_style))
    s.append(bullets([
        "Vérifie que le <b>JWT</b> est bon dans Réglages > Service AlphaCast (pas d'espace "
        "avant/après, copié dans son intégralité depuis ce document).",
        "Re-clique sur « <b>Tester la connexion</b> » dans la vue Publier après "
        "avoir enregistré.",
        "Si ça passe toujours pas après avril 2027 → le JWT a expiré. Demande à "
        "Jordan d'en regénérer un nouveau (script <font name='Courier'>tools/generate_clerk_jwt.py</font>).",
        "Vérifie aussi que ton ordi est connecté à internet (le service est en cloud).",
    ]))

    s.append(Paragraph("« Erreur SMTP » au moment d'envoyer un email", h2_style))
    s.append(bullets([
        "<b>99% du temps</b> : tu as collé ton mot de passe Google normal au lieu du "
        "mot de passe d'application 16 caractères. Retourne sur "
        "<font color='#4F46E5'>myaccount.google.com/apppasswords</font> et regénère-en un.",
        "Sinon : vérifie que la double authentification Google est bien activée.",
    ]))

    s.append(Paragraph("« Triskell Core introuvable »", h2_style))
    s.append(Paragraph(
        "Ne devrait pas arriver — Triskell Core est intégré à l'exe. Si tu vois ce "
        "message, écris à Jordan (probablement un bug de packaging).",
        body_style,
    ))

    s.append(Paragraph("Autre problème", h2_style))
    s.append(Paragraph(
        "Fais une capture d'écran et envoie-la à Jordan. Précise dans quelle vue "
        "tu étais (Prospects / Campagnes / Publier / Réglages) et ce que tu venais "
        "de cliquer.",
        body_style,
    ))

    s.append(Spacer(1, 12))
    s.append(Paragraph(
        "— Bon courage. Une fois configuré, tu n'auras plus à y revenir. —",
        small_style,
    ))

    return s


def main():
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title="Configuration Triskell Command",
        author="Triskell Studio",
        subject="Guide de paramétrage interne",
    )
    doc.build(build_story())
    print(f"OK -> {OUT}")
    print(f"Taille : {OUT.stat().st_size / 1024:.1f} kB")


if __name__ == "__main__":
    main()
