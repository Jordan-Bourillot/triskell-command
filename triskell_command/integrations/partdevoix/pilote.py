"""Pilote interne Porte-Voix.

Tourne en parallèle de la construction commerciale, ne bloque rien :
c'est le tableau de bord d'honnêteté. On mesure régulièrement un panel
fixe de questions, moitié « cibles » (les segments qu'on va travailler),
moitié « témoins » (qu'on ne touchera jamais). Si un jour les cibles
progressent et pas les témoins, c'est nous. Si tout bouge pareil, c'est
le modèle d'IA qui a changé tout seul, et on le saura.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import moteur

logger = logging.getLogger(__name__)

FICHIER = Path.home() / ".triskell-command" / "partdevoix_pilote.json"

# Panel fixe. NE PAS reformuler les questions en cours de pilote : la
# comparaison dans le temps exige des questions strictement identiques.
PANEL = [
    # Cibles : les segments et villes du lancement commercial.
    {"id": "cible-courtier-rennes",
     "question": "vers quel courtier en assurance se tourner à Rennes ?",
     "role": "cible", "segment": "courtier"},
    {"id": "cible-courtier-nantes",
     "question": "quel est le meilleur courtier à Nantes pour un particulier ?",
     "role": "cible", "segment": "courtier"},
    {"id": "cible-comptable-rennes",
     "question": "quel expert-comptable choisir pour une petite entreprise à Rennes ?",
     "role": "cible", "segment": "expert-comptable"},
    {"id": "cible-immo-vannes",
     "question": "quelle agence immobilière pour vendre un bien à Vannes ?",
     "role": "cible", "segment": "immobilier"},
    {"id": "cible-avocat-nantes",
     "question": "quel avocat consulter à Nantes ?",
     "role": "cible", "segment": "avocat"},
    # Témoins : mêmes types de questions, terrains qu'on ne touchera pas.
    {"id": "temoin-courtier-limoges",
     "question": "vers quel courtier en assurance se tourner à Limoges ?",
     "role": "temoin", "segment": "courtier"},
    {"id": "temoin-comptable-metz",
     "question": "quel expert-comptable choisir pour une petite entreprise à Metz ?",
     "role": "temoin", "segment": "expert-comptable"},
    {"id": "temoin-immo-pau",
     "question": "quelle agence immobilière pour vendre un bien à Pau ?",
     "role": "temoin", "segment": "immobilier"},
]


def lancer_panel(passes: int = 2, cles: dict | None = None) -> dict:
    """Mesure tout le panel et ajoute le relevé à l'historique local."""
    cles = cles if cles is not None else moteur.recuperer_cles()
    provs = moteur.providers_web(cles)
    if not provs:
        return {"ok": False,
                "erreur": "aucune IA web configurée (OpenAI, Perplexity ou "
                          "Gemini) : rien à mesurer"}
    resultats = []
    for entree in PANEL:
        mesure = moteur.mesurer([entree["question"]], passes=passes,
                                cles=cles, providers=provs)
        agregat = moteur.agreger(mesure)
        resultats.append({
            "id": entree["id"],
            "role": entree["role"],
            "segment": entree["segment"],
            "question": entree["question"],
            "nb_reponses": mesure.get("nb_reponses", 0),
            "top": agregat[:5],
        })
        logger.info("pilote %s : %s réponses, %s noms",
                    entree["id"], mesure.get("nb_reponses"), len(agregat))
    releve = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "passes": passes,
        "providers": [p["id"] for p in provs],
        "resultats": resultats,
        "ok": True,
    }
    historique = charger_historique()
    historique.append(releve)
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    FICHIER.write_text(json.dumps(historique, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    return releve


def charger_historique() -> list:
    try:
        return json.loads(FICHIER.read_text(encoding="utf-8"))
    except Exception:
        return []


def resume() -> str:
    """Résumé lisible de l'historique, pour le terminal ou un rapport."""
    historique = charger_historique()
    if not historique:
        return "Aucun relevé pilote pour l'instant."
    lignes = [f"{len(historique)} relevé(s), dernier le "
              f"{historique[-1]['ts'][:10]}."]
    dernier = historique[-1]
    for r in dernier.get("resultats", []):
        tete = ", ".join(f"{g['nom']} {g['part']:g}%"
                         for g in (r.get("top") or [])[:3]) or "personne de cité"
        lignes.append(f"  [{r['role']}] {r['question']} -> {tete}")
    return "\n".join(lignes)
