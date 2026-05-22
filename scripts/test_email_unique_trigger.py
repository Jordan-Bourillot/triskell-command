"""Test rapide du trigger anti-doublon email (migration 39).

Cree un prospect temporaire, tente d'en creer un 2e avec le meme email,
verifie que le 2e est rejete par le trigger, puis nettoie.

Usage :
  python scripts/test_email_unique_trigger.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def get_service_client():
    settings_path = Path.home() / ".triskell-command" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    sb_cfg = data.get("supabase") or {}
    url = sb_cfg["url"]
    key = sb_cfg.get("service_role_key") or sb_cfg["service_key"]
    from supabase import create_client
    return create_client(url, key)


def main() -> int:
    sb = get_service_client()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    test_email = f"test-trigger-{stamp}@triskell-test.invalid"
    print(f"[INFO] Email de test : {test_email}\n")

    # Recupere un workspace_id existant pour respecter la contrainte NOT NULL
    ws_res = sb.table("prospects").select("workspace_id").limit(1).execute()
    workspace_id = (ws_res.data or [{}])[0].get("workspace_id")
    if not workspace_id:
        print("[ECHEC] Impossible de recuperer un workspace_id.")
        return 1
    base_row = {"status": "new", "workspace_id": workspace_id}

    # 1. Insert initial : doit reussir
    print("-> 1. Insert d'un prospect TEST A avec cet email...")
    r1 = (sb.table("prospects")
          .insert({**base_row,
                   "emails": [test_email],
                   "name": f"TEST TRIGGER A {stamp}"})
          .execute())
    if not r1.data:
        print("[ECHEC] L'insert initial n'a pas reussi.")
        return 1
    id1 = r1.data[0]["id"]
    print(f"   [OK] cree id={id1}\n")

    # 2. Insert doublon : doit echouer (trigger leve une exception 23505)
    print("-> 2. Tentative d'insert d'un prospect TEST B avec le MEME email...")
    blocked = False
    err_msg = ""
    id2 = None
    try:
        r2 = (sb.table("prospects")
              .insert({**base_row,
                       "emails": [test_email],
                       "name": f"TEST TRIGGER B {stamp}"})
              .execute())
        if r2.data:
            id2 = r2.data[0]["id"]
    except Exception as exc:
        blocked = True
        err_msg = str(exc)

    if blocked:
        print(f"   [OK] Bloque par le trigger.")
        # Affiche un extrait du message
        for line in err_msg.split("\n")[:3]:
            print(f"       {line[:150]}")
    else:
        print("   [ECHEC] L'insert du doublon est PASSE — le trigger ne bloque pas !")

    # 3. Cleanup
    print("\n-> 3. Cleanup des prospects de test...")
    sb.table("prospects").delete().eq("id", id1).execute()
    print(f"   [OK] supprime id={id1}")
    if id2:
        sb.table("prospects").delete().eq("id", id2).execute()
        print(f"   [OK] supprime id={id2}")

    print()
    if blocked:
        print("====================================================")
        print("  RESULTAT : Trigger anti-doublon FONCTIONNEL.")
        print("====================================================")
        return 0
    else:
        print("====================================================")
        print("  RESULTAT : Trigger NE BLOQUE PAS. Migration a refaire.")
        print("====================================================")
        return 1


if __name__ == "__main__":
    sys.exit(main())
