# -*- coding: utf-8 -*-
"""Smoke test FIABILITÉ (2026-06-10) — les protocoles de validation.

Vérifie SANS réseau :
  1. Contrôle qualité des données (emails fabriqués, noms fantômes,
     doublons internes) — rien de faux ne passe.
  2. Test à blanc (dry-run) : la simulation produit un rapport complet
     et n'écrit RIEN ; refus propre pour les créateurs.
  3. Versement réel : le filtre qualité est branché dans les pushers
     (vérifié sur une vraie chasse posée sur disque, CRM intercepté).
  4. Garde-fous d'envoi : un mail avec des trous ({{nom}}…) est bloqué ;
     la sélection des relances J+5 ne vise que les bons profils.
  5. Endpoint prospection_start accepte dry_run et refuse les créateurs.

Usage :  python scripts/smoke_fiabilite.py
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


print("1) Contrôle qualité des données…")
from triskell_command.integrations.data_quality import (  # noqa: E402
    filter_for_push, report_to_french, validate_prospect,
)

batch = [
    {"nom": "Plomberie Michel", "email": "contact@plomberie-michel.fr"},
    {"nom": "Boulangerie Dupain", "email": "marie@dupain.fr"},
    {"nom": "Test", "email": "vrai@mail.fr"},                  # nom fantôme
    {"nom": "Garage Réel", "email": "online@www.aaa.com"},      # email fabriqué
    {"nom": "Resto Sans Mail", "email": ""},                    # sans email
    {"nom": "Doublon SARL", "email": "CONTACT@plomberie-michel.fr"},  # doublon
    {"nom": "lorem ipsum", "email": "x@y.fr"},                  # nom fantôme
]
kept, report = filter_for_push(batch, email_key="email", name_key="nom")
check("les 2 vraies fiches passent, les 5 fausses sautent",
      report["kept"] == 2 and len(kept) == 2,
      f"(rapport : {report})")
check("chaque écart est compté avec sa raison",
      report["dropped"]["placeholder_name"] == 2
      and report["dropped"]["bad_email"] == 1
      and report["dropped"]["no_email"] == 1
      and report["dropped"]["duplicate_in_batch"] == 1)
check("échantillon des écartés fourni (≤5)",
      0 < len(report["samples_dropped"]) <= 5)
check("résumé en français lisible",
      "2/7 gardés" in report_to_french(report))
v = validate_prospect({"nom": "Vraie Boîte", "email": "jordan@vraie.fr"})
check("fiche saine validée", v["ok"] and v["email"] == "jordan@vraie.fr")

print("2) Test à blanc (machine à états)…")
from triskell_command.integrations import missions as MI  # noqa: E402


def mk(dry=True, status=MI.ST_HANDING, source="pme"):
    return {"id": "m1", "created_at": "2026-06-10T10:00:00+00:00",
            "updated_at": "", "source": source, "label": "T", "params": {},
            "dry_run": dry, "hunt_ref": "h1", "status": status, "error": "",
            "counts": {"found": 7, "with_email": 5, "pushed": 0,
                       "created": 0, "merged": 0},
            "autopilot": {"kicked": False, "note": ""}}


real_push_called = []
kick_called = []
m, _ = MI.advance_mission(
    mk(dry=True),
    hunt_state=lambda s, r: {},
    push=lambda s, r: real_push_called.append(1) or {"ok": True},
    kick_autopilot=lambda: kick_called.append(1) or (True, "x"),
    dry_push=lambda s, r: {"ok": True, "would_push": 5, "would_create": 3,
                            "would_merge": 2,
                            "quality": {"total": 7, "kept": 5,
                                        "dropped": {"bad_email": 2}},
                            "sample": [{"nom": "A", "email": "a@b.fr",
                                        "sort": "nouvelle fiche"}]})
check("test à blanc : AUCUNE écriture réelle", not real_push_called)
check("test à blanc : Auto-pilote PAS prévenu",
      not kick_called and m["autopilot"]["kicked"] is False)
check("rapport complet (seraient versés / nouveaux / fusions)",
      m["counts"]["would_push"] == 5 and m["counts"]["would_create"] == 3
      and m["counts"]["would_merge"] == 2)
check("qualité + échantillon attachés à la mission",
      m["quality"]["kept"] == 5 and len(m["preview"]) == 1)
check("note explicite « rien n'est entré »",
      "rien" in m["autopilot"]["note"])
check("mission réelle inchangée (le réel passe par le vrai versement)",
      MI.advance_mission(mk(dry=False), hunt_state=lambda s, r: {},
                          push=lambda s, r: {"ok": True, "pushed": 5,
                                              "created": 5, "merged": 0,
                                              "quality": {"total": 7, "kept": 5,
                                                          "dropped": {}}},
                          kick_autopilot=lambda: (True, "ok"))[0]
      ["counts"]["pushed"] == 5)
r = MI.create_mission("createurs", {"niche": "x"}, dry_run=True)
check("test à blanc refusé pour les créateurs (avec explication)",
      r.get("ok") is False and "petit volume" in (r.get("error") or ""))

print("3) Versement réel filtré (vraie chasse sur disque, CRM intercepté)…")
from triskell_command.integrations import chasseur  # noqa: E402
from triskell_core.prospect.core import crm as core_crm  # noqa: E402


class FakeCRM:
    def __init__(self):
        self.received = []
    def upsert_many(self, prospects):
        self.received = list(prospects)
        return {"created": len(self.received), "merged": 0,
                "total": len(self.received)}
    def save(self):
        pass


with tempfile.TemporaryDirectory() as td:
    old_dir, old_get = chasseur.HUNTS_DIR, core_crm.get_crm
    fake = FakeCRM()
    core_crm.get_crm = lambda **kw: fake
    chasseur.HUNTS_DIR = Path(td)
    try:
        hunt = {"id": "q1", "label": "test", "created_at": "2026-06-10",
                "status": "done", "progress": 100, "log": [],
                "filters": {"mode": "all", "sector_input": "plombier"},
                "stats": {}, "error": "",
                "prospects": [
                    {"nom": "Plomberie Michel", "siren": "1",
                     "email": "contact@plomberie-michel.fr"},
                    {"nom": "Test", "siren": "2", "email": "t@t.fr"},
                    {"nom": "Vraie SARL", "siren": "3",
                     "email": "only@savagex.com"},
                ]}
        (Path(td) / "q1.json").write_text(json.dumps(hunt), encoding="utf-8")
        res = chasseur.push_to_autopilot("q1")
        check("seule la fiche saine est versée",
              res.get("ok") and res.get("pushed") == 1
              and len(fake.received) == 1
              and fake.received[0].name == "Plomberie Michel",
              f"(res : {res})")
        check("rapport qualité renvoyé par le versement réel",
              (res.get("quality") or {}).get("kept") == 1
              and res["quality"]["total"] == 3)
    finally:
        chasseur.HUNTS_DIR = old_dir
        core_crm.get_crm = old_get

print("4) Garde-fous d'envoi…")
from triskell_command.integrations import prospect_status as PS  # noqa: E402

bad = PS.mail_is_safe_to_send("Bonjour {{first_name}}",
                               "On a vu votre site {site}…")
check("mail avec des trous ({{...}}) BLOQUÉ avant envoi",
      bad.get("ok") is False and bad.get("unrendered"))
good = PS.mail_is_safe_to_send("Bonjour Michel", "On a vu votre site hier.")
check("mail propre autorisé", good.get("ok") is True)

from triskell_core.prospect.core.prospect import Prospect  # noqa: E402
from triskell_core.prospect.outreach.smtp_sender import (  # noqa: E402
    select_due_for_followup,
)


class MiniCRM:
    def __init__(self, prospects): self._p = prospects
    def all(self): return self._p


def _p(status, days_ago, with_followup=False, replied=False):
    from datetime import datetime, timedelta
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
    hist = [{"kind": "email_sent", "ts": ts, "template_key": "tpl_v1"}]
    if with_followup:
        hist.append({"kind": "email_sent", "ts": ts,
                     "template_key": "tpe_relance_j5"})
    if replied:
        hist.append({"kind": "reply_received", "ts": ts})
    p = Prospect(name="X", emails=["x@y.fr"], status=status)
    p.history = hist
    return p


due = select_due_for_followup(MiniCRM([
    _p("contacted", 7),                       # ✓ doit être relancé
    _p("contacted", 2),                       # trop tôt
    _p("contacted", 9, with_followup=True),   # déjà relancé
    _p("replied", 8),                         # a répondu → on ne relance pas
]), limit=10, follow_up_days=5)
check("relance J+5 : seul le bon profil est sélectionné",
      len(due) == 1 and due[0].history[0]["template_key"] == "tpl_v1")

print("5) Endpoint…")
from triskell_command.web.api import Api  # noqa: E402

api = Api()
r = api.prospection_start({"source": "createurs",
                            "params": {"niche": "x"}, "dry_run": True})
check("endpoint : dry_run transmis (refus créateurs traversant l'API)",
      r.get("ok") is False and "petit volume" in (r.get("error") or ""))

print()
print(f"{len(PASS)} OK / {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
