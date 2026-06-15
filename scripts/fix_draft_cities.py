# -*- coding: utf-8 -*-
"""Comble le trou de ville dans les brouillons déjà rédigés (« … à , … » /
« … à — … » laissés quand la fiche n'avait pas de ville), puis RENOTE le mail
corrigé avec la 2e IA (bascule auto). N'ENVOIE rien, ne SUPPRIME rien.

On ne touche qu'aux brouillons dont la fiche a MAINTENANT une ville et dont le
texte contient une de ces anomalies (français correct n'écrit jamais « à , »
ni « à — »), donc le remplacement est sûr.

Usage :
    python -X utf8 scripts/fix_draft_cities.py            # TEST (montre, n'écrit pas)
    python -X utf8 scripts/fix_draft_cities.py --apply     # corrige + renote
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "triskell-core"))

from triskell_core.db import get_client  # noqa: E402
from triskell_core.prospect.quality_reviewer import review_email  # noqa: E402
from triskell_command.integrations import shared_secrets  # noqa: E402

APPLY = "--apply" in sys.argv
_ALL = ("anthropic", "openai", "google", "mistral", "xai", "deepseek")


def comble_trou(text: str, city: str) -> tuple[str, bool]:
    """Insère la ville là où le gabarit l'avait laissée vide."""
    if not text or not city:
        return text, False
    out = re.sub(r"à\s+,", f"à {city},", text)        # "… à , est-ce"
    out = re.sub(r"à\s+—", f"à {city} —", out)         # "… à — parfois"
    return out, (out != text)


def main() -> int:
    c = get_client()
    if not getattr(c, "is_authenticated", False):
        try:
            c.restore_session()
        except Exception:
            pass
    if not getattr(c, "is_authenticated", False):
        print("Pas connecté à la base."); return 2

    api_keys = shared_secrets.get_ai_keys(client=c) or {}
    import json as _json
    _sp = Path.home() / ".triskell-command" / "settings.json"
    if _sp.exists():
        try:
            _local = ((_json.loads(_sp.read_text(encoding="utf-8")).get("ai")
                       or {}).get("api_keys") or {})
            for p in _ALL:
                if not (api_keys.get(p) or "").strip() and (_local.get(p) or "").strip():
                    api_keys[p] = _local[p]
        except Exception:
            pass

    sb = c.raw
    rows = (sb.table("prospect_drafts")
            .select("id, subject, body, body_html, review_score, "
                    "prospects:prospect_id(name, city)")
            .eq("status", "pending").limit(500).execute().data or [])

    print("MODE : ECRITURE REELLE" if APPLY else "MODE : TEST (rien ecrit)")
    print("-" * 76)
    fixed = written = down = 0
    for r in rows:
        pr = r.get("prospects") or {}
        city = (pr.get("city") or "").strip()
        if not city:
            continue
        subj, s1 = comble_trou(r.get("subject") or "", city)
        body, s2 = comble_trou(r.get("body") or "", city)
        html, s3 = comble_trou(r.get("body_html") or "", city)
        if not (s1 or s2 or s3):
            continue
        fixed += 1
        name = pr.get("name") or "?"
        ctx = f"Nom: {name}\nVille: {city}\nSecteur: ?\nDescription: "
        review = review_email(subject=subj, body=body, prospect_context=ctx,
                              provider="anthropic", model="claude-sonnet-4-5",
                              api_keys=api_keys, audience="")
        if review.get("engine_down") or str(review.get("comment") or "").startswith("reviewer "):
            down += 1
            print(f"  ~ {name[:34]:34} | trou comble ({city}) | note IA indispo")
            note_new = "?"
        else:
            note_new = f"{int(review.get('score') or 0)}/10 [{review.get('verdict')}]"
        old = r.get("review_score")
        print(f"  - {name[:34]:34} | ville={city:16} | {('--' if old is None else str(old)+'/10'):>6} -> {note_new}")
        if APPLY:
            upd = {"subject": subj, "body": body}
            if s3:
                upd["body_html"] = html
            if not review.get("engine_down") and not str(review.get("comment") or "").startswith("reviewer "):
                upd["review_score"] = int(review.get("score") or 0)
                upd["review_verdict"] = str(review.get("verdict") or "")
                upd["review_comment"] = str(review.get("comment") or "")[:300]
            try:
                sb.table("prospect_drafts").update(upd).eq("id", r.get("id")).execute()
                written += 1
            except Exception as e:
                print(f"      ! ecriture KO : {e}")

    print("-" * 76)
    if APPLY:
        print(f"{written} brouillon(s) corrige(s) + renote(s), {down} sans IA dispo.")
    else:
        print(f"{fixed} brouillon(s) avec trou de ville a corriger. "
              f"(TEST : rien ecrit. --apply pour appliquer.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
