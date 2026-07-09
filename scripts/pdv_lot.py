# -*- coding: utf-8 -*-
"""Génère les audits Porte-Voix d'un lot de prospects de la base.

Prend les prospects éligibles (métier Porte-Voix + site + mail + statut
frais), génère l'audit de chacun (page HTML + lien mémorisé pour
{lien_audit}), et écrit un journal de lot.

Usage :
  python scripts/pdv_lot.py --max 50            # le lot du jour
  python scripts/pdv_lot.py --max 5 --passes 1  # essai économique
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DOSSIER_AUDITS = (Path(__file__).resolve().parents[2]
                  / "portevoix" / "site" / "audits")


def main() -> int:
    p = argparse.ArgumentParser(description="Lot d'audits Porte-Voix")
    p.add_argument("--max", type=int, default=50)
    p.add_argument("--passes", type=int, default=2)
    args = p.parse_args()

    from triskell_core.prospect.core.crm import get_crm
    from triskell_core.prospect.pipeline import _offer_product_for
    from triskell_command.integrations.partdevoix import audit, liens, moteur

    cles = moteur.recuperer_cles()
    if not moteur.providers_web(cles):
        print("ECHEC : aucune IA web configurée.")
        return 1

    crm = get_crm()
    eligibles = []
    for prospect in crm.all():
        statut = (getattr(prospect, "status", "") or "").lower()
        if statut not in ("new", "qualified", ""):
            continue
        emails = getattr(prospect, "emails", None) or []
        if not emails:
            continue
        if not _offer_product_for(prospect):
            continue
        # Déjà un audit mémorisé ? On ne paie pas deux fois.
        if liens.audit_url_for(email=emails[0]):
            continue
        eligibles.append(prospect)

    lot = eligibles[: args.max]
    print(f"{len(eligibles)} éligibles sans audit, lot de {len(lot)}")

    fait, rate = 0, 0
    for i, prospect in enumerate(lot, 1):
        nom = prospect.name or "?"
        ville = prospect.city or ""
        metier = prospect.industry or ""
        try:
            resultat = audit.generer_audit(nom, metier, ville,
                                           passes=args.passes, cles=cles)
            if not resultat.get("nb_reponses"):
                print(f"[{i}/{len(lot)}] {nom} : AUCUNE réponse d'IA, sauté")
                rate += 1
                continue
            fichiers = audit.enregistrer(resultat, DOSSIER_AUDITS)
            liens.enregistrer_lien(
                email=prospect.emails[0], entreprise=nom, ville=ville,
                url=f"{liens.BASE_URL}/{fichiers['url_relative']}",
                issue=resultat["issue"])
            print(f"[{i}/{len(lot)}] {nom} ({ville}) : {resultat['issue']}, "
                  f"part {resultat['part_prospect']:g} %")
            fait += 1
        except Exception as exc:
            print(f"[{i}/{len(lot)}] {nom} : ERREUR {exc}")
            rate += 1
        time.sleep(1.5)  # politesse envers les API

    print(f"\nTermine : {fait} audits generes, {rate} rates.")
    print("Penser a redéployer le site (les audits sont des pages du site).")
    return 0 if fait else 1


if __name__ == "__main__":
    raise SystemExit(main())
