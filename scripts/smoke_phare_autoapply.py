# -*- coding: utf-8 -*-
"""Smoke test : automatisations ciblées du Phare (22/06/2026).

Deux drapeaux « fantômes » (lus par AUCUN code) deviennent de vrais
interrupteurs, et une mission pose les étiquettes invisibles (données
structurées) sur tout le site :

  1. run_schema_pass : crée UNE carte « schema_architect » pour les pages
     sans données structurées, exclut l'accueil, ne crée rien si tout est
     déjà balisé.
  2. classify_for_apply : une carte schema_architect = bouton vert (code).
  3. _is_metadata_only : une carte schema = invisible (pas de faux « diff
     visuel » bloquant).
  4. auto_apply_safe : les drapeaux granulaires n'auto-appliquent QUE leur
     famille (schema seul / images seules), sans ouvrir la vanne globale ;
     la vanne globale, elle, prend bien les trois.
  5. Endpoints : phare_automerge_get expose les 3 réglages, phare_autoapply_set
     n'écrit que ceux demandés.

Sans réseau, sans base : on remplace les accès repo par des bouchons.

Usage :  python scripts/smoke_phare_autoapply.py
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


from triskell_command.integrations.phare import (  # noqa: E402
    orchestrator, plain_language, executor)
import triskell_command.integrations.phare.repo as repo  # noqa: E402
from triskell_command.web.api import Api  # noqa: E402

SITE = {"id": "s1", "domain": "ex.fr", "name": "Ex", "repo_github": "x/y"}

print("1) run_schema_pass — carte « étiquettes » par site…")
repo.get_site = lambda sid: dict(SITE)
repo.list_pages = lambda sid, limit=500: [
    {"path": "/", "schema_types": []},                       # accueil → exclu
    {"path": "/services", "schema_types": []},               # à équiper
    {"path": "/contact", "schema_types": ["Organization"]},  # déjà balisé
]
captured = {}
repo.insert_action = lambda a: (captured.update(action=a), {"id": "act1", **a})[1]
r = orchestrator.run_schema_pass("s1")
check("crée une carte (1 page concernée, accueil exclu)", r.get("pages") == 1, r)
check("agent = schema_architect",
      captured.get("action", {}).get("agent") == "schema_architect")
check("la page d'accueil n'est PAS dans la carte",
      "/services" in captured["action"]["detail_md"]
      and "/contact" not in captured["action"]["detail_md"])

repo.list_pages = lambda sid, limit=500: [{"path": "/x", "schema_types": ["Article"]}]
check("rien à faire si tout est déjà balisé",
      orchestrator.run_schema_pass("s1").get("pages") == 0)

print("2) Une carte schema = bouton vert (le robot sait faire)…")
schema_card = {"agent": "schema_architect", "status": "draft",
               "title": "Étiquettes pour les IA : 2 pages à équiper",
               "detail_md": "Pages concernées : /services, /blog."}
v = plain_language.classify_for_apply(schema_card, SITE)
check("can=True et mode=code", v.get("can") and v.get("mode") == "code", v)
v2 = plain_language.classify_for_apply(schema_card, {"repo_github": ""})
check("sans dépôt relié → à brancher (pas de faux vert)", v2.get("can") is False)

print("3) Une carte schema est « invisible » (pas de faux diff visuel)…")
check("_is_metadata_only(schema) = True",
      executor._is_metadata_only({"agent": "schema_architect", "title": "x"}))

print("4) auto_apply_safe — les drapeaux granulaires ciblent leur famille…")
schema_act = {"id": "a1", "agent": "schema_architect", "status": "draft",
              "site_id": "s1", "title": "Étiquettes pour les IA : 2 pages",
              "detail_md": "Pages : /a, /b."}
img_act = {"id": "a2", "agent": "image_seo", "status": "draft", "site_id": "s1",
           "title": "Image SEO : 3 alts générés", "detail_md": "des images"}
title_act = {"id": "a3", "agent": "optimiseur_onpage", "status": "draft",
             "site_id": "s1", "title": "Optim on-page /services",
             "detail_md": "Title cible : Services de plomberie à Brest"}
repo.list_actions = lambda status=None, limit=200: [schema_act, img_act, title_act]
repo.get_site = lambda sid: dict(SITE)


def _run_autoapply(cfg):
    repo.get_config = lambda: dict(cfg)
    done = []
    repo.update_action = lambda aid, patch: (done.append(aid), True)[1]
    orchestrator.auto_apply_safe()
    return done


check("tout coupé → rien ne part",
      _run_autoapply({}) == [])
check("schema seul activé → SEULE la carte étiquettes part",
      _run_autoapply({"auto_apply_schema": True}) == ["a1"])
check("images seules activées → SEULE la carte images part",
      _run_autoapply({"auto_apply_image_alts": True}) == ["a2"])
check("les deux ciblés → étiquettes + images (pas le titre)",
      set(_run_autoapply({"auto_apply_schema": True,
                          "auto_apply_image_alts": True})) == {"a1", "a2"})
check("vanne globale → les trois corrections sûres partent",
      set(_run_autoapply({"auto_merge_enabled": True})) == {"a1", "a2", "a3"})

print("5) Endpoints de réglage…")
api = Api()
store = {"auto_apply_schema": False, "auto_apply_image_alts": False,
         "auto_merge_enabled": False}
repo.get_config = lambda: dict(store)
repo.update_config = lambda patch: (store.update(patch), True)[1]
g = api.phare_automerge_get()
check("get expose les 3 réglages",
      g.get("ok") and "auto_apply_schema" in g and "auto_apply_image_alts" in g
      and "enabled" in g)
s = api.phare_autoapply_set({"schema": True})
check("activer les étiquettes n'écrit QUE cette clé",
      store["auto_apply_schema"] is True
      and store["auto_apply_image_alts"] is False
      and store["auto_merge_enabled"] is False)
api.phare_autoapply_set({"image_alts": True})
check("activer les images écrit sa clé", store["auto_apply_image_alts"] is True)
check("régler sans rien demander est refusé proprement",
      api.phare_autoapply_set({}).get("ok") is False)

print()
print(f"{len(PASS)} OK / {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
