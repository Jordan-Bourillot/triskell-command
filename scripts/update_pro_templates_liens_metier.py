# -*- coding: utf-8 -*-
"""Branche les pages métier de pixel-pros.fr dans les 3 modèles de
prospection « pro » (prosp_pp_pro_cabinet / _commerce / _artisan).

Ce que ça change dans chaque modèle (validé par Jordan le 2026-06-12) :
  - body_text : une ligne de plus avant la signature, avec le lien démo
    en clair → la version texte du mail a ENFIN un lien, et le HTML
    auto-régénéré (si le texte est retouché à la validation) garde un
    bouton cliquable.
  - body_html : le bouton « Découvrir Pixel Pros » pointe vers la page
    de pub du métier du prospect ({{page_metier}}), et un second bouton
    « Voir un exemple » mène à la démo du métier ({{page_demo}}).

{{page_metier}} / {{page_demo}} sont remplis automatiquement selon le
secteur de la fiche (coiffeuse → /beaute + /demo-beaute ; secteur
inconnu → accueil + /demo). Cf. integrations/pixelpros_pages.py.

Usage :
    python scripts/update_pro_templates_liens_metier.py            (test à blanc)
    python scripts/update_pro_templates_liens_metier.py --apply    (écrit en base)

UPDATE ciblé sur body_text/body_html uniquement — jamais d'upsert
partiel sur triskell_email_templates (un upsert partiel met des NULL
partout, leçon du 11/06/2026).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from supabase import create_client  # noqa: E402

KEYS = ("prosp_pp_pro_cabinet", "prosp_pp_pro_commerce",
        "prosp_pp_pro_artisan")

# --- body_text : ligne ajoutée avant la signature --------------------------
SIGNATURE_TXT = "\n\nJordan\nPixel Pros · Studio breton"
LIGNE_DEMO_TXT = ("\n\nPour voir ce que ça donne en vrai, voici un exemple "
                  "de site pour votre métier : {{page_demo}}")

# --- body_html : bouton principal ciblé + second bouton démo ---------------
ANCRE_HREF = 'href="https://pixel-pros.fr"'
NOUVEAU_HREF = 'href="{{page_metier}}"'
ANCRE_BOUTON = "Découvrir Pixel Pros &rarr;</a>"
BOUTON_DEMO = (
    'Découvrir Pixel Pros &rarr;</a> '
    '<a href="{{page_demo}}" style="display:inline-block;'
    "background:#fffaf0;color:#b8860b;text-decoration:none;"
    "font-weight:700;font-size:14px;padding:11px 21px;"
    'border-radius:8px;border:1px solid #facc15;margin-left:8px;">'
    "Voir un exemple &rarr;</a>"
)


def main() -> int:
    apply = "--apply" in sys.argv
    cfg_path = Path.home() / ".triskell-command" / "settings.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    sb_cfg = cfg["supabase"]
    sb = create_client(sb_cfg["url"], sb_cfg["service_role_key"])

    rows = (sb.table("triskell_email_templates")
              .select("key, body_text, body_html")
              .eq("category", "prospection")
              .eq("product", "pixel-pros")
              .eq("audience", "pro")
              .execute().data or [])
    by_key = {r["key"]: r for r in rows}

    n_ok = 0
    for key in KEYS:
        r = by_key.get(key)
        if not r:
            print(f"SKIP {key} : introuvable en base")
            continue
        bt, bh = r.get("body_text") or "", r.get("body_html") or ""

        # Garde-fous : on ne touche QUE si les ancres exactes sont là
        # (et pas déjà branchées — relancer le script doit être inoffensif).
        if "{{page_demo}}" in bt or "{{page_metier}}" in bh:
            print(f"SKIP {key} : déjà branché sur les pages métier")
            continue
        problemes = []
        if SIGNATURE_TXT not in bt:
            problemes.append("signature texte introuvable")
        if bh.count(ANCRE_HREF) != 1:
            problemes.append(f"href accueil x{bh.count(ANCRE_HREF)} (attendu 1)")
        if bh.count(ANCRE_BOUTON) != 1:
            problemes.append("bouton « Découvrir Pixel Pros » introuvable")
        if problemes:
            print(f"REFUS {key} : {', '.join(problemes)} — modèle inchangé")
            continue

        new_bt = bt.replace(SIGNATURE_TXT, LIGNE_DEMO_TXT + SIGNATURE_TXT, 1)
        new_bh = (bh.replace(ANCRE_HREF, NOUVEAU_HREF, 1)
                    .replace(ANCRE_BOUTON, BOUTON_DEMO, 1))

        if apply:
            sb.table("triskell_email_templates").update({
                "body_text": new_bt,
                "body_html": new_bh,
                "updated_by": "liens-pages-metier-2026-06-12",
            }).eq("product", "pixel-pros").eq("key", key).execute()
            print(f"OK   {key} : liens pages métier branchés")
        else:
            print(f"PRÊT {key} (test à blanc, rien écrit) :")
            print(f"  + texte : « {LIGNE_DEMO_TXT.strip()} »")
            print(f"  + bouton principal → {{{{page_metier}}}}")
            print(f"  + second bouton « Voir un exemple » → {{{{page_demo}}}}")
        n_ok += 1

    print(f"\n{n_ok}/{len(KEYS)} modèles "
          + ("mis à jour." if apply else "prêts (relancer avec --apply)."))
    return 0 if n_ok == len(KEYS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
