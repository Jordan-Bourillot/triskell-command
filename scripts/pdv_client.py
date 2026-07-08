# -*- coding: utf-8 -*-
"""Gère le registre des clients Porte-Voix (fichier local).

Usage :
  python scripts/pdv_client.py ajouter "Cabinet Durand" --metier "courtier" --ville "Rennes" --concurrent "Le Goff Assurances" --concurrent "Cabinet Petit" --palier "essentiel"
  python scripts/pdv_client.py lister
  python scripts/pdv_client.py lister --tous
  python scripts/pdv_client.py modifier "Cabinet Durand" --fait "2 pages publiées" --avenir "3 avis clients à collecter"
  python scripts/pdv_client.py desactiver "Cabinet Durand"
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from triskell_command.integrations.partdevoix import clients  # noqa: E402


def _ligne(c: dict) -> str:
    etat = "actif" if c.get("actif", True) else "DESACTIVE"
    villes = ", ".join(c.get("villes") or [])
    concs = ", ".join(c.get("concurrents") or []) or "aucun concurrent désigné"
    return (f"  [{etat}] {c.get('entreprise')} (id {c.get('id')}) — "
            f"{c.get('metier')}, {villes} — palier "
            f"{c.get('palier') or 'non renseigné'} — entré le "
            f"{c.get('entree_le')}\n"
            f"          concurrents : {concs}")


def main() -> int:
    p = argparse.ArgumentParser(description="Registre des clients Porte-Voix")
    sous = p.add_subparsers(dest="action", required=True)

    aj = sous.add_parser("ajouter", help="ajouter un client suivi")
    aj.add_argument("entreprise")
    aj.add_argument("--metier", required=True)
    aj.add_argument("--ville", action="append", required=True,
                    help="répétable : --ville Rennes --ville Nantes")
    aj.add_argument("--concurrent", action="append", default=[],
                    help="répétable, 3 au maximum")
    aj.add_argument("--question", action="append", default=[],
                    help="répétable : questions personnalisées (sinon "
                         "celles du métier)")
    aj.add_argument("--palier", default="")
    aj.add_argument("--entree", default="",
                    help="date d'entrée AAAA-MM-JJ (défaut : aujourd'hui)")

    li = sous.add_parser("lister", help="lister les clients suivis")
    li.add_argument("--tous", action="store_true",
                    help="inclure les clients désactivés")

    mo = sous.add_parser("modifier", help="modifier une fiche")
    mo.add_argument("client", help="id ou nom de l'entreprise")
    mo.add_argument("--metier")
    mo.add_argument("--ville", action="append")
    mo.add_argument("--concurrent", action="append")
    mo.add_argument("--question", action="append")
    mo.add_argument("--palier")
    mo.add_argument("--fait", action="append",
                    help="répétable : ce qui a été fait ce mois-ci "
                         "(repris par le prochain rapport)")
    mo.add_argument("--avenir", action="append",
                    help="répétable : ce qui vient le mois prochain")

    de = sous.add_parser("desactiver", help="sortir un client du suivi")
    de.add_argument("client", help="id ou nom de l'entreprise")

    args = p.parse_args()
    try:
        if args.action == "ajouter":
            c = clients.ajouter_client(
                args.entreprise, args.metier, args.ville,
                concurrents=args.concurrent, questions=args.question,
                palier=args.palier, entree_le=args.entree)
            print(f"Client ajouté (id {c['id']}).")
            print(_ligne(c))
        elif args.action == "lister":
            liste = clients.lister_clients(actifs=not args.tous)
            if not liste:
                print("Aucun client dans le registre.")
            for c in liste:
                print(_ligne(c))
        elif args.action == "modifier":
            champs = {}
            for nom, valeur in (("metier", args.metier),
                                ("villes", args.ville),
                                ("concurrents", args.concurrent),
                                ("questions", args.question),
                                ("palier", args.palier),
                                ("fait", args.fait),
                                ("avenir", args.avenir)):
                if valeur is not None:
                    champs[nom] = valeur
            if not champs:
                print("Rien à modifier (aucune option fournie).")
                return 1
            c = clients.modifier_client(args.client, **champs)
            print("Fiche mise à jour.")
            print(_ligne(c))
        else:  # desactiver
            c = clients.desactiver_client(args.client)
            print(f"{c['entreprise']} sorti du suivi (historique conservé).")
    except ValueError as exc:
        print(f"ECHEC : {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
