"""Le Phare — Initialisation OAuth2 user pour Google Search Console.

À lancer une seule fois pour autoriser Triskell Command à lire les
métriques Search Console. Ouvre un onglet navigateur où tu te connectes
avec le compte Google qui possède les properties (Jordan).

Pré-requis :
  1. Console GCP → APIs & Services → Credentials → Create Credentials →
     OAuth client ID → Application type "Desktop". Télécharge le JSON.
  2. Place-le sous : ~/.triskell-command/gsc-oauth-client.json
  3. Active l'API "Google Search Console API" dans le projet GCP.

Lancement :
    cd "Triskell Command"
    py -3 scripts/phare_setup_gsc_oauth.py

Une fois autorisé, le token est stocké dans
~/.triskell-command/gsc-oauth-token.json et tous les appels GSC
deviennent silencieux. Le token se rafraîchit automatiquement.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Permet d'exécuter le script depuis n'importe où
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from triskell_command.integrations.phare import gsc  # noqa: E402


def main() -> int:
    client_path = Path.home() / ".triskell-command" / "gsc-oauth-client.json"
    if not client_path.exists():
        print(f"✗ Manque le fichier client_secrets : {client_path}")
        print("  Crée un OAuth client ID 'Desktop' dans la console GCP,")
        print("  télécharge le JSON et copie-le à cet emplacement.")
        return 1

    print("→ Lancement du flow OAuth2 (un onglet navigateur va s'ouvrir)…")
    creds = gsc._oauth_credentials()
    if creds is None:
        print("✗ Échec du flow OAuth. Voir les logs.")
        return 1

    token_path = Path.home() / ".triskell-command" / "gsc-oauth-token.json"
    print(f"✓ OAuth réussi. Token persisté : {token_path}")

    print("→ Test : fetch des top requêtes pour triskell-studio.fr…")
    rows = gsc.fetch_top_queries("triskell-studio.fr", days=7, limit=5)
    if rows:
        print(f"✓ GSC opérationnel — {len(rows)} top requêtes récupérées :")
        for r in rows[:5]:
            print(f"   · {r['query']:40s} {r['clicks']:4d} clicks")
    else:
        print("⚠ Pas de données retournées (normal si site jeune ou pas")
        print("  encore vérifié dans Search Console).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
