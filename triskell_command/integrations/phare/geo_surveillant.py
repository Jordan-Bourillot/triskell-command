"""GEO-Surveillant — Generative Engine Optimization. ⚰️ RETRAITÉ 03/07/2026.

🚫 MODULE RÉDUIT À UN STUB — PLUS AUCUN APPEL IA.
Retiré du planning le 03/07/2026. Raison : mesure fantôme — ce module
écrivait dans `phare_geo_mentions`, une table que RIEN ne lit (aucun écran,
aucun rapport, aucun endpoint — vérifié), et ses cartes d'action avaient
déjà été supprimées le 18/06 à la demande de Jordan. Chaque passage du jeudi
dépensait des appels IA (Perplexity, OpenAI, Claude…) pour remplir un tiroir
mort, en doublon de l'écran GEO (qui interroge jusqu'à 8 IA, AFFICHE ses
résultats et alimente l'auto-pilote GEO). L'écran GEO est désormais la mesure
unique de « les IA citent-elles mes sites ? ».

Le module reste IMPORTABLE (pour ne rien casser : run_now("geo_check", …)
existe toujours, un test l'appelle), mais toutes ses fonctions publiques
sont neutralisées : elles ne font AUCUN appel IA/réseau et renvoient une
erreur claire. Ne pas le re-planifier. Si un jour on veut mesurer Google AI
Overview (seule capacité que l'écran GEO n'a pas), l'ajouter comme
fournisseur de l'écran GEO — pas ressusciter ce module.

--- description d'origine (pour mémoire) ---
Surveillait la présence des sites Triskell dans les réponses des moteurs
génératifs (ChatGPT, Perplexity, Claude, Google AI Overview) : pour chaque
site, requêtes pivot issues des mots-clés suivis, interrogation de chaque
« surface », détection des citations et des concurrents, stockage dans
phare_geo_mentions.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Message unique renvoyé par toutes les entrées publiques du module retiré.
_RETIRED = {
    "ok": False,
    "error": "Module retiré le 03/07 — la mesure GEO vit dans l'écran GEO.",
}


def run_geo_check(site_id: str, *, max_queries: int = 5,
                  surfaces: Optional[list[str]] = None,
                  app_state=None) -> dict:
    """Neutralisé : ne dépense plus d'appels IA. Renvoie l'erreur de retrait.

    La signature est conservée à l'identique pour que run_now("geo_check", …)
    et les tests continuent d'appeler sans planter — mais aucune surface LLM
    n'est interrogée (voir docstring en tête de module)."""
    logger.debug("run_geo_check appelé sur module retiré (site_id=%s) — ignoré",
                 site_id)
    return dict(_RETIRED)
