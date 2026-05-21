"""Génère le PDF de démo "Chantiers Mairie de Lannion" utilisé dans la
vidéo de présentation du Convoi.

Lance simplement :
    python docs/demo_convoi/build_demo_pdf.py

Produit : docs/demo_convoi/chantiers_mairie_lannion_mars_2026.pdf
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)


OUT = Path(__file__).parent / "chantiers_mairie_lannion_mars_2026.pdf"


PROSPECTS = [
    # (raison sociale, contact, métier, adresse, ville, CP, tel, email)
    ("Plomberie Le Bras",        "Yann Le Bras",      "plombier chauffagiste",
     "12 rue des Korrigans",     "Lannion",      "22300", "02 96 37 14 22",
     "contact@plomberie-lebras.fr"),
    ("Électricité Tanguy & Fils","Maël Tanguy",       "électricien",
     "3 impasse Saint-Jean",     "Trégastel",    "22730", "02 96 23 88 41",
     "devis@elec-tanguy.bzh"),
    ("Maçonnerie du Trégor",     "Pierrick Quéré",    "maçon gros œuvre",
     "47 route de Perros",       "Lannion",      "22300", "02 96 48 11 67",
     "pquere@maconnerie-tregor.fr"),
    ("Couverture Penven",        "Erwan Penven",      "couvreur zingueur",
     "8 chemin du Calvaire",     "Pleumeur-Bodou","22560", "02 96 91 02 88",
     "erwan@couverture-penven.com"),
    ("Menuiserie Le Goff",       "Sandrine Le Goff",  "menuisier ébéniste",
     "21 boulevard d'Armor",     "Lannion",      "22300", "02 96 14 70 33",
     "s.legoff@menuiserie-legoff.fr"),
    ("Peinture Atlantique",      "Nolwenn Riou",      "peintre décorateur",
     "5 rue de Brest",           "Perros-Guirec","22700", "02 96 49 25 09",
     "n.riou@peinture-atlantique.fr"),
    ("Carrelage Kerlann",        "Tristan Kerlann",   "carreleur",
     "30 rue des Sables",        "Trébeurden",   "22560", "02 96 23 56 14",
     "atelier@carrelage-kerlann.bzh"),
    ("Chauffage Bretagne Pro",   "Gwendal Allain",    "chauffagiste plombier",
     "16 quai d'Aiguillon",      "Lannion",      "22300", "02 96 37 80 12",
     "contact@chauffage-bretagne.fr"),
    ("Étanchéité Mer & Toit",    "Loïc Floch",        "étancheur toiture terrasse",
     "9 zone d'activité Pégase", "Lannion",      "22300", "02 96 48 73 28",
     "l.floch@etancheite-mt.fr"),
    ("Paysagisme Ar Mor",        "Anaïg Le Roux",     "paysagiste",
     "62 rue de Trégastel",      "Louannec",     "22700", "02 96 23 41 76",
     "anaig@paysagisme-armor.bzh"),
]


def build() -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
        title="Chantiers retenus — Mars 2026",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title", parent=styles["Title"], fontSize=18, leading=22,
        textColor=colors.HexColor("#0F172A"),
    )
    sub_style = ParagraphStyle(
        "sub", parent=styles["Normal"], fontSize=10, leading=14,
        textColor=colors.HexColor("#475569"),
    )
    body_style = ParagraphStyle(
        "body", parent=styles["Normal"], fontSize=9, leading=12,
    )

    story = []

    # En-tête institutionnel
    story.append(Paragraph(
        "Mairie de Lannion — Service Marchés Publics", title_style,
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Liste des entreprises retenues pour les chantiers communaux "
        "et inter-communaux — appel à candidatures Mars 2026. "
        "Document à diffuser aux membres de la commission.",
        sub_style,
    ))
    story.append(Spacer(1, 14))

    # Construit le tableau
    header = ["Raison sociale", "Contact", "Activité",
              "Adresse", "Ville (CP)", "Téléphone", "Email"]
    rows = [header]
    for r in PROSPECTS:
        raison, contact, metier, adresse, ville, cp, tel, email = r
        rows.append([
            Paragraph(raison, body_style),
            Paragraph(contact, body_style),
            Paragraph(metier, body_style),
            Paragraph(adresse, body_style),
            Paragraph(f"{ville} ({cp})", body_style),
            Paragraph(tel, body_style),
            Paragraph(email, body_style),
        ])

    col_widths = [3.2*cm, 2.4*cm, 2.6*cm, 3.0*cm, 2.4*cm, 2.2*cm, 3.2*cm]
    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING",    (0, 0), (-1, 0), 6),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F8FAFC")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tbl)

    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "Document interne — Mairie de Lannion, Place du Général Leclerc, "
        "22300 Lannion — Tél : 02 96 46 64 22.",
        sub_style,
    ))

    doc.build(story)
    print(f"PDF généré : {OUT}")
    return OUT


if __name__ == "__main__":
    build()
