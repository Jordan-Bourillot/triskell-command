"""Vérifie que la config Supabase fonctionne (URL + clé + auth + tables).

Usage :
    python scripts/verify_supabase.py

Le script :
1. Lit l'URL + anon_key depuis ~/.triskell-command/settings.json
   (section "supabase") OU les variables d'environnement.
2. Teste qu'on peut se connecter au projet (anon).
3. Liste les 9 tables attendues — signale si une manque.
4. Compte les users (doit être 2 : Jordan + Thomas).
5. Affiche les UUIDs des 2 users.

À lancer après avoir suivi les étapes 1-5 du supabase/README.md.
"""

from __future__ import annotations

import sys
from pathlib import Path


EXPECTED_TABLES = [
    "users", "shared_settings", "prospects", "email_history",
    "prospect_drafts", "templates", "convoy_campaigns", "convoy_drafts",
    "send_log",
]


def main() -> int:
    here = Path(__file__).resolve().parent.parent
    core_root = here.parent / "Triskell Core"
    if core_root.exists() and str(core_root) not in sys.path:
        sys.path.insert(0, str(core_root))
    sys.path.insert(0, str(here))

    print("=== Vérification Supabase ===\n")

    # 1. Config
    try:
        from triskell_core.db.client import SupabaseConfig, SupabaseNotConfigured
    except ImportError as exc:
        print(f"✗ Imports cassés : {exc}")
        return 1

    try:
        cfg = SupabaseConfig.resolve()
    except SupabaseNotConfigured as exc:
        print(f"✗ {exc}")
        print("\n→ Lance Triskell Command et utilise le dialogue de login pour")
        print("  saisir l'URL et la clé, OU édite ~/.triskell-command/settings.json :")
        print('  {"supabase": {"url": "https://xxx.supabase.co", "anon_key": "..."}}')
        return 1

    print(f"✓ Config trouvée : {cfg.url}")

    # 2. Connexion (sans login, juste vérifier que l'URL répond)
    try:
        from supabase import create_client
        client = create_client(cfg.url, cfg.anon_key)
    except Exception as exc:
        print(f"✗ Connexion échouée : {exc}")
        return 1
    print("✓ Client Supabase créé")

    # 3. Liste les tables (en passant par les RLS — sans login on doit voir vide
    #    mais pas avoir d'erreur "table not found")
    print("\nVérification des tables :")
    missing: list[str] = []
    for table in EXPECTED_TABLES:
        try:
            res = client.table(table).select("*").limit(0).execute()
            print(f"  ✓ {table}")
        except Exception as exc:
            err = str(exc)
            if "not found" in err.lower() or "does not exist" in err.lower():
                missing.append(table)
                print(f"  ✗ {table} : {err[:80]}")
            else:
                # RLS deny est normal sans login → table existe quand même
                if "policy" in err.lower() or "permission" in err.lower():
                    print(f"  ✓ {table} (RLS active)")
                else:
                    print(f"  ? {table} : {err[:80]}")

    if missing:
        print(f"\n✗ Tables manquantes : {missing}")
        print("→ Tu n'as pas encore lancé 01_schema.sql. Va dans le SQL Editor")
        print("  de Supabase et exécute les fichiers du dossier supabase/.")
        return 1

    # 4. Tente de lire les users (sans login)
    print("\nTentative de lecture de la table 'users' (sans login)…")
    try:
        res = client.table("users").select("user_id, display_name").execute()
        users = res.data or []
        if not users:
            print("  → 0 user visible (RLS bloque sans login). C'est normal.")
            print("  → Continue : lance Triskell Command pour faire le 1er login.")
        else:
            print(f"  → {len(users)} user(s) visible(s) :")
            for u in users:
                print(f"     {u.get('display_name')} ({u.get('user_id')[:8]}...)")
    except Exception as exc:
        print(f"  → Lecture refusée : {exc} (RLS active, attendu)")

    print("\n=== Vérification OK ===")
    print("Prochaines étapes :")
    print("  1. Lance `python run.py`")
    print("  2. Au login : email + mot de passe Supabase")
    print("  3. Si ça passe : `python scripts/migrate_to_supabase.py --dry-run`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
