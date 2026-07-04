# -*- coding: utf-8 -*-
"""Smoke test du compteur « améliorations GEO en attente » (13/06/2026).

Demande Jordan : voir d'un coup d'œil les corrections d'audit IA qui
attendent sa validation (badge ✏️ sur les cartes de sites + signal dans
le Guide/Perceval), et qu'elles sortent du compteur une fois appliquées.

Vérifie SANS réseau et SANS toucher au vrai état (racine GEO factice,
sauvegarde neutralisée, publication simulée) :
  1. _geo_pending_fixes_by_site : seul le DERNIER audit de chaque site
     compte, les suggestions appliquées sont exclues.
  2. geo_state : pending_fixes posé sur chaque site.
  3. geo_publish_finding : publication réussie → suggestion marquée
     appliquée (et une publication ratée ne marque RIEN).
  4. guide_snapshot : compteur geo_pending_fixes présent.
  5. L'écran et Perceval utilisent bien ces champs.

Usage :  python scripts/smoke_geo_fixes.py
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


from triskell_command.web.api import Api  # noqa: E402

api = Api()

# Racine GEO factice — on ne touche JAMAIS au vrai AppState.
fake_root = {
    "sites": [
        {"id": "s1", "name": "Site Un",   "url": "https://un.fr",   "brand": "Un"},
        {"id": "s2", "name": "Site Deux", "url": "https://deux.fr", "brand": "Deux"},
    ],
    "questions": {"s1": [{"id": "q1", "text": "?"}]},
    "audits": [], "surveillance_runs": [], "reputation_runs": [],
    "generated": [],
    "ai_audits": [
        # Du plus récent au plus ancien (comme en vrai : insert(0)).
        # s1, audit FRAIS : 2 suggestions en attente + 1 déjà appliquée.
        {"id": "a2", "site_id": "s1", "ts": "2026-06-13T01:00:00",
         "verdict": "", "provider": "test",
         "findings": [
             {"id": "f1", "title": "Titre trop vague", "problem": "p",
              "fix_title": "Réécrire le titre", "fix_html": "<p>x</p>"},
             {"id": "f2", "title": "Pas de FAQ", "problem": "p",
              "fix_title": "Ajouter une FAQ", "fix_html": "<p>y</p>"},
             {"id": "f3", "title": "Déjà fait", "problem": "p",
              "fix_title": "—", "fix_html": "<p>z</p>",
              "applied_at": "2026-06-12T00:00:00"},
         ]},
        # s1, VIEIL audit (périmé) : ses 5 suggestions ne comptent plus.
        {"id": "a1", "site_id": "s1", "ts": "2026-06-10T01:00:00",
         "findings": [{"id": f"old{i}", "title": "vieux"} for i in range(5)]},
        # s2 : tout est appliqué → 0 en attente.
        {"id": "a3", "site_id": "s2", "ts": "2026-06-12T01:00:00",
         "findings": [{"id": "g1", "title": "ok",
                       "applied_at": "2026-06-12T02:00:00"}]},
    ],
}
api._geo_root = lambda: fake_root
api._geo_save = lambda: None

print("1) Compteur par site (dernier audit seulement, appliquées exclues)…")
pend = api._geo_pending_fixes_by_site(fake_root)
check("s1 → 2 en attente (la 3e est appliquée)", pend.get("s1") == 2)
check("le vieil audit de s1 ne compte pas (sinon on aurait 7)",
      pend.get("s1") == 2)
check("s2 → rien (tout appliqué)", "s2" not in pend)

print("2) geo_state expose pending_fixes…")
st = api.geo_state({})
sites = {s["id"]: s for s in (st.get("sites") or [])}
check("geo_state ok", bool(st.get("ok")))
check("s1.pending_fixes = 2", sites.get("s1", {}).get("pending_fixes") == 2)
check("s2.pending_fixes = 0", sites.get("s2", {}).get("pending_fixes") == 0)

print("3) Publication d'une suggestion → marquée appliquée…")
api.geo_publish_content = lambda p: {"ok": True, "url": "https://un.fr/geo/x"}
r = api.geo_publish_finding({"audit_id": "a2", "finding_id": "f1"})
f1 = next(f for f in fake_root["ai_audits"][0]["findings"] if f["id"] == "f1")
check("publication ok", bool(r.get("ok")))
check("f1 marquée appliquée (applied_at posé)", bool(f1.get("applied_at")))
check("le compteur tombe à 1",
      api._geo_pending_fixes_by_site(fake_root).get("s1") == 1)

api.geo_publish_content = lambda p: {"ok": False, "error": "panne simulée"}
r2 = api.geo_publish_finding({"audit_id": "a2", "finding_id": "f2"})
f2 = next(f for f in fake_root["ai_audits"][0]["findings"] if f["id"] == "f2")
check("publication ratée → refus transmis", r2.get("ok") is False)
check("…et la suggestion N'EST PAS marquée appliquée",
      not f2.get("applied_at"))
check("…le compteur reste à 1",
      api._geo_pending_fixes_by_site(fake_root).get("s1") == 1)

print("4) guide_snapshot expose le total…")
api._supabase = lambda: None  # aucun accès base pendant le test
Api._GUIDE_CACHE["data"] = None
Api._GUIDE_CACHE["at"] = 0
snap = api.guide_snapshot({})
check("guide_snapshot ok", bool(snap.get("ok")))
check("geo_pending_fixes = 1 (s1 seul)", snap.get("geo_pending_fixes") == 1)

print("5) L'écran et Perceval branchés…")
ui = HERE / "triskell_command" / "web" / "ui"
geo_js = (ui / "scripts" / "geo.js").read_text(encoding="utf-8")
perceval_js = (ui / "scripts" / "perceval.js").read_text(encoding="utf-8")
css = (ui / "styles" / "main.css").read_text(encoding="utf-8")
check("geo.js affiche le badge (pending_fixes)",
      "pending_fixes" in geo_js and "geo-site-fixes" in geo_js)
check("geo.js distingue les suggestions appliquées",
      "applied_at" in geo_js and "Appliquée le" in geo_js)
check("perceval.js recommande les améliorations GEO",
      "geo_pending_fixes" in perceval_js)
check("style du badge présent", ".geo-site-fixes" in css)

print("6) Garde-fou anti-invention (avant mise en ligne)…")
# Bloque tout bloc citant un montant/pourcentage/loi/lien absent de la vraie
# page (l'IA fabrique des faits — vécu le 04/07 : faux prix Lagriffe 49,97 €
# au lieu de 49 €, faux article de loi sur le site client Ingrid, taux inventé
# Eliks, URL LinkedIn inventée WoW). Laisse passer les faits réellement repris.
_g = api._geo_unsupported_facts

_src_lag = ("Lagriffe Studio, agence web. Sites a partir de 49 EUR HT par mois. "
            "Sans engagement. 2500 a 5000 EUR ailleurs.")
_bad = _g("<p>~600 EUR annuels (49,97 EUR/mois). Fonde en 2026.</p>", _src_lag)
check("faux prix 49,97 EUR (page dit 49) → bloqué",
      any("49,97" in b["value"] for b in _bad))
check("'fondé en 2026' absent de la page → bloqué",
      any(b["kind"] == "année" for b in _bad))

_src_ing = ("Ingrid Services, aide a domicile a Blanzy 71450. 22 EUR de l'heure. "
            "Credit d'impot article 293 B.")
_bad = _g("<p>Article L. 248-1 du code monetaire et financier, plafonne a "
          "12 000 EUR par an.</p>", _src_ing)
check("faux article de loi L.248-1 → bloqué",
      any(b["kind"] == "référence légale" for b in _bad))
check("'code monétaire et financier' inventé → bloqué",
      any(b["kind"] == "code de loi" for b in _bad))
check("plafond 12 000 EUR absent de la page → bloqué",
      any(b["kind"] == "montant" for b in _bad))

_src_eliks = "Eliks Studio. Commission pure, zero fixe. 48h appel gratuit. Max 6 clients."
check("taux '10-30%' inventé → bloqué",
      any(b["kind"] == "pourcentage"
          for b in _g("<p>Commission de 10-30% sur les ventes.</p>", _src_eliks)))

_src_wow = "Studio WoW. 80+ projets dans 14 pays. Paiement 30/30/40."
check("URL LinkedIn inventée → bloquée",
      any(b["kind"] == "lien" for b in _g(
          '<a href="https://linkedin.com/company/wow-studio">Nous</a>', _src_wow)))

# Faits RÉELS repris depuis la page → rien ne doit être bloqué.
_src_rk = ("RankUs Studio SEO. Creation de site des 490 EUR HT. Premiers "
           "resultats en moins de 3 mois. Sans engagement.")
check("FAQ qui reprend 490 EUR / 3 mois réels → rien bloqué",
      _g("<p>Des 490 EUR HT, resultats en moins de 3 mois, sans engagement.</p>",
         _src_rk) == [])
check("séparateur de liste '71450, 22 EUR' non fusionné en faux nombre",
      _g("<p>Blanzy 71450, 22 EUR de l'heure, article 293 B.</p>", _src_ing) == [])
check("entiers structurels (3 questions, 5 critères) → ignorés",
      _g("<p>3 questions, 5 criteres.</p>", _src_rk) == [])

print()
print(f"{len(PASS)} OK / {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
