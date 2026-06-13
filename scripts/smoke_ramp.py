# -*- coding: utf-8 -*-
"""Smoke test de la montée automatique du volume d'envoi (« rampe »).

Vérifie SANS réseau et SANS toucher à la base :
  1. Le barème paliers (volume 30 j → plafond du jour).
  2. apply_ramp : compatibilité (pool sans rampe intact, zéro lecture),
     boîte neuve, plancher « déjà rodée », min avec le plafond max,
     frein rebonds (déclenché ET non déclenché), panne de lecture.
  3. pool_status_with_ramp : statut UI enrichi.
  4. Les branchements : endpoint API, greffe dans le runner, signature
     mark_bounced avec account_id.

Usage :  python scripts/smoke_ramp.py
"""
from __future__ import annotations

import inspect
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Console Windows en cp1252 : on force l'UTF-8 pour les caractères du
# rapport (→, ✗…), comme sur la CI Linux.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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


from triskell_command.integrations import sender_pool_tracker as spt  # noqa: E402

# ---------------------------------------------------------------------------
print("1) Barème paliers (volume 30 j → plafond du jour)…")
expected = [(0, 10), (39, 10), (40, 15), (119, 15), (120, 25), (249, 25),
            (250, 35), (449, 35), (450, 50), (799, 50), (800, 70), (5000, 70)]
for vol, want in expected:
    got = spt.ramp_step_for_volume(vol)
    check(f"volume {vol} → {want}/j", got == want, f"(obtenu {got})")

# ---------------------------------------------------------------------------
print("2) apply_ramp…")

_NOW = datetime.now(timezone.utc)


def _ts(days_ago: float) -> str:
    return (_NOW - timedelta(days=days_ago)).isoformat()


def _fake_history(sends: list[dict], bounces: list[dict]):
    """Fabrique un _read_history_days factice."""
    def _fake(days: int, kinds: list[str]):
        if "email_sent" in kinds:
            return list(sends)
        return list(bounces)
    return _fake


_orig_read = spt._read_history_days

# 2a. Pool SANS rampe : intact, et l'historique n'est JAMAIS lu.
def _boom(days, kinds):
    raise AssertionError("lecture historique alors qu'aucune boîte en rampe")

spt._read_history_days = _boom
r = spt.apply_ramp([{"account_id": "primary", "daily_cap": 30}])
check("pool sans rampe → ok, aucune lecture",
      r["ok"] and r["details"] == [])
check("pool sans rampe → cap intact",
      r["pool"][0]["daily_cap"] == 30)

# 2b. Boîte neuve (0 envoi) : départ en douceur 10/j, « déjà rodée » 25/j.
spt._read_history_days = _fake_history([], [])
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 100, "ramp": True}])
check("boîte neuve, départ en douceur → 10/j",
      r["pool"][0]["daily_cap"] == 10 and r["details"][0]["effective_cap"] == 10)
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 100, "ramp": True,
                     "ramp_start": "warm"}])
check("boîte neuve, déjà rodée → 25/j", r["pool"][0]["daily_cap"] == 25)

# 2c. Le plafond max saisi reste le maximum (jamais dépassé).
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 5, "ramp": True,
                     "ramp_start": "warm"}])
check("max 5 < palier 25 → 5/j (le max gagne)",
      r["pool"][0]["daily_cap"] == 5)

# 2d. Palier atteint par l'historique réel : 500 envois sur 30 j → 50/j.
sends_500 = [{"ts": _ts(15), "kind": "email_sent", "account_id": "a"}
             for _ in range(500)]
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 100, "ramp": True}])
spt._read_history_days = _fake_history(sends_500, [])
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 100, "ramp": True}])
check("500 envois sur 30 j → palier 50/j",
      r["pool"][0]["daily_cap"] == 50 and r["details"][0]["sent_30d"] == 500)

# 2e. Frein rebonds : 3 rebonds récents pour 20 envois 7 j → palier divisé.
sends_mixed = ([{"ts": _ts(2), "kind": "email_sent", "account_id": "a"}
                for _ in range(20)]
               + [{"ts": _ts(20), "kind": "email_sent", "account_id": "a"}
                  for _ in range(480)])
bounces_3 = [{"ts": _ts(1), "kind": "status_bounced", "account_id": "a"}
             for _ in range(3)]
spt._read_history_days = _fake_history(sends_mixed, bounces_3)
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 100, "ramp": True}])
d = r["details"][0]
check("3 rebonds / 20 envois 7 j → frein actif",
      d["braked"] and r["pool"][0]["daily_cap"] == 25,
      f"(braked={d['braked']}, cap={r['pool'][0]['daily_cap']})")

# 2f. Pas de frein quand le taux est sain : 3 rebonds / 300 envois 7 j.
sends_300 = [{"ts": _ts(2), "kind": "email_sent", "account_id": "a"}
             for _ in range(300)]
spt._read_history_days = _fake_history(sends_300 + sends_500, bounces_3)
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 100, "ramp": True}])
check("3 rebonds / 300 envois 7 j → pas de frein",
      not r["details"][0]["braked"])

# 2g. Les rebonds d'une AUTRE boîte ne freinent pas celle-ci.
bounces_other = [{"ts": _ts(1), "kind": "status_bounced", "account_id": "b"}
                 for _ in range(5)]
spt._read_history_days = _fake_history([], bounces_other)
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 100, "ramp": True}])
check("rebonds d'une autre boîte → pas de frein ici",
      not r["details"][0]["braked"])

# 2h. Vieux rebonds sans account_id (historique d'avant) : ignorés.
bounces_anon = [{"ts": _ts(1), "kind": "status_bounced", "account_id": ""}
                for _ in range(5)]
spt._read_history_days = _fake_history([], bounces_anon)
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 100, "ramp": True}])
check("rebonds sans boîte identifiée → ignorés",
      not r["details"][0]["braked"])

# 2i. Panne de lecture → pool d'ORIGINE inchangé, ok=False.
spt._read_history_days = lambda days, kinds: None
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 42, "ramp": True}])
check("panne de lecture → caps manuels intacts, ok=False",
      not r["ok"] and r["pool"][0]["daily_cap"] == 42 and r["details"] == [])

# 2j. Pool mixte : la boîte sans rampe garde son cap exact.
spt._read_history_days = _fake_history([], [])
r = spt.apply_ramp([
    {"account_id": "a", "daily_cap": 100, "ramp": True},
    {"account_id": "b", "daily_cap": 33},
])
by_id = {p["account_id"]: p["daily_cap"] for p in r["pool"]}
check("pool mixte : rampe 10/j, boîte fixe 33/j",
      by_id == {"a": 10, "b": 33})
check("pool mixte : un seul détail de rampe",
      len(r["details"]) == 1 and r["details"][0]["account_id"] == "a")

# ---------------------------------------------------------------------------
print("2k) Plancher de départ sur-mesure (ramp_floor)…")
# Démarrer à 15 dès maintenant (peu d'historique) puis monter vers 50.
spt._read_history_days = _fake_history(
    [{"ts": _ts(15), "kind": "email_sent", "account_id": "a"} for _ in range(25)], [])
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 50, "ramp": True, "ramp_floor": 15}])
check("ramp_floor 15, peu d'historique → démarre à 15",
      r["pool"][0]["daily_cap"] == 15, f"(obtenu {r['pool'][0]['daily_cap']})")

# Gros volume → monte jusqu'au max (50), le plancher ne bride pas.
spt._read_history_days = _fake_history(
    [{"ts": _ts(10), "kind": "email_sent", "account_id": "a"} for _ in range(900)], [])
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 50, "ramp": True, "ramp_floor": 15}])
check("ramp_floor 15, gros volume → monte jusqu'au max 50",
      r["pool"][0]["daily_cap"] == 50, f"(obtenu {r['pool'][0]['daily_cap']})")

# Plancher > max réglé → le max plafonne (jamais au-dessus du max).
spt._read_history_days = _fake_history([], [])
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 15, "ramp": True, "ramp_floor": 20}])
check("ramp_floor 20 mais max 15 → plafonné à 15",
      r["pool"][0]["daily_cap"] == 15)

# ramp_floor absent → rétrocompat ancien preset warm (25).
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 100, "ramp": True, "ramp_start": "warm"}])
check("sans ramp_floor → ancien preset warm (25)",
      r["pool"][0]["daily_cap"] == 25)

# ramp_floor illisible → fallback douceur (10).
r = spt.apply_ramp([{"account_id": "a", "daily_cap": 100, "ramp": True, "ramp_floor": "abc"}])
check("ramp_floor invalide → fallback douceur (10)",
      r["pool"][0]["daily_cap"] == 10)

# ---------------------------------------------------------------------------
print("3) pool_status_with_ramp (statut UI)…")
spt._read_history_days = _fake_history(sends_500, [])
_orig_sends24 = spt._read_sends_24h
spt._read_sends_24h = lambda: []
st = spt.pool_status_with_ramp([
    {"account_id": "a", "daily_cap": 100, "ramp": True, "ramp_start": "warm"},
    {"account_id": "b", "daily_cap": 33},
])
accs = {x["account_id"]: x for x in st.get("accounts", [])}
check("statut : ok + 2 boîtes", st.get("ok") and len(accs) == 2)
check("statut boîte en rampe : cap du jour 50, max 100, palier exposé",
      accs.get("a", {}).get("daily_cap") == 50
      and accs.get("a", {}).get("max_cap") == 100
      and accs.get("a", {}).get("ramp") is True
      and accs.get("a", {}).get("sent_30d") == 500)
check("statut boîte fixe : cap 33, pas de rampe",
      accs.get("b", {}).get("daily_cap") == 33
      and accs.get("b", {}).get("ramp") is False
      and accs.get("b", {}).get("max_cap") == 33)
spt._read_sends_24h = _orig_sends24
spt._read_history_days = _orig_read

# ---------------------------------------------------------------------------
print("4) Branchements…")
from triskell_command.web.api import Api  # noqa: E402

api = Api()
check("endpoint autopilot_sender_pool_status existe",
      callable(getattr(api, "autopilot_sender_pool_status", None)))

from triskell_command.integrations import autopilot_runner  # noqa: E402

src = inspect.getsource(autopilot_runner.run_pipeline_with_ui_modes)
check("le runner applique la rampe avant chaque passage",
      "apply_ramp" in src)

from triskell_command.integrations import prospect_status  # noqa: E402

sig = inspect.signature(prospect_status.mark_bounced)
check("mark_bounced accepte account_id (frein par boîte)",
      "account_id" in sig.parameters)

from triskell_command.integrations import replies_poller  # noqa: E402

src_rp = inspect.getsource(replies_poller)
check("le poller trace la boîte d'envoi sur chaque rebond",
      "account_id=account_id" in src_rp)

# ---------------------------------------------------------------------------
print()
print(f"=== {len(PASS)} OK, {len(FAIL)} FAIL ===")
if FAIL:
    for f in FAIL:
        print(f"  ✗ {f}")
    sys.exit(1)
print("Tout est bon.")
