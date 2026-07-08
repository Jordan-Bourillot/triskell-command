# -*- coding: utf-8 -*-
"""Essais du connecteur WordPress Porte-Voix, chez un client ou en local.

Usage (le mot de passe d'application entre guillemets, avec ses espaces) :
  python scripts/pdv_wordpress.py --site https://exemple.fr --identifiant portevoix --mdp "xxxx xxxx xxxx xxxx xxxx xxxx"
  ... --tester              # vérifier la connexion (action par défaut)
  ... --publier-test        # ajouter un brouillon de test (jamais en ligne)
  ... --lister              # ce que nous avons ajouté chez ce client
  ... --retirer 123         # mettre à la corbeille (nos contenus uniquement)

Rien ne part en ligne depuis ce script : le brouillon de test reste un
brouillon, visible seulement dans l'administration du site.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from triskell_command.integrations.partdevoix import wordpress  # noqa: E402

TITRE_TEST = "Essai Porte-Voix (brouillon, à retirer)"
CONTENU_TEST = ("<p>Brouillon de test du connecteur Porte-Voix. Il ne sera "
                "jamais publié et peut être retiré sans aucun risque.</p>")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Connecteur WordPress Porte-Voix (essais)")
    p.add_argument("--site", required=True, help="adresse du site client")
    p.add_argument("--identifiant", required=True,
                   help="identifiant du compte dédié (portevoix)")
    p.add_argument("--mdp", required=True,
                   help="mot de passe d'application, entre guillemets")
    p.add_argument("--tester", action="store_true",
                   help="vérifier la connexion (action par défaut)")
    p.add_argument("--publier-test", action="store_true",
                   dest="publier_test",
                   help="ajouter un brouillon de test")
    p.add_argument("--lister", action="store_true",
                   help="lister ce que nous avons ajouté")
    p.add_argument("--retirer", type=int, default=0, metavar="NUMERO",
                   help="mettre un de nos contenus à la corbeille")
    args = p.parse_args()

    if args.publier_test:
        r = wordpress.publier_page(args.site, args.identifiant, args.mdp,
                                   TITRE_TEST, CONTENU_TEST)
        if not r["ok"]:
            print(f"ECHEC : {r['erreur']}")
            return 1
        print(f"OK, {r['genre']} n° {r['id']} ajouté en {r['statut']}.")
        print(f"Pour le retirer : python scripts/pdv_wordpress.py "
              f"--site {args.site} --identifiant {args.identifiant} "
              f"--mdp \"...\" --retirer {r['id']}")
        return 0

    if args.lister:
        r = wordpress.lister_nos_pages(args.site, args.identifiant, args.mdp)
        if not r["ok"]:
            print(f"ECHEC : {r['erreur']}")
            return 1
        if not r["pages"]:
            print("Rien de nous chez ce client (aucun contenu ajouté).")
            return 0
        print(f"{len(r['pages'])} contenu(s) ajouté(s) par nous :")
        for page in r["pages"]:
            print(f"  n° {page['id']}  [{page['statut']}]  {page['titre']}"
                  f"  ({page['genre']}, {page['date']})")
        return 0

    if args.retirer:
        r = wordpress.retirer_page(args.site, args.identifiant, args.mdp,
                                   args.retirer)
        if not r["ok"]:
            print(f"ECHEC : {r['erreur']}")
            return 1
        print(f"OK, {r['genre']} n° {r['id']} mis à la corbeille "
              "(WordPress le garde 30 jours).")
        return 0

    # Action par défaut : tester la connexion.
    r = wordpress.tester_connexion(args.site, args.identifiant, args.mdp)
    if not r["ok"]:
        print(f"ECHEC : {r['erreur']}")
        return 1
    print(f"OK, connecté à {r['site']} en tant que « {r['utilisateur']} ».")
    print(f"Publication possible en : {r['genre_publication']}.")
    for a in r.get("avertissements") or []:
        print(f"  Note : {a}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
