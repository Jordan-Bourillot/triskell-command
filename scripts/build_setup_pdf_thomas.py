"""Génère le PDF d'instructions Setup Supabase pour Thomas.

Sortie : Triskell Command/docs/Setup_Supabase_Thomas.pdf

Usage :
    python scripts/build_setup_pdf_thomas.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# Palette Triskell (héritée du theme.py de l'app)
INDIGO = colors.HexColor("#7C7FE9")
GOLD = colors.HexColor("#D4B35A")
DARK = colors.HexColor("#14171F")
TEXT_DIM = colors.HexColor("#4A4F5E")
TEXT_MUTED = colors.HexColor("#6F7484")
PANEL = colors.HexColor("#F3F4F8")
BORDER = colors.HexColor("#D4D7E0")


def build_styles():
    base = getSampleStyleSheet()
    s = {}
    s["title"] = ParagraphStyle(
        "TitleTriskell", parent=base["Title"],
        fontName="Helvetica-Bold", fontSize=26, leading=32,
        textColor=DARK, spaceAfter=4,
    )
    s["subtitle"] = ParagraphStyle(
        "Subtitle", parent=base["Normal"],
        fontName="Helvetica", fontSize=12, leading=16,
        textColor=GOLD, spaceAfter=16,
    )
    s["h1"] = ParagraphStyle(
        "H1", parent=base["Heading1"],
        fontName="Helvetica-Bold", fontSize=18, leading=22,
        textColor=INDIGO, spaceBefore=18, spaceAfter=10,
    )
    s["h2"] = ParagraphStyle(
        "H2", parent=base["Heading2"],
        fontName="Helvetica-Bold", fontSize=13, leading=17,
        textColor=DARK, spaceBefore=10, spaceAfter=6,
    )
    s["body"] = ParagraphStyle(
        "Body", parent=base["Normal"],
        fontName="Helvetica", fontSize=11, leading=16,
        textColor=DARK, spaceAfter=8,
    )
    s["body_muted"] = ParagraphStyle(
        "BodyMuted", parent=base["Normal"],
        fontName="Helvetica-Oblique", fontSize=10, leading=14,
        textColor=TEXT_DIM, spaceAfter=8,
    )
    s["step"] = ParagraphStyle(
        "Step", parent=base["Normal"],
        fontName="Helvetica", fontSize=11, leading=16,
        textColor=DARK, spaceAfter=6, leftIndent=14,
    )
    s["mono"] = ParagraphStyle(
        "Mono", parent=base["Code"],
        fontName="Courier", fontSize=10, leading=14,
        textColor=DARK, backColor=PANEL,
        borderPadding=6, leftIndent=10, rightIndent=10,
        spaceBefore=4, spaceAfter=10,
    )
    s["callout"] = ParagraphStyle(
        "Callout", parent=base["Normal"],
        fontName="Helvetica", fontSize=10, leading=14,
        textColor=DARK, backColor=colors.HexColor("#FFF8E1"),
        borderColor=GOLD, borderWidth=1, borderPadding=10,
        leftIndent=4, rightIndent=4,
        spaceBefore=8, spaceAfter=12,
    )
    return s


def hr(color=BORDER):
    return HRFlowable(
        width="100%", thickness=0.6, color=color,
        spaceBefore=6, spaceAfter=10,
    )


def step_item(s, n: int, text: str):
    return Paragraph(f"<b>{n}.</b> &nbsp; {text}", s["step"])


def callout(s, label: str, text: str):
    return Paragraph(f"<b>{label}.</b> &nbsp; {text}", s["callout"])


def build_doc(out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    s = build_styles()
    story = []

    # ============ Page de garde ============
    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph("Triskell Command", s["title"]))
    story.append(Paragraph("Setup Supabase — pour Thomas", s["subtitle"]))
    story.append(hr(GOLD))

    intro = (
        "Salut Thomas,<br/><br/>"
        "Jordan a fini de monter <b>Triskell Command</b> en version partagée : "
        "désormais tu pourras travailler avec lui sur les <b>mêmes prospects</b>, "
        "les <b>mêmes campagnes mail</b> et les <b>mêmes drafts à valider</b>, "
        "depuis ta machine, en parallèle de la sienne. Plus besoin de s'envoyer "
        "des fichiers Excel.<br/><br/>"
        "Pour que ça marche, on a besoin d'un <b>petit serveur en ligne</b> qui "
        "stocke les données partagées entre vous deux. On utilise un service "
        "gratuit qui s'appelle <b>Supabase</b>. C'est lui qui héberge la base "
        "de données.<br/><br/>"
        "Pour des raisons de quota, c'est <b>toi</b> qui dois créer le projet "
        "Supabase (le compte de Jordan a déjà atteint sa limite de projets "
        "gratuits). Une fois créé, tu invites Jordan, et c'est lui qui finit "
        "le boulot.<br/><br/>"
        "<b>Ce que tu vas faire en gros</b> :<br/>"
        "&nbsp;&nbsp;• Créer un compte Supabase (gratuit, ~2 min)<br/>"
        "&nbsp;&nbsp;• Créer un projet dedans (~3 min)<br/>"
        "&nbsp;&nbsp;• Inviter Jordan en tant qu'<b>Owner</b> (~1 min)<br/>"
        "&nbsp;&nbsp;• Lui envoyer un message pour lui dire que c'est bon<br/><br/>"
        "<b>Total : 10 minutes</b>. Pas de carte bancaire, pas d'abonnement, "
        "pas de jargon technique. Suis juste les étapes ci-dessous, dans "
        "l'ordre."
    )
    story.append(Paragraph(intro, s["body"]))

    story.append(callout(
        s, "Important",
        "Si tu te retrouves bloqué à un endroit, ne force pas : prends une "
        "capture d'écran et envoie-la à Jordan. Il t'aide en 30 secondes. "
        "C'est plus rapide que de chercher tout seul."
    ))

    story.append(PageBreak())

    # ============ Étape 1 : Créer le compte ============
    story.append(Paragraph("Étape 1 — Créer ton compte Supabase", s["h1"]))
    story.append(Paragraph(
        "On commence par te créer un compte sur Supabase, le service "
        "qui va héberger les données partagées avec Jordan.",
        s["body_muted"],
    ))

    story.append(step_item(
        s, 1,
        "Ouvre ton navigateur (Chrome, Firefox, Edge, peu importe) et "
        "va sur cette adresse : "
        "<font color='#7C7FE9'><b>https://supabase.com/dashboard</b></font>"
    ))
    story.append(step_item(
        s, 2,
        "Tu vas tomber sur une page qui te propose de te connecter. "
        "Comme tu n'as pas encore de compte, clique sur "
        "<b>« Sign up »</b> (en bas, sous le formulaire de connexion). "
        "Ça veut dire « créer un compte »."
    ))
    story.append(step_item(
        s, 3,
        "Tu as 2 choix : créer un compte avec ton email Gmail, ou se "
        "connecter directement avec ton compte Google. Le plus simple : "
        "clique sur <b>« Continue with GitHub »</b> ou "
        "<b>« Continue with Google »</b> si l'option est là, sinon utilise "
        "<b>email + mot de passe</b>."
    ))
    story.append(step_item(
        s, 4,
        "Si tu choisis email + mot de passe : utilise "
        "<font color='#7C7FE9'><b>thomasbourillot@gmail.com</b></font> "
        "et choisis un mot de passe solide. <b>Note ce mot de passe</b> "
        "(dans un gestionnaire de mot de passe, ou un fichier sécurisé). "
        "Tu en auras besoin tout à l'heure."
    ))
    story.append(step_item(
        s, 5,
        "Supabase va t'envoyer un email de confirmation. Va dans ta boîte "
        "Gmail, ouvre le mail de Supabase, et clique sur le lien dedans "
        "pour confirmer ton adresse. Sans ça, ton compte ne marche pas."
    ))
    story.append(step_item(
        s, 6,
        "Reviens sur supabase.com/dashboard. Tu es maintenant connecté. "
        "Si on te demande de remplir des infos comme « nom de "
        "l'organisation » ou « usage prévu », mets ce que tu veux "
        "(par exemple : <i>Triskell Studio</i>, et coche « personnel / "
        "internal use »)."
    ))

    story.append(callout(
        s, "Astuce",
        "Si Supabase te demande de créer une « organization », appelle-la "
        "<b>« Triskell Shared »</b>. C'est le conteneur qui regroupera tes "
        "projets. Choisis le plan <b>Free</b>, jamais autre chose."
    ))

    story.append(PageBreak())

    # ============ Étape 2 : Créer le projet ============
    story.append(Paragraph("Étape 2 — Créer le projet « triskell-shared »", s["h1"]))
    story.append(Paragraph(
        "Maintenant on crée la base de données proprement dite : "
        "le projet qui va contenir vos prospects, vos drafts, etc.",
        s["body_muted"],
    ))

    story.append(step_item(
        s, 1,
        "Sur la page d'accueil du dashboard, tu vois un grand bouton "
        "<b>« New project »</b> (vert, au centre ou en haut à droite). "
        "Clique dessus."
    ))
    story.append(step_item(
        s, 2,
        "Une fenêtre s'ouvre avec plusieurs champs à remplir :"
    ))
    story.append(Paragraph(
        "&nbsp;&nbsp;• <b>Project name :</b> tape exactement "
        "<font face='Courier'><b>triskell-shared</b></font> "
        "(sans majuscule, avec un tiret au milieu, sans espace).<br/>"
        "&nbsp;&nbsp;• <b>Database password :</b> Supabase te propose "
        "automatiquement un mot de passe (un truc long et bizarre). "
        "Clique sur <b>« Generate a password »</b> pour qu'il en "
        "génère un solide. <b>Copie-le et garde-le précieusement</b> "
        "(par exemple dans un fichier texte sur ton bureau, ou un "
        "gestionnaire de mots de passe). Tu n'auras probablement jamais "
        "besoin de t'en servir, mais s'il est perdu, on perd l'accès "
        "direct à la base.<br/>"
        "&nbsp;&nbsp;• <b>Region :</b> choisis "
        "<font face='Courier'><b>Frankfurt (eu-central-1)</b></font>. "
        "C'est l'Allemagne, c'est le plus rapide depuis la France.<br/>"
        "&nbsp;&nbsp;• <b>Pricing Plan :</b> choisis <b>Free</b>. "
        "Surtout pas autre chose.",
        s["step"],
    ))
    story.append(step_item(
        s, 3,
        "Clique sur <b>« Create new project »</b> tout en bas. "
        "Une page de chargement apparaît avec un message du genre "
        "<i>« Setting up your project »</i>. Ça prend environ 1 minute. "
        "Ne ferme pas l'onglet."
    ))
    story.append(step_item(
        s, 4,
        "Quand le chargement est fini, tu arrives sur la page d'accueil "
        "du projet : tu vois un menu à gauche avec des icônes "
        "(maison, base de données, authentification, etc.). "
        "Bravo, le projet existe."
    ))

    story.append(callout(
        s, "Si tu vois une erreur",
        "« You have reached the limit of free projects » → c'est que tu as "
        "déjà 2 projets sur ton compte. Demande à Jordan, c'est probablement "
        "un cas qu'on n'avait pas prévu et il aura une solution."
    ))

    story.append(PageBreak())

    # ============ Étape 3 : Inviter Jordan ============
    story.append(Paragraph("Étape 3 — Inviter Jordan en tant qu'Owner", s["h1"]))
    story.append(Paragraph(
        "Maintenant que le projet existe, il faut donner à Jordan les "
        "droits pour bosser dessus. On va l'inviter dans ton organisation "
        "Supabase avec le rôle le plus élevé : <b>Owner</b>.",
        s["body_muted"],
    ))

    story.append(step_item(
        s, 1,
        "Tout en haut de la page, à gauche du nom du projet, tu vois "
        "le nom de ton organisation (probablement <b>« Triskell Shared »</b> "
        "ou <b>« Thomas Bourillot's Org »</b>). Clique dessus."
    ))
    story.append(step_item(
        s, 2,
        "Un menu déroulant s'ouvre. Tout en bas, clique sur "
        "<b>« Organization Settings »</b> (avec une petite icône d'engrenage)."
    ))
    story.append(step_item(
        s, 3,
        "Sur la page qui s'ouvre, dans le menu de gauche, tu vois plusieurs "
        "onglets : <i>General, Team, Billing, Audit Logs…</i> "
        "Clique sur <b>« Team »</b>."
    ))
    story.append(step_item(
        s, 4,
        "Tu vois la liste des membres de ton organisation (pour l'instant, "
        "juste toi). En haut à droite, clique sur le bouton "
        "<b>« Invite »</b> (ou <b>« Invite member »</b> selon les versions)."
    ))
    story.append(step_item(
        s, 5,
        "Une fenêtre s'ouvre avec 2 champs à remplir :"
    ))
    story.append(Paragraph(
        "&nbsp;&nbsp;• <b>Email :</b> mets l'adresse email avec laquelle "
        "Jordan utilise habituellement Supabase. "
        "<b>Demande-lui</b> juste avant si tu n'es pas sûr "
        "(probablement <font face='Courier'>jordan@triskell-studio.fr</font> "
        "ou son email perso).<br/>"
        "&nbsp;&nbsp;• <b>Role :</b> choisis <b>Owner</b> (le plus "
        "haut niveau de droits). Si <i>Owner</i> n'est pas dans la liste, "
        "prends <b>Administrator</b>.",
        s["step"],
    ))
    story.append(step_item(
        s, 6,
        "Clique <b>« Send invitation »</b>. Jordan recevra un mail "
        "avec un lien pour accepter. Quand il aura accepté, il verra ton "
        "projet dans son dashboard et pourra finir le setup."
    ))

    story.append(callout(
        s, "Vérification",
        "Reviens sur l'onglet <b>Team</b> après quelques minutes. Si Jordan "
        "a accepté, tu verras une 2e ligne avec son email et son rôle. "
        "Si après 1h tu ne vois rien, demande-lui s'il a bien reçu le mail "
        "(parfois ça tombe en spam)."
    ))

    story.append(PageBreak())

    # ============ Étape 4 : Confirmer ============
    story.append(Paragraph("Étape 4 — Préviens Jordan que c'est fait", s["h1"]))

    story.append(Paragraph(
        "Une fois les 3 étapes finies, envoie un message à Jordan "
        "(SMS, mail, WhatsApp, peu importe) avec :",
        s["body"],
    ))

    msg_table = Table(
        [
            ["Information", "Comment la trouver"],
            ["1. Confirmation : compte créé + projet « triskell-shared » créé + invitation envoyée à toi.",
             "À taper toi-même."],
            ["2. Adresse email avec laquelle tu t'es inscrit sur Supabase.",
             "Probablement thomasbourillot@gmail.com."],
            ["3. Mot de passe Supabase (celui de ton compte, pas celui de la base).",
             "Celui que tu as choisi à l'étape 1.4."],
        ],
        colWidths=[9.5 * cm, 7 * cm],
        repeatRows=1,
    )
    msg_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 11),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, PANEL]),
    ]))
    story.append(msg_table)
    story.append(Spacer(1, 12))

    story.append(callout(
        s, "Sécurité",
        "Le mot de passe Supabase de ton compte est sensible. Envoie-le par "
        "un canal sécurisé (Signal, ou un message éphémère). Si tu n'es pas "
        "sûr, dis à Jordan de te créer un compte de connexion séparé après, "
        "et tu changeras ton mot de passe principal."
    ))

    story.append(Paragraph("C'est tout !", s["h2"]))
    story.append(Paragraph(
        "Tu as fini ta partie. Jordan va prendre le relais : il va "
        "configurer la base de données, créer ton compte de connexion à "
        "l'application, et te livrer un fichier d'installation pour "
        "Triskell Command sur ta machine. Tu n'as plus rien à faire jusque "
        "là.<br/><br/>"
        "Quand Jordan te dira <b>« c'est prêt »</b>, il t'enverra un fichier "
        "<b>Setup.exe</b>. Tu double-cliques dessus, ça installe l'app, tu "
        "te connectes avec ton email et un mot de passe qu'il aura choisi "
        "pour toi (que tu pourras changer après).",
        s["body"],
    ))

    story.append(Spacer(1, 1 * cm))
    story.append(hr(GOLD))
    story.append(Paragraph(
        "<font color='#6F7484'>Triskell Studio — Outil interne Jordan + Thomas — "
        "Document généré pour le setup Supabase.</font>",
        ParagraphStyle("Footer", fontName="Helvetica-Oblique", fontSize=9,
                       leading=12, alignment=1, textColor=TEXT_MUTED),
    ))

    # ============ Build ============
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title="Triskell Command — Setup Supabase pour Thomas",
        author="Jordan Bourillot",
    )
    doc.build(story)
    print(f"PDF généré : {out_path}")


if __name__ == "__main__":
    here = Path(__file__).resolve().parent.parent
    out = here / "docs" / "Setup_Supabase_Thomas.pdf"
    build_doc(out)
