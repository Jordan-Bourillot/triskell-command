"""Contrôle de cohérence des liaisons site ↔ dépôt GitHub du Phare.

Pour chaque site Le Phare relié (repo_github + netlify_site_id), on demande
à l'API Netlify quel dépôt GitHub construit RÉELLEMENT ce site, et on
compare. Un croisement de fils ici = le robot publierait des modifications
SEO sur le MAUVAIS site → contrôle obligatoire avant d'activer le bouton
« OK, fais-le ».

Lecture seule : ce script n'écrit RIEN.

    py -3 scripts/phare_check_repo_links.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    import requests
    from triskell_command.integrations.phare import repo

    sb = repo._sb()
    if sb is None:
        print("❌ Connexion à la base impossible.")
        return 1
    token = (repo.get_config() or {}).get("netlify_token") or ""
    if not token:
        print("❌ Pas de jeton Netlify en config — contrôle impossible.")
        return 1

    sites = repo.list_sites(active_only=False)
    mismatches = 0
    checked = 0
    for s in sites:
        domain = (s.get("domain") or "").lower()
        repo_db = (s.get("repo_github") or "").strip()
        nl_id = (s.get("netlify_site_id") or "").strip()
        if not repo_db or not nl_id:
            continue
        try:
            r = requests.get(f"https://api.netlify.com/api/v1/sites/{nl_id}",
                             headers={"Authorization": f"Bearer {token}"},
                             timeout=20)
        except requests.RequestException as exc:
            print(f"• {domain} : API Netlify injoignable ({exc})")
            continue
        if r.status_code >= 400:
            print(f"• {domain} : Netlify HTTP {r.status_code} (site id {nl_id})")
            mismatches += 1
            continue
        data = r.json() or {}
        nl_domain = (data.get("custom_domain") or "").lower().removeprefix("www.")
        nl_repo = ((data.get("build_settings") or {}).get("repo_url")
                   or "").removeprefix("https://github.com/")
        checked += 1
        problems = []
        if nl_domain and nl_domain != domain and domain not in [
                a.lower() for a in (data.get("domain_aliases") or [])]:
            problems.append(f"le site Netlify sert « {nl_domain} », pas « {domain} »")
        if nl_repo and nl_repo.lower() != repo_db.lower():
            problems.append(f"Netlify construit « {nl_repo} », la base dit « {repo_db} »")
        if problems:
            mismatches += 1
            print(f"❌ {s.get('name')} ({domain})")
            for p in problems:
                print(f"     {p}")
        else:
            print(f"✅ {s.get('name')} ({domain}) — {repo_db}"
                  + (f" (Netlify ne déclare pas de dépôt)" if not nl_repo else ""))

    print(f"\nBilan : {checked} liaisons contrôlées, {mismatches} incohérence(s).")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
