# -*- coding: utf-8 -*-
"""Installe l'offre « Porte-Voix » dans Triskell Command.

Crée le produit au catalogue central et pose ses 8 modèles de mails de
prospection en base (2 objets par segment : courtier, expert-comptable,
avocat, agence immobilière).

SÉCURITÉ : tout est posé DÉSARMÉ (produit inactif + modèles désactivés).
Tant que rien n'est armé, l'Auto-pilote se comporte exactement comme avant.

Usage :
  python scripts/pdv_catalogue.py            # installe, désarmé
  python scripts/pdv_catalogue.py --etat     # montre l'état actuel
  python scripts/pdv_catalogue.py --armer    # active produit + modèles (GO Jordan)
  python scripts/pdv_catalogue.py --desarmer # coupe tout
  python scripts/pdv_catalogue.py --adresse contact@triskell-studio.fr
      # fixe l'adresse d'expéditeur exigée sur tous les modèles (après
      # création et chauffe des boîtes dédiées ; vide au lancement =
      # tirage dans le pool d'adresses existant)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PRODUIT_ID = "la-part-de-voix"

PRODUIT = {
    "id": PRODUIT_ID,
    "name": "Porte-Voix",
    "tagline": "Être dans la réponse quand vos clients demandent à ChatGPT",
    "description": ("Service mensuel : mesure de la part de voix dans les "
                    "réponses des IA (ChatGPT, Gemini), "
                    "publications qui la construisent, rapport lisible en "
                    "deux minutes. Sans engagement."),
    "category": "services",
    "kind": "service",
    "price": 149,
    "price_note": "HT/mois (lancement, verrouillé à vie ; grille 179/290/449)",
    "buy_url": "https://portevoix.triskell-studio.fr",
    "color": "#1c2b3a",
    "initial": "V",
}

_SIGNATURE = "{sender_name}\nPorte-Voix, un service de Triskell Studio"

_CORPS_COMMUN = (
    "Le relevé complet, captures d'écran comprises, se consulte en deux "
    "minutes : {lien_audit}\n\n"
    "Ces réponses varient d'une conversation à l'autre, l'audit mesure une "
    "tendance, pas une vérité absolue. Elle est nette. Et ChatGPT compte "
    "plus de 18 millions d'utilisateurs par mois en France (mesure "
    "Médiamétrie).\n\n"
    "Porte-Voix fait le travail pour que votre nom apparaisse dans ces "
    "réponses, mesure le résultat chaque mois, et vous l'envoie dans un "
    "rapport lisible en deux minutes. 149 euros par mois au tarif de "
    "lancement, sans engagement, premier mois remboursé s'il ne vous "
    "convainc pas.\n\n"
    "Le détail : https://portevoix.triskell-studio.fr\n\n" + _SIGNATURE
)


_PIED_OFFRE = (
    "149 euros par mois au tarif de lancement, sans engagement, premier "
    "mois remboursé s'il ne vous convainc pas.\n\n"
    "Le détail : https://portevoix.triskell-studio.fr\n\n" + _SIGNATURE
)


def _corps(question: str, noms_de: str) -> str:
    """Mail « concurrents cités » : ses rivaux sortent, pas lui."""
    return (
        f"Bonjour,\n\n"
        f"Quand un particulier demande à ChatGPT « {question} {{ville}} », "
        f"la réponse cite des noms {noms_de}. Nous avons posé la question "
        f"plusieurs dizaines de fois, sous plusieurs formulations, sur "
        f"ChatGPT et Gemini. {{raison_sociale}} n'y apparaît pas, ou "
        f"trop rarement pour compter.\n\n" + _CORPS_COMMUN
    )


def _corps_deja(question: str) -> str:
    """Mail « déjà cité » : sa place existe, elle se surveille et se défend.
    JAMAIS envoyé à un absent (l'aiguillage par issue s'en charge)."""
    return (
        f"Bonjour,\n\n"
        f"Bonne nouvelle. Quand un particulier demande à ChatGPT "
        f"« {question} {{ville}} », {{raison_sociale}} apparaît dans une "
        f"partie des réponses. Nous avons mesuré à quelle fréquence, et "
        f"face à qui :\n\n"
        f"Le relevé complet, captures d'écran comprises : {{lien_audit}}\n\n"
        f"Cette position n'est pas acquise. Les réponses des IA bougent au "
        f"fil de ce qu'elles trouvent en ligne, et vos concurrents finiront "
        f"par s'intéresser à la place que vous occupez. Porte-Voix surveille "
        f"votre part de voix chaque mois, entretient ce qui la soutient, et "
        f"vous envoie le relevé dans un rapport lisible en deux minutes.\n\n"
        + _PIED_OFFRE
    )


def _corps_vide(question: str, metier_nom: str) -> str:
    """Mail « place vide » : personne n'est cité, premier arrivé premier
    cité. Pour les villes moyennes et les métiers encore muets."""
    return (
        f"Bonjour,\n\n"
        f"Quand un particulier demande à ChatGPT « {question} {{ville}} », "
        f"la réponse ne cite aujourd'hui aucun professionnel local. Nous "
        f"avons vérifié, plusieurs dizaines de fois, sous plusieurs "
        f"formulations :\n\n"
        f"Le relevé complet : {{lien_audit}}\n\n"
        f"Cette place vide ne le restera pas. Les IA citent les "
        f"professionnels dont elles trouvent des traces solides en ligne, "
        f"et le premier {metier_nom} de {{ville}} qui s'en occupe "
        f"sérieusement prendra la place, avant que les autres ne s'y "
        f"mettent. Porte-Voix fait ce travail, mesure le résultat chaque "
        f"mois, et vous l'envoie dans un rapport lisible en deux minutes.\n\n"
        + _PIED_OFFRE
    )


TEMPLATES = [
    {
        "key": "lpv_cabinet_courtier_a",
        "label": "Porte-Voix — courtier, objet A",
        "subject": "Ce que ChatGPT répond à « quel courtier à {ville} »",
        "body_text": _corps("vers quel courtier se tourner à", "de cabinets"),
    },
    {
        "key": "lpv_cabinet_courtier_b",
        "label": "Porte-Voix — courtier, objet B",
        "subject": "Vos concurrents sont dans les réponses de ChatGPT. Pas {raison_sociale}.",
        "body_text": _corps("vers quel courtier se tourner à", "de cabinets"),
    },
    {
        "key": "lpv_cabinet_comptable_a",
        "label": "Porte-Voix — expert-comptable, objet A",
        "subject": "Ce que ChatGPT répond à « quel expert-comptable à {ville} »",
        "body_text": _corps("quel expert-comptable choisir pour une petite entreprise à", "de cabinets"),
    },
    {
        "key": "lpv_cabinet_comptable_b",
        "label": "Porte-Voix — expert-comptable, objet B",
        "subject": "Vos confrères sont dans les réponses de ChatGPT. Pas {raison_sociale}.",
        "body_text": _corps("quel expert-comptable choisir pour une petite entreprise à", "de cabinets"),
    },
    {
        "key": "lpv_cabinet_avocat_a",
        "label": "Porte-Voix — avocat, objet A",
        "subject": "Ce que ChatGPT répond à « quel avocat à {ville} »",
        "body_text": _corps("quel avocat consulter à", "de cabinets"),
    },
    {
        "key": "lpv_cabinet_avocat_b",
        "label": "Porte-Voix — avocat, objet B",
        "subject": "Vos confrères sont dans les réponses de ChatGPT. Pas {raison_sociale}.",
        "body_text": _corps("quel avocat consulter à", "de cabinets"),
    },
    {
        "key": "lpv_commerce_immo_a",
        "label": "Porte-Voix — agence immobilière, objet A",
        "subject": "Ce que ChatGPT répond à « quelle agence pour vendre à {ville} »",
        "body_text": _corps("quelle agence immobilière pour vendre un bien à", "d'agences"),
    },
    {
        "key": "lpv_commerce_immo_b",
        "label": "Porte-Voix — agence immobilière, objet B",
        "subject": "Vos concurrents sont dans les réponses de ChatGPT. Pas {raison_sociale}.",
        "body_text": _corps("quelle agence immobilière pour vendre un bien à", "d'agences"),
    },
    # --- Issue « déjà cité » (le prospect apparaît : on défend sa place,
    #     jamais le mail « vous n'y apparaissez pas ») ---
    {
        "key": "lpv_cabinet_courtier_deja",
        "label": "Porte-Voix — courtier, déjà cité",
        "subject": "{raison_sociale} est cité par ChatGPT. Voici où.",
        "body_text": _corps_deja("vers quel courtier se tourner à"),
    },
    {
        "key": "lpv_cabinet_comptable_deja",
        "label": "Porte-Voix — expert-comptable, déjà cité",
        "subject": "{raison_sociale} est cité par ChatGPT. Voici où.",
        "body_text": _corps_deja("quel expert-comptable choisir pour une petite entreprise à"),
    },
    {
        "key": "lpv_cabinet_avocat_deja",
        "label": "Porte-Voix — avocat, déjà cité",
        "subject": "{raison_sociale} est cité par ChatGPT. Voici où.",
        "body_text": _corps_deja("quel avocat consulter à"),
    },
    {
        "key": "lpv_commerce_immo_deja",
        "label": "Porte-Voix — agence immobilière, déjà citée",
        "subject": "{raison_sociale} est citée par ChatGPT. Voici où.",
        "body_text": _corps_deja("quelle agence immobilière pour vendre un bien à"),
    },
    # --- Issue « place vide » (personne n'est cité : premier arrivé,
    #     premier cité — villes moyennes et métiers encore muets) ---
    {
        "key": "lpv_cabinet_courtier_vide",
        "label": "Porte-Voix — courtier, place vide",
        "subject": "Personne n'est encore la réponse de ChatGPT à {ville}",
        "body_text": _corps_vide("vers quel courtier se tourner à", "courtier"),
    },
    {
        "key": "lpv_cabinet_comptable_vide",
        "label": "Porte-Voix — expert-comptable, place vide",
        "subject": "Personne n'est encore la réponse de ChatGPT à {ville}",
        "body_text": _corps_vide("quel expert-comptable choisir pour une petite entreprise à", "cabinet"),
    },
    {
        "key": "lpv_cabinet_avocat_vide",
        "label": "Porte-Voix — avocat, place vide",
        "subject": "Personne n'est encore la réponse de ChatGPT à {ville}",
        "body_text": _corps_vide("quel avocat consulter à", "cabinet"),
    },
    {
        "key": "lpv_commerce_immo_vide",
        "label": "Porte-Voix — agence immobilière, place vide",
        "subject": "Personne n'est encore la réponse de ChatGPT à {ville}",
        "body_text": _corps_vide("quelle agence immobilière pour vendre un bien à", "professionnel"),
    },
]

PLACEHOLDERS = ["{ville}", "{raison_sociale}", "{lien_audit}", "{sender_name}"]


def _sb():
    from triskell_core.db import get_client
    return get_client()


def installer(sb) -> None:
    from triskell_command.integrations import catalog_central
    res = catalog_central.save_product(PRODUIT)
    print(f"Produit au catalogue : {res.get('ok', res)}")
    # Un produit fraîchement créé naît ACTIF : on le désarme aussitôt,
    # l'armement est un geste explicite (--armer, au GO de Jordan).
    catalog_central.set_active(PRODUIT_ID, False)
    for t in TEMPLATES:
        ligne = {
            "product": PRODUIT_ID,
            "key": t["key"],
            "category": "prospection",
            "audience": "pro",
            "enabled": False,
            "label": t["label"],
            "subject": t["subject"],
            "body_text": t["body_text"],
            "from_address": "",
            "placeholders": PLACEHOLDERS,
            "description": ("Mail initial Porte-Voix. L'aiguillage par issue "
                            "d'audit choisit automatiquement le bon modèle "
                            "(concurrents cités / déjà cité / place vide) et "
                            "saute tout prospect sans audit généré."),
        }
        existant = (sb.table("triskell_email_templates")
                    .select("key")
                    .eq("product", PRODUIT_ID).eq("key", t["key"])
                    .execute().data or [])
        if existant:
            (sb.table("triskell_email_templates")
             .update(ligne)
             .eq("product", PRODUIT_ID).eq("key", t["key"]).execute())
            print(f"  modèle mis à jour : {t['key']}")
        else:
            sb.table("triskell_email_templates").insert(ligne).execute()
            print(f"  modèle créé : {t['key']} (désactivé)")


def armer(sb, actif: bool) -> None:
    from triskell_command.integrations import catalog_central
    catalog_central.set_active(PRODUIT_ID, actif)
    (sb.table("triskell_email_templates")
     .update({"enabled": actif})
     .eq("product", PRODUIT_ID).eq("category", "prospection").execute())
    print(f"Produit et modèles {'ARMÉS' if actif else 'désarmés'}.")
    if actif:
        print("⚠️ À partir de maintenant, les métiers Porte-Voix avec site "
              "reçoivent SES mails (jamais ceux de Pixel Pro), et "
              "réciproquement. Vérifier qu'un lot d'audits est généré "
              "(scripts/pdv_audit.py) avant tout passage de l'Auto-pilote.")


def adresse(sb, valeur: str) -> None:
    (sb.table("triskell_email_templates")
     .update({"from_address": valeur.strip()})
     .eq("product", PRODUIT_ID).eq("category", "prospection").execute())
    print(f"Adresse d'expéditeur exigée sur tous les modèles : "
          f"'{valeur.strip() or '(aucune : pool par défaut)'}'")


def etat(sb) -> None:
    from triskell_command.integrations import catalog_central
    full = catalog_central.get_full()
    prod = next((p for p in full.get("products", [])
                 if p.get("id") == PRODUIT_ID), None)
    if prod is None:
        print("Produit : ABSENT du catalogue (lancer sans option pour l'installer)")
    else:
        print(f"Produit : présent, {'ACTIF' if prod.get('is_active') else 'inactif'}")
    rows = (sb.table("triskell_email_templates")
            .select("key, enabled, from_address")
            .eq("product", PRODUIT_ID).execute().data or [])
    print(f"Modèles : {len(rows)}")
    for r in rows:
        print(f"  {r['key']}: {'ACTIF' if r.get('enabled') else 'inactif'}"
              f"{', depuis ' + r['from_address'] if r.get('from_address') else ''}")


def main() -> int:
    p = argparse.ArgumentParser(description="Installer Porte-Voix")
    p.add_argument("--etat", action="store_true")
    p.add_argument("--armer", action="store_true")
    p.add_argument("--desarmer", action="store_true")
    p.add_argument("--adresse", default=None)
    args = p.parse_args()
    sb = _sb()
    if sb is None:
        print("ECHEC : pas de connexion à la base partagée.")
        return 1
    if args.etat:
        etat(sb)
    elif args.armer:
        armer(sb, True)
    elif args.desarmer:
        armer(sb, False)
    elif args.adresse is not None:
        adresse(sb, args.adresse)
    else:
        installer(sb)
        etat(sb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
