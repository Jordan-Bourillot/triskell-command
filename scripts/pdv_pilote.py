# -*- coding: utf-8 -*-
"""Lance un relevé du pilote Porte-Voix (panel cibles + témoins).

Usage :
  python scripts/pdv_pilote.py            # relevé complet (2 passages)
  python scripts/pdv_pilote.py --passes 3
  python scripts/pdv_pilote.py --resume   # affiche l'historique sans mesurer

L'historique s'accumule dans ~/.triskell-command/partdevoix_pilote.json.
À relancer chaque semaine pendant la construction (mêmes questions,
comparaison dans le temps).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from triskell_command.integrations.partdevoix import pilote  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Pilote Porte-Voix")
    p.add_argument("--passes", type=int, default=2)
    p.add_argument("--resume", action="store_true",
                   help="afficher l'historique sans lancer de mesure")
    args = p.parse_args()

    if args.resume:
        print(pilote.resume())
        return 0

    print(f"Relevé du panel ({len(pilote.PANEL)} questions, "
          f"{args.passes} passages)...")
    releve = pilote.lancer_panel(passes=args.passes)
    if not releve.get("ok"):
        print(f"ECHEC : {releve.get('erreur')}")
        return 1
    print(f"OK, {sum(r['nb_reponses'] for r in releve['resultats'])} "
          f"réponses recueillies sur {releve['providers']}.")
    print(pilote.resume())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
