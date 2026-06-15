# -*- coding: utf-8 -*-
"""Renote les brouillons de prospection EN ATTENTE avec la 2e IA (bascule auto).

Utile après une panne du correcteur qui a laissé de faux « 0/10 ».
N'ENVOIE rien, ne SUPPRIME rien : met juste à jour score/verdict/commentaire.

Usage :
    python -X utf8 scripts/rescore_drafts.py            # TEST (montre, n'écrit pas)
    python -X utf8 scripts/rescore_drafts.py --apply    # écrit les nouvelles notes
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent              # triskell-command
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "triskell-core"))     # triskell-core

APPLY = "--apply" in sys.argv

from triskell_core.db import get_client, SupabaseNotConfigured  # noqa: E402
from triskell_core.prospect.quality_reviewer import review_email  # noqa: E402
from triskell_command.integrations import shared_secrets  # noqa: E402

_ALL = ("anthropic", "openai", "google", "mistral", "xai", "deepseek")


def main() -> int:
    try:
        c = get_client()
    except SupabaseNotConfigured:
        print("Base non configurée."); return 2
    if not getattr(c, "is_authenticated", False):
        try:
            c.restore_session()
        except Exception:
            pass
    if not getattr(c, "is_authenticated", False):
        print("Pas connecté à la base."); return 2

    api_keys = shared_secrets.get_ai_keys(client=c) or {}
    # Complète avec les clés rangées en local (ex DeepSeek, pas encore poussé
    # dans le cloud) pour que la bascule ait le maximum d'IA sous la main.
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
    dispo = [p for p in _ALL if (api_keys.get(p) or "").strip()]
    print(f"IA disponibles pour la relecture : {', '.join(dispo) or 'AUCUNE'}")
    provider, model = "anthropic", "claude-sonnet-4-5"

    sb = c.raw
    res = (sb.table("prospect_drafts")
           .select("id, subject, body, review_score, review_verdict, "
                   "prospects:prospect_id(name, legal_name, city, industry, "
                   "description)")
           .eq("status", "pending").limit(500).execute())
    rows = res.data or []
    print(f"{len(rows)} brouillon(s) en attente.")
    print("MODE : ECRITURE REELLE" if APPLY else "MODE : TEST (rien ecrit)")
    print("-" * 78)

    rescored = down = skipped = problem = 0
    buckets = {"ok": 0, "draft": 0}
    for r in rows:
        subject = (r.get("subject") or "").strip()
        body = (r.get("body") or "").strip()
        pr = r.get("prospects") or {}
        name = pr.get("name") or pr.get("legal_name") or "(sans nom)"
        if not body:
            skipped += 1
            continue
        ctx = (f"Nom: {name}\nVille: {pr.get('city') or '?'}\n"
               f"Secteur: {pr.get('industry') or '?'}\n"
               f"Description: {(pr.get('description') or '')[:200]}")
        old = r.get("review_score")

        def _do_review():
            return review_email(
                subject=subject, body=body, prospect_context=ctx,
                provider=provider, model=model, api_keys=api_keys, audience="")

        try:
            review = _do_review()
            # Réponse IA illisible (JSON cassé, vide…) → 1 nouvelle tentative
            # (souvent une autre IA via la bascule au 2e essai).
            if (not review.get("engine_down")
                    and str(review.get("comment") or "").startswith("reviewer ")):
                review = _do_review()
        except Exception as e:
            print(f"  ! {name[:32]:32} : erreur relecture ({e})")
            skipped += 1
            continue
        if review.get("engine_down"):
            down += 1
            print(f"  ~ {name[:32]:32} : AUCUNE IA dispo (laisse tel quel)")
            continue
        if str(review.get("comment") or "").startswith("reviewer "):
            # L'IA a répondu mais illisible 2x : on NE remplace PAS (jamais un
            # faux 0 — on garde la note actuelle du brouillon).
            problem += 1
            print(f"  ? {name[:32]:32} : reponse IA illisible, laisse tel quel")
            continue
        sc = int(review.get("score") or 0)
        vd = str(review.get("verdict") or "")
        cm = str(review.get("comment") or "")[:80]
        oldlabel = "--" if old is None else f"{old}/10"
        print(f"  - {name[:32]:32} : {oldlabel:>5} -> {sc}/10 [{vd}]  {cm}")
        buckets[vd] = buckets.get(vd, 0) + 1
        if APPLY:
            try:
                sb.table("prospect_drafts").update({
                    "review_score": sc,
                    "review_verdict": vd,
                    "review_comment": str(review.get("comment") or "")[:300],
                }).eq("id", r.get("id")).execute()
                rescored += 1
            except Exception as e:
                print(f"      ! ecriture KO : {e}")
                skipped += 1
        else:
            rescored += 1

    print("-" * 78)
    verb = "renotes" if APPLY else "a renoter"
    print(f"Bilan : {rescored} {verb}, {down} sans IA dispo, "
          f"{problem} illisibles (laisses tels quels), {skipped} ignores.")
    print(f"Repartition : {buckets.get('ok', 0)} bons (>=7, 'ok'), "
          f"{buckets.get('draft', 0)} a relire (<7, 'draft').")
    if not APPLY:
        print("\n(TEST : rien n'a ete ecrit. Relance avec --apply pour appliquer.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
