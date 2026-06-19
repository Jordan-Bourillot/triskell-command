# -*- coding: utf-8 -*-
"""Fabrique le badge Triskell (logo triskel sur rond sombre) et l'héberge sur
le bucket Supabase public utilisé pour les aperçus → URL stable utilisée dans
le rond d'en-tête des mails créateurs (cf. integrations/creator_mail.py).

Lancer une seule fois (idempotent : upsert). Réutilise le triskel SVG officiel
des signatures (3 spirales indigo/violet/orange).

Usage : python scripts/make_triskell_badge.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BUCKET = "pp-client-photos"
OBJECT_PATH = "brand/triskell_badge.png"

_TRISKEL = (
    'd="M18,18 C20,15 22,10 20,6 C18,2 13,3 13,7.5 C13,12 16,15.5 18,18Z"')
SVG = f"""<svg width="240" height="240" viewBox="0 0 240 240" xmlns="http://www.w3.org/2000/svg">
  <circle cx="120" cy="120" r="120" fill="#0B0B14"/>
  <g transform="translate(120,120) scale(4.3) translate(-18,-18)">
    <path {_TRISKEL} fill="#6366F1"/>
    <path {_TRISKEL} fill="#8B5CF6" transform="rotate(120 18 18)"/>
    <path {_TRISKEL} fill="#F97316" transform="rotate(240 18 18)"/>
    <circle cx="18" cy="18" r="2.8" fill="#0B0B14"/>
  </g>
</svg>"""

HTML = (f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<style>*{{margin:0;padding:0}}body{{width:240px;height:240px}}</style>'
        f'</head><body>{SVG}</body></html>')


def _render_png() -> bytes:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            pg = b.new_page(viewport={"width": 240, "height": 240},
                            device_scale_factor=2)
            pg.set_content(HTML, wait_until="domcontentloaded")
            pg.wait_for_timeout(300)
            return pg.screenshot(omit_background=False,
                                 clip={"x": 0, "y": 0, "width": 240, "height": 240})
        finally:
            b.close()


def main() -> int:
    from supabase import create_client
    cfg = json.loads((Path.home() / ".triskell-command" / "settings.json")
                     .read_text(encoding="utf-8"))
    sb_cfg = cfg["supabase"]
    sb = create_client(sb_cfg["url"], sb_cfg["service_role_key"])

    png = _render_png()
    print(f"PNG généré : {len(png)} octets")
    sb.storage.from_(BUCKET).upload(
        path=OBJECT_PATH, file=png,
        file_options={"content-type": "image/png", "upsert": "true"})
    url = (f'{sb_cfg["url"].rstrip("/")}/storage/v1/object/public/'
           f'{BUCKET}/{OBJECT_PATH}')
    print(f"OK → {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
