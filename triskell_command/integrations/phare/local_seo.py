"""Local SEO — Google Business Profile.

Wrapper basique pour suivre la fiche Google d'Eliks Studio (ou tout autre
site Triskell ayant un GBP). Pas d'écriture directe sur GBP via API
(nécessite OAuth + validation Google) : on lit, on suggère, et l'humain
applique manuellement.

Sources possibles :
- Google Places API (Place Details) : payant mais plafond gratuit 200$/mois
- Scraping Google Maps : fragile, déconseillé
- Bright Data / Outscraper : payant

On reste sur Google Places API officielle. Si pas configurée, fallback :
on lit juste le HTML public (rating moyen, total reviews) sans avis détaillés.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from . import agents, repo

logger = logging.getLogger(__name__)


PLACES_API = "https://maps.googleapis.com/maps/api/place/details/json"


def _places_api_key() -> str:
    cfg = repo.get_config()
    return (cfg.get("google_places_api_key", "")
            or cfg.get("pagespeed_api_key", ""))   # parfois la même


def _gbp_place_id(site_id: str) -> str:
    cfg = repo.get_config()
    mapping = cfg.get("gbp_place_ids", {}) or {}
    return mapping.get(site_id, "")


def fetch_gbp(place_id: str) -> dict:
    """Récupère les détails d'une fiche GBP via Places API."""
    api_key = _places_api_key()
    if not api_key or not place_id:
        return {}
    try:
        r = requests.get(
            PLACES_API,
            params={
                "place_id": place_id,
                "key": api_key,
                "fields": ("name,formatted_address,formatted_phone_number,"
                            "website,rating,user_ratings_total,reviews,"
                            "photos,opening_hours,types"),
                "language": "fr",
            }, timeout=15,
        )
        if r.status_code >= 400:
            return {}
        return r.json().get("result", {}) or {}
    except Exception as exc:
        logger.warning("places api: %s", exc)
        return {}


def completeness_score(details: dict) -> int:
    """0-100 selon les champs remplis."""
    fields = ["name", "formatted_address", "formatted_phone_number",
              "website", "rating", "photos", "opening_hours"]
    filled = sum(1 for f in fields if details.get(f))
    return int(filled / len(fields) * 100)


def suggestions(details: dict) -> list[str]:
    out = []
    if not details.get("website"):
        out.append("Renseigner le champ Website (lien vers la landing dédiée).")
    if not details.get("formatted_phone_number"):
        out.append("Ajouter un numéro de téléphone.")
    if (details.get("photos") or []) == [] or len(details.get("photos", [])) < 5:
        out.append("Ajouter au moins 5 photos (intérieur, équipe, en action).")
    if not details.get("opening_hours"):
        out.append("Renseigner les horaires d'ouverture.")
    rating = details.get("rating") or 0
    if rating and rating < 4.0:
        out.append(f"Note moyenne {rating}/5 — engager un travail de "
                    f"sollicitation d'avis pour remonter au-dessus de 4.5.")
    return out


# ---------------------------------------------------------------------------
class ReviewResponder(agents.Agent):
    name = "review_responder"
    role = """Tu es le ReviewResponder de Le Phare.

Mission : à partir d'un avis Google laissé sur la fiche d'un service
Triskell, proposer une réponse publique courte (60-100 mots), française,
chaleureuse, qui :
- remercie spécifiquement (pas un copier-coller générique)
- reprend un mot-clé naturel du métier (SEO local)
- propose un CTA léger (revenir, recommander, contacter)
- gère les cas négatifs avec sang-froid et propose un canal privé

Voix Triskell (préambule).

Format JSON strict : {"response": str, "tone": "warm"|"professional"|"apologetic"}"""

    def run(self, *, review: dict, business_name: str, app_state=None) -> dict:
        prompt = f"""ENTREPRISE : {business_name}

AVIS :
- Auteur : {review.get('author_name', 'anonyme')}
- Note : {review.get('rating', '?')} / 5
- Texte : {review.get('text', '')[:600]}

Réponds au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------------------
def run_local_check(site_id: str, *, app_state=None) -> dict:
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    place_id = _gbp_place_id(site_id)
    if not place_id:
        return {"ok": False, "error": "place_id non configuré pour ce site"}

    details = fetch_gbp(place_id)
    if not details:
        return {"ok": False, "error": "fetch GBP échoué"}

    sb = repo._sb()
    score = completeness_score(details)
    suggs = suggestions(details)

    if sb is not None:
        try:
            sb.table("phare_gbp_status").insert({
                "site_id": site_id,
                "place_id": place_id,
                "name": details.get("name", ""),
                "address": details.get("formatted_address", ""),
                "phone": details.get("formatted_phone_number", ""),
                "website": details.get("website", ""),
                "rating": details.get("rating"),
                "reviews_count": details.get("user_ratings_total", 0),
                "photos_count": len(details.get("photos", []) or []),
                "completeness_score": score,
                "suggestions": suggs,
            }).execute()
        except Exception as exc:
            logger.warning("gbp_status insert: %s", exc)

    # Avis nouveaux
    new_reviews = 0
    pending_responses = 0
    responder = ReviewResponder()
    for r in (details.get("reviews") or [])[:10]:
        review_id = r.get("time")  # timestamp Unix sert d'ID
        if review_id is None:
            continue
        review_id = str(review_id)
        if sb is None:
            continue
        existing = (sb.table("phare_reviews").select("id")
                    .eq("review_id", review_id).limit(1).execute().data)
        if existing:
            continue
        # Génère une réponse proposée
        resp_obj = {}
        try:
            resp_obj = responder.run(
                review={"author_name": r.get("author_name", ""),
                          "rating": r.get("rating"),
                          "text": r.get("text", "")},
                business_name=details.get("name", site.get("name", "")),
                app_state=app_state,
            )
        except Exception as exc:
            logger.debug("review_resp LLM: %s", exc)
        try:
            sb.table("phare_reviews").insert({
                "site_id": site_id,
                "place_id": place_id,
                "review_id": review_id,
                "author_name": r.get("author_name", ""),
                "rating": r.get("rating"),
                "text_excerpt": (r.get("text") or "")[:500],
                "proposed_response_md": resp_obj.get("response", ""),
                "posted_at": datetime.fromtimestamp(int(review_id),
                                                      tz=timezone.utc).isoformat(),
            }).execute()
            new_reviews += 1
            if resp_obj.get("response"):
                pending_responses += 1
        except Exception as exc:
            logger.warning("review insert: %s", exc)

    repo.insert_action({
        "site_id": site_id,
        "agent": "local_seo",
        "kind": "recommandation",
        "title": (f"GBP {details.get('name', '?')} : score {score}/100, "
                  f"{new_reviews} nouveaux avis"),
        "detail_md": (f"**Suggestions** :\n" +
                      "\n".join(f"- {s}" for s in suggs) +
                      f"\n\n**Nouveaux avis** : {new_reviews}, dont "
                      f"{pending_responses} avec réponse pré-rédigée à valider."),
        "status": "draft",
        "impact": 4, "effort": 2,
    })

    return {"ok": True, "completeness_score": score,
            "new_reviews": new_reviews,
            "pending_responses": pending_responses}
