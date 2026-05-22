"""Test rapide du trigger anti-collision client (migration 40).

Cree un client temporaire avec un email unique, tente de creer un prospect
avec ce meme email, verifie que c'est bloque par le trigger, puis nettoie.

Usage :
  python scripts/test_client_collision_trigger.py
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
    test_email = f"test-client-collision-{stamp}@triskell-test.invalid"
    print(f"[INFO] Email de test : {test_email}\n")

    # Recupere un workspace_id existant
    ws_res = sb.table("prospects").select("workspace_id").limit(1).execute()
    workspace_id = (ws_res.data or [{}])[0].get("workspace_id")
    if not workspace_id:
        print("[ECHEC] Impossible de recuperer un workspace_id.")
        return 1

    # 1. Cree un client de test
    print("-> 1. Insert d'un CLIENT de test avec cet email...")
    client_id = None
    try:
        rc = (sb.table("clients")
              .insert({
                  "email": test_email,
                  "first_name": "Test",
                  "last_name": f"Collision {stamp}",
                  "status": "lead",
                  "workspace_id": workspace_id,
              })
              .execute())
        if rc.data:
            client_id = rc.data[0]["id"]
            print(f"   [OK] client cree id={client_id}\n")
    except Exception as exc:
        print(f"   [ECHEC] insert client a echoue : {exc}\n")
        return 1

    # 2. Tente de creer un prospect avec le meme email -> doit echouer
    print("-> 2. Tentative d'insert d'un PROSPECT avec le MEME email...")
    blocked = False
    err_msg = ""
    prospect_id = None
    try:
        rp = (sb.table("prospects")
              .insert({
                  "emails": [test_email],
                  "status": "new",
                  "name": f"TEST PROSPECT {stamp}",
                  "workspace_id": workspace_id,
              })
              .execute())
        if rp.data:
            prospect_id = rp.data[0]["id"]
    except Exception as exc:
        blocked = True
        err_msg = str(exc)

    if blocked:
        print("   [OK] Bloque par le trigger.")
        for line in err_msg.split("\n")[:3]:
            print(f"       {line[:180]}")
    else:
        print("   [ECHEC] L'insert du prospect est PASSE — le trigger ne bloque pas !")

    # 3. Cleanup
    print("\n-> 3. Cleanup...")
    if prospect_id:
        sb.table("prospects").delete().eq("id", prospect_id).execute()
        print(f"   [OK] prospect supprime id={prospect_id}")
    if client_id:
        sb.table("clients").delete().eq("id", client_id).execute()
        print(f"   [OK] client supprime id={client_id}")

    print()
    if blocked and "client_email_collision" in err_msg:
        print("====================================================")
        print("  RESULTAT : Trigger anti-collision client FONCTIONNEL.")
        print("====================================================")
        return 0
    elif blocked:
        print("====================================================")
        print("  RESULTAT : Insert bloque mais pas par notre trigger.")
        print("  Verifie le message d'erreur ci-dessus.")
        print("====================================================")
        return 2
    else:
        print("====================================================")
        print("  RESULTAT : Trigger NE BLOQUE PAS. Migration a refaire.")
        print("====================================================")
        return 1


if __name__ == "__main__":
    sys.exit(main())
