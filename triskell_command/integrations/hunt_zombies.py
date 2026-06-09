"""Détection des chasses zombies — commun Chasseur / Chasseur Créateur /
Prospecteur Google.

Le problème : une chasse tourne dans un thread du serveur. Quand le serveur
redémarre (redéploiement Coolify, crash), le thread meurt mais le fichier
JSON de la chasse garde son statut "searching" / "enriching". Résultat :
des chasses affichées « en cours » pour toujours dans l'interface.

La solution : au moment de lister ou recharger une chasse, si son statut est
actif mais qu'aucun thread ne tourne pour elle ET que son fichier n'a pas
bougé depuis un moment, on la requalifie en "error" avec un message clair,
et on persiste pour ne pas refaire le diagnostic à chaque affichage.

Le délai de grâce évite de zombifier une chasse qui vient juste d'être
lancée (fenêtre entre la création du fichier et le démarrage du thread).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Statuts considérés comme "en cours" (un thread devrait être vivant).
ACTIVE_STATUSES = ("pending", "searching", "enriching")

# Délai de grâce : on ne touche pas aux fichiers modifiés il y a moins de
# 2 minutes (chasse en train de démarrer, ou snapshot très récent).
GRACE_SECONDS = 120

ZOMBIE_ERROR_MESSAGE = (
    "Chasse interrompue par un redémarrage du serveur. "
    "Les résultats déjà trouvés sont conservés — relance une chasse "
    "pour compléter."
)


def reconcile_hunt_file(path: Path, *, is_running: bool) -> dict | None:
    """Charge le JSON d'une chasse et corrige son statut si zombie.

    - `path`       : fichier JSON de la chasse.
    - `is_running` : True si un thread vivant travaille sur cette chasse.

    Renvoie le dict (corrigé ou non), ou None si illisible.
    Persiste la correction dans le fichier pour que ce soit définitif.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("reconcile_hunt_file %s : %s", path.name, exc)
        return None
    if not isinstance(data, dict):
        return None

    status = (data.get("status") or "").strip()
    if status not in ACTIVE_STATUSES or is_running:
        return data

    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        age = GRACE_SECONDS + 1
    if age < GRACE_SECONDS:
        return data  # trop récent — laisse-lui le temps de démarrer

    data["status"] = "error"
    if not (data.get("error") or "").strip():
        data["error"] = ZOMBIE_ERROR_MESSAGE
    log = data.get("log")
    if isinstance(log, list):
        log.append("⚠ " + ZOMBIE_ERROR_MESSAGE)
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        logger.info("Chasse zombie requalifiée : %s", path.name)
    except Exception as exc:
        logger.debug("reconcile_hunt_file write %s : %s", path.name, exc)
    # Copie de secours cloud (l'outil = nom du dossier parent des chasses :
    # ~/.triskell-command/<outil>/hunts/<id>.json)
    try:
        from .hunt_cloud_backup import mirror_hunt
        tool = path.parent.parent.name
        mirror_hunt(tool, data)
    except Exception:
        pass
    return data
