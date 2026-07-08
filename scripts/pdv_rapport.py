# -*- coding: utf-8 -*-
"""Génère le rapport mensuel d'un client Porte-Voix.

Usage :
  python scripts/pdv_rapport.py "Cabinet Durand"
  python scripts/pdv_rapport.py "Cabinet Durand" --fait "2 pages publiées" --fait "Fiche Google complétée" --avenir "3 avis clients à collecter"
  python scripts/pdv_rapport.py "Cabinet Durand" --sans-mesure

Mesure la part de voix du client et de ses concurrents désignés
(3 passages par question par défaut), archive le relevé, puis écrit la
page HTML du rapport dans portevoix/rapports/ (adresse non devinable).
--sans-mesure rejoue le dernier relevé archivé, sans aucun appel aux IA.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from triskell_command.integrations.partdevoix import (  # noqa: E402
    clients, rapport)

DOSSIER_DEFAUT = (Path(__file__).resolve().parents[2]
                  / "portevoix" / "rapports")


def main() -> int:
    p = argparse.ArgumentParser(description="Rapport mensuel Porte-Voix")
    p.add_argument("client", help="id ou nom de l'entreprise")
    p.add_argument("--passes", type=int, default=3)
    p.add_argument("--sans-mesure", action="store_true",
                   help="ne pas relancer de mesure : rejouer le dernier "
                        "relevé archivé")
    p.add_argument("--fait", action="append",
                   help="répétable : ce qui a été fait ce mois-ci (sinon "
                        "la rubrique posée sur la fiche)")
    p.add_argument("--avenir", action="append",
                   help="répétable : ce qui vient le mois prochain")
    p.add_argument("--dossier", default=str(DOSSIER_DEFAUT))
    args = p.parse_args()

    if args.passes < 1:
        print("ECHEC : --passes doit valoir au moins 1.")
        return 1

    client = clients.trouver_client(args.client)
    if client is None:
        print(f"ECHEC : client introuvable : {args.client}")
        actifs = clients.lister_clients()
        if actifs:
            print("Clients suivis : "
                  + ", ".join(c["entreprise"] for c in actifs))
        else:
            print("Le registre est vide (python scripts/pdv_client.py "
                  "ajouter ...).")
        return 1

    try:
        if args.sans_mesure:
            print(f"Rejeu du dernier relevé de {client['entreprise']} "
                  f"(aucun appel aux IA).")
        else:
            if not client.get("actif", True):
                print(f"ECHEC : {client['entreprise']} est désactivé, pas "
                      f"de nouvelle mesure (rejeu possible avec "
                      f"--sans-mesure).")
                return 1
            questions = clients.questions_du_client(client)
            print(f"Mesure de {client['entreprise']} : {len(questions)} "
                  f"questions, {args.passes} passages par question...")
            releve = rapport.mesurer_client(client, passes=args.passes)
            print(f"{releve['nb_reponses']} réponses recueillies sur "
                  f"{', '.join(releve['ias']) or '?'}.")
        donnees = rapport.generer_rapport(client, fait=args.fait,
                                          avenir=args.avenir)
        fichiers = rapport.enregistrer(donnees, args.dossier)
    except ValueError as exc:
        print(f"ECHEC : {exc}")
        return 1

    print(f"Part de voix : {donnees['part_client']:g} % — "
          f"{rapport.texte_evolution(donnees['evolution'])}.")
    for c in donnees["concurrents"]:
        print(f"  concurrent : {c['nom']} {c['part']:g} % — "
              f"{rapport.texte_evolution(c['evolution'], pour_concurrent=True)}")
    if donnees["moyenne_concurrents"] is not None:
        print(f"  moyenne des concurrents : "
              f"{donnees['moyenne_concurrents']:g} %")
    for alerte in donnees["alertes"]:
        print(f"  (!) {alerte}")
    print(f"Page : {fichiers['html']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
