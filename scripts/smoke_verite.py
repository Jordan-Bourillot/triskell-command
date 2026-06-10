# -*- coding: utf-8 -*-
"""Smoke test VÉRITÉ FONCTIONNELLE (2026-06-10).

Principe : un outil qui affiche « OK » n'est pas un outil qui marche.
On maltraite chaque point d'accès de la prospection (entrées vides,
cassées, ids bidons) : il doit répondre par un REFUS PROPRE en français
— jamais un plantage, jamais un faux succès.

Et l'assistant : ses actions passent par une liste blanche stricte,
le tag est extrait/exécuté correctement, les garde-fous tiennent.

Usage :  python scripts/smoke_verite.py
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


print("1) Chaque point d'accès refuse proprement les entrées cassées…")
from triskell_command.web.api import Api  # noqa: E402

api = Api()

# (endpoint, payload pourri, bout de message attendu — None = juste ok:False)
CASES = [
    ("chasseur_start_hunt", {}, "secteur"),
    ("chasseur_get_hunt", {}, "hunt_id"),
    ("chasseur_export_csv", {}, "hunt_id"),
    ("chasseur_push_to_autopilot", {}, "hunt_id"),
    ("chasseur_delete_hunt", {}, "hunt_id"),
    ("chasseur_createurs_start_hunt", {}, None),
    ("chasseur_createurs_get_hunt", {}, "hunt_id"),
    ("chasseur_createurs_push_to_prospects", {}, "hunt_id"),
    ("prospecteur_google_start_hunt", {}, None),
    ("prospecteur_google_get_hunt", {}, "hunt_id"),
    ("prospecteur_google_push_to_prospects", {}, "hunt_id"),
    ("prospection_start", {}, "cible"),
    # Mission PME sans métier ni zone : refusée (sinon chasse France entière
    # — bug réel attrapé par cette batterie le 10/06/2026)
    ("prospection_start", {"source": "pme", "params": {}}, "métier"),
    ("prospection_start", {"source": "local", "params": {}}, None),
    ("prospection_start", {"source": "createurs", "params": {}}, None),
    ("prospection_mission_cancel", {}, "id"),
    ("prospection_mission_cancel", {"id": "zzz-bidon"}, "introuvable"),
    ("mail_dns_check", {"domain": "pas-un-domaine"}, None),
    ("obelisk_get_creator", {}, None),
    ("obelisk_delete_creator", {}, None),
]
for name, payload, expect in CASES:
    fn = getattr(api, name, None)
    if not callable(fn):
        check(f"{name} : existe", False, "(endpoint manquant)")
        continue
    try:
        r = fn(payload)
        ok_false = isinstance(r, dict) and r.get("ok") is False
        msg = (r.get("error") or "") if isinstance(r, dict) else ""
        cond = ok_false and (expect is None or expect in msg)
        check(f"{name} : refus propre", cond, f"(reçu : {r})")
    except Exception as exc:
        check(f"{name} : refus propre", False, f"(PLANTAGE : {exc})")

print("2) Les actions de l'assistant…")
from triskell_command.integrations.claude_advisor import (  # noqa: E402
    _extract_action, execute_assistant_action,
)

# Extraction du tag
t, a = _extract_action(
    'C’est parti, je lance ça. [ACTION:{"do":"navigate","view":"drafts"}]')
check("tag extrait et retiré du texte parlé",
      a == {"do": "navigate", "view": "drafts"} and "ACTION" not in t)
t, a = _extract_action("Réponse normale sans action.")
check("pas de tag → pas d'action", a is None and "normale" in t)
t, a = _extract_action('Oups. [ACTION:{json cassé}]')
check("JSON cassé → ignoré proprement, texte nettoyé",
      a is None and "ACTION" not in t)

# Exécution — liste blanche
r = execute_assistant_action({"do": "navigate", "view": "drafts"})
check("navigation autorisée vers un écran connu",
      r["ok"] and r.get("navigate") == "drafts")
r = execute_assistant_action({"do": "navigate", "view": "config_secrete"})
check("écran hors liste blanche → refusé", r["ok"] is False)
r = execute_assistant_action({"do": "rm_rf", "view": "x"})
check("action inconnue → rien fait", r["ok"] is False and "inconnue" in r["summary"])
r = execute_assistant_action({"do": "start_prospection", "source": "zzz",
                               "params": {}})
check("prospection avec cible inconnue → refus relayé en français",
      r["ok"] is False and "Impossible" in r["summary"])
r = execute_assistant_action({"do": "cancel_mission", "id": "zzz-bidon"})
check("abandon de mission inconnue → échec propre (lecture seule)",
      r["ok"] is False)

# Garde-fou : pas d'allumage vocal si l'envoi est en AUTOMATIQUE
import triskell_command.integrations.claude_advisor as CA  # noqa: E402
from unittest import mock  # noqa: E402

with mock.patch.object(Api, "autopilot_get_stage_modes",
                       return_value={"ok": True, "modes": {"send": "auto"}}):
    with mock.patch("triskell_core.prospect.pipeline.PipelineConfig.save"):
        r = execute_assistant_action({"do": "toggle_autopilot",
                                       "enabled": True})
check("envoi AUTO → l'assistant REFUSE d'allumer à la voix",
      r["ok"] is False and "sécurité" in r["summary"]
      and r.get("navigate") == "prospection")

with mock.patch.object(Api, "autopilot_get_stage_modes",
                       return_value={"ok": True, "modes": {"send": "manual"}}):
    with mock.patch("triskell_core.prospect.pipeline.PipelineConfig.save") as sv:
        r = execute_assistant_action({"do": "toggle_autopilot",
                                       "enabled": True})
check("envoi en brouillons → allumage vocal accepté (config sauvée)",
      r["ok"] is True and "brouillons" in r["summary"] and sv.called)

print("3) Cohérence de l'interface après rationalisation…")
ui = HERE / "triskell_command/web/ui"
html = (ui / "index.html").read_text(encoding="utf-8")
check("Chasseur Créateur retiré du menu",
      'data-view="chasseur_createurs"' not in html)
check("sa vue reste routée (lien direct possible)",
      "case 'chasseur_createurs'" in
      (ui / "scripts/app.js").read_text(encoding="utf-8"))
check("bannière de remplacement sur la vue",
      "remplacé par" in
      (ui / "scripts/chasseur_createurs.js").read_text(encoding="utf-8"))
check("compteur du groupe à jour (5)", 'nav-group-count">5' in html)
check("Éclaireur renommé « Compléter les fiches »",
      "<span>Compléter les fiches</span>" in html)

print()
print(f"{len(PASS)} OK / {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
