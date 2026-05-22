"""Test du check anti-envoi strict (Auto-pilote v2, etape 1.4).

Verifie que has_recent_send avec les nouveaux flags fonctionne :
  - forever=True : un envoi vieux (au-dela du cooldown 72h) bloque quand meme
  - check_clients=True : un email present dans clients bloque (last_kind=client)
  - Cas de controle : forever=False sur un envoi vieux ne bloque pas

Usage :
  python scripts/test_anti_envoi_strict.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CORE_ROOT_CANDIDATES = [
    HERE.parent / "triskell-core",
    HERE.parent / "Triskell Core",
]
for candidate in CORE_ROOT_CANDIDATES:
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
sys.path.insert(0, str(HERE))

from triskell_command.integrations import prospect_status as PS  # noqa: E402


class FakeClient:
    """Wrapper minimal compatible avec has_recent_send."""

    def __init__(self, raw):
        self.raw = raw

    def get_shared_setting(self, key, default=None):
        return default


def get_service_client():
    settings_path = Path.home() / ".triskell-command" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    sb_cfg = data["supabase"]
    from supabase import create_client
    return create_client(sb_cfg["url"],
                         sb_cfg.get("service_role_key") or sb_cfg["service_key"])


def main() -> int:
    sb = get_service_client()
    fake = FakeClient(sb)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    prospect_email = f"test-anti-envoi-{stamp}@triskell-test.invalid"
    client_email = f"test-anti-envoi-client-{stamp}@triskell-test.invalid"

    # Recupere workspace_id
    ws = sb.table("prospects").select("workspace_id").limit(1).execute()
    workspace_id = (ws.data or [{}])[0].get("workspace_id")
    if not workspace_id:
        print("[ECHEC] workspace_id introuvable.")
        return 1

    prospect_id = None
    client_id = None
    history_id = None

    try:
        # === Setup 1 : prospect + envoi simule il y a 1 an ===
        print("-> Setup : creation prospect + envoi historique d'il y a 1 an...")
        rp = (sb.table("prospects").insert({
            "emails": [prospect_email],
            "status": "contacted",
            "name": f"TEST ANTI-ENVOI {stamp}",
            "workspace_id": workspace_id,
        }).execute())
        prospect_id = rp.data[0]["id"]
        old_ts = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        rh = (sb.table("email_history").insert({
            "prospect_id": prospect_id,
            "kind": "email_sent",
            "ts": old_ts,
            "subject": "Test ancien envoi",
            "extra": {"to": prospect_email},
            "workspace_id": workspace_id,
        }).execute())
        history_id = rh.data[0]["id"]
        print(f"   [OK] prospect_id={prospect_id[:8]}... history_id={history_id[:8]}...\n")

        # === Test 1 : forever=False (defaut) sur envoi vieux ===
        print("-> Test 1 : forever=False sur envoi vieux d'1 an")
        r1 = PS.has_recent_send(fake, prospect_id=prospect_id, hours=72)
        if r1.get("recent"):
            print(f"   [ECHEC] should be recent=False, got {r1}")
        else:
            print(f"   [OK] recent=False (cooldown 72h depasse)")

        # === Test 2 : forever=True sur le meme envoi ===
        print("\n-> Test 2 : forever=True sur le meme envoi vieux d'1 an")
        r2 = PS.has_recent_send(fake, prospect_id=prospect_id, forever=True)
        if r2.get("recent"):
            print(f"   [OK] recent=True (memoire a vie) "
                  f"last_ts={r2.get('last_ts', '')[:10]}")
        else:
            print(f"   [ECHEC] should be recent=True, got {r2}")

        # === Setup 2 : creation client ===
        print("\n-> Setup : creation client de test...")
        rc = (sb.table("clients").insert({
            "email": client_email,
            "first_name": "Test",
            "last_name": f"Anti-Envoi {stamp}",
            "status": "lead",
            "workspace_id": workspace_id,
        }).execute())
        client_id = rc.data[0]["id"]
        print(f"   [OK] client_id={client_id[:8]}...\n")

        # === Test 3 : check_clients=True sur email present dans clients ===
        print("-> Test 3 : check_clients=True sur email present dans clients")
        r3 = PS.has_recent_send(fake, email=client_email, check_clients=True)
        if r3.get("recent") and r3.get("last_kind") == "client":
            print(f"   [OK] recent=True last_kind=client")
        else:
            print(f"   [ECHEC] should be recent=True last_kind=client, got {r3}")

        # === Test 4 : check_clients=False sur le meme email (controle) ===
        print("\n-> Test 4 : check_clients=False sur email present dans clients")
        r4 = PS.has_recent_send(fake, email=client_email, check_clients=False)
        if not r4.get("recent"):
            print(f"   [OK] recent=False (check clients desactive)")
        else:
            print(f"   [ECHEC] should be recent=False, got {r4}")

        # Recap
        oks = sum([
            not r1.get("recent"),
            r2.get("recent") is True,
            r3.get("recent") is True and r3.get("last_kind") == "client",
            not r4.get("recent"),
        ])
        print(f"\n{'=' * 52}")
        if oks == 4:
            print(f"  RESULTAT : {oks}/4 tests OK -- TOUT FONCTIONNE.")
        else:
            print(f"  RESULTAT : {oks}/4 tests OK -- problemes detectes.")
        print("=" * 52)
        return 0 if oks == 4 else 1
    finally:
        # === Cleanup ===
        print("\n-> Cleanup...")
        if history_id:
            sb.table("email_history").delete().eq("id", history_id).execute()
            print(f"   [OK] history supprime")
        if prospect_id:
            sb.table("prospects").delete().eq("id", prospect_id).execute()
            print(f"   [OK] prospect supprime")
        if client_id:
            sb.table("clients").delete().eq("id", client_id).execute()
            print(f"   [OK] client supprime")


if __name__ == "__main__":
    sys.exit(main())
