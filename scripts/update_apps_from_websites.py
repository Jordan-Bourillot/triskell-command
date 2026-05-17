"""Met a jour apps.json avec les infos scrapees depuis chaque site public.

A executer une seule fois apres rafraichissement. Source : pages d'accueil
publiques de chaque produit Triskell, dont WebFetch a extrait un JSON.
"""
from __future__ import annotations

import json
from pathlib import Path

APPS_JSON = Path(__file__).resolve().parents[1] / "triskell_command" / "data" / "apps.json"


# Champs a remplacer pour chaque produit (apps.json utilise camelCase)
UPDATES: dict[str, dict] = {
    "suite-des-heros": {
        "name": "La Suite des Héros",
        "tagline": "11 outils desktop pour reprendre le contrôle de ton PC.",
        "motto": "Une suite de héros pour ton PC en bordel.",
        "description": "Suite de 11 applications Windows 10/11 qui rangent, renomment, "
                       "désinstallent, compressent et convertissent tes fichiers. Aucune "
                       "installation système, aucun compte, 100 % hors ligne — rien ne sort "
                       "de ton PC.",
        "salesPitch": "Tes fichiers, ta machine, ton ordre — sans cloud ni abonnement.",
        "price": 27,
        "priceNote": "paiement unique, pas d'abonnement",
        "kind": "app",
        "features": [
            {"title": "11 outils spécialisés", "detail": "Tri, renommage, déduplication, compression vidéo, fusion PDF, conversion d'images."},
            {"title": "100 % hors ligne", "detail": "Aucune donnée envoyée, pas de compte, pas de cloud."},
            {"title": "Annulation 1 clic", "detail": "Tous les outils permettent de revenir en arrière sans risque."},
            {"title": "Mises à jour 1 an", "detail": "Accès à tous les nouveaux outils et corrections pendant 12 mois."},
            {"title": "Garantie 14 jours", "detail": "Satisfait ou remboursé, sans questions."},
        ],
    },
    "delinote": {
        "name": "DéliNote",
        "tagline": "L'app de notes rapide, belle, et vraiment à toi.",
        "motto": "Paie 79 € une seule fois. Profite à vie.",
        "description": "DéliNote est une app de prise de notes pensée en France, qui met "
                       "l'écriture au centre. Paiement unique à vie (pas d'abonnement), "
                       "chiffrement bout-en-bout, mises à jour perpétuelles.",
        "salesPitch": "Une vraie app de notes : pas d'abonnement, chiffrée, à toi pour toujours.",
        "price": 79,
        "priceNote": "paiement unique, à vie",
        "kind": "app",
        "features": [
            {"title": "Paiement unique", "detail": "79 € à vie, pas de mensualité, pas de renouvellement."},
            {"title": "Mises à jour à vie", "detail": "Toutes les versions futures incluses, indéfiniment."},
            {"title": "Chiffrement bout-en-bout", "detail": "Tes notes restent privées, même nous ne pouvons pas les lire."},
            {"title": "Éditeur riche", "detail": "Titres, listes à puces, checklists, mise en forme propre."},
            {"title": "Garantie 30 jours", "detail": "Tu testes, et si ça ne te va pas, tu es remboursé."},
        ],
    },
    "studio-pdf": {
        "name": "Le Studio PDF",
        "tagline": "Fusion, split, OCR, signature — tout pour tes PDF.",
        "motto": "Tout ce qu'il faut faire à un PDF, dans une seule app.",
        "description": "Le Studio PDF regroupe les manipulations PDF essentielles : "
                       "fusion, découpe, OCR (reconnaissance de texte sur les scans) et "
                       "signature numérique. Une app, paiement unique, sans abonnement.",
        "salesPitch": "Arrête de jongler entre 5 sites en ligne — un seul outil, à vie.",
        "price": 39,
        "priceNote": "paiement unique, à vie",
        "kind": "app",
        "features": [
            {"title": "Fusion", "detail": "Combine plusieurs PDF en un seul document, ordre libre."},
            {"title": "Découpe", "detail": "Divise un PDF en plusieurs fichiers selon les pages."},
            {"title": "OCR", "detail": "Convertit un scan en texte sélectionnable et cherchable."},
            {"title": "Signature numérique", "detail": "Ajoute une signature image ou tracée à la souris."},
        ],
    },
    "bobeez": {
        "name": "Bobeez",
        "tagline": "Gestionnaire d'images moderne — calendrier, carte, tri rapide.",
        "motto": "Tes photos, enfin retrouvables.",
        "description": "Bobeez organise et gère ta photothèque autrement : vue calendrier, "
                       "carte des lieux pris en photo, tri rapide pour faire le ménage. "
                       "Paiement unique, accès à vie.",
        "salesPitch": "Pour qui en a marre de chercher la photo de l'anniversaire de 2019.",
        "price": 27,
        "priceNote": "paiement unique, à vie",
        "kind": "app",
        "features": [
            {"title": "Vue calendrier", "detail": "Visualise tes photos jour par jour, mois par mois."},
            {"title": "Vue carte", "detail": "Retrouve les photos par leur lieu de prise de vue."},
            {"title": "Tri rapide", "detail": "Élimine les doublons et photos floues en deux clics."},
        ],
    },
    "le-denicheur": {
        "name": "Obelisk",
        "tagline": "Trouve les créateurs non-monétisés dans ta niche, avant tout le monde.",
        "motto": "La prospection à l'aveugle, c'est une perte de temps.",
        "description": "Obelisk (anciennement Le Dénicheur) scanne 9 plateformes — YouTube, "
                       "Twitch, Reddit, Bluesky, Mastodon, Apple Podcasts, Dailymotion, "
                       "Kick, GitHub — pour identifier les créateurs sans monétisation "
                       "déjà en place. Il sort 30 prospects qualifiés en 5 minutes, avec "
                       "emails extraits et premier message rédigé par IA.",
        "salesPitch": "Trouve les créateurs qui n'ont encore signé avec personne — avant tes concurrents.",
        "price": 129,
        "priceNote": "paiement unique",
        "kind": "app",
        "features": [
            {"title": "Recherche multi-plateforme", "detail": "9 sources scannées en parallèle avec filtres mots-clés, abonnés, langue."},
            {"title": "Détection de monétisation", "detail": "Exclut automatiquement créateurs sponsorisés, shop ou Linktree (25+ patterns)."},
            {"title": "Auto-pilote IA", "detail": "Rédige et envoie les mails personnalisés via SMTP, 5 providers IA supportés."},
            {"title": "CRM intégré", "detail": "Statuts, notes, historique, export CSV — sans abonnement."},
            {"title": "100 % local", "detail": "Tout reste sur ta machine. Aucune télémétrie, RGPD-friendly."},
        ],
    },
    "artisia-studio": {
        "name": "Artisia Studio",
        "tagline": "Outils numériques sur-mesure pour pros qui refusent les logiciels génériques.",
        "motto": "Des outils faits pour vos mains. Pas pour le marché.",
        "description": "Artisia Studio conçoit des logiciels métier sur-mesure pour pros "
                       "qui refusent de plier leur métier aux outils existants. On part "
                       "de ton vocabulaire et de tes process réels, on intègre l'IA "
                       "uniquement quand ça apporte un gain mesurable, et tu es "
                       "propriétaire du résultat — pas dépendant d'un abonnement.",
        "salesPitch": "Quand ton métier mérite mieux qu'un SaaS plié au plus grand dénominateur commun.",
        "kind": "service",
        "features": [
            {"title": "Sur-mesure vraiment", "detail": "Le logiciel s'adapte à ton métier, pas l'inverse."},
            {"title": "L'IA quand elle sert", "detail": "Déploiement ML uniquement là où il y a un gain mesurable."},
            {"title": "L'outil t'appartient", "detail": "Code, données et infra à ton nom, sans dépendance perpétuelle."},
            {"title": "4 formats de livraison", "detail": "Desktop, Web, Hybride ou Clé en main selon le besoin."},
            {"title": "Diagnostic offert", "detail": "Première journée gratuite pour comprendre le métier et proposer une solution."},
        ],
    },
    "triskell-studio-sites": {
        "name": "Triskell Studio",
        "tagline": "Nouvelle version arrive bientôt.",
        "motto": "",
        "description": "Le site Triskell Studio est en refonte. Une nouvelle version "
                       "regroupant l'ensemble de l'écosystème arrive prochainement.",
        "salesPitch": "Le portail central Triskell — refonte en cours.",
        "kind": "service",
        "features": [],
    },
    "eliks-studio": {
        "name": "Eliks Studio",
        "tagline": "Growth Operator — commission pure, zéro mensualité.",
        "motto": "Vos réseaux sociaux en machine à ventes.",
        "description": "Eliks Studio transforme tes réseaux sociaux en machine à ventes : "
                       "stratégie, analyse, optimisation sur Instagram, TikTok, LinkedIn, "
                       "YouTube ou X — sans toucher à la production de contenu. Modèle "
                       "commission pure : tu ne paies que sur les ventes générées.",
        "salesPitch": "On opère tes réseaux sociaux pour générer des ventes — on est payés sur le résultat.",
        "priceFrom": "10 à 25 % du CA additionnel",
        "priceNote": "commission variable selon marge et ticket moyen",
        "kind": "service",
        "features": [
            {"title": "Stratégie de contenu", "detail": "Positionnement, hooks, angles éditoriaux et calendrier data-driven."},
            {"title": "Analyse de performance", "detail": "Watch time, retention, CTR, dashboard hebdo, tests A/B."},
            {"title": "Systèmes & automatisation", "detail": "Workflows DM, capture email, nurturing — n8n, Make, ManyChat."},
            {"title": "Monétisation", "detail": "Offer design, landing pages haute conversion, tunnels de vente."},
            {"title": "Limite à 6 clients", "detail": "Sélection stricte pour garantir accompagnement sur-mesure."},
        ],
    },
    "le-heraut": {
        "name": "AlphaCast",
        "tagline": "De 2 h/jour à 10 min/jour, sans sonner comme une IA.",
        "motto": "One source. Every network. Your voice.",
        "description": "AlphaCast publie ton contenu sur LinkedIn, X, Bluesky et YouTube "
                       "Shorts à partir d'une seule source — en gardant ton style. Il "
                       "apprend ta voix depuis tes anciens posts, analyse les "
                       "performances chaque nuit, et te livre 3 axes d'amélioration "
                       "concrets.",
        "salesPitch": "Multi-plateforme dans TA voix, sans le ton plat des IA classiques.",
        "priceFrom": "à partir de 0 €",
        "priceNote": "par mois",
        "kind": "app",
        "features": [
            {"title": "Multi-plateforme natif", "detail": "LinkedIn, X, Bluesky, YouTube Shorts — chaque format adapté."},
            {"title": "Une voix qui n'a pas l'air IA", "detail": "Importe tes anciens posts pour apprendre ton style."},
            {"title": "Apprentissage continu", "detail": "Tes posts sont notés chaque nuit, 3 patterns concrets extraits."},
            {"title": "Multi-angles", "detail": "Génère plusieurs angles à partir d'une seule source, dans ta voix."},
            {"title": "Publication en 1 swipe", "detail": "Valide et publie tout de suite, ou planifie sur tous les réseaux."},
        ],
    },
    "ultimate-prompt-builder": {
        "name": "AlphaBeast",
        "tagline": "Sortir tes IA du mode validation par défaut.",
        "motto": "Pour qui veut sortir des LLM mode validation par défaut.",
        "description": "AlphaBeast combine ton prompt avec une bibliothèque de 16 Mega "
                       "Prompts puissants et l'envoie à Claude, GPT, Gemini, Mistral ou "
                       "Grok en un clic. Il désactive les biais de validation des modèles "
                       "pour obtenir des réponses plus honnêtes et exploitables.",
        "salesPitch": "Quand tu veux que l'IA te dise la vérité, pas juste te flatter.",
        "price": 19,
        "priceNote": "paiement unique, à vie",
        "kind": "app",
        "features": [
            {"title": "16 Mega Prompts brandés", "detail": "Honnêteté brutale, Anti-slop, Pre-mortem, Coach socratique — combinables."},
            {"title": "5 providers IA natifs", "detail": "Anthropic, OpenAI, Google, Mistral, xAI avec config locale."},
            {"title": "7 presets prêts à l'emploi", "detail": "Build d'app, Décision stratégique, Recherche, Diagnostic, Production."},
            {"title": "100 % local, zéro tracker", "detail": "Tes clés API et tes prompts restent sur ta machine."},
            {"title": "Mises à jour à vie", "detail": "Vérification et installation silencieuses via GitHub Releases."},
        ],
    },
    "alphapitch": {
        "name": "AlphaPitch",
        "tagline": "Génère ton message de prospection en 4 clics.",
        "motto": "Le bon message, au bon moment, pour le bon client.",
        "description": "AlphaPitch (anciennement Triskell Sales Tunnel) génère des "
                       "templates de prospection en 4 clics à partir d'environ 50 "
                       "messages rédigés à la main — pas du LLM. 100 % local, sans "
                       "compte. Reformulation IA optionnelle via tes propres clés "
                       "Claude/GPT/Gemini.",
        "salesPitch": "Des messages humains, pas du contenu généré au kilomètre.",
        "priceNote": "gratuit (reformulation IA via clés perso)",
        "kind": "app",
        "features": [
            {"title": "4 étapes simples", "detail": "Produit → Cible → Canal → Personnalisation, et c'est prêt."},
            {"title": "Templates manuels", "detail": "~50 messages rédigés à la main, pas de génération LLM."},
            {"title": "Reformulation IA optionnelle", "detail": "Anthropic, OpenAI ou Google avec tes propres clés API."},
            {"title": "Export multi-formats", "detail": "Copie 1 clic, .txt, .pdf brandé, .docx Word."},
            {"title": "100 % offline", "detail": "Aucune télémétrie, stockage local uniquement."},
        ],
    },
    "outils-batiment": {
        "name": "Triskell Outils Pro",
        "tagline": "L'outil chantier de l'artisan.",
        "motto": "Quantités, chutes, conditionnements — pensé pour le terrain.",
        "description": "App mobile de calcul pour artisans du bâtiment. Calcule les "
                       "quantités de matériaux, les chutes et les conditionnements "
                       "directement sur le chantier. Fonctionne hors-ligne, s'installe "
                       "sur l'écran d'accueil.",
        "salesPitch": "Le métré, sans la calculette, sans le carnet, sans la galère.",
        "price": 9,
        "priceNote": "par mois",
        "kind": "app",
        "features": [
            {"title": "Surface nette", "detail": "Pièce avec ouvertures déduites en un calcul."},
            {"title": "TVA travaux", "detail": "5,5 % / 10 % / 20 % toujours sous la main."},
            {"title": "Conversions", "detail": "m² · m³ · ml · sacs — sans réflexion."},
            {"title": "Modes métier", "detail": "Carreleur, Plaquiste, Peintre, Maçon."},
            {"title": "Hors-ligne", "detail": "Pas besoin de réseau sur le chantier."},
        ],
    },
    "pack-electricien-pro": {
        "name": "Pack Électricien Pro",
        "tagline": "Devis, factures et CGV prêts à l'emploi pour électriciens indépendants.",
        "motto": "Tu remplis, tu envoies, tu signes.",
        "description": "Pack tout-en-un : 6 modèles de devis et 7 de factures pré-remplis "
                       "(Word + Excel avec TVA auto), CGV type électricien conformes 2026 "
                       "(16 articles + relances impayés), tableau Excel de suivi avec "
                       "12 KPI, guide chiffrage 18 pages. Triskell Outils Pro offert.",
        "salesPitch": "Envoie tes devis en 10 minutes au lieu d'une heure — et fais-toi payer plus vite.",
        "price": 27,
        "priceNote": "TTC (TVA non applicable)",
        "kind": "product",
        "features": [
            {"title": "Devis et factures prêts", "detail": "6 devis et 7 factures pré-remplis (Word + Excel avec calculs TVA auto)."},
            {"title": "CGV type électricien", "detail": "16 articles conformes 2026, avec 3 niveaux de relance impayés."},
            {"title": "Tableau de suivi Excel", "detail": "Dashboard auto avec 12 KPI : CA, impayés, alertes retard."},
            {"title": "Guide chiffrage 18 pages", "detail": "Méthode de facturation, temps de pose, cas pratiques."},
            {"title": "Bundle Outils Pro", "detail": "11 calculateurs chantier offerts à vie (valeur 108 €/an)."},
        ],
    },
}


def main():
    text = APPS_JSON.read_text(encoding="utf-8")
    data = json.loads(text)
    n_changed = 0
    for app in data.get("apps", []):
        upd = UPDATES.get(app.get("id"))
        if not upd:
            continue
        # Si un champ est null/"" dans upd, on l'écrase quand même (vue mise à jour explicite)
        for k, v in upd.items():
            app[k] = v
        n_changed += 1
    APPS_JSON.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"✓ {n_changed} produits mis à jour dans {APPS_JSON.name}")


if __name__ == "__main__":
    main()
