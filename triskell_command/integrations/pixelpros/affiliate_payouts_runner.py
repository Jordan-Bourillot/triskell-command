"""Pixel Pros — Worker de promotion automatique des commissions affiliés.

Toutes les `POLL_INTERVAL_SECONDS` (6 heures par défaut), appelle
`promote_pending_sales(30)` côté DB. Cette opération est idempotente :
elle promeut en `available` toutes les commissions `pending` dont la vente
date de plus de 30 jours.

Pattern aligné sur les autres runners (drip_runner, post_sale_runner, etc.).
Lancé depuis main.py au démarrage de Triskell Command.
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

# 6 heures : assez fréquent pour capter rapidement les transitions, mais
# sans bombarder la DB. Idempotent donc aucun risque de double-promotion.
POLL_INTERVAL_SECONDS = 6 * 60 * 60

_worker_thread: threading.Thread | None = None


def _tick() -> int:
    """Un cycle de promotion. Retourne le nombre de lignes promues."""
    try:
        from . import affiliates
    except Exception as exc:
        logger.debug("affiliate_payouts_runner: import affiliates KO : %s", exc)
        return 0

    try:
        n = affiliates.promote_pending_sales(min_age_days=30)
        if n > 0:
            logger.info("affiliate_payouts_runner: %d commission(s) "
                        "passée(s) de 'pending' à 'available'", n)
        return n
    except Exception as exc:
        logger.warning("affiliate_payouts_runner._tick: %s", exc)
        return 0


def start_worker(app_state=None) -> bool:
    """Lance le thread background. Idempotent.

    Retourne True si le worker est démarré (ou déjà actif).
    Retourne False si Supabase n'est pas dispo (pas de raison de tourner).
    """
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return True

    # Petit smoke test : peut-on contacter Supabase ?
    try:
        from .repo import _sb
        if _sb() is None:
            logger.debug("affiliate_payouts_runner: Supabase indispo, "
                         "worker pas lancé")
            return False
    except Exception as exc:
        logger.debug("affiliate_payouts_runner: smoke test KO : %s", exc)
        return False

    def loop():
        logger.info("affiliate_payouts_runner: thread démarré "
                    "(cycle %d h)", POLL_INTERVAL_SECONDS // 3600)
        # Premier tick immédiat pour traiter ce qui s'est accumulé pendant
        # que le worker était down.
        try:
            _tick()
        except Exception as exc:
            logger.exception("affiliate_payouts_runner first tick: %s", exc)
        while True:
            time.sleep(POLL_INTERVAL_SECONDS)
            try:
                _tick()
            except Exception as exc:
                logger.exception("affiliate_payouts_runner tick: %s", exc)

    _worker_thread = threading.Thread(
        target=loop, name="affiliate_payouts_runner", daemon=True)
    _worker_thread.start()
    return True
