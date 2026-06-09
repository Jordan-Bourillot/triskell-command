# -*- coding: utf-8 -*-
"""Smoke test de la remise à neuf prospection (2026-06-10).

Vérifie SANS réseau et SANS démarrer les workers :
  1. Les nouveaux endpoints existent et valident leurs entrées.
  2. La requalification des chasses zombies fonctionne (vieille chasse
     "enriching" sans thread → "error" ; chasse fraîche → intacte).
  3. Le filtre central anti-fausses-adresses est branché dans les 3
     extracteurs (Chasseur Créateur, Prospecteur Google, Chasseur).
  4. Les list_hunts renvoient bien les nouveaux compteurs.

Usage :  python scripts/smoke_prospection_refit.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
CORE = HERE.parent / "triskell-core"
if CORE.exists():
    sys.path.insert(0, str(CORE))

PASS = []
FAIL = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(label)
        print(f"  OK  - {label}")
    else:
        FAIL.append(label)
        print(f"  FAIL- {label} {detail}")


print("1) Endpoints API…")
from triskell_command.web.api import Api  # noqa: E402

api = Api()
check("endpoint chasseur_createurs_push_to_prospects existe",
      callable(getattr(api, "chasseur_createurs_push_to_prospects", None)))
check("endpoint prospecteur_google_push_to_prospects existe",
      callable(getattr(api, "prospecteur_google_push_to_prospects", None)))
r = api.chasseur_createurs_push_to_prospects({})
check("push créateurs sans hunt_id → refus propre",
      r.get("ok") is False and "hunt_id" in (r.get("error") or ""))
r = api.prospecteur_google_push_to_prospects({})
check("push google sans hunt_id → refus propre",
      r.get("ok") is False and "hunt_id" in (r.get("error") or ""))
r = api.chasseur_createurs_push_to_prospects({"hunt_id": "zzz-inexistant"})
check("push créateurs chasse inconnue → refus propre",
      r.get("ok") is False)

print("2) Chasses zombies…")
from triskell_command.integrations.hunt_zombies import (  # noqa: E402
    reconcile_hunt_file, ZOMBIE_ERROR_MESSAGE,
)

with tempfile.TemporaryDirectory() as td:
    # Cas A : chasse "enriching", fichier vieux de 10 min, pas de thread
    old = Path(td) / "vieille.json"
    old.write_text(json.dumps({"id": "vieille", "status": "enriching",
                               "log": [], "prospects": [{"nom": "X"}]}),
                   encoding="utf-8")
    past = time.time() - 600
    os.utime(old, (past, past))
    data = reconcile_hunt_file(old, is_running=False)
    check("vieille chasse en cours sans thread → error",
          data.get("status") == "error")
    check("…avec message clair",
          ZOMBIE_ERROR_MESSAGE in (data.get("error") or ""))
    on_disk = json.loads(old.read_text(encoding="utf-8"))
    check("…persistée sur disque", on_disk.get("status") == "error")
    check("…prospects conservés", on_disk.get("prospects"))

    # Cas B : chasse "enriching" toute fraîche → intacte (délai de grâce)
    fresh = Path(td) / "fraiche.json"
    fresh.write_text(json.dumps({"id": "fraiche", "status": "enriching"}),
                     encoding="utf-8")
    data = reconcile_hunt_file(fresh, is_running=False)
    check("chasse fraîche → laissée en cours",
          data.get("status") == "enriching")

    # Cas C : chasse en cours AVEC thread vivant → intacte même si vieille
    old2 = Path(td) / "active.json"
    old2.write_text(json.dumps({"id": "active", "status": "searching"}),
                    encoding="utf-8")
    os.utime(old2, (past, past))
    data = reconcile_hunt_file(old2, is_running=True)
    check("chasse avec thread vivant → intacte",
          data.get("status") == "searching")

    # Cas D : chasse terminée → jamais touchée
    done = Path(td) / "done.json"
    done.write_text(json.dumps({"id": "done", "status": "done"}),
                    encoding="utf-8")
    os.utime(done, (past, past))
    data = reconcile_hunt_file(done, is_running=False)
    check("chasse terminée → intacte", data.get("status") == "done")

print("3) Filtre anti-fausses-adresses branché…")
from triskell_command.integrations.chasseur_createurs import _clean_emails  # noqa: E402

got = _clean_emails({
    "online@www.aaa.com",      # fragment d'URL — doit sauter
    "only@savagex.com",         # domaine factice — doit sauter
    "info@www.gobble.com",      # www. — doit sauter
    "contact@studio-reel.fr",   # légitime — doit rester
    "jordan@triskell-studio.fr",  # légitime — doit rester
})
check("Chasseur Créateur : fausses adresses rejetées",
      "contact@studio-reel.fr" in got
      and "jordan@triskell-studio.fr" in got
      and len(got) == 2, f"(obtenu : {got})")

from triskell_command.integrations.argus.email_utils import is_valid_email  # noqa: E402
check("Argus : online@www.aaa.com rejeté",
      not is_valid_email("online@www.aaa.com"))
check("Argus : adresse pro valide acceptée",
      is_valid_email("contact@studio-reel.fr"))

from triskell_command.integrations.chasseur import _extract_emails_from_html  # noqa: E402
html = ('<a href="mailto:contact@boulangerie-michel.fr">mail</a> '
        "retrouvez-nous online@www.aaa.com et only@savagex.com")
got = _extract_emails_from_html(html)
check("Chasseur : extraction filtrée",
      got == ["contact@boulangerie-michel.fr"], f"(obtenu : {got})")

print("4) Compteurs dans list_hunts…")
import inspect  # noqa: E402
from triskell_command.integrations import chasseur as _ch  # noqa: E402
from triskell_command.integrations import chasseur_createurs as _cc  # noqa: E402
from triskell_command.integrations import prospecteur_google as _pg  # noqa: E402
check("chasseur.list_hunts expose prospects_count",
      "prospects_count" in inspect.getsource(_ch.list_hunts))
check("chasseur_createurs.list_hunts expose creators_count",
      "creators_count" in inspect.getsource(_cc.list_hunts))
check("prospecteur_google.list_hunts expose prospects_count",
      "prospects_count" in inspect.getsource(_pg.list_hunts))
check("chasseur_createurs.push_to_prospects existe",
      callable(getattr(_cc, "push_to_prospects", None)))
check("prospecteur_google.push_to_prospects existe",
      callable(getattr(_pg, "push_to_prospects", None)))

print()
print(f"{len(PASS)} OK / {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
