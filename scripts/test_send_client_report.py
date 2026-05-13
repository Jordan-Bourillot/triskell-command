"""Script de test manuel pour l'envoi de rapport SEO client.

DESTINATION FINALE :
    Triskell\\triskell-command\\scripts\\test_send_client_report.py

Permet à Jordan de tester l'envoi sans attendre le 1er du mois.

Usage :
    # Lister les clients en cadence auto_mensuel et leur dernier envoi
    python scripts/test_send_client_report.py --list

    # Dry-run sur tous les clients auto_mensuel (génère + simule, n'envoie pas)
    python scripts/test_send_client_report.py --dry-run

    # Envoi réel pour un client précis
    python scripts/test_send_client_report.py --client-id <uuid>

    # Envoi réel pour un client précis sur un mois spécifique
    python scripts/test_send_client_report.py --client-id <uuid> --month 2026-04

    # Envoi de test vers une adresse perso (Jordan), bypass le contact_email
    # du client. Utilise le premier client auto_mensuel comme source de données.
    python scripts/test_send_client_report.py --to jordan@triskell-studio.fr
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime

# Permet de lancer le script depuis triskell-command/ (racine repo)
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from triskell_command.integrations.phare import (  # noqa: E402
    client_report_sender, repo,
)


def _parse_month(s: str) -> date:
    return datetime.strptime(s, "%Y-%m").date().replace(day=1)


def _list_clients() -> None:
    clients = repo.list_clients_with_cadence("auto_mensuel")
    print(f"{len(clients)} client(s) en cadence auto_mensuel :\n")
    for c in clients:
        last = c.get("last_report_sent_at") or "(jamais)"
        print(f"  • {c.get('id')[:8]}…  {c.get('contact_name', ''):<25}  "
              f"{c.get('contact_email', ''):<35}  dernier envoi : {last}")
    if not clients:
        print("  (aucun — créer une fiche client avec report_cadence = 'auto_mensuel')")


def _send_test_to_override(to_email: str, target_month, dry_run: bool) -> dict:
    """Prend le premier client auto_mensuel comme source de données, mais
    envoie le mail à `to_email` à la place. Utile pour Jordan qui veut voir
    le résultat sans déranger un client réel.
    """
    clients = repo.list_clients_with_cadence("auto_mensuel")
    if not clients:
        return {"ok": False, "error": "aucun client auto_mensuel pour servir de source"}

    source = dict(clients[0])
    source["contact_email"] = to_email
    source["contact_name"] = "Test override"
    return client_report_sender.send_for_client(
        source,
        target_month=target_month or client_report_sender._previous_month_first_day(),
        cfg=repo.get_config() or {},
        dry_run=dry_run,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true",
                        help="Liste les clients auto_mensuel et leur dernier envoi.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simule sans appeler Resend.")
    parser.add_argument("--client-id", default=None,
                        help="UUID du client à servir (sinon tous).")
    parser.add_argument("--month", default=None, type=_parse_month,
                        help="Mois cible YYYY-MM (défaut : mois précédent).")
    parser.add_argument("--to", default=None,
                        help="Adresse email override (bypass contact_email).")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.list:
        _list_clients()
        return 0

    if args.to:
        result = _send_test_to_override(args.to, args.month, args.dry_run)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0 if result.get("ok") else 1

    summary = client_report_sender.send_pending_reports(
        target_month=args.month,
        only_client_id=args.client_id,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
