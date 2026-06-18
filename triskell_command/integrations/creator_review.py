"""2e IA relectrice DÉDIÉE aux mails créateurs.

Le mail créateur est un gabarit FIXE déjà validé (accroche, aperçus, bouton) ;
seule la phrase de monétisation (le « pitch » / l'angle) est sur mesure. La
relectrice de prospection (`quality_reviewer.review_email`) note le corps
ENTIER comme un mail libre — appliquée à la seule phrase d'angle, elle la juge
hors contexte et la sous-note (« offre floue », « pas de perso »).

Ici, on lui donne le MAIL COMPLET pour une note juste, mais on ne lui fait
proposer une retouche QUE sur le pitch (la seule partie régénérable sans casser
le template). Réutilise l'infra IA de triskell_core (providers + bascule auto).
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_PROMPT = """\
Tu es relecteur senior. Voici un MAIL COMPLET envoyé à un créateur de contenu \
pour lui proposer un assistant IA à sa marque (plus un quiz, une analyse de sa \
chaîne et une offre de monétisation). Le mail suit un gabarit FIXE déjà validé \
(accroche, aperçus, bouton) ; la SEULE partie sur mesure est la PHRASE DE \
MONÉTISATION (le « pitch »), recopiée plus bas.

1) Note le mail ENTIER sur 10 : clarté de l'offre, ton naturel (zéro jargon, \
zéro bullshit), cohérence avec CE créateur. Le tutoiement ou le vouvoiement \
est VOULU par l'auteur : ne pénalise jamais ça.

2) Regarde SEULEMENT le pitch (la ligne sur la monétisation). Un bon pitch \
reste CONCRET sur le gain. Il décrit un revenu récurrent et presque passif, via \
un abonnement que prend sa communauté, dont une part lui revient pendant que \
Triskell s'occupe de tout. Évite les formules vagues ou passives comme « tu \
touches une part » seule, qui affaiblissent l'attrait. N'invente JAMAIS de \
chiffre, de pourcentage ni de montant. Si tu peux rendre le pitch plus \
percutant, plus clair ou plus juste POUR CE CRÉATEUR en l'ancrant dans son \
univers, propose une version améliorée : une seule phrase, longueur proche, \
même esprit. Interdits : deux-points d'annonce, tiret cadratin, « sans \
pression », impératif. Sinon, laisse vide.

Réponds UNIQUEMENT en JSON, sans markdown, sans rien avant ni après :
{{
  "score": <int 1-10>,
  "comment": "<une phrase qui explique la note et la retouche éventuelle>",
  "pitch_revised": "<le pitch amélioré OU chaîne vide si rien à changer>",
  "modif_type": "<une catégorie: fluidité|répétition|personnalisation|clarté|ton|concision|accroche OU chaîne vide>"
}}

CONTEXTE DU CRÉATEUR :
{context}

LE MAIL COMPLET :
{mail_text}

LE PITCH À ÉVALUER (et à améliorer si besoin) :
{pitch}
"""


def review_creator(*, mail_text: str, pitch: str, context: str,
                   provider: str, model: str, api_keys: dict) -> dict:
    """Note le mail créateur (score/10) et propose éventuellement un pitch
    révisé. Renvoie {score, comment, pitch_revised, modif_type, reviewed_by,
    engine_down}. Conservatif en cas de panne IA (engine_down=True)."""
    try:
        from triskell_core.ai import providers as ai_providers
        from triskell_core.prospect.quality_reviewer import normalize_modif_type
    except Exception as exc:
        logger.warning("creator_review: infra IA indisponible (%s)", exc)
        return {"score": 0, "comment": "infra IA indisponible",
                "pitch_revised": "", "modif_type": "", "engine_down": True}

    prompt = _PROMPT.format(
        context=(context or "(aucun contexte)").strip()[:600],
        mail_text=(mail_text or "").strip()[:3500],
        pitch=(pitch or "").strip()[:600],
    )
    try:
        raw, used, _model = ai_providers.send_with_fallback(
            provider, model, prompt, api_keys)
        raw = raw or ""
    except ai_providers.AllProvidersFailed as exc:
        logger.warning("creator_review: aucune IA disponible (%s)", exc)
        return {"score": 0,
                "comment": ("Aucune IA disponible pour relire (plus de crédit "
                            "ou coupure). Mail gardé tel quel."),
                "pitch_revised": "", "modif_type": "", "engine_down": True}
    except Exception as exc:  # garde-fou : ne jamais laisser remonter
        logger.warning("creator_review: appel IA échoué (%s)", exc)
        return {"score": 0, "comment": f"relecture plantée : {exc}",
                "pitch_revised": "", "modif_type": "", "engine_down": True}

    data = _parse(raw)
    data["reviewed_by"] = used
    data["engine_down"] = False
    try:
        data["modif_type"] = normalize_modif_type(data.get("modif_type") or "")
    except Exception:
        pass
    return data


def _parse(raw: str) -> dict:
    raw = (raw or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw,
                     flags=re.IGNORECASE | re.MULTILINE).strip()
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if not m:
        return {"score": 0, "comment": "réponse non-JSON",
                "pitch_revised": "", "modif_type": ""}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"score": 0, "comment": "JSON invalide",
                "pitch_revised": "", "modif_type": ""}
    try:
        score = max(0, min(10, int(d.get("score", 0))))
    except Exception:
        score = 0
    return {
        "score": score,
        "comment": str(d.get("comment") or "").strip()[:300],
        "pitch_revised": str(d.get("pitch_revised") or "").strip(),
        "modif_type": str(d.get("modif_type") or "").strip(),
    }
