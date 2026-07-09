"""Rapporteur Porte-Voix — le robot des rapports mensuels.

Chaque mois, pour chaque client suivi actif, il mesure la part de voix
(quelques minutes d'appels aux IA), fabrique le rapport et l'archive,
puis prévient Jordan par notification : le rapport est PRÉPARÉ, jamais
envoyé au client tout seul (l'envoi reste une décision humaine, règle
absolue de la maison).

Interrupteur `partdevoix_rapporteur_auto` (défaut : COUPÉ — l'offre est
désarmée, rien ne tourne tant que Jordan n'allume pas). La décision
« quels clients sont dus » est une fonction PURE (clients_dus) pour être
testable sans réseau.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60 * 60          # un passage par heure
INITIAL_DELAY_SECONDS = 120              # laisse le boot finir
SETTING_ENABLED = "partdevoix_rapporteur_auto"

# On attend le 2 du mois (le 1er, les IA parlent encore du mois passé et
# un redéploiement du 1er ne doit pas faire sauter un rapport : le
# passage se rattrape tout seul n'importe quel jour suivant).
JOUR_DU_MOIS = 2

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


def _get_client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        return c if c.is_authenticated else None
    except Exception:
        return None


# ---------------------------------------------------------- interrupteur

def is_enabled() -> bool:
    """True si le rapport mensuel automatique est allumé (défaut : COUPÉ)."""
    c = _get_client()
    if c is None:
        return False
    try:
        return bool(c.get_shared_setting(SETTING_ENABLED, default=False))
    except Exception:
        return False


def set_enabled(value: bool) -> tuple[bool, str]:
    """Allume/coupe le rapport mensuel automatique (relit pour confirmer)."""
    c = _get_client()
    if c is None:
        return False, "Base partagée non connectée."
    try:
        c.set_shared_setting(SETTING_ENABLED, bool(value))
        reel = bool(c.get_shared_setting(SETTING_ENABLED, default=False))
        if reel != bool(value):
            return False, "Le réglage n'a pas pu être enregistré."
        return True, ("Rapport mensuel automatique allumé."
                      if reel else "Rapport mensuel automatique coupé.")
    except Exception as exc:
        return False, str(exc)


# ------------------------------------------------------- décision (pure)

def clients_dus(liste_clients: list[dict], archives: list[dict],
                now: datetime) -> list[dict]:
    """Les clients dont le rapport du mois est dû. Fonction PURE.

    Un client est dû quand : il est actif, il n'est pas entré ce mois-ci
    (son premier rapport attend un mois plein de travail), on est au
    moins le {JOUR_DU_MOIS} du mois, et aucun rapport n'a encore été
    archivé pour lui ce mois-ci (idempotent : un redémarrage ne fait
    jamais un deuxième rapport)."""
    if now.day < JOUR_DU_MOIS:
        return []
    mois = now.strftime("%Y-%m")
    deja_servis = {r.get("client_id") for r in archives
                   if (r.get("archive_ts") or "")[:7] == mois}
    dus = []
    for c in liste_clients:
        if not c.get("actif", True):
            continue
        if (c.get("entree_le") or "")[:7] >= mois:
            continue
        if c.get("id") in deja_servis:
            continue
        dus.append(c)
    return dus


# --------------------------------------------------------------- passage

def tick(now: datetime | None = None) -> dict:
    """Un passage : mesure et archive le rapport des clients dus.

    Une erreur sur un client (clés API, réseau) n'empêche pas les
    autres ; elle est notée dans le résultat, visible en page Santé."""
    now = now or datetime.now(timezone.utc)
    if _get_client() is None:
        return {"skipped_reason": "supabase_indispo"}
    if not is_enabled():
        return {"skipped_reason": "disabled"}
    from . import clients as registre, rapport
    try:
        # Base illisible = passage sauté : décider « déjà servi ? » sur le
        # fichier local de secours (aveugle aux rapports archivés par
        # l'autre conteneur) ferait re-mesurer et payer en double.
        dus = clients_dus(registre.lister_clients(),
                          rapport.rapports_archives(), now)
    except ValueError as exc:
        logger.warning("rapporteur : %s", exc)
        return {"skipped_reason": "base_illisible"}
    if not dus:
        return {"generes": 0, "clients_dus": 0}
    resultat = {"generes": 0, "clients_dus": len(dus), "erreurs": []}
    for client in dus:
        try:
            rapport.mesurer_client(client, passes=3)
            # Fiche relue APRÈS la mesure (plusieurs minutes) : des
            # rubriques posées entre-temps doivent entrer dans le rapport.
            fiche = registre.trouver_client(client.get("id") or "") or client
            donnees = rapport.generer_rapport(fiche)
            rapport.alerte_rubriques_perimees(fiche, donnees)
            entree = rapport.archiver_rapport(donnees)
            resultat["generes"] += 1
            _prevenir(fiche, donnees, entree)
        except Exception as exc:
            logger.warning("rapporteur %s: %s", client.get("id"), exc)
            resultat["erreurs"].append(
                f"{client.get('entreprise')}: {exc}")
    if resultat["erreurs"]:
        resultat["error"] = " ; ".join(resultat["erreurs"])[:400]
    return resultat


def _prevenir(client: dict, donnees: dict, entree: dict) -> None:
    """Notification à Jordan : le rapport est prêt, à relire avant envoi."""
    try:
        from ...web.push import send_push
        part = donnees.get("part_client")
        corps = (f"Part de voix : {part:g} %. À relire avant envoi."
                 if isinstance(part, (int, float))
                 else "À relire avant envoi.")
        if donnees.get("alertes"):
            corps += " ⚠ Rubriques du mois à revoir."
        send_push(
            title=f"📊 Rapport Porte-Voix prêt : {client.get('entreprise')}",
            body=corps,
            user_id="jordan",
            url="/#portevoix",
            tag_group="clients",
            extra_data={"rapport_id": entree.get("id")},
        )
    except Exception as exc:  # la notification ne bloque jamais le rapport
        logger.warning("rapporteur push: %s", exc)


# ---------------------------------------------------------------- worker

def start_worker(app_state=None) -> bool:
    """Démarre le thread du rapporteur (idempotent)."""
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True

        def _loop():
            global _LAST_RUN_AT, _LAST_RUN_RESULT
            logger.info("partdevoix rapporteur : thread démarré (cycle 1 h)")
            time.sleep(INITIAL_DELAY_SECONDS)
            while True:
                try:
                    _LAST_RUN_RESULT = tick()
                except Exception as exc:
                    logger.exception("rapporteur tick: %s", exc)
                    _LAST_RUN_RESULT = {"error": str(exc)}
                _LAST_RUN_AT = datetime.now(timezone.utc).isoformat(
                    timespec="seconds")
                time.sleep(POLL_INTERVAL_SECONDS)

        _WORKER_THREAD = threading.Thread(
            target=_loop, name="partdevoix_rapporteur", daemon=True)
        _WORKER_THREAD.start()
    return True


def get_status() -> dict:
    """Format attendu par la page Santé (system_health)."""
    return {
        "running": _WORKER_THREAD is not None and _WORKER_THREAD.is_alive(),
        "last_run_at": _LAST_RUN_AT,
        "last_run_result": dict(_LAST_RUN_RESULT),
    }
