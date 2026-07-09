"""Stockage Porte-Voix : base partagée d'abord, fichier local en secours.

Le registre des clients, l'historique des relevés et les rapports
archivés doivent survivre aux redéploiements du serveur ET être les
mêmes vus du site et du poste de Jordan → ils vivent dans
`shared_settings` (comme les missions de prospection). Hors-ligne, on
retombe sur les fichiers `~/.triskell-command/partdevoix_*.json` : une
panne de base ne bloque jamais le travail, elle le rend juste local.

Les tests posent MODE_FICHIER_SEUL = True et redirigent FICHIERS vers
un dossier temporaire : aucune batterie ne touche ni la base ni les
vrais fichiers.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Verrou des cycles lire-modifier-écrire (même motif que missions.py) :
# deux threads du même serveur ne peuvent pas s'écraser mutuellement une
# collection. Le croisement entre conteneurs (site/robots) reste en
# dernier-écrivain-gagnant, assumé au volume réel (fenêtres < 1 s).
VERROU = threading.RLock()

_DOSSIER_LOCAL = Path.home() / ".triskell-command"
FICHIERS = {
    "clients": _DOSSIER_LOCAL / "partdevoix_clients.json",
    "releves": _DOSSIER_LOCAL / "partdevoix_releves.json",
    "rapports": _DOSSIER_LOCAL / "partdevoix_rapports.json",
}
CLES_BASE = {
    "clients": "partdevoix_clients",
    "releves": "partdevoix_releves",
    "rapports": "partdevoix_rapports",
}

# Posé à True par les batteries de tests : jamais la base, jamais les
# vrais fichiers (FICHIERS est redirigé vers un dossier temporaire).
MODE_FICHIER_SEUL = False


def _client_base():
    if MODE_FICHIER_SEUL:
        return None
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        return c if c.is_authenticated else None
    except Exception:
        return None


def _lire_fichier(nom: str, defaut):
    try:
        return json.loads(FICHIERS[nom].read_text(encoding="utf-8"))
    except Exception:
        return defaut


def _ecrire_fichier(nom: str, valeur) -> None:
    chemin = FICHIERS[nom]
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(valeur, ensure_ascii=False, indent=1),
                      encoding="utf-8")


def lire(nom: str, defaut):
    """Lit une collection. Base configurée : la base fait foi ; si elle
    ne répond pas, on REFUSE (ValueError) plutôt que de rendre une vue
    tronquée — un cycle lire-modifier-écrire parti d'une lecture de
    secours écraserait toute la collection au retour de la base. Le
    fichier local ne sert que sans base configurée (usage hors-ligne)
    ou tant que la clé n'a jamais été posée (migration douce).

    On interroge la table directement plutôt que get_shared_setting :
    ce dernier avale ses erreurs et renvoie le défaut, ce qui rendrait
    une panne de base indistinguable d'un registre vide."""
    c = _client_base()
    if c is not None:
        try:
            res = (c.table("shared_settings").select("value")
                   .eq("key", CLES_BASE[nom]).limit(1).execute())
        except Exception as exc:
            logger.warning("partdevoix stockage lecture %s: %s", nom, exc)
            raise ValueError("lecture impossible pour l'instant (base "
                             "partagée injoignable) — réessaie dans un "
                             "moment") from exc
        data = res.data or []
        if data:
            valeur = data[0].get("value")
            return valeur if valeur is not None else defaut
        # Clé jamais posée en base : le fichier local peut avoir une
        # longueur d'avance (données créées hors-ligne).
    return _lire_fichier(nom, defaut)


def ecrire(nom: str, valeur) -> bool:
    """Écrit une collection. Base configurée : la base fait foi (via
    upsert_setting, qui dit la vérité sur l'écriture) + copie locale de
    secours ; False si la base n'a pas pris (l'appelant refuse alors
    proprement plutôt que de perdre la modification en silence). Sans
    base configurée : fichier local seulement (usage hors-ligne assumé)."""
    c = _client_base()
    if c is not None:
        try:
            from ..shared_settings_db import upsert_setting
            ok_base = bool(upsert_setting(c, CLES_BASE[nom], valeur))
        except Exception as exc:
            logger.warning("partdevoix stockage écriture %s: %s", nom, exc)
            ok_base = False
        if not ok_base:
            # Refus VRAI : on ne pose pas non plus la copie locale, sinon
            # le fichier de secours divergerait de la base qui fait foi.
            return False
        try:
            _ecrire_fichier(nom, valeur)  # copie de secours, best-effort
        except Exception as exc:
            logger.warning("partdevoix stockage fichier %s: %s", nom, exc)
        return True
    try:
        _ecrire_fichier(nom, valeur)
        return True
    except Exception as exc:
        logger.warning("partdevoix stockage fichier %s: %s", nom, exc)
        return False
