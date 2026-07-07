"""Contrôle : rétablissement automatique d'un throttle temporaire de volume.

Verrouille _maybe_restore_nightly_target : échéance passée -> remet la cible et
efface les marqueurs ; échéance future ou absente -> ne touche à rien. Sans réseau.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from triskell_command.integrations.autopilot_runner import (
    _maybe_restore_nightly_target as R,
)

_ok = _ko = 0
def check(label, cond):
    global _ok, _ko
    if cond: _ok += 1; print(f"  OK   {label}")
    else: _ko += 1; print(f"  ÉCHEC {label}")

# échéance PASSÉE -> rétablit la cible + efface les marqueurs
past = R(None, {"nightly_target": 35,
                "nightly_target_restore_at": "2020-01-01T00:00:00+00:00",
                "nightly_target_restore_to": 70})
check("échéance passée -> nightly_target rétabli à 70", past.get("nightly_target") == 70)
check("échéance passée -> marqueur 'restore_at' effacé", "nightly_target_restore_at" not in past)
check("échéance passée -> marqueur 'restore_to' effacé", "nightly_target_restore_to" not in past)

# échéance FUTURE -> ne touche à rien
fut = R(None, {"nightly_target": 35,
               "nightly_target_restore_at": "2099-01-01T00:00:00+00:00",
               "nightly_target_restore_to": 70})
check("échéance future -> nightly_target inchangé (35)", fut.get("nightly_target") == 35)
check("échéance future -> marqueur conservé", "nightly_target_restore_at" in fut)

# pas de marqueur -> inchangé
check("sans marqueur -> inchangé", R(None, {"nightly_target": 35}).get("nightly_target") == 35)

# date pourrie -> ne casse rien (best-effort)
bad = R(None, {"nightly_target": 35, "nightly_target_restore_at": "pas-une-date"})
check("date invalide -> inchangé, pas de plantage", bad.get("nightly_target") == 35)

print(f"\n{_ok} OK / {_ko} échec(s)")
sys.exit(1 if _ko else 0)
