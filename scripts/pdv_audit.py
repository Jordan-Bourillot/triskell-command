# -*- coding: utf-8 -*-
"""Génère un audit La Part de Voix pour un prospect.

Usage :
  python scripts/pdv_audit.py "Cabinet Durand" "courtier" "Rennes"
  python scripts/pdv_audit.py "Cabinet Durand" "courtier" "Rennes" --passes 4

Écrit la page HTML + les données dans lapartdevoix/site/audits/ (adresse
non devinable) et affiche le verdict.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from triskell_command.integrations.partdevoix import audit as pdv_audit  # noqa: E402

DOSSIER_DEFAUT = (Path(__file__).resolve().parents[2]
                  / "lapartdevoix" / "site" / "audits")


def main() -> int:
    p = argparse.ArgumentParser(description="Audit La Part de Voix")
    p.add_argument("entreprise")
    p.add_argument("metier")
    p.add_argument("ville")
    p.add_argument("--passes", type=int, default=3)
    p.add_argument("--dossier", default=str(DOSSIER_DEFAUT))
    p.add_argument("--email", default="",
                   help="mail du prospect, pour brancher {lien_audit} dans "
                        "les modèles de prospection")
    args = p.parse_args()

    print(f"Audit de {args.entreprise} ({args.metier}, {args.ville}), "
          f"{args.passes} passages par question...")
    resultat = pdv_audit.generer_audit(
        args.entreprise, args.metier, args.ville, passes=args.passes)
    if not resultat.get("nb_reponses"):
        print("ECHEC : aucune réponse d'IA recueillie. Clés API web "
              "(OpenAI / Perplexity / Gemini) configurées ?")
        return 1
    fichiers = pdv_audit.enregistrer(resultat, args.dossier)
    try:
        from triskell_command.integrations.partdevoix import liens
        liens.enregistrer_lien(
            email=args.email, entreprise=args.entreprise, ville=args.ville,
            url=f"{liens.BASE_URL}/{fichiers['url_relative']}",
            issue=resultat["issue"])
        print("Lien enregistré pour {lien_audit}.")
    except Exception as exc:
        print(f"(index des liens non mis à jour : {exc})")
    print(f"Issue : {resultat['issue']}")
    print(f"Part de voix du prospect : {resultat['part_prospect']:g} %")
    for c in resultat["concurrents"]:
        print(f"  concurrent cité : {c['nom']} ({c['part']:g} %)")
    print(f"Page : {fichiers['html']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
