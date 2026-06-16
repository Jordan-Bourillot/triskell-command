# -*- coding: utf-8 -*-
"""Contrôles SANS RÉSEAU du système « site à refaire » :
  - site_quality.py : signaux texte (forts/faibles), précision (zéro faux
    positif sur les pièges connus), classification d'adresse, verdicts ;
  - site_vision.py  : lecture du verdict de l'IA, verrou de confiance,
    bascule de providers (avec une fausse IA), robustesse.

Usage : python scripts/smoke_site_redo.py   (doit afficher 0 échec)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from triskell_command.integrations import site_quality as sq  # noqa: E402
from triskell_command.integrations import site_vision as sv  # noqa: E402

ok = 0
ko = 0


def check(label, cond):
    global ok, ko
    if cond:
        ok += 1
    else:
        ko += 1
        print(f"  ❌ {label}")


VP = '<meta name=viewport content="width=device-width">'
TXT = "du contenu " * 60


def page(head="", body=TXT, title="Titre"):
    t = f"<title>{title}</title>" if title else ""
    return f"<!doctype html><html><head>{t}{head}</head><body>{body}</body></html>"


# ---------- site_quality : signaux FORTS (chacun flague seul) ----------
print("site_quality — signaux forts")
check("moderne complet = OK", not sq.score_site_html(page(VP), "https://x.fr")["to_redo"])
check("pas de viewport = à refaire",
      sq.score_site_html(page(""), "https://x.fr")["to_redo"])
check("frames = à refaire",
      sq.score_site_html("<frameset><frame></frameset>" + page(VP), "https://x.fr")["to_redo"])
check("flash .swf = à refaire",
      sq.score_site_html(page(VP, body="<object data='intro.swf'></object>" + TXT), "https://x.fr")["to_redo"])
check("générateur mort (FrontPage) = à refaire",
      sq.score_site_html(page('<meta name=generator content="Microsoft FrontPage 5.0">' + VP), "https://x.fr")["to_redo"])
check("pas de titre = à refaire",
      sq.score_site_html(page(VP, title=""), "https://x.fr")["to_redo"])
check("appli JS sans titre = OK (garde SPA)",
      not sq.score_site_html(
          page(VP, body='<div id="root"></div>' + ("texte " * 60), title=""),
          "https://x.fr")["to_redo"])
check("en construction (page courte) = à refaire",
      sq.score_site_html("<html><body>Site en construction</body></html>", "https://x.fr")["to_redo"])
check("coming soon = à refaire",
      sq.score_site_html(page(VP, body="Coming soon " * 20), "https://x.fr")["to_redo"])

# ---------- site_quality : PRÉCISION (pièges = ne PAS flaguer) ----------
print("site_quality — précision (pièges connus)")
check("maçon qui parle de construction = OK",
      not sq.score_site_html(page(VP, body="Specialiste en construction de maisons. " * 8), "https://x.fr")["to_redo"])
check("http seul (faible) = OK",
      not sq.score_site_html(page(VP), "http://x.fr")["to_redo"])
check("copyright ancien seul = OK",
      not sq.score_site_html(page(VP, body="© 2016 " + TXT), "https://x.fr")["to_redo"])
check("flash mentionné dans un script = OK (scripts retirés)",
      not sq.score_site_html(page(VP, body="<script>var t='shockwave-flash';</script>" + TXT), "https://x.fr")["to_redo"])

# ---------- site_quality : classification d'adresse ----------
print("site_quality — type d'adresse")
check("facebook = social", sq.classify_url("https://facebook.com/macompany") == "social")
check("wixsite = free_host", sq.classify_url("https://jean.wixsite.com/resto") == "free_host")
check("domaine propre = normal", sq.classify_url("https://mon-resto.fr") == "normal")
check("vide = empty", sq.classify_url("") == "empty")
check("leroux.com PAS pris pour x.com",
      sq.classify_url("https://leroux.com") == "normal")

# ---------- site_quality : verdicts combinés ----------
print("site_quality — verdicts combinés")
check("assess social = no_site",
      sq.assess_from_signals("https://facebook.com/x", None)["category"] == "no_site")
check("assess free_host = free_host",
      sq.assess_from_signals("https://x.wixsite.com/y", None)["category"] == "free_host")
v_old = sq.assess_from_signals("https://x.fr", sq.score_site_html(page(""), "https://x.fr"))
check("assess domaine + vieux = old", v_old["category"] == "old")

# ---------- site_vision : lecture verdict + verrou confiance ----------
print("site_vision — jugement IA (fausse IA injectée)")
orig = sv._vision_call


def fake(verdict_json):
    return lambda prompt, b64, keys: (verdict_json, "fake")


sv._vision_call = fake('{"a_refaire": true, "confiance": 90, "style": "daté", "raison": "look années 2000"}')
r1 = sv.judge_design(b"PNGDATA", "X", "coiffeur", keys={"x": "1"})
check("IA dit oui + confiance 90 = à refaire", r1["ok"] and r1["to_redo"] and r1["confidence"] == 90)
check("raison récupérée", "années 2000" in r1["reason"])

sv._vision_call = fake('{"a_refaire": true, "confiance": 50, "style": "?", "raison": "bof"}')
r2 = sv.judge_design(b"PNGDATA", "X", "coiffeur", keys={"x": "1"})
check("confiance trop basse (50<75) = PAS flagué", r2["ok"] and not r2["to_redo"])

sv._vision_call = fake('{"a_refaire": false, "confiance": 95, "style": "moderne", "raison": "propre"}')
r3 = sv.judge_design(b"PNGDATA", "X", "coiffeur", keys={"x": "1"})
check("IA dit non = PAS flagué même très confiant", r3["ok"] and not r3["to_redo"])

sv._vision_call = lambda p, b, k: ("blabla pas de json", "fake")
r4 = sv.judge_design(b"PNGDATA", "X", "", keys={"x": "1"})
check("réponse sans JSON = erreur propre, pas de flag", (not r4["ok"]) and not r4["to_redo"])

check("pas de capture = erreur propre", not sv.judge_design(b"", "X")["ok"])
sv._vision_call = orig

# ---------- site_vision : constantes ----------
print("site_vision — réglages")
check("seuil de confiance = 75", sv.MIN_CONFIDENCE == 75)
check("catégorie visuelle posée", sv.VISION_CATEGORY == "redo_visuel")

print(f"\n{'✅' if ko == 0 else '❌'} {ok} OK, {ko} échec(s)")
sys.exit(1 if ko else 0)
