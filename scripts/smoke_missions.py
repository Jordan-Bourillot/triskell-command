# -*- coding: utf-8 -*-
"""Smoke test des MISSIONS de prospection (passe 3, 2026-06-10).

Vérifie SANS réseau :
  1. La machine à états (avance_mission) sur tous les cas de figure.
  2. Une chaîne SIMULÉE de bout en bout : vraie chasse Chasseur sur disque
     (fichier au vrai format) → lecture d'état réelle → versement (simulé)
     → transmission Auto-pilote (simulée) → mission terminée.
  3. Le stockage des missions (client factice en mémoire).
  4. Les endpoints exposés + refus propres.

Usage :  python scripts/smoke_missions.py
"""
from __future__ import annotations

import json
import sys
import tempfile
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


from triskell_command.integrations import missions as MI  # noqa: E402


def mk_mission(source="pme", status=MI.ST_HUNTING, **over):
    m = {
        "id": "m1", "created_at": "2026-06-10T10:00:00+00:00",
        "updated_at": "", "created_by": "jordan", "source": source,
        "label": "Test", "params": {}, "hunt_ref": "h1",
        "status": status, "error": "",
        "counts": {"found": 0, "with_email": 0, "pushed": 0,
                   "created": 0, "merged": 0},
        "autopilot": {"kicked": False, "note": ""},
    }
    m.update(over)
    return m


KICK_OK = lambda: (True, "Auto-pilote lancé sur la base")        # noqa: E731
KICK_OFF = lambda: (False, "Auto-pilote éteint")                 # noqa: E731

print("1) Machine à états…")

# Chasse en cours → compteurs mis à jour, statut inchangé
m, ch = MI.advance_mission(
    mk_mission(),
    hunt_state=lambda s, r: {"status": "enriching", "progress": 40,
                              "found": 12, "with_email": 7},
    push=lambda s, r: None, kick_autopilot=KICK_OK)
check("chasse en cours → compteurs vivants, toujours en chasse",
      ch and m["status"] == MI.ST_HUNTING
      and m["counts"]["found"] == 12 and m["counts"]["with_email"] == 7)

# Chasse finie → versement + transmission dans le MÊME passage
calls = []
m, ch = MI.advance_mission(
    mk_mission(),
    hunt_state=lambda s, r: {"status": "done", "progress": 100,
                              "found": 12, "with_email": 7},
    push=lambda s, r: (calls.append("push")
                       or {"ok": True, "pushed": 7, "created": 5, "merged": 2}),
    kick_autopilot=lambda: (calls.append("kick") or (True, "lancé")))
check("chasse finie → versé puis transmis dans le même passage",
      m["status"] == MI.ST_HANDED and calls == ["push", "kick"]
      and m["counts"]["pushed"] == 7 and m["counts"]["created"] == 5)
check("…note Auto-pilote enregistrée",
      m["autopilot"]["kicked"] is True and m["autopilot"]["note"] == "lancé")

# Chasse en erreur → mission en erreur
m, _ = MI.advance_mission(
    mk_mission(),
    hunt_state=lambda s, r: {"status": "error", "error": "API morte"},
    push=lambda s, r: None, kick_autopilot=KICK_OK)
check("chasse en erreur → mission en erreur avec message",
      m["status"] == MI.ST_ERROR and "API morte" in m["error"])

# Versement qui plante → erreur claire
m, _ = MI.advance_mission(
    mk_mission(status=MI.ST_HANDING),
    hunt_state=lambda s, r: {},
    push=lambda s, r: {"ok": False, "error": "base injoignable"},
    kick_autopilot=KICK_OK)
check("versement KO → erreur claire",
      m["status"] == MI.ST_ERROR and "base injoignable" in m["error"])

# « aucun prospect avec mail » = pas une panne
m, _ = MI.advance_mission(
    mk_mission(status=MI.ST_HANDING),
    hunt_state=lambda s, r: {},
    push=lambda s, r: {"ok": False, "error": "aucun prospect avec mail à pousser"},
    kick_autopilot=KICK_OFF)
check("chasse bredouille → terminée proprement (0 versé)",
      m["status"] == MI.ST_HANDED and m["counts"]["pushed"] == 0)

# Créateurs (Obélisk) : pas de versement nécessaire
m, _ = MI.advance_mission(
    mk_mission(source="createurs", status=MI.ST_HANDING,
               counts={"found": 9, "with_email": 6, "pushed": 0,
                       "created": 0, "merged": 0}),
    hunt_state=lambda s, r: {},
    push=lambda s, r: None, kick_autopilot=KICK_OFF)
check("créateurs → directement dans la base (pas de versement)",
      m["status"] == MI.ST_HANDED and m["counts"]["pushed"] == 9)
check("…Auto-pilote éteint → noté, pas une erreur",
      m["autopilot"]["kicked"] is False and "éteint" in m["autopilot"]["note"])

print("2) Chaîne simulée de bout en bout (vrais fichiers Chasseur)…")
from triskell_command.integrations import chasseur  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    old_dir = chasseur.HUNTS_DIR
    chasseur.HUNTS_DIR = Path(td)
    try:
        hunt = {
            "id": "e2e123", "label": "plombier — dept 71",
            "created_at": "2026-06-10T10:00:00",
            "status": "enriching", "progress": 60,
            "log": [], "filters": {"sector_input": "plombier"},
            "stats": {"candidats": 30, "traites": 18, "retenus": 9,
                      "avec_mail": 6},
            "prospects": [{"nom": "Plomberie Michel", "siren": "123",
                           "email": "contact@plomberie-michel.fr"}],
            "error": "",
        }
        p = Path(td) / "e2e123.json"
        p.write_text(json.dumps(hunt), encoding="utf-8")

        mission = mk_mission(hunt_ref="e2e123")

        # Passage 1 : la chasse tourne encore (lecture RÉELLE du fichier)
        mission, _ = MI.advance_mission(
            mission, hunt_state=MI.hunt_state_for,
            push=lambda s, r: None, kick_autopilot=KICK_OK)
        check("lecture réelle d'une chasse en cours",
              mission["status"] == MI.ST_HUNTING
              and mission["counts"]["found"] == 9
              and mission["counts"]["with_email"] == 6)

        # La chasse se termine (fichier réécrit, comme le fait le vrai outil)
        hunt["status"] = "done"
        hunt["progress"] = 100
        p.write_text(json.dumps(hunt), encoding="utf-8")

        # Passage 2 : fin détectée → versement (simulé) → transmission
        pushed = []
        mission, _ = MI.advance_mission(
            mission, hunt_state=MI.hunt_state_for,
            push=lambda s, r: (pushed.append(r)
                               or {"ok": True, "pushed": 6, "created": 6,
                                   "merged": 0}),
            kick_autopilot=KICK_OK)
        check("fin de chasse détectée sur le vrai fichier → chaîne déroulée",
              mission["status"] == MI.ST_HANDED and pushed == ["e2e123"]
              and mission["counts"]["pushed"] == 6)
        check("…note Auto-pilote présente",
              "Auto-pilote" in mission["autopilot"]["note"])
    finally:
        chasseur.HUNTS_DIR = old_dir

print("3) Stockage des missions…")


class FakeClient:
    def __init__(self):
        self.store = {}
    def get_shared_setting(self, key, default=None):
        return self.store.get(key, default)
    def set_shared_setting(self, key, value):
        self.store[key] = value


fc = FakeClient()
ms = [mk_mission(id="a", created_at="2026-06-10T08:00:00+00:00"),
      mk_mission(id="b", created_at="2026-06-10T09:00:00+00:00")]
MI.save_missions(ms, fc)
loaded = MI.load_missions(fc)
check("sauvegarde + relecture", len(loaded) == 2)
check("plus récentes d'abord", loaded[0]["id"] == "b")
r = MI.cancel_mission("a", fc)
check("abandon d'une mission", r.get("ok")
      and any(m["id"] == "a" and m["status"] == MI.ST_CANCELLED
              for m in MI.load_missions(fc)))
check("abandon d'une mission inconnue → refus propre",
      MI.cancel_mission("zzz", fc).get("ok") is False)

print("4) Endpoints…")
from triskell_command.web.api import Api, get_api_instance  # noqa: E402

api = Api()
check("singleton Api enregistré", get_api_instance() is api)
for ep in ("prospection_start", "prospection_missions",
           "prospection_mission_cancel"):
    check(f"endpoint {ep} exposé", callable(getattr(api, ep, None)))
r = api.prospection_start({"source": "zzz", "params": {}})
check("cible inconnue → refus propre",
      r.get("ok") is False and "inconnue" in (r.get("error") or ""))
r = api.prospection_mission_cancel({})
check("abandon sans id → refus propre", r.get("ok") is False)

print()
print(f"{len(PASS)} OK / {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
