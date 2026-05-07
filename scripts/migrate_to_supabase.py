"""Script de migration : pousse les données JSON locales vers Supabase.

À lancer UNE FOIS chez Jordan, après que Supabase est configuré et que
Jordan est loggé. Thomas n'a pas besoin de migrer (il commence avec une
base vierge — il verra automatiquement les données poussées par Jordan).

Usage :
    python scripts/migrate_to_supabase.py [--dry-run]

Le script lit :
- ~/.triskell-prospect/prospects.json     → table prospects + email_history
                                              + prospect_drafts
- ~/.triskell-prospect/templates.json      → table templates
- ~/.triskell-command/convoy/campaigns/*.json → tables convoy_campaigns +
                                                  convoy_drafts

Il est idempotent : tu peux le relancer sans dupliquer (les match_keys du
prospect évitent les doublons, les UUID des campagnes/drafts aussi).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("migrate")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Simule sans écrire en base")
    parser.add_argument("--prospect-dir",
                        default=str(Path.home() / ".triskell-prospect"),
                        help="Dossier source du CRM local")
    parser.add_argument("--convoy-dir",
                        default=str(Path.home() / ".triskell-command" / "convoy" / "campaigns"),
                        help="Dossier source des campagnes Convoi")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # Setup imports — Triskell Core doit être accessible
    here = Path(__file__).resolve().parent.parent
    core_root = here.parent / "Triskell Core"
    if core_root.exists() and str(core_root) not in sys.path:
        sys.path.insert(0, str(core_root))
    sys.path.insert(0, str(here))

    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        logger.error("Module Supabase absent. pip install supabase")
        return 1

    try:
        client = get_client()
    except SupabaseNotConfigured:
        logger.error("Supabase pas configuré. Termine d'abord le setup "
                     "(cf. supabase/README.md).")
        return 1

    if not client.is_authenticated:
        logger.error("Pas authentifié. Lance Triskell Command, fais login, "
                     "puis relance ce script.")
        return 1

    logger.info("Connecté en tant que %s (user_id=%s)",
                client.user_display_name or "?", client.user_id)

    if args.dry_run:
        logger.info("DRY-RUN : aucune écriture ne sera effectuée.")

    n_prospects = migrate_prospects(client, Path(args.prospect_dir),
                                     dry_run=args.dry_run)
    n_templates = migrate_templates(client, Path(args.prospect_dir),
                                     dry_run=args.dry_run)
    n_campaigns = migrate_convoy(client, Path(args.convoy_dir),
                                  dry_run=args.dry_run)

    logger.info("=== Migration terminée ===")
    logger.info("Prospects : %d", n_prospects)
    logger.info("Templates : %d", n_templates)
    logger.info("Campagnes Convoi : %d", n_campaigns)
    return 0


# ---------------------------------------------------------------------------
def migrate_prospects(client, src_dir: Path, *, dry_run: bool) -> int:
    src = src_dir / "prospects.json"
    if not src.exists():
        logger.info("Pas de %s à migrer.", src)
        return 0

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Lecture impossible : %s", exc)
        return 0
    if not isinstance(data, list):
        logger.error("Format inattendu dans %s", src)
        return 0

    from triskell_core.prospect.core.prospect import Prospect
    from triskell_core.db.repos import (history_event_to_row,
                                          prospect_to_row, draft_dict_to_row)

    n = 0
    for raw in data:
        try:
            p = Prospect.from_dict(raw)
        except Exception as exc:
            logger.warning("Prospect illisible : %s", exc)
            continue
        row = prospect_to_row(p)
        row["created_by"] = client.user_id
        row["updated_by"] = client.user_id

        if dry_run:
            logger.info("[DRY] prospect %s (%s)", p.name or p.legal_name,
                        p.emails[0] if p.emails else "—")
            n += 1
            continue

        try:
            # Cherche d'abord par match_keys pour éviter les doublons
            existing_id = None
            for k in p.match_keys:
                # match_keys sont en JSONB array, on requête avec contains
                res = (client.raw.table("prospects").select("id")
                       .contains("match_keys", [k]).limit(1).execute())
                if res.data:
                    existing_id = res.data[0]["id"]
                    break
            if existing_id:
                client.raw.table("prospects").update(row).eq(
                    "id", existing_id).execute()
                prospect_id = existing_id
            else:
                ins = client.raw.table("prospects").insert(row).execute()
                prospect_id = ins.data[0]["id"] if ins.data else None
        except Exception as exc:
            logger.warning("Insert prospect %s : %s", p.name, exc)
            continue

        if not prospect_id:
            continue

        # Migre l'history
        for event in (p.history or []):
            try:
                hrow = history_event_to_row(prospect_id, event,
                                              created_by=client.user_id)
                client.raw.table("email_history").insert(hrow).execute()
            except Exception as exc:
                logger.debug("Insert history %s : %s", event.get("kind"), exc)

        # Migre les pending_drafts
        for d in (p.pending_drafts or []):
            try:
                drow = draft_dict_to_row(prospect_id, d,
                                          created_by=client.user_id)
                client.raw.table("prospect_drafts").insert(drow).execute()
            except Exception as exc:
                logger.debug("Insert draft : %s", exc)

        n += 1
        if n % 20 == 0:
            logger.info("  ... %d prospects migrés", n)

    logger.info("Prospects migrés : %d", n)
    return n


# ---------------------------------------------------------------------------
def migrate_templates(client, src_dir: Path, *, dry_run: bool) -> int:
    src = src_dir / "templates.json"
    if not src.exists():
        logger.info("Pas de %s à migrer.", src)
        return 0
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    n = 0
    for key, tpl in data.items():
        row = {
            "key": key,
            "channel": tpl.get("channel", "email"),
            "subject": tpl.get("subject", ""),
            "body": tpl.get("body", ""),
            "is_default": False,
            "created_by": client.user_id,
            "updated_by": client.user_id,
        }
        if dry_run:
            logger.info("[DRY] template %s", key)
        else:
            try:
                client.raw.table("templates").upsert(row).execute()
            except Exception as exc:
                logger.warning("Upsert template %s : %s", key, exc)
                continue
        n += 1
    logger.info("Templates migrés : %d", n)
    return n


# ---------------------------------------------------------------------------
def migrate_convoy(client, campaigns_dir: Path, *, dry_run: bool) -> int:
    if not campaigns_dir.exists():
        logger.info("Pas de %s à migrer.", campaigns_dir)
        return 0
    files = sorted(campaigns_dir.glob("*.json"))
    if not files:
        return 0

    from triskell_command.integrations.convoy_runner import (
        ConvoyCampaign, _campaign_to_row, _draft_to_row,
    )

    n = 0
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            camp = ConvoyCampaign.from_dict(data)
        except Exception as exc:
            logger.warning("Campagne illisible %s : %s", f, exc)
            continue

        camp_row = _campaign_to_row(camp)
        camp_row["created_by"] = client.user_id

        if dry_run:
            logger.info("[DRY] campagne %s (%d drafts)", camp.name,
                        len(camp.drafts))
            n += 1
            continue

        try:
            client.raw.table("convoy_campaigns").upsert(camp_row).execute()
            if camp.drafts:
                drafts_rows = [_draft_to_row(d, camp.id) for d in camp.drafts]
                client.raw.table("convoy_drafts").upsert(drafts_rows).execute()
        except Exception as exc:
            logger.warning("Upsert campagne %s : %s", camp.name, exc)
            continue
        n += 1
    logger.info("Campagnes migrées : %d", n)
    return n


if __name__ == "__main__":
    sys.exit(main())
