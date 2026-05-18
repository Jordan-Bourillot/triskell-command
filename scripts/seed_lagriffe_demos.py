"""Seed les 21 démos métier Lagriffe Studio dans le catalogue Triskell.

Usage (depuis le repo triskell-command, après avoir été loggé via la session
Supabase locale) :

    python -m scripts.seed_lagriffe_demos

OU si tu préfères passer en standalone :

    python scripts/seed_lagriffe_demos.py

Le script appelle `catalog_central.save_product()` pour chaque démo avec
kind="demo". Il est idempotent : relancer ne crée pas de doublon (chaque
démo a un id slugifié stable, save_product upsert).

Si tu veux ajouter d'autres démos plus tard, édite la liste DEMOS ci-dessous
et relance.
"""

from __future__ import annotations

import sys
from pathlib import Path


# Permet de lancer en standalone (python scripts/seed_lagriffe_demos.py)
HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Liste des démos à créer (nom, url, keywords)
# ---------------------------------------------------------------------------
DEMOS: list[dict] = [
    {
        "name":     "Démo brasserie — La Rose des Vents",
        "url":      "https://brasserie-la-rose-des-vents.netlify.app",
        "keywords": "brasserie, bar à bières, microbrasserie, taverne, pub, "
                    "débit de boissons, bar artisanal",
        "tagline":  "Site pour brasseries, bars à bières et microbrasseries",
    },
    {
        "name":     "Démo services à la personne — Ingrid Services",
        "url":      "https://ingrid-services.fr",
        "keywords": "ménage, services à la personne, aide à domicile, "
                    "nettoyage, entretien maison, repassage, garde d'enfants",
        "tagline":  "Site pour prestataires de ménage et services à domicile",
    },
    {
        "name":     "Démo boutique vape — Vaporlux",
        "url":      "https://vaporlux.triskell-studio.fr",
        "keywords": "vape, cigarette électronique, e-cigarette, vapoteur, "
                    "e-liquide, CBD, boutique vape, vape shop",
        "tagline":  "Site pour boutiques de vape et cigarette électronique",
    },
    {
        "name":     "Démo atelier sculpteur — Missor",
        "url":      "https://missor.triskell-studio.fr",
        "keywords": "sculpteur, sculpture, fonderie, fondeur d'art, "
                    "atelier d'art, bronze, statuaire, artisan d'art",
        "tagline":  "Site pour sculpteurs et fonderies d'art",
    },
    {
        "name":     "Démo influenceur / créateur — Anyme",
        "url":      "https://anyme.triskell-studio.fr",
        "keywords": "influenceur, streamer, créateur de contenu, "
                    "content creator, twitch, youtube, instagram, tiktok, "
                    "personal branding",
        "tagline":  "Site pour influenceurs, streamers et créateurs de contenu",
    },
    {
        "name":     "Démo garagiste — Triskell",
        "url":      "https://garage.triskell-studio.fr",
        "keywords": "garagiste, garage, mécanicien, mécanique auto, "
                    "réparation automobile, carrosserie, entretien voiture, "
                    "dépannage, automobile",
        "tagline":  "Site pour garagistes et mécaniciens auto",
    },
    {
        "name":     "Démo paysagiste — Triskell",
        "url":      "https://paysagiste.triskell-studio.fr",
        "keywords": "paysagiste, jardinier, espaces verts, aménagement paysager, "
                    "jardin, entretien jardin, taille, élagage, terrasse, gazon",
        "tagline":  "Site pour paysagistes et jardiniers",
    },
    {
        "name":     "Démo thérapeute / bien-être — Graphothérapeute",
        "url":      "https://graphotherapeute.triskell-studio.fr",
        "keywords": "graphothérapeute, graphothérapie, yoga, professeur de yoga, "
                    "orthophoniste, orthophonie, sophrologue, sophrologie, "
                    "naturopathe, hypnothérapeute, médecine douce, bien-être, "
                    "thérapeute, praticien, ostéopathe, réflexologue",
        "tagline":  "Site pour praticiens du bien-être (yoga, ortho, sophro…)",
    },
    {
        "name":     "Démo boutique vape — Variante moderne",
        "url":      "https://vape.triskell-studio.fr",
        "keywords": "vape, cigarette électronique, e-cigarette, vapoteur, "
                    "e-liquide, CBD, boutique vape, vape shop",
        "tagline":  "Variante moderne pour boutiques de vape",
    },
    {
        "name":     "Démo plombier — Triskell",
        "url":      "https://plombier.triskell-studio.fr",
        "keywords": "plombier, plomberie, chauffagiste, dépannage plomberie, "
                    "sanitaire, fuite d'eau, chauffage, installation sanitaire, "
                    "robinetterie",
        "tagline":  "Site pour plombiers et chauffagistes",
    },
    {
        "name":     "Démo peintre — Triskell",
        "url":      "https://peintre.triskell-studio.fr",
        "keywords": "peintre, peinture, peintre en bâtiment, ravalement, "
                    "papier peint, décoration murale, façade, "
                    "peinture intérieure, peinture extérieure",
        "tagline":  "Site pour peintres en bâtiment",
    },
    {
        "name":     "Démo plaquiste — Triskell",
        "url":      "https://plaquiste.triskell-studio.fr",
        "keywords": "plaquiste, placo, cloisons, isolation, faux plafond, "
                    "doublage, BA13, aménagement intérieur",
        "tagline":  "Site pour plaquistes",
    },
    {
        "name":     "Démo maçon — Triskell",
        "url":      "https://macon.triskell-studio.fr",
        "keywords": "maçon, maçonnerie, gros œuvre, construction, fondations, "
                    "rénovation, BTP, entrepreneur, terrassement",
        "tagline":  "Site pour maçons et entreprises de gros œuvre",
    },
    {
        "name":     "Démo carreleur — Triskell",
        "url":      "https://carreleur.triskell-studio.fr",
        "keywords": "carreleur, carrelage, faïence, pose carrelage, "
                    "salle de bain, sol, mosaïque, dallage",
        "tagline":  "Site pour carreleurs",
    },
    {
        "name":     "Démo électricien — Triskell",
        "url":      "https://electricien.triskell-studio.fr",
        "keywords": "électricien, électricité, installation électrique, "
                    "dépannage électrique, tableau électrique, mise aux normes, "
                    "courant fort, courant faible, domotique",
        "tagline":  "Site pour électriciens",
    },
    {
        "name":     "Démo boulangerie — Le Fournil de Goulven",
        "url":      "https://boulangerie.triskell-studio.fr",
        "keywords": "boulanger, boulangerie, pain, viennoiserie, pâtisserie, "
                    "baguette, artisan boulanger, fournil, pâtissier",
        "tagline":  "Site pour boulangeries et pâtisseries artisanales",
    },
    {
        "name":     "Démo restaurant — La Belle Époque",
        "url":      "https://restaurant.triskell-studio.fr",
        "keywords": "restaurant, restaurateur, cuisine, brasserie, traiteur, "
                    "bistrot, gastronomie, cuisine traditionnelle, menu, carte",
        "tagline":  "Site pour restaurants traditionnels",
    },
    {
        "name":     "Démo salon de coiffure — Maison Lou",
        "url":      "https://salon-coiffure.triskell-studio.fr",
        "keywords": "coiffeur, coiffeuse, salon de coiffure, coupe, coloration, "
                    "balayage, mèches, brushing, soin capillaire",
        "tagline":  "Site pour salons de coiffure",
    },
    {
        "name":     "Démo barbier — L'Atelier de Brieuc",
        "url":      "https://salons.triskell-studio.fr",
        "keywords": "barbier, barber shop, barberie, rasage, taille de barbe, "
                    "salon de barbier, soin homme, coupe homme",
        "tagline":  "Site pour barbiers et barber shops",
    },
    {
        "name":     "Démo restaurant cubain — Clandestino",
        "url":      "https://clandestino.triskell-studio.fr",
        "keywords": "restaurant cubain, cuisine latino, world food, "
                    "bar à cocktails, restaurant à thème, tapas, "
                    "ambiance, rhum, latino",
        "tagline":  "Site pour restaurants à thème et cuisine du monde",
    },
    {
        "name":     "Démo tatoueur — Despiertos",
        "url":      "https://despiertos.triskell-studio.fr",
        "keywords": "tatoueur, tatouage, tattoo, salon de tatouage, "
                    "tattoo artist, piercing, body art, ink, atelier tatouage",
        "tagline":  "Site pour tatoueurs et studios de tatouage",
    },
]


def main() -> int:
    try:
        from triskell_command.integrations import catalog_central
    except Exception as exc:
        print(f"❌ Impossible d'importer catalog_central : {exc}")
        return 1

    ok, fail = 0, 0
    print(f"📥 Seed de {len(DEMOS)} démos métier dans le catalogue Triskell…")
    for d in DEMOS:
        payload = {
            "name":          d["name"],
            "tagline":       d.get("tagline", ""),
            "kind":          "demo",          # ← TYPE = démo métier
            "category":      "sites",         # même section que Lagriffe / WoW / RankUs
            "buy_url":       d["url"],
            "keywords":      d["keywords"],
            "prospect_pitch": (
                "Démo prête à montrer aux prospects de ce métier : "
                "preuve visuelle directe de ce qu'on peut leur faire."
            ),
        }
        res = catalog_central.save_product(payload)
        if res and res.get("ok"):
            ok += 1
            print(f"  ✅ {d['name']}")
        else:
            fail += 1
            print(f"  ❌ {d['name']} → {res}")
    print()
    print(f"Terminé : {ok} ajoutées, {fail} échouées.")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
