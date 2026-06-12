# -*- coding: utf-8 -*-
"""Batterie « fiche réparée » — la 3e IA qui corrige les fiches sales.

Verrouille le mécanisme du 12/06/2026 (demande Jordan : « quand des
erreurs comme celles-ci sont détectées, une autre IA les corrige ») :

  1. les heuristiques de détection/découpage des noms pollués,
  2. les garde-fous du parseur IA (JAMAIS d'invention de nom),
  3. le nettoyage préventif au versement (data_quality),
  4. le branchement dans le pipeline (présence structurelle),
  5. la règle absolue : aucun enrichissement extérieur dans le module.

Sans réseau, sans Supabase, sans clé IA. Usage :
    python scripts/smoke_fiche_reparee.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "triskell-core"))

OK = 0
KO = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global OK, KO
    if cond:
        OK += 1
        print(f"  [OK] {label}")
    else:
        KO += 1
        print(f"  [KO] {label} {('-- ' + detail) if detail else ''}")


print("== 1. Heuristiques de nom pollué ==")
from triskell_core.prospect.record_repair import (  # noqa: E402
    name_looks_polluted, split_polluted_name, parse_repair, REPAIR_TAG)

GF = ("GF ARMOR ELEC . électricien. Dépannage, installation et rénovation. "
      "Mise aux normes. Devis sous 48h.")
check("le nom GF Armor (cas réel) est détecté pollué", name_looks_polluted(GF))
parts = split_polluted_name(GF)
check("découpage : raison sociale extraite", bool(parts) and parts[0] == "GF ARMOR ELEC",
      str(parts))
check("découpage : le descriptif n'est pas perdu",
      bool(parts) and "Dépannage" in parts[1])
check("un nom sain est laissé tranquille",
      not name_looks_polluted("L'île Aux Huîtres SARL"))
check("un nom sain avec virgule est laissé tranquille",
      not name_looks_polluted("Boulangerie Martin, fils & co"))
check("un nom trop long est suspect",
      name_looks_polluted("X" * 80))
check("un nom vide ne déclenche rien", not name_looks_polluted(""))
check("découpage refusé si le reste est trop court (pas du descriptif)",
      split_polluted_name("SARL Dupont. Rennes") is None)

print("== 2. Garde-fous du parseur IA (jamais d'invention) ==")
ORIG = "L'île Aux Huîtres SARL"
ok_payload = '{"name": null, "industry": "ostréiculture", "reason": "secteur incohérent"}'
rep = parse_repair(ok_payload, original_name=ORIG)
check("proposition de secteur valide acceptée",
      bool(rep) and rep["industry"] == "ostréiculture")
check("name=null respecté (pas de changement de nom)",
      bool(rep) and rep["name"] is None)

invented = '{"name": "Huîtres Bretonnes Premium", "industry": null, "reason": "x"}'
check("nom INVENTÉ refusé (mots absents de l'original)",
      parse_repair(invented, original_name=ORIG) is None)

subset = '{"name": "GF ARMOR ELEC", "industry": null, "reason": "nom nettoyé"}'
rep2 = parse_repair(subset, original_name=GF)
check("nom raccourci à partir des mots d'origine accepté",
      bool(rep2) and rep2["name"] == "GF ARMOR ELEC")

check("JSON malformé -> aucune réparation",
      parse_repair("je pense que {name est", original_name=ORIG) is None)
check("rien à changer (null partout) -> None",
      parse_repair('{"name": null, "industry": null, "reason": "ok"}',
                   original_name=ORIG) is None)
check("industry insensée (trop longue) refusée",
      parse_repair('{"name": null, "industry": "' + "x" * 60 + '", "reason": ""}',
                   original_name=ORIG) is None)
check("industry avec caractères louches refusée",
      parse_repair('{"name": null, "industry": "<script>alert(1)</script>", "reason": ""}',
                   original_name=ORIG) is None)

print("== 3. Nettoyage préventif au versement (data_quality) ==")
from triskell_command.integrations.data_quality import (  # noqa: E402
    filter_for_push, report_to_french)

batch = [
    {"nom": GF, "email": "gfarmorelec@outlook.fr"},
    {"nom": "Boulangerie Martin", "email": "martin@boulangerie.fr"},
    {"nom": "test", "email": "test@vrai-domaine.fr"},
]
kept, report = filter_for_push(batch)
check("la fournée garde les fiches valides", len(kept) == 2, str(report))
check("le nom pollué a été nettoyé au versement",
      kept[0]["nom"] == "GF ARMOR ELEC", repr(kept[0].get("nom")))
check("le descriptif est rangé dans la fiche (pas perdu)",
      "Dépannage" in (kept[0].get("description") or ""))
check("le compteur cleaned_names compte juste", report.get("cleaned_names") == 1)
check("le nom sain n'est pas modifié", kept[1]["nom"] == "Boulangerie Martin")
check("le rapport français mentionne le nettoyage",
      "nettoyé" in report_to_french(report))
b2, r2 = filter_for_push([{"nom": "Plombier Breizh", "email": "pb@breizh.fr"}])
check("fournée 100% saine : aucun nettoyage, rapport muet",
      r2.get("cleaned_names") == 0 and "nettoyé" not in report_to_french(r2))

print("== 4. Branchement dans le pipeline (structurel) ==")
pipeline_src = (ROOT.parent / "triskell-core" / "triskell_core" / "prospect"
                / "pipeline.py").read_text(encoding="utf-8")
check("le pipeline importe record_repair",
      "from .record_repair import" in pipeline_src)
check("la réparation n'agit QUE sur verdict draft",
      'review_for_draft.get("verdict") == "draft"' in pipeline_src)
check("anti-boucle : une fiche déjà réparée ne repasse pas",
      '"fiche_reparee" not in (prospect.tags or [])' in pipeline_src)
check("le brouillon fautif n'est PAS créé après réparation (continue)",
      "continue" in pipeline_src.split("fiche réparée")[1][:600]
      if "fiche réparée" in pipeline_src else False)
check("la fiche réparée est persistée",
      "_persist_prospect(crm, prospect)" in
      pipeline_src.split("record_repaired")[0][-2500:]
      if "record_repaired" in pipeline_src else False)
check("trace dans l'historique (record_repaired)",
      '"kind": "record_repaired"' in pipeline_src)
check("le tag de réparation vient du module central",
      "REPAIR_TAG" in pipeline_src and REPAIR_TAG == "fiche_reparee")

print("== 5. Règle absolue : aucun enrichissement extérieur ==")
repair_src = (ROOT.parent / "triskell-core" / "triskell_core" / "prospect"
              / "record_repair.py").read_text(encoding="utf-8")
for forbidden in ("import requests", "urllib", "httpx", "BeautifulSoup",
                  "duckduckgo", "googlesearch"):
    check(f"record_repair ne touche pas au réseau ({forbidden})",
          forbidden not in repair_src)
check("le prompt interdit explicitement l'invention",
      "N'invente rien" in repair_src)
check("seuls name/industry/description sont réparables",
      "emails/téléphones/urls intouchables" in repair_src)

print()
print(f"{OK} OK / {KO} KO")
sys.exit(1 if KO else 0)
