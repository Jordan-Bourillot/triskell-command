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
           "prospection_mission_cancel", "prospection_hunt_log"):
    check(f"endpoint {ep} exposé", callable(getattr(api, ep, None)))
r = api.prospection_start({"source": "zzz", "params": {}})
check("cible inconnue → refus propre",
      r.get("ok") is False and "inconnue" in (r.get("error") or ""))
r = api.prospection_mission_cancel({})
check("abandon sans id → refus propre", r.get("ok") is False)

print("5) Carnet de chasse (la mémoire des recherches)…")
from triskell_command.integrations import hunt_log as HL  # noqa: E402

# Normalisation : accents / majuscules / espaces / tirets ignorés
check("« Électricien  / 22 » == « electricien / 22 »",
      HL.criteria_key("pme", {"metier": "Électricien ", "departement": "22"})
      == HL.criteria_key("pme", {"metier": "electricien",
                                  "departement": " 22"}))
check("« Peintre en bâtiment » == « peintre-en-batiment »",
      HL.criteria_key("local", {"metier": "Peintre en bâtiment",
                                 "zone": "Brest"})
      == HL.criteria_key("local", {"metier": "peintre-en-batiment",
                                    "zone": "brest"}))
check("le volume ne fait pas l'identité d'une recherche",
      HL.criteria_key("local", {"metier": "restaurant", "zone": "Rennes",
                                 "volume": 30})
      == HL.criteria_key("local", {"metier": "restaurant", "zone": "Rennes",
                                    "volume": 200}))
check("« sans site » = une AUTRE recherche",
      HL.criteria_key("local", {"metier": "garage", "zone": "Lorient"})
      != HL.criteria_key("local", {"metier": "garage", "zone": "Lorient",
                                    "sans_site": True}))
check("créateurs : l'ordre des plateformes est ignoré",
      HL.criteria_key("createurs", {"niche": "cuisine",
                                     "plateformes": ["twitch", "youtube"]})
      == HL.criteria_key("createurs", {"niche": "Cuisine",
                                        "plateformes": ["youtube", "twitch"]}))

# Garde-fou « déjà chassé » dans create_mission (chasse simulée, rien ne part)
fc2 = FakeClient()
_old_start = MI.start_hunt_for
MI.start_hunt_for = lambda s, p: {"ok": True, "hunt_ref": "hx",
                                   "label": "plombier — dept 35"}
try:
    r1 = MI.create_mission("pme", {"metier": "plombier", "departement": "35",
                                    "volume": 100}, client=fc2)
    e1 = HL.find("pme", {"metier": "plombier", "departement": "35"},
                 client=fc2)
    check("1er lancement → passe et entre au carnet",
          r1.get("ok") is True and e1 is not None
          and int(e1.get("runs") or 0) == 1)
    r2 = MI.create_mission("pme", {"metier": "Plombier ",
                                    "departement": " 35", "volume": 50},
                           client=fc2)
    check("même recherche → needs_confirm, RIEN n'est lancé",
          r2.get("ok") is False and r2.get("needs_confirm") is True)
    w = r2.get("warning") or ""
    check("…avertissement en français : déjà faite + libellé + doublons",
          "déjà faite" in w and "plombier" in w and "doublon" in w)
    check("…et error porte le même message (anciens fronts)",
          r2.get("error") == w)
    r3 = MI.create_mission("pme", {"metier": "plombier",
                                    "departement": "35"},
                           force=True, client=fc2)
    e3 = HL.find("pme", {"metier": "plombier", "departement": "35"},
                 client=fc2)
    check("force=True → relance acceptée, compteur à 2",
          r3.get("ok") is True and int(e3.get("runs") or 0) == 2)
    check("…l'avertissement dit maintenant « 2 fois »",
          "2 fois" in HL.warning_for(e3))
    rf = MI.create_mission("pme", {"metier": "plombier",
                                    "departement": "35",
                                    "force": True}, client=fc2)
    check("force glissé dans params → toléré aussi",
          rf.get("ok") is True)
    rd = MI.create_mission("pme", {"metier": "plombier",
                                    "departement": "35"},
                           dry_run=True, client=fc2)
    e4 = HL.find("pme", {"metier": "plombier", "departement": "35"},
                 client=fc2)
    check("test à blanc : ni averti, ni compté",
          rd.get("ok") is True and int(e4.get("runs") or 0) == 3)
    r5 = MI.create_mission("local", {"metier": "fleuriste",
                                      "zone": "Lorient"}, client=fc2)
    check("recherche différente → passe sans question",
          r5.get("ok") is True)

    # Un carnet en panne ne bloque JAMAIS une chasse
    _old_find, _old_rec = HL.find, HL.record_launch
    HL.find = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    HL.record_launch = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("boom"))
    try:
        rz = MI.create_mission("local", {"metier": "tatoueur",
                                          "zone": "Brest"}, client=fc2)
        check("carnet en panne → la chasse part quand même",
              rz.get("ok") is True)
    finally:
        HL.find, HL.record_launch = _old_find, _old_rec
finally:
    MI.start_hunt_for = _old_start

# Fin de mission → récolte notée ; abandon → noté aussi
m_done = mk_mission(source="pme", status=MI.ST_HANDED,
                    params={"metier": "plombier", "departement": "35"},
                    counts={"found": 24, "with_email": 24, "pushed": 22,
                            "created": 20, "merged": 2})
HL.record_result(m_done, client=fc2)
e5 = HL.find("pme", {"metier": "plombier", "departement": "35"}, client=fc2)
check("mission terminée → récolte au carnet (22 versées / 24 trouvées)",
      e5 is not None and e5.get("status") == "terminée"
      and (e5.get("result") or {}).get("pushed") == 22
      and "22" in HL.warning_for(e5))

# Rattrapage : carnet absent → reconstruit depuis les missions (sans les 🧪)
ents = HL.backfill_from_missions([
    mk_mission(id="x", source="local", status=MI.ST_HANDED,
               params={"metier": "coiffeur", "zone": "Vannes"},
               counts={"found": 25, "with_email": 13, "pushed": 13}),
    mk_mission(id="y", source="local", dry_run=True,
               params={"metier": "coiffeur", "zone": "Vannes"}),
    mk_mission(id="z", source="local", status=MI.ST_HUNTING,
               params={"metier": "coiffeur", "zone": "vannes "}),
])
check("rattrapage : 2 vraies missions identiques → 1 entrée ×2, 🧪 exclu",
      len(ents) == 1 and ents[0]["runs"] == 2)

print("6) Reprise automatique après interruption serveur…")

ZOMBIE = ("Chasse interrompue par un redémarrage du serveur. "
          "Les résultats déjà trouvés sont conservés.")
RELAUNCH_OK = lambda s, p: {"ok": True, "hunt_ref": "h-neuf",       # noqa: E731
                             "label": "relancée"}
RELAUNCH_KO = lambda s, p: {"ok": False, "error": "outil indispo"}  # noqa: E731

# Chasse interrompue → la mission REPART en chasse (pas d'erreur)
m, ch = MI.advance_mission(
    mk_mission(),
    hunt_state=lambda s, r: {"status": "error", "error": ZOMBIE},
    push=lambda s, r: None, kick_autopilot=KICK_OK,
    relaunch=RELAUNCH_OK)
check("interruption serveur → chasse relancée, mission toujours en chasse",
      ch and m["status"] == MI.ST_HUNTING and m["hunt_ref"] == "h-neuf"
      and m["relaunches"] == 1 and "reprise automatiquement" in m["resume_note"])

# Fichier de chasse disparu avec l'ancien conteneur → pareil
m, _ = MI.advance_mission(
    mk_mission(),
    hunt_state=lambda s, r: {"status": "error", "error": "chasse introuvable"},
    push=lambda s, r: None, kick_autopilot=KICK_OK,
    relaunch=RELAUNCH_OK)
check("chasse introuvable (conteneur neuf) → relancée aussi",
      m["status"] == MI.ST_HUNTING and m["relaunches"] == 1)

# Une VRAIE panne ne se relance pas (clé API, réseau…)
calls = []
m, _ = MI.advance_mission(
    mk_mission(),
    hunt_state=lambda s, r: {"status": "error", "error": "clé API manquante"},
    push=lambda s, r: None, kick_autopilot=KICK_OK,
    relaunch=lambda s, p: (calls.append("relaunch")
                            or {"ok": True, "hunt_ref": "x"}))
check("vraie panne → erreur directe, AUCUNE relance",
      m["status"] == MI.ST_ERROR and calls == [])

# Plafond : 2 reprises max, après on s'arrête proprement
m, _ = MI.advance_mission(
    mk_mission(relaunches=MI.MAX_AUTO_RELAUNCHES),
    hunt_state=lambda s, r: {"status": "error", "error": ZOMBIE},
    push=lambda s, r: None, kick_autopilot=KICK_OK,
    relaunch=RELAUNCH_OK)
check("plafond de reprises atteint → erreur assumée",
      m["status"] == MI.ST_ERROR and "interrompue" in m["error"].lower())

# Relance impossible (outil KO) → erreur claire, pas de boucle
m, _ = MI.advance_mission(
    mk_mission(),
    hunt_state=lambda s, r: {"status": "error", "error": ZOMBIE},
    push=lambda s, r: None, kick_autopilot=KICK_OK,
    relaunch=RELAUNCH_KO)
check("relance impossible → erreur conservée",
      m["status"] == MI.ST_ERROR)

# Sans relanceur branché (compat) → comportement historique
m, _ = MI.advance_mission(
    mk_mission(),
    hunt_state=lambda s, r: {"status": "error", "error": ZOMBIE},
    push=lambda s, r: None, kick_autopilot=KICK_OK)
check("sans relanceur → comportement historique (erreur)",
      m["status"] == MI.ST_ERROR)

# Repêchage des missions tuées AVANT ce déploiement (cas du 13/06)
from datetime import datetime as _dt, timezone as _tz, timedelta as _td
_now_dt = _dt(2026, 6, 13, 1, 0, 0, tzinfo=_tz.utc)
lot = [
    mk_mission(id="r1", status=MI.ST_ERROR, error=ZOMBIE,
               updated_at=(_now_dt - _td(hours=1)).isoformat()),
    mk_mission(id="r2", status=MI.ST_ERROR, error=ZOMBIE,
               updated_at=(_now_dt - _td(hours=30)).isoformat()),
    mk_mission(id="r3", status=MI.ST_ERROR, error="clé API manquante",
               updated_at=(_now_dt - _td(hours=1)).isoformat()),
    mk_mission(id="r4", status=MI.ST_CANCELLED,
               updated_at=(_now_dt - _td(hours=1)).isoformat()),
]
lot2, n = MI.rescue_interrupted(lot, relaunch=RELAUNCH_OK, now=_now_dt)
by_id = {m["id"]: m for m in lot2}
check("repêchage : la récente interrompue repart en chasse",
      n == 1 and by_id["r1"]["status"] == MI.ST_HUNTING
      and by_id["r1"]["relaunches"] == 1)
check("…la vieille (> 24 h) reste en erreur",
      by_id["r2"]["status"] == MI.ST_ERROR)
check("…la vraie panne reste en erreur",
      by_id["r3"]["status"] == MI.ST_ERROR)
check("…l'abandonnée reste abandonnée",
      by_id["r4"]["status"] == MI.ST_CANCELLED)

# Le tri du carnet (récentes d'abord) + le plafond
entries_data = {"v": 1, "entries": [
    {"key": f"k{i}", "label": f"l{i}", "source": "pme",
     "first_at": f"2026-06-{(i % 28) + 1:02d}T00:00:00+00:00",
     "last_at": f"2026-06-{(i % 28) + 1:02d}T00:00:00+00:00",
     "runs": 1, "status": "terminée", "result": None, "mission_id": ""}
    for i in range(HL.MAX_ENTRIES + 25)]}
fc3 = FakeClient()
HL._save_raw(entries_data, fc3)
saved = fc3.store[HL.SHARED_KEY]["entries"]
check("plafond du carnet appliqué (anciennes écartées d'abord)",
      len(saved) == HL.MAX_ENTRIES
      and saved[0]["last_at"] >= saved[-1]["last_at"])

print()
print(f"{len(PASS)} OK / {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
