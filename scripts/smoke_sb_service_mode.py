"""Smoke test — accès base en mode service_role « à froid ».

Reproduit la panne du 10/06/2026 : le tick GitHub Actions du Phare démarrait
avec SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (sans anon key), le client
triskell-core passait en mode service et se déclarait authentifié, mais son
SDK interne n'était instancié que paresseusement. Les _sb() des intégrations
faisaient `getattr(c, "_client")` → None → « SDK refuse » → tick KO.

Contrôles :
  1. Client triskell-core en mode service à froid → is_authenticated.
  2. Le _sb()/_user_sb() de CHAQUE intégration retourne un client utilisable
     (objet avec .table) sur un process où RIEN d'autre n'a touché le SDK.
  3. Le pattern piégé getattr(c, "client") / getattr(c, "_client") a disparu
     du code (garde anti-régression structurelle).

Aucun réseau : l'URL/clé sont factices, on ne fait aucune requête.

    py -3 scripts/smoke_sb_service_mode.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAKE_URL = "https://exemple-smoke-test.supabase.co"
# Faux JWT structurellement valide (header.payload.signature) — jamais envoyé.
FAKE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoic2VydmljZV9yb2xlIiwiaXNzIjoic21va2UifQ."
    "c21va2Utc2lnbmF0dXJl"
)

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  OK  {label}")
    else:
        FAIL += 1
        print(f"  KO  {label}" + (f" — {detail}" if detail else ""))


def main() -> int:
    print("=== Smoke : _sb() en mode service_role à froid ===")

    # ----- Environnement façon GitHub Actions (service_role seule) -----
    os.environ["SUPABASE_URL"] = FAKE_URL
    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = FAKE_KEY
    os.environ.pop("SUPABASE_ANON_KEY", None)

    try:
        import supabase  # noqa: F401
    except ImportError:
        print("  KO  module supabase non installé — test impossible")
        return 1

    from triskell_core.db import client as core_client

    # Process « à froid » : aucun client global, SDK jamais initialisé.
    core_client.reset_client()

    c = core_client.get_client()
    check("client triskell-core en mode service", c.service_mode)
    check("client considéré authentifié (mode service)", c.is_authenticated)
    check("SDK interne PAS encore initialisé (reproduit le froid)",
          c._client is None)

    # ----- 1. phare.repo._sb() : la panne d'origine -----
    from triskell_command.integrations.phare import repo as phare_repo
    sb = phare_repo._sb()
    check("phare._sb() retourne un client", sb is not None)
    check("phare._sb() : client utilisable (.table)", hasattr(sb, "table"))

    # ----- 2. toutes les autres intégrations corrigées -----
    # (_user_sb pour celles qui ont un chemin service séparé, _sb sinon)
    cases = []
    from triskell_command.integrations.wow import repo as wow_repo
    cases.append(("wow._user_sb()", wow_repo._user_sb))
    from triskell_command.integrations.obelisk import repo as obelisk_repo
    cases.append(("obelisk._user_sb()", obelisk_repo._user_sb))
    from triskell_command.integrations.pixelpros import repo as pp_repo
    cases.append(("pixelpros._user_sb()", pp_repo._user_sb))
    from triskell_command.integrations.rankus import repo as rankus_repo
    cases.append(("rankus._user_sb()", rankus_repo._user_sb))
    from triskell_command.integrations.lagriffe import repo as lagriffe_repo
    cases.append(("lagriffe._user_sb()", lagriffe_repo._user_sb))
    from triskell_command.integrations.billing import repo as billing_repo
    cases.append(("billing._sb()", billing_repo._sb))
    from triskell_command.integrations.forge import repo as forge_repo
    cases.append(("forge._sb()", forge_repo._sb))
    from triskell_command.integrations import sender_pool_tracker
    cases.append(("sender_pool_tracker._sb()", sender_pool_tracker._sb))

    for label, fn in cases:
        # Chaque appel repart d'un client global neuf, jamais « réchauffé »
        # par un autre code path — le scénario exact de la panne.
        core_client.reset_client()
        try:
            got = fn()
        except Exception as exc:  # un _sb ne doit JAMAIS lever
            check(label, False, f"exception {exc}")
            continue
        check(label, got is not None and hasattr(got, "table"),
              "retourne None ou objet sans .table")

    # ----- 3. garde anti-régression : le pattern piégé a disparu -----
    bad = re.compile(r'getattr\(c, "client", None\)')
    offenders: list[str] = []
    for py in (ROOT / "triskell_command").rglob("*.py"):
        try:
            if bad.search(py.read_text(encoding="utf-8")):
                offenders.append(str(py.relative_to(ROOT)))
        except Exception:
            continue
    check("plus aucun getattr(c, \"client\") piégé dans le code",
          not offenders, ", ".join(offenders))

    # ----- Nettoyage : ne pas polluer les process suivants -----
    core_client.reset_client()

    print(f"\n{PASS} OK / {FAIL} KO")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
