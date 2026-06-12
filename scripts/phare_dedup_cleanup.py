"""Nettoie le stock de propositions Le Phare : doublons + périssables.

Constat du 12/06/2026 : 263 propositions ouvertes, dont beaucoup de cartes
en double (le même conseil réinséré à chaque audit) et des piles de
bulletins quotidiens / plans du mois périmés. Depuis ce jour, l'insertion
dédoublonne (integrations/phare/dedup.py) — ce script remet le STOCK au
propre avec les mêmes règles.

Usage :
    py -3 scripts/phare_dedup_cleanup.py            # essai à blanc
    py -3 scripts/phare_dedup_cleanup.py --apply    # nettoie pour de vrai

Ce qui est fait, site par site :
    1. bulletins (agent analyste) : on garde LE plus récent, les anciens
       passent en « expired » (un bulletin d'il y a 5 jours n'est plus une
       info, c'est du bruit) ;
    2. plans du mois (chef d'orchestre) : pareil, le plus récent gagne ;
    3. le reste : grappes de doublons (integrations/phare/dedup.py) — la
       carte la plus récente est gardée, ses jumelles passent en « expired »
       avec la mention « Doublon — fusionné avec … ».

Rien n'est supprimé : tout passe en statut « expired » (réversible à la
main en base si besoin). Les cartes déjà validées/refusées ne sont jamais
touchées.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    apply = "--apply" in sys.argv

    from triskell_command.integrations.phare import dedup, repo
    sb = repo._sb()
    if sb is None:
        print("❌ Connexion à la base impossible (session locale ou env vars).")
        return 1

    sites = repo.list_sites(active_only=False)
    total_expired = 0
    total_kept = 0

    for s in sites:
        sid = s["id"]
        name = s.get("name") or s.get("domain") or sid
        try:
            rows = (sb.table("phare_actions").select("*")
                    .eq("site_id", sid)
                    .in_("status", list(dedup.OPEN_STATUSES))
                    .order("created_at", desc=True)
                    .limit(500).execute().data) or []
        except Exception as exc:
            print(f"• {name} : lecture impossible ({exc})")
            continue
        if not rows:
            continue

        to_expire: list[tuple[dict, str]] = []   # (action, raison)
        rest: list[dict] = []

        # 1 & 2 — périssables : bulletins et plans du mois (le + récent gagne)
        for prefix, agent, label in (("Bulletin", "analyste", "bulletin"),
                                     ("Plan du mois", "chef_orchestre", "plan du mois")):
            family = [a for a in rows
                      if (a.get("agent") or "") == agent
                      and (a.get("title") or "").startswith(prefix)]
            family.sort(key=lambda a: str(a.get("created_at") or ""), reverse=True)
            for old in family[1:]:
                to_expire.append((old, f"Remplacé par le {label} le plus récent"))

        expire_ids = {a["id"] for a, _ in to_expire}
        rest = [a for a in rows if a["id"] not in expire_ids]

        # 3 — grappes de doublons sur le reste
        for group in dedup.group_duplicates(rest):
            kept = group[0]
            total_kept += 1
            for twin in group[1:]:
                to_expire.append(
                    (twin, f"Doublon — fusionné avec « {(kept.get('title') or '')[:70]} »"))

        if not to_expire:
            print(f"• {name} : {len(rows)} cartes, rien à nettoyer.")
            continue

        print(f"• {name} : {len(rows)} cartes ouvertes → "
              f"{len(to_expire)} en double/périmées, "
              f"{len(rows) - len(to_expire)} gardées")
        for a, reason in to_expire:
            print(f"    - [{(a.get('agent') or '?')}] "
                  f"{(a.get('title') or '?')[:80]}  ({reason})")
            if apply:
                try:
                    sb.table("phare_actions").update({
                        "status": "expired",
                        "rejected_reason": reason,
                    }).eq("id", a["id"]).execute()
                except Exception as exc:
                    print(f"      ❌ écriture impossible : {exc}")
                    continue
            total_expired += 1
        print()

    mode = "nettoyées" if apply else "à nettoyer (relance avec --apply)"
    print(f"\nBilan : {total_expired} carte(s) {mode}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
