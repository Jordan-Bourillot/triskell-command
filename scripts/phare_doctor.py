"""Le Phare — Doctor : auto-diagnostic de la configuration.

Vérifie en cascade :
  1. Imports Python du module phare
  2. Connexion Supabase + RLS authentifié
  3. Présence et schéma des tables phare_*
  4. Configuration phare_config (tokens GitHub, Netlify, DataForSEO, GSC, PSI)
  5. Mapping des sites (repo_github, netlify_site_id renseignés)
  6. Disponibilité des binaires externes (git, ping HTTP triskell-studio.fr)
  7. Test rapide d'un appel Anthropic si la clé est posée

Sortie :
  - Pour chaque check : ✓ / ✗ / ?
  - Résumé final : « ready_to_run » oui/non + actions concrètes à faire
  - Code retour 0 si tout est vert, 1 sinon

Lancement :
    cd "Triskell Command"
    py -3 scripts/phare_doctor.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

# Force UTF-8 sur stdout/stderr (Windows cp1252 sinon)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# Permet d'importer triskell_core et triskell_command depuis n'importe où
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CORE = ROOT.parent / "Triskell Core"
for p in (str(CORE), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)


GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _ok(label: str, detail: str = "") -> None:
    print(f"  {GREEN}[OK]{RESET} {label}{(' -- ' + DIM + detail + RESET) if detail else ''}")


def _ko(label: str, detail: str = "") -> None:
    print(f"  {RED}[KO]{RESET} {label}{(' -- ' + detail) if detail else ''}")


def _warn(label: str, detail: str = "") -> None:
    print(f"  {YELLOW}[??]{RESET} {label}{(' -- ' + DIM + detail + RESET) if detail else ''}")


def _section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")
    print(DIM + ("-" * len(title)) + RESET)


# ---------------------------------------------------------------------------
def check_imports() -> bool:
    _section("1. Imports du module phare")
    failed = []
    for name in ("voice", "repo", "crawler", "pagespeed", "gsc",
                  "dataforseo", "agents", "git_pipeline", "patcher",
                  "orchestrator", "scheduler"):
        try:
            __import__(f"triskell_command.integrations.phare.{name}")
            _ok(name)
        except Exception as exc:
            _ko(name, str(exc)[:120])
            failed.append(name)
    return not failed


def check_supabase() -> tuple[bool, object]:
    _section("2. Supabase")
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except Exception as exc:
        _ko("import triskell_core.db", str(exc))
        return False, None
    try:
        client = get_client()
    except SupabaseNotConfigured:
        _ko("get_client()", "SUPABASE_URL/KEY non configurés")
        return False, None
    if not client.is_authenticated:
        _ko("authentification", "user non loggé (lancer Triskell Command + Réglages → Connexion)")
        return False, None
    _ok("client Supabase", f"user = {client.user_display_name or 'inconnu'}")
    sb = getattr(client, "client", None) or getattr(client, "_client", None)
    return True, sb


def check_tables(sb) -> bool:
    _section("3. Tables phare_*")
    if sb is None:
        _ko("skip", "Supabase non disponible")
        return False
    tables = ("phare_sites", "phare_audits", "phare_keywords",
              "phare_pages", "phare_actions", "phare_metrics",
              "phare_backlinks", "phare_content_briefs")
    all_ok = True
    for t in tables:
        try:
            sb.table(t).select("id").limit(1).execute()
            _ok(t)
        except Exception as exc:
            _ko(t, str(exc)[:120])
            all_ok = False
    return all_ok


def check_phare_config(sb) -> tuple[bool, dict]:
    _section("4. phare_config (credentials)")
    if sb is None:
        return False, {}
    try:
        rows = (sb.table("shared_settings").select("value")
                .eq("key", "phare_config").limit(1).execute().data)
    except Exception as exc:
        _ko("lecture shared_settings.phare_config", str(exc)[:120])
        return False, {}
    if not rows:
        _ko("entrée phare_config", "manquante (relancer 06_phare.sql)")
        return False, {}
    cfg = rows[0].get("value") or {}
    fields = {
        "github_token":         "PR auto Optimiseur On-Page",
        "netlify_token":        "wait preview deploy",
        "dataforseo_login":     "volumes mots-clés FR",
        "dataforseo_password":  "(complément de DataForSEO)",
        "gsc_credentials_path": "métriques de trafic réel",
        "pagespeed_api_key":    "facultatif (quota anonyme suffit)",
        "anthropic_model_default": "modèle par défaut",
        "anthropic_model_strategy": "modèle Chef d'Orchestre",
    }
    crit_ok = True
    for k, label in fields.items():
        v = cfg.get(k)
        if v:
            _ok(k, label)
        else:
            crit = k in ("github_token", "netlify_token",
                         "dataforseo_login", "dataforseo_password",
                         "gsc_credentials_path")
            if crit:
                _ko(k, label + " — à coller en base")
                crit_ok = False
            else:
                _warn(k, label)
    if cfg.get("gsc_credentials_path"):
        path = Path(cfg["gsc_credentials_path"])
        if not path.exists():
            _ko("gsc_credentials_path", f"fichier introuvable : {path}")
            crit_ok = False
        else:
            _ok("gsc credentials file lisible", str(path))
    return crit_ok, cfg


def check_anthropic_key(sb) -> bool:
    _section("5. Clé Anthropic")
    if sb is None:
        return False
    try:
        rows = (sb.table("shared_settings").select("value")
                .eq("key", "ai_keys").limit(1).execute().data)
    except Exception as exc:
        _ko("lecture shared_settings.ai_keys", str(exc)[:120])
        return False
    if not rows:
        _ko("entrée ai_keys", "manquante")
        return False
    val = rows[0].get("value") or {}
    if val.get("anthropic"):
        _ok("anthropic", "clé présente")
        return True
    _ko("anthropic", "clé absente — Réglages → Clés API")
    return False


def check_sites_mapping(sb) -> bool:
    _section("6. Mapping des sites (repo_github, netlify_site_id)")
    if sb is None:
        return False
    try:
        sites = (sb.table("phare_sites").select("name, domain, repo_github, netlify_site_id, is_active")
                 .eq("is_active", True).execute().data) or []
    except Exception as exc:
        _ko("lecture phare_sites", str(exc)[:120])
        return False
    if not sites:
        _ko("phare_sites", "aucun site actif")
        return False
    full_ok = True
    for s in sites:
        miss = []
        if not s.get("repo_github"):
            miss.append("repo_github")
        if not s.get("netlify_site_id"):
            miss.append("netlify_site_id")
        if miss:
            _warn(s["domain"], f"manquant : {', '.join(miss)}")
            full_ok = False
        else:
            _ok(s["domain"], f"{s['repo_github']} | {s['netlify_site_id'][:8]}…")
    return full_ok


def check_externals() -> bool:
    _section("7. Outils externes")
    ok = True
    if shutil.which("git"):
        try:
            v = subprocess.run(["git", "--version"], capture_output=True,
                                text=True, timeout=3).stdout.strip()
            _ok("git", v)
        except Exception:
            _ok("git", "présent (version inconnue)")
    else:
        _ko("git", "binaire 'git' introuvable dans le PATH")
        ok = False
    try:
        import requests
        r = requests.get("https://triskell-studio.fr", timeout=8,
                          allow_redirects=True)
        if r.status_code < 400:
            _ok("réseau triskell-studio.fr", f"HTTP {r.status_code}")
        else:
            _warn("réseau triskell-studio.fr", f"HTTP {r.status_code}")
    except Exception as exc:
        _warn("réseau triskell-studio.fr", str(exc)[:120])
    return ok


def check_anthropic_call(sb) -> bool:
    _section("8. Test d'appel Anthropic (peut consommer 1c)")
    if sb is None:
        _warn("skip", "Supabase non disponible")
        return False
    try:
        rows = (sb.table("shared_settings").select("value")
                .eq("key", "ai_keys").limit(1).execute().data)
        key = ((rows or [{}])[0].get("value") or {}).get("anthropic", "")
    except Exception:
        key = ""
    if not key:
        _warn("skip", "clé Anthropic absente")
        return False
    try:
        from triskell_core.ai.providers import call_anthropic
        out = call_anthropic('Réponds uniquement par "ok".',
                              "claude-haiku-4-5-20251001", key)
        if "ok" in out.lower():
            _ok("appel Anthropic", "réponse reçue")
            return True
        _warn("appel Anthropic", f"réponse inattendue : {out[:80]}")
        return False
    except Exception as exc:
        _ko("appel Anthropic", str(exc)[:160])
        return False


# ---------------------------------------------------------------------------
def main() -> int:
    print(BOLD + "\nLE PHARE — DOCTOR\n" + RESET +
          DIM + "Auto-diagnostic de la configuration\n" + RESET)

    checks: list[tuple[str, bool]] = []

    checks.append(("Imports", check_imports()))
    sb_ok, sb = check_supabase()
    checks.append(("Supabase", sb_ok))
    checks.append(("Tables phare_*", check_tables(sb)))
    cfg_ok, cfg = check_phare_config(sb)
    checks.append(("phare_config", cfg_ok))
    checks.append(("Clé Anthropic", check_anthropic_key(sb)))
    checks.append(("Mapping sites", check_sites_mapping(sb)))
    checks.append(("Outils externes", check_externals()))
    checks.append(("Anthropic call", check_anthropic_call(sb)))

    _section("Resume")
    total = len(checks)
    ok = sum(1 for _, b in checks if b)
    for name, b in checks:
        symbol = f"{GREEN}[OK]{RESET}" if b else f"{RED}[KO]{RESET}"
        print(f"  {symbol} {name}")

    ready = ok == total
    print()
    if ready:
        print(GREEN + BOLD + f"PRET -- {ok}/{total} checks verts. " +
              "Le Phare est operationnel." + RESET)
        return 0
    print(YELLOW + BOLD + f"PAS PRET -- {ok}/{total} checks verts." + RESET)
    print(DIM + "Corrige les [KO] ci-dessus puis relance ce script." + RESET)
    return 1


if __name__ == "__main__":
    sys.exit(main())
