# -*- coding: utf-8 -*-
"""Smoke test SÉPARATION SITE/ROBOTS — santé & vérité (2026-07-03).

Le soir de l'activation de la séparation (TRISKELL_ROLE web/workers),
Perceval a crié « 12 robots en panne » alors que tout allait bien :
guide_snapshot comptait les robots délégués comme des pannes. Et deux
trous plus graves dormaient derrière : la mort du conteneur robots était
totalement silencieuse (son chien de garde meurt avec lui), et le bouton
« Relancer » de la page Santé pouvait démarrer un robot EN DOUBLE sur le
conteneur web.

Cette batterie grave les règles :
  1. process_role : les 3 rôles + valeurs tordues.
  2. guide_snapshot rôle web : battement frais → 12 robots verts ;
     battement muet → 12 rouges (alerte MÉRITÉE) ; base injoignable →
     compteurs à zéro (pas de faux cri au loup).
  3. system_health rôle web : carte « Serveur des robots (battement de
     cœur) » — verte si frais, rouge si muet ; les 16 délégués verts.
  4. system_health rôle workers : pas de carte Phare (sinon les DEUX
     conteneurs aboieraient), pas de carte battement.
  5. worker_restart rôle web : refus propre (jamais de robot en double).
  6. Chien de garde : ignore les délégués, aboie sur la carte battement.

Usage :  python scripts/smoke_roles_sante.py   (sans réseau)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Console Windows en cp1252 : sans ça, le premier « → » plante le script.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
CORE = HERE.parent / "triskell-core"
if CORE.exists():
    sys.path.insert(0, str(CORE))

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'OK  ' if cond else 'FAIL'}- {label} {detail if not cond else ''}")


# ---------------------------------------------------------------------------
# Faux client Supabase : répond « vide » à toutes les requêtes, et sert le
# battement de cœur qu'on lui donne. Aucun réseau.
# ---------------------------------------------------------------------------
class _FakeResult:
    count = 0
    data = []


class _FakeQuery:
    def execute(self):
        return _FakeResult()

    def __getattr__(self, name):
        return lambda *a, **k: self


class _FakeSB:
    def table(self, name):
        return _FakeQuery()


class FakeClient:
    is_authenticated = True

    def __init__(self, heartbeat=None):
        self.heartbeat = heartbeat
        self.raw = _FakeSB()

    def get_shared_setting(self, key, default=None):
        if key == "server_heartbeat":
            return self.heartbeat if self.heartbeat is not None else default
        return default

    def set_shared_setting(self, key, value):
        pass


def _hb(age_seconds: int) -> dict:
    at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return {"at": at.isoformat(timespec="seconds"), "host": "conteneur-test"}


def _reset_guide_cache(Api):
    Api._GUIDE_CACHE["data"] = None
    Api._GUIDE_CACHE["at"] = 0.0


# ---------------------------------------------------------------------------
print("1) process_role : les 3 rôles + valeurs tordues…")
from triskell_command.integrations import process_role  # noqa: E402

for value, role, workers, ui in [
    (None, "all", True, True),
    ("all", "all", True, True),
    ("web", "web", False, True),
    ("workers", "workers", True, False),
    ("WEB  ", "web", False, True),          # casse + espaces tolérés
    ("n'importe quoi", "all", True, True),  # valeur inconnue = all
]:
    if value is None:
        os.environ.pop("TRISKELL_ROLE", None)
    else:
        os.environ["TRISKELL_ROLE"] = value
    check(f"rôle {value!r} → {role}", process_role.get_role() == role)
    check(f"rôle {value!r} → robots {workers}",
          process_role.runs_workers() is workers)
    check(f"rôle {value!r} → état UI {ui}",
          process_role.owns_ui_state() is ui)

# ---------------------------------------------------------------------------
print("2) guide_snapshot en rôle web : la vérité vient du battement de cœur…")
from triskell_command.web.api import Api  # noqa: E402

# Hermétique : le Phare ne doit pas aller lire la vraie base pendant le test
from triskell_command.integrations.phare import heartbeat as _phare_hb  # noqa: E402
_phare_hb.virtual_worker = lambda: None

api = Api()
os.environ["TRISKELL_ROLE"] = "web"

# 2a) battement FRAIS → les 12 robots délégués comptent « en bonne santé »
api._supabase = lambda: FakeClient(_hb(120))
_reset_guide_cache(Api)
snap = api.guide_snapshot()
w = snap.get("workers") or {}
check("battement frais → 12 verts, 0 panne",
      w.get("healthy") == 12 and w.get("error") == 0, f"({w})")

# 2b) battement MUET (> 15 min) → 12 pannes : l'alerte devient méritée
api._supabase = lambda: FakeClient(_hb(3600))
_reset_guide_cache(Api)
w = (api.guide_snapshot().get("workers")) or {}
check("battement muet → 12 pannes (alerte méritée)",
      w.get("error") == 12 and w.get("healthy") == 0, f"({w})")

# 2c) pas de battement du tout (clé absente) → pareil : panne
api._supabase = lambda: FakeClient(None)
_reset_guide_cache(Api)
w = (api.guide_snapshot().get("workers")) or {}
check("aucun battement → 12 pannes",
      w.get("error") == 12, f"({w})")

# 2d) base injoignable → état inconnu, on ne crie PAS au loup
api._supabase = lambda: None
_reset_guide_cache(Api)
w = (api.guide_snapshot().get("workers")) or {}
check("base injoignable → compteurs à zéro (pas de faux cri)",
      w.get("error") == 0 and w.get("healthy") == 0, f"({w})")

# ---------------------------------------------------------------------------
print("3) system_health en rôle web : carte battement de cœur…")

api._supabase = lambda: FakeClient(_hb(120))
health = api.system_health()
cards = {c.get("name"): c for c in health.get("workers") or []}
wc = cards.get("workers_container")
check("carte « Serveur des robots » présente", wc is not None)
check("battement frais → carte verte",
      wc is not None and wc.get("health") == "healthy"
      and wc.get("running") is True, f"({wc})")
delegated = [c for c in (health.get("workers") or []) if c.get("delegated")]
check("robots délégués tous verts (16 attendus)",
      len(delegated) >= 16
      and all(c.get("health") == "healthy" for c in delegated),
      f"({len(delegated)} délégués)")

api._supabase = lambda: FakeClient(_hb(3600))
health = api.system_health()
cards = {c.get("name"): c for c in health.get("workers") or []}
wc = cards.get("workers_container")
check("battement muet → carte ROUGE",
      wc is not None and wc.get("health") == "error", f"({wc})")
check("carte rouge → message en français normal",
      wc is not None
      and "battement" in ((wc.get("last_run_result") or {}).get("error") or ""))

api._supabase = lambda: None
health = api.system_health()
cards = {c.get("name"): c for c in health.get("workers") or []}
wc = cards.get("workers_container")
check("base injoignable → carte AVERTISSEMENT (pas rouge)",
      wc is not None and wc.get("health") == "warning", f"({wc})")

# ---------------------------------------------------------------------------
print("4) system_health en rôle workers : pas de doublon d'aboiement…")

os.environ["TRISKELL_ROLE"] = "workers"
api._supabase = lambda: FakeClient(_hb(120))
health = api.system_health()
names = [c.get("name") for c in health.get("workers") or []]
check("pas de carte battement côté workers",
      "workers_container" not in names)
check("pas de carte Phare côté workers (le web s'en charge)",
      "phare_scheduler" not in names)
geo = next((c for c in (health.get("workers") or [])
            if c.get("name") == "geo_autopilot"), None)
check("GEO délégué au conteneur site côté workers",
      geo is not None and geo.get("delegated") is True, f"({geo})")

# ---------------------------------------------------------------------------
print("5) worker_restart en rôle web : refus propre, jamais de doublon…")

os.environ["TRISKELL_ROLE"] = "web"
r = api.worker_restart({"name": "drip_runner"})
check("relance refusée en rôle web",
      r.get("ok") is False and "serveur des robots" in (r.get("error") or ""),
      f"({r})")
r = api.worker_restart({"name": "workers_container"})
check("carte battement jamais relançable",
      r.get("ok") is False, f"({r})")

os.environ["TRISKELL_ROLE"] = "all"
r = api.worker_restart({"name": "nom-bidon"})
check("rôle all : le garde-fou rôle ne bloque pas (refus = nom inconnu)",
      r.get("ok") is False
      and "serveur des robots" not in (r.get("error") or ""), f"({r})")

# ---------------------------------------------------------------------------
print("6) chien de garde : ignore les délégués, aboie sur le battement…")
from triskell_command.integrations import worker_watchdog as wd  # noqa: E402

problems = wd.diagnose_workers([
    {"name": "drip_runner", "label": "Relances", "health": "healthy",
     "running": False, "delegated": True,
     "last_run_result": {"skipped_reason": "délégué au conteneur robots"}},
])
check("robot délégué → jamais d'aboiement", problems == [])

problems = wd.diagnose_workers([
    {"name": "workers_container", "label": "Serveur des robots",
     "health": "error", "running": False,
     "last_run_result": {"error": "aucun battement de cœur depuis plus de 15 min"}},
])
check("battement muet → le chien de garde aboie",
      len(problems) == 1 and problems[0]["name"] == "workers_container",
      f"({problems})")

# ---------------------------------------------------------------------------
os.environ.pop("TRISKELL_ROLE", None)
print()
print(f"{len(PASS)} OK, {len(FAIL)} FAIL")
if FAIL:
    print("ÉCHECS :")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("Batterie séparation site/robots : tout est vert.")
