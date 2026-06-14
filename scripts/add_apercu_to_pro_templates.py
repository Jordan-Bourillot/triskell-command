# -*- coding: utf-8 -*-
"""Ajoute l'aperçu de site personnalisé ({{apercu_site}}) dans les 2 modèles
de prospection « pro » qui s'y prêtent : Commerces et Artisans.

Ce que ça change dans body_html (validé par Jordan le 2026-06-14) :
  - juste AVANT le paragraphe des boutons, on insère une phrase
    « voici à quoi pourrait ressembler votre site : » suivie du
    placeholder {{apercu_site}}. Au rendu du mail, ce placeholder est
    remplacé par une image hébergée : la 1re vue du VRAI site de démo
    Pixel Pros du métier, personnalisée au nom + à la ville du prospect
    (cf. integrations/apercu_site.py).

Le modèle « Cabinets » (avocats/comptables/médecins) est volontairement
LAISSÉ DE CÔTÉ : pas de page de démo qui colle, et son pitch propose un
échange plutôt qu'une démonstration visuelle.

Garde-fous :
  - idempotent : si {{apercu_site}} est déjà présent, on saute.
  - on n'écrit QUE si l'ancre des boutons est trouvée (sinon on refuse).
  - UPDATE ciblé sur body_html + placeholders uniquement — JAMAIS d'upsert
    partiel sur triskell_email_templates (un upsert partiel met des NULL
    partout, leçon du 11/06/2026). .update() ne touche que les colonnes
    fournies → sûr.

Usage :
    python scripts/add_apercu_to_pro_templates.py            (test à blanc)
    python scripts/add_apercu_to_pro_templates.py --apply    (écrit en base)

⚠️ À lancer APRÈS le déploiement du nouveau apercu_site.py (sinon le
placeholder serait remplacé par du vide tant que le serveur n'a pas le
code qui génère l'image).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from supabase import create_client  # noqa: E402

KEYS = ("prosp_pp_pro_commerce", "prosp_pp_pro_artisan")

# Ancre : le paragraphe des 2 boutons (présent à l'identique dans les 2 modèles).
BTN_MARKER = '<p style="margin:24px 0 8px 0;"><a href="{{page_metier}}"'

# Bloc inséré juste avant cette ancre (même style que les autres paragraphes).
APERCU_BLOCK = (
    '<p style="margin:0 0 14px 0;">Pour vous donner une idée concrète, '
    'voici à quoi pourrait ressembler votre site :</p>{{apercu_site}}'
)


def main() -> int:
    apply = "--apply" in sys.argv
    cfg = json.loads((Path.home() / ".triskell-command" / "settings.json")
                     .read_text(encoding="utf-8"))
    sb_cfg = cfg["supabase"]
    sb = create_client(sb_cfg["url"], sb_cfg["service_role_key"])

    rows = (sb.table("triskell_email_templates")
              .select("key, body_html, placeholders")
              .eq("product", "pixel-pros").eq("audience", "pro")
              .in_("key", list(KEYS))
              .execute().data or [])
    by_key = {r["key"]: r for r in rows}

    n_ok = 0
    for key in KEYS:
        r = by_key.get(key)
        if not r:
            print(f"SKIP {key} : introuvable en base")
            continue
        bh = r.get("body_html") or ""

        if "{{apercu_site}}" in bh:
            print(f"SKIP {key} : aperçu déjà présent")
            n_ok += 1
            continue
        if BTN_MARKER not in bh:
            print(f"REFUS {key} : ancre des boutons introuvable — modèle inchangé")
            continue

        new_bh = bh.replace(BTN_MARKER, APERCU_BLOCK + BTN_MARKER, 1)

        # placeholders (métadonnée d'UI) : on ajoute "apercu_site" si absent.
        ph = r.get("placeholders") or []
        if isinstance(ph, str):
            try:
                ph = json.loads(ph)
            except Exception:
                ph = []
        if "apercu_site" not in ph:
            ph = list(ph) + ["apercu_site"]

        if apply:
            (sb.table("triskell_email_templates")
               .update({"body_html": new_bh, "placeholders": ph,
                        "updated_by": "apercu-site-2026-06-14"})
               .eq("product", "pixel-pros").eq("key", key).execute())
            print(f"OK   {key} : aperçu inséré avant les boutons")
        else:
            print(f"PRÊT {key} (test à blanc, rien écrit) — insertion avant les boutons")
        n_ok += 1

    print(f"\n{n_ok}/{len(KEYS)} modèles "
          + ("traités." if apply else "prêts (relancer avec --apply)."))
    return 0 if n_ok == len(KEYS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
