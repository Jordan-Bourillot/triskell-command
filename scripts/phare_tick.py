"""Lance UN tick du scheduler Le Phare en standalone — sans Triskell Command
desktop ouvert.

Utilisé par le workflow GitHub Actions `.github/workflows/phare_scheduler.yml`
qui le déclenche toutes les heures, mais peut aussi être exécuté à la main :

    py -3 scripts/phare_tick.py

Pré-requis (variables d'environnement) :
    SUPABASE_URL                   — URL du projet Supabase
    SUPABASE_SERVICE_ROLE_KEY      — clé service_role (bypasse RLS)

La clé Anthropic est lue automatiquement dans `shared_settings.ai_keys` côté
Supabase. Pas besoin d'env var pour ça.

Comportement :
    - Lit l'heure courante UTC
    - Détermine quelles missions doivent tourner (audit lundi 6-22h, veille
      lundi+jeudi 7h, bulletin tous les jours 8h, etc.)
    - Lance les missions, persiste les actions dans `phare_actions`
    - Affiche un résumé JSON sur stdout
    - Exit code 0 si tout va bien, 1 si une erreur fatale
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)
logger = logging.getLogger("phare_tick")


def main() -> int:
    # ----- Validation des env vars -----
    if not os.environ.get("SUPABASE_URL"):
        logger.error("SUPABASE_URL manquante.")
        return 1
    if not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        logger.error("SUPABASE_SERVICE_ROLE_KEY manquante.")
        return 1

    # ----- Import paresseux : les modules utilisent le fallback env vars -----
    try:
        from triskell_command.integrations.phare import scheduler, repo
    except ImportError as exc:
        logger.error("Import phare échoué : %s", exc)
        return 1

    # ----- Sanity check : on doit pouvoir lire la base -----
    sb = repo._sb()
    if sb is None:
        logger.error("Impossible de se connecter à Supabase (env vars présentes "
                     "mais SDK refuse). Vérifie la valeur de service_role_key.")
        return 1

    # Petit ping : combien de sites actifs ?
    try:
        cnt = sb.table("phare_sites").select("id", count="exact").eq("is_active", True).execute()
        n_sites = cnt.count or 0
        logger.info("Connecté à Supabase. %d sites actifs sous surveillance.", n_sites)
    except Exception as exc:
        logger.error("Ping Supabase échoué : %s", exc)
        return 1

    # ----- Tick -----
    started = datetime.now()
    logger.info("=== Tick Le Phare — %s ===", started.isoformat(timespec="seconds"))
    try:
        result = scheduler._tick(app_state=None)
    except Exception as exc:
        logger.exception("Tick échoué : %s", exc)
        return 1
    elapsed = (datetime.now() - started).total_seconds()
    logger.info("=== Tick terminé en %.1fs ===", elapsed)

    # ----- Résumé human-readable -----
    if isinstance(result, dict):
        # le scheduler retourne `actions_done` (clé historique)
        actions = result.get("actions_done") or result.get("actions") or []
        skipped = result.get("skipped")
    else:
        actions = []
        skipped = None

    if skipped:
        logger.info("Aucune mission lancée (raison : %s)", skipped)
    elif not actions:
        logger.info("Aucune mission lancée à cette heure-ci.")
    else:
        logger.info("%d mission(s) déclenchée(s) :", len(actions))
        for a in actions:
            mission = a.get("mission") or "?"
            site = a.get("site") or "(global)"
            ok = a.get("ok")
            badge = "OK" if ok else "KO"
            logger.info("  [%s] %s — %s", badge, mission, site)

    # ----- JSON brut sur stdout pour le log GitHub Actions -----
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
