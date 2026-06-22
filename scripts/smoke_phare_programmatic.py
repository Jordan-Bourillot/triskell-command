# -*- coding: utf-8 -*-
"""Smoke test : pages en série (SEO programmatique) — UI branchée au moteur.

Le moteur phare/programmatic.py existait mais n'avait NI écran NI circuit de
publication. Ce test vérifie, sans réseau, la validation des entrées de
création de modèle (la partie que Jordan touche) + le garde-fou « table
absente ».

Usage :  python scripts/smoke_phare_programmatic.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
CORE = HERE.parent / "triskell-core"
if CORE.exists():
    sys.path.insert(0, str(CORE))

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'OK  ' if cond else 'FAIL'}- {label} {detail if not cond else ''}")


from triskell_command.web.api import Api  # noqa: E402
import triskell_command.integrations.phare.programmatic as prog  # noqa: E402

api = Api()
captured = {}
prog.create_template = lambda sid, **kw: (
    captured.clear(), captured.update(sid=sid, **kw),
    {"ok": True, "template_id": "t1"})[2]


def mk(**over):
    base = {"site_id": "s1", "name": "Plombier par ville", "var_name": "ville",
            "url_pattern": "/plombier-{ville}",
            "title_pattern": "Plombier à {ville}", "values": "Brest"}
    base.update(over)
    return base


print("1) Validation des entrées…")
check("site manquant → refus",
      api.phare_prog_template_create(mk(site_id="")).get("ok") is False)
check("nom manquant → refus",
      api.phare_prog_template_create(mk(name="")).get("ok") is False)
r = api.phare_prog_template_create(mk(url_pattern="/plombier"))
check("le mot variable doit figurer dans l'adresse → refus + message clair",
      r.get("ok") is False and "ville" in (r.get("error") or ""))
r = api.phare_prog_template_create(mk(title_pattern="Plombier"))
check("le mot variable doit figurer dans le titre → refus",
      r.get("ok") is False)
check("liste de valeurs vide → refus",
      api.phare_prog_template_create(mk(values="   ")).get("ok") is False)

print("2) Parsing de la liste de valeurs…")
r = api.phare_prog_template_create(
    mk(values="Brest\nQuimper, Brest\n  Lorient  \n", min_words=50))
check("création acceptée", r.get("ok"), r)
items = captured.get("variables_payload", {}).get("items", [])
check("3 valeurs uniques (Brest dédoublonné, virgule gérée)",
      len(items) == 3, f"({items})")
check("1re valeur = {{'ville': 'Brest'}}", items and items[0] == {"ville": "Brest"})
check("longueur mini plancher à 300 (50 demandé)",
      captured.get("min_words") == 300)
check("meta vide → on reprend le titre comme repli",
      captured.get("meta_pattern") == "Plombier à {ville}")

print("3) Garde-fou « table absente »…")
check("PGRST détecté comme migration manquante",
      api._prog_missing_table(Exception("PGRST205: relation does not exist")))
check("une vraie panne n'est PAS prise pour une migration manquante",
      not api._prog_missing_table(Exception("connection timeout")))

print("4) Endpoints présents…")
for name in ("phare_prog_list", "phare_prog_template_create",
             "phare_prog_template_delete", "phare_prog_generate",
             "phare_prog_pages_list", "phare_prog_page_delete",
             "phare_prog_publish"):
    check(f"{name} existe", callable(getattr(api, name, None)))

print()
print(f"{len(PASS)} OK / {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
