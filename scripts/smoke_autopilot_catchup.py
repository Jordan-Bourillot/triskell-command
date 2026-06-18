"""Smoke test du filet de securite (rattrapage) de l'autopilote nocturne.

Valide la fonction pure `_window_decision` : quand l'autopilote a-t-il le
droit de partir ? On verifie la table de verite complete, sans reseau ni
Supabase (la fonction est pure).

Lancer : python scripts/smoke_autopilot_catchup.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from triskell_command.integrations.autopilot_runner import (  # noqa: E402
    _window_decision,
    CATCHUP_UNTIL_HOUR,
    DEFAULT_HOUR_PARIS,
)

_checks = 0
_fails = 0


def check(label: str, cond: bool) -> None:
    global _checks, _fails
    _checks += 1
    if cond:
        print(f"  ok   {label}")
    else:
        _fails += 1
        print(f"  FAIL {label}")


def expect_run(now_hour, target, already, catchup, label):
    d = _window_decision(now_hour, target, already)
    check(f"{label} -> doit LANCER", d.skip_reason is None)
    check(f"{label} -> rattrapage={catchup}", d.catchup is catchup)


def expect_skip(now_hour, target, already, reason_prefix, label):
    d = _window_decision(now_hour, target, already)
    ok = d.skip_reason is not None and d.skip_reason.startswith(reason_prefix)
    check(f"{label} -> doit SKIP ({reason_prefix}…)", ok)
    check(f"{label} -> pas un rattrapage", d.catchup is False)


print("== Constantes ==")
check("creneau par defaut = 3h", DEFAULT_HOUR_PARIS == 3)
check("rattrapage jusqu'a 11h", CATCHUP_UNTIL_HOUR == 11)

T = 3  # creneau cible par defaut

print("\n== Heure pile (run normal) ==")
expect_run(T, T, False, catchup=False, label="3h, pas encore tourne")
expect_skip(T, T, True, "already_ran_today", label="3h, deja tourne aujourd'hui")

print("\n== Avant l'heure cible (jamais en avance) ==")
expect_skip(T - 1, T, False, "outside_window", label="2h")
expect_skip(0, T, False, "outside_window", label="minuit")

print("\n== Rattrapage matinal (creneau manque) ==")
expect_run(T + 1, T, False, catchup=True, label="4h, manque")
expect_run(7, T, False, catchup=True, label="7h, manque")
expect_run(CATCHUP_UNTIL_HOUR, T, False, catchup=True,
           label="11h (borne incluse), manque")

print("\n== Trop tard : jamais d'envoi l'apres-midi / le soir ==")
expect_skip(CATCHUP_UNTIL_HOUR + 1, T, False, "outside_window", label="12h")
expect_skip(18, T, False, "outside_window", label="18h")
expect_skip(23, T, False, "outside_window", label="23h")

print("\n== Rattrapage neutralise si deja tourne aujourd'hui ==")
# deja tourne + hors fenetre pile : on skip, pas de second run dans la journee
expect_skip(7, T, True, "outside_window", label="7h, deja tourne")

print("\n== Autres creneaux configures ==")
# Un creneau en journee marche en run normal, mais sans rattrapage matinal.
expect_run(14, 14, False, catchup=False, label="cible 14h, a 14h pile")
d = _window_decision(15, 14, False)
check("cible 14h a 15h -> pas de rattrapage l'apres-midi",
      d.skip_reason is not None and d.catchup is False)
# Creneau minuit : rattrapage matinal possible.
expect_run(0, 0, False, catchup=False, label="cible minuit, a minuit")
expect_run(6, 0, False, catchup=True, label="cible minuit, rattrape a 6h")

print("\n== Heure cible aberrante : clamp dans [0..23] ==")
d = _window_decision(23, 25, False)
check("cible 25 -> clampee a 23 (lance a 23h)",
      d.skip_reason is None and d.target_hour == 23)
d = _window_decision(0, -5, False)
check("cible -5 -> clampee a 0 (lance a minuit)",
      d.skip_reason is None and d.target_hour == 0)

print(f"\n{_checks - _fails}/{_checks} controles OK.")
if _fails:
    print(f"[ECHEC] {_fails} controle(s) en echec.")
    sys.exit(1)
print("[OK] Filet de securite valide.")
