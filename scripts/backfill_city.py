# -*- coding: utf-8 -*-
"""Rétro-remplit la VILLE (et le code postal) des fiches qui ont une adresse
mais pas de ville — séquelle des fiches Google Maps versées sans ville isolée.

Lecture seule par défaut ; n'écrit que les champs city / postal_code (jamais
les emails, donc aucun déclenchement des verrous SQL).

Usage :
    python -X utf8 scripts/backfill_city.py            # TEST (montre, n'écrit pas)
    python -X utf8 scripts/backfill_city.py --apply     # écrit ville + code postal
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "triskell-core"))

from triskell_core.db import get_client  # noqa: E402
from triskell_core.prospect.core.prospect import split_fr_address  # noqa: E402

APPLY = "--apply" in sys.argv


def main() -> int:
    c = get_client()
    if not getattr(c, "is_authenticated", False):
        try:
            c.restore_session()
        except Exception:
            pass
    if not getattr(c, "is_authenticated", False):
        print("Pas connecté à la base."); return 2
    sb = c.raw

    todo = []          # (id, name, address, cp, city, old_cp)
    no_city_no_addr = 0
    page, size = 0, 1000
    while True:
        res = (sb.table("prospects")
               .select("id,name,address,city,postal_code")
               .range(page * size, (page + 1) * size - 1).execute())
        rows = res.data or []
        if not rows:
            break
        for r in rows:
            addr = (r.get("address") or "").strip()
            city = (r.get("city") or "").strip()
            if city:
                continue
            if not addr:
                no_city_no_addr += 1
                continue
            cp, ci = split_fr_address(addr)
            if ci:
                todo.append((r.get("id"), r.get("name") or "", addr, cp, ci,
                             (r.get("postal_code") or "").strip()))
        if len(rows) < size:
            break
        page += 1

    print(f"{len(todo)} fiche(s) avec adresse mais SANS ville -> ville deduite")
    print(f"{no_city_no_addr} fiche(s) sans ville ET sans adresse "
          f"(rien a deduire, on n'y touche pas)")
    print("MODE : ECRITURE REELLE" if APPLY else "MODE : TEST (rien ecrit)")
    print("-" * 76)
    for (_id, name, addr, cp, ci, old_cp) in todo[:20]:
        print(f"  {name[:30]:30} | {addr[:38]:38} -> {ci}  ({cp})")
    if len(todo) > 20:
        print(f"  ... et {len(todo) - 20} autre(s)")
    print("-" * 76)

    if APPLY:
        done = 0
        for (_id, name, addr, cp, ci, old_cp) in todo:
            upd = {"city": ci}
            if cp and not old_cp:
                upd["postal_code"] = cp
            try:
                sb.table("prospects").update(upd).eq("id", _id).execute()
                done += 1
            except Exception as e:
                print(f"  ! {name[:30]} : ecriture KO ({e})")
        print(f"OK : {done}/{len(todo)} fiche(s) completee(s).")
    else:
        print(f"(TEST : rien ecrit. {len(todo)} fiche(s) seraient completees. "
              f"Relance avec --apply.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
