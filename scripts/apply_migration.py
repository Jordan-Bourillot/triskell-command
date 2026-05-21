"""Applique un fichier SQL sur la base Supabase Triskell.

Usage :
    python scripts/apply_migration.py supabase/34_email_templates_audience.sql
    python scripts/apply_migration.py supabase/34b_seed_prospection_pros.sql

Variables :
- Argument 1 : chemin du fichier .sql à exécuter.
- Option `--dry-run` : affiche les statements sans les exécuter.

Comment ça trouve la base :
1. Variable d'environnement `SUPABASE_DB_URL` (priorité).
2. Champ `supabase_db_url` dans `~/.triskell-command/settings.json`.
3. À défaut : message d'aide pour récupérer la chaîne dans le dashboard
   Supabase (Settings → Database → Connection string → URI).

La connection string ressemble à :
    postgresql://postgres.<ref>:<password>@<region>.pooler.supabase.com:5432/postgres

⚠ Cette chaîne contient le mot de passe DB en clair. Si tu la stockes dans
   settings.json, vérifie que le fichier reste local (~/.triskell-command/
   n'est pas commit par Git).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


SETTINGS_PATH = Path.home() / ".triskell-command" / "settings.json"


def _read_db_url() -> str:
    """Cherche la connection string Postgres dans env > settings.json."""
    env = os.environ.get("SUPABASE_DB_URL", "").strip()
    if env:
        return env
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            url = (data.get("supabase_db_url") or "").strip()
            if url:
                return url
        except Exception:
            pass
    return ""


def _print_setup_help() -> None:
    print("""
✗ Aucune connection string Postgres trouvée.

Pour la configurer une fois pour toutes :

1. Dans ton dashboard Supabase : https://supabase.com/dashboard
   → ton projet → Settings → Database → Connection string → URI
   Copie la ligne « postgresql://postgres.xxxx:<MOT_DE_PASSE>@xxx.pooler.supabase.com:5432/postgres »
   (remplace <MOT_DE_PASSE> par le password DB que tu as noté à la création
    du projet — Settings → Database → Database password si tu l'as perdu).

2. Stocke-la, au choix :
   a) Dans %USERPROFILE%\\.triskell-command\\settings.json, ajoute :
        "supabase_db_url": "postgresql://postgres...."
   b) Ou en variable d'env (PowerShell) :
        $env:SUPABASE_DB_URL = "postgresql://postgres...."

3. Relance ce script.

⚠ Ce fichier reste local. Ne le commit jamais.
""".rstrip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Applique un .sql sur Supabase")
    parser.add_argument("sql_file", help="Chemin du fichier SQL")
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche le contenu sans l'exécuter")
    args = parser.parse_args()

    sql_path = Path(args.sql_file)
    if not sql_path.exists():
        print(f"✗ Fichier introuvable : {sql_path}")
        return 2

    sql = sql_path.read_text(encoding="utf-8")
    if not sql.strip():
        print(f"✗ Fichier vide : {sql_path}")
        return 2

    print(f"→ Migration : {sql_path.name} ({len(sql)} caractères, "
          f"{sql.count(chr(10)) + 1} lignes)")

    if args.dry_run:
        print("\n--- DRY RUN — contenu du fichier ---")
        print(sql)
        print("--- (rien n'a été exécuté) ---")
        return 0

    db_url = _read_db_url()
    if not db_url:
        _print_setup_help()
        return 3

    try:
        import psycopg2
    except ImportError:
        print("✗ psycopg2 non installé. Lance : pip install psycopg2-binary")
        return 4

    print("→ Connexion Supabase…")
    try:
        conn = psycopg2.connect(db_url, connect_timeout=15)
    except Exception as exc:
        print(f"✗ Connexion échouée : {exc}")
        print("  Vérifie la chaîne (mot de passe, région, port 5432 ou 6543).")
        return 5

    print("→ Exécution du SQL…")
    conn.autocommit = False
    cur = conn.cursor()
    try:
        cur.execute(sql)
        # Récupère le statut final (rowcount sur le dernier statement)
        rc = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"✗ SQL échoué (rollback effectué) : {exc}")
        cur.close()
        conn.close()
        return 6

    cur.close()
    conn.close()
    print(f"✓ Migration appliquée. ({rc} ligne(s) impactée(s) "
          f"sur le dernier statement — peut être 0 sur des DDL.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
