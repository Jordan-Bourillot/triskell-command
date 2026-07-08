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
                    "réponses des IA (ChatGPT, Perplexity, Gemini), "
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


def _corps(question: str, metier: str) -> str:
    return (
        f"Bonjour,\n\n"
        f"Quand un particulier demande à ChatGPT « {question} {{ville}} », "
        f"la réponse cite des noms de {metier}. Nous avons posé la question "
        f"plusieurs dizaines de fois, sous plusieurs formulations, sur "
        f"ChatGPT et Perplexity. {{raison_sociale}} n'y apparaît pas, ou "
        f"trop rarement pour compter.\n\n" + _CORPS_COMMUN
    )


TEMPLATES = [
    {
        "key": "lpv_cabinet_courtier_a",
        "label": "Porte-Voix — courtier, objet A",
        "subject": "Ce que ChatGPT répond à « quel courtier à {ville} »",
        "body_text": _corps("vers quel courtier se tourner à", "cabinets"),
    },
    {
        "key": "lpv_cabinet_courtier_b",
        "label": "Porte-Voix — courtier, objet B",
        "subject": "Vos concurrents sont dans les réponses de ChatGPT. Pas {raison_sociale}.",
        "body_text": _corps("vers quel courtier se tourner à", "cabinets"),
    },
    {
        "key": "lpv_cabinet_comptable_a",
        "label": "Porte-Voix — expert-comptable, objet A",
        "subject": "Ce que ChatGPT répond à « quel expert-comptable à {ville} »",
        "body_text": _corps("quel expert-comptable choisir pour une petite entreprise à", "cabinets"),
    },
    {
        "key": "lpv_cabinet_comptable_b",
        "label": "Porte-Voix — expert-comptable, objet B",
        "subject": "Vos confrères sont dans les réponses de ChatGPT. Pas {raison_sociale}.",
        "body_text": _corps("quel expert-comptable choisir pour une petite entreprise à", "cabinets"),
    },
    {
        "key": "lpv_cabinet_avocat_a",
        "label": "Porte-Voix — avocat, objet A",
        "subject": "Ce que ChatGPT répond à « quel avocat à {ville} »",
        "body_text": _corps("quel avocat consulter à", "cabinets"),
    },
    {
        "key": "lpv_cabinet_avocat_b",
        "label": "Porte-Voix — avocat, objet B",
        "subject": "Vos confrères sont dans les réponses de ChatGPT. Pas {raison_sociale}.",
        "body_text": _corps("quel avocat consulter à", "cabinets"),
    },
    {
        "key": "lpv_commerce_immo_a",
        "label": "Porte-Voix — agence immobilière, objet A",
        "subject": "Ce que ChatGPT répond à « quelle agence pour vendre à {ville} »",
        "body_text": _corps("quelle agence immobilière pour vendre un bien à", "agences"),
    },
    {
        "key": "lpv_commerce_immo_b",
        "label": "Porte-Voix — agence immobilière, objet B",
        "subject": "Vos concurrents sont dans les réponses de ChatGPT. Pas {raison_sociale}.",
        "body_text": _corps("quelle agence immobilière pour vendre un bien à", "agences"),
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
            "description": ("Mail initial Porte-Voix (issue « concurrents "
                            "cités »). Ne s'envoie qu'à un prospect dont "
                            "l'audit est en issue A."),
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
