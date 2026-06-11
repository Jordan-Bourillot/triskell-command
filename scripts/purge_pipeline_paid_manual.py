"""Purge les lignes wow/rankus stage=paid mode=manual residuelles de
triskell_pipeline_settings (finitions post-refonte UX, point 12 du chantier).

Pourquoi : wow et rankus n'ont PAS de bouton « Lancer finalisation »
(endpoint *_finalize_now inexistant). Une demande payee en mode manual
resterait donc coincee a vie. L'UI s'auto-repare a la visite ; ce script
est la ceinture cote base.

Modes :
  --scan       (defaut) liste les lignes concernees, ne touche a rien.
  --apply      supprime les lignes listees.

Usage :
  python scripts/purge_pipeline_paid_manual.py
  python scripts/purge_pipeline_paid_manual.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))


def get_service_client():
    """Client Supabase service_role (meme lecture que dedupe_prospects)."""
    import os
    url = os.environ.get("SUPABASE_URL") or ""
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
           or os.environ.get("SUPABASE_SERVICE_KEY") or "")
    if not (url and key):
        settings_path = Path.home() / ".triskell-command" / "settings.json"
        if not settings_path.exists():
            return None, "settings.json introuvable"
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return None, f"settings.json illisible : {exc}"
        sb = data.get("supabase") or {}
        url = sb.get("url") or ""
        key = sb.get("service_role_key") or sb.get("service_key") or ""
    if not url or not key:
        return None, "service_role_key absente (env + settings.json)"
    try:
        from supabase import create_client
    except ImportError:
        return None, "module 'supabase' manquant : pip install supabase"
    try:
        return create_client(url, key), None
    except Exception as exc:
        return None, f"creation client echec : {exc}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="supprime les lignes (defaut : scan seul)")
    args = parser.parse_args()

    sb, err = get_service_client()
    if sb is None:
        print(f"ERREUR : {err}")
        return 1

    rows = (sb.table("triskell_pipeline_settings")
              .select("product, stage, mode, updated_at, updated_by")
              .in_("product", ["wow", "rankus"])
              .eq("stage", "paid")
              .eq("mode", "manual")
              .execute().data or [])

    if not rows:
        print("OK : aucune ligne wow/rankus stage=paid mode=manual en base. "
              "Rien a purger.")
        return 0

    print(f"{len(rows)} ligne(s) residuelle(s) :")
    for r in rows:
        print(f"  - {r.get('product')} / {r.get('stage')} / {r.get('mode')}"
              f"  (modifie {r.get('updated_at') or '?'}"
              f" par {r.get('updated_by') or '?'})")

    if not args.apply:
        print("\nScan seul — relance avec --apply pour supprimer.")
        return 0

    for r in rows:
        (sb.table("triskell_pipeline_settings")
           .delete()
           .eq("product", r["product"])
           .eq("stage", "paid")
           .eq("mode", "manual")
           .execute())
    print(f"\nPurge faite : {len(rows)} ligne(s) supprimee(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
