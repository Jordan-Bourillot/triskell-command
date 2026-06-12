"""Relie les sites Le Phare à leur code (repo GitHub) et à Netlify.

Pourquoi : sans `repo_github`, les robots ne peuvent que CONSEILLER —
impossible de préparer/publier une modification. Constat du 12/06/2026 :
les 7 sites surveillés avaient tous repo_github vide → toutes les
propositions étaient « à faire à la main ».

Usage :
    py -3 scripts/phare_fill_repos.py            # essai à blanc (rien n'est écrit)
    py -3 scripts/phare_fill_repos.py --apply    # écrit pour de vrai

Règles :
    - ne remplit QUE les champs vides (jamais d'écrasement) ;
    - netlify_site_id retrouvé via l'API Netlify (token de phare_config)
      en cherchant le site dont le domaine correspond ;
    - un site sans dépôt connu (ingrid-services.fr) est listé, pas touché.

Connexion : session locale Triskell OU variables d'env SUPABASE_URL +
SUPABASE_SERVICE_ROLE_KEY (même mécanique que les autres scripts phare).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Vérité terrain du 12/06/2026 (remotes des dossiers locaux + gh repo list) :
#   - triskell-studio.fr  → triskell-site-officiel (le dossier "triskell-studio"
#     est une archive de maquettes, PAS le site en ligne)
#   - pixel-pros.fr       → pixel-studio (la vitrine, déploiement Netlify au push)
#   - ingrid-services.fr  → aucun dépôt GitHub trouvé
REPO_BY_DOMAIN: dict[str, str] = {
    "triskell-studio.fr": "Jordan-Bourillot/triskell-site-officiel",
    "lagriffe-studio.fr": "Jordan-Bourillot/lagriffe-studio",
    "studio-wow.fr": "Jordan-Bourillot/studio-wow",
    "eliks-studio.fr": "Jordan-Bourillot/eliks-studio",
    "rankus-studio.fr": "Jordan-Bourillot/rankus-studio",
    "pixel-pros.fr": "Jordan-Bourillot/pixel-studio",
}


def _netlify_sites(token: str) -> list[dict]:
    if not token:
        return []
    import requests
    out: list[dict] = []
    page = 1
    while page <= 5:
        try:
            r = requests.get("https://api.netlify.com/api/v1/sites",
                             headers={"Authorization": f"Bearer {token}"},
                             params={"per_page": 100, "page": page}, timeout=20)
        except requests.RequestException as exc:
            print(f"  ⚠️  API Netlify injoignable : {exc}")
            return out
        if r.status_code >= 400:
            print(f"  ⚠️  API Netlify HTTP {r.status_code}")
            return out
        batch = r.json() or []
        out.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return out


def _netlify_id_for_domain(sites: list[dict], domain: str) -> str:
    domain = domain.lower()
    for s in sites:
        custom = (s.get("custom_domain") or "").lower()
        aliases = [a.lower() for a in (s.get("domain_aliases") or [])]
        if domain == custom or f"www.{domain}" == custom or domain in aliases:
            return s.get("site_id") or s.get("id") or ""
    return ""


def main() -> int:
    apply = "--apply" in sys.argv

    from triskell_command.integrations.phare import repo
    sb = repo._sb()
    if sb is None:
        print("❌ Connexion à la base impossible (session locale ou env vars).")
        return 1

    cfg = repo.get_config() or {}
    netlify_token = cfg.get("netlify_token") or ""
    nl_sites = _netlify_sites(netlify_token)
    if nl_sites:
        print(f"Netlify : {len(nl_sites)} sites lus via l'API.")
    else:
        print("Netlify : aucun site lu (token absent ou API muette) — "
              "on ne remplira que les dépôts GitHub.")

    sites = repo.list_sites(active_only=False)
    print(f"{len(sites)} sites Le Phare en base.\n")

    changed = 0
    for s in sites:
        domain = (s.get("domain") or "").lower()
        name = s.get("name") or domain
        patch: dict = {}

        cur_repo = (s.get("repo_github") or "").strip()
        want_repo = REPO_BY_DOMAIN.get(domain, "")
        if cur_repo:
            repo_line = f"déjà relié à {cur_repo}"
        elif want_repo:
            patch["repo_github"] = want_repo
            repo_line = f"→ {want_repo}"
        else:
            repo_line = "⚠️ aucun dépôt GitHub connu (restera en conseils manuels)"

        cur_nl = (s.get("netlify_site_id") or "").strip()
        if cur_nl:
            nl_line = "Netlify déjà relié"
        else:
            nl_id = _netlify_id_for_domain(nl_sites, domain)
            if nl_id:
                patch["netlify_site_id"] = nl_id
                nl_line = f"Netlify → {nl_id}"
            else:
                nl_line = "Netlify : pas trouvé (les publications se feront sans aperçu)"

        print(f"• {name} ({domain})")
        print(f"    code   : {repo_line}")
        print(f"    aperçu : {nl_line}")

        if patch and apply:
            try:
                sb.table("phare_sites").update(patch).eq("id", s["id"]).execute()
                print("    ✅ écrit")
                changed += 1
            except Exception as exc:
                print(f"    ❌ écriture impossible : {exc}")
        elif patch:
            print("    (essai à blanc — rien n'est écrit)")
            changed += 1
        print()

    mode = "écrits" if apply else "à écrire (relance avec --apply)"
    print(f"Bilan : {changed} site(s) {mode}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
