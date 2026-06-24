#!/usr/bin/env python3
"""Batterie « vérité » du Studio d'images (FLUX via Pollinations) — SANS réseau.

Vérifie les parties pures (styles, formats, composition du prompt, URL
Pollinations) et le refus du prompt vide. Aucun appel réseau n'est effectué
(le chemin réseau est validé séparément avec une vraie génération).

    python scripts/smoke_flux.py
"""

import os
import sys

try:                                  # console Windows (cp1252) → forcer UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from triskell_command.integrations import flux_studio as fx  # noqa: E402

_checks = []


def check(name, cond):
    _checks.append((name, bool(cond)))


# 1) Styles ------------------------------------------------------------------
styles = fx.list_styles()
check("au moins un style", len(styles) >= 1)
check("DEFAULT_STYLE existe", any(s["id"] == fx.DEFAULT_STYLE for s in styles))
sids = [s["id"] for s in styles]
check("ids de styles uniques", len(sids) == len(set(sids)))
check("chaque style a un libellé", all(s.get("label") for s in styles))
check("style « aucun » présent", "aucun" in sids)

# 2) Formats -----------------------------------------------------------------
formats = fx.list_formats()
check("au moins un format", len(formats) >= 1)
check("DEFAULT_FORMAT existe", any(f["id"] == fx.DEFAULT_FORMAT for f in formats))
check("dimensions plausibles (256..1600)",
      all(256 <= f["w"] <= 1600 and 256 <= f["h"] <= 1600 for f in formats))

# 3) compose_prompt ----------------------------------------------------------
st_photo = fx._style("photo")
st_aucun = fx._style("aucun")
p_photo = fx.compose_prompt("un chat roux", st_photo)
check("style ajoute des mots-clés", "photorealistic" in p_photo and p_photo.startswith("un chat roux"))
p_aucun = fx.compose_prompt("un chat roux", st_aucun)
check("style « aucun » ne change rien", p_aucun == "un chat roux")
check("prompt plafonné à 1500", len(fx.compose_prompt("a" * 5000, st_aucun)) <= 1500)

# 4) build_url ---------------------------------------------------------------
fmt = fx._format("paysage")
url = fx.build_url("un chat", st_aucun, fmt, 42)
check("URL pointe Pollinations", "image.pollinations.ai/prompt/" in url)
check("URL : bonne largeur", "width=%d" % fmt["w"] in url)
check("URL : bonne hauteur", "height=%d" % fmt["h"] in url)
check("URL : seed repris", "seed=42" in url)
check("URL : modèle flux", "model=flux" in url)
check("URL : sans watermark", "nologo=true" in url)
check("URL : prompt encodé", "un%20chat" in url)

# 5) Fallbacks ---------------------------------------------------------------
check("style inconnu → défaut", fx._style("zzz")["id"] == fx.DEFAULT_STYLE)
check("format inconnu → défaut", fx._format("zzz")["id"] == fx.DEFAULT_FORMAT)

# 6) Refus prompt vide (aucun réseau touché) ---------------------------------
r_empty = fx.generate("   ")
check("prompt vide refusé proprement",
      r_empty.get("ok") is False and bool(r_empty.get("error")))

# 7) Bilan -------------------------------------------------------------------
ok = sum(1 for _, c in _checks if c)
for name, c in _checks:
    print(("  ok  " if c else " FAIL ") + name)
print(f"\n{ok}/{len(_checks)} contrôles OK")
sys.exit(0 if ok == len(_checks) else 1)
