"""GEO-Surveillant — Generative Engine Optimization.

Surveille la présence des sites Triskell dans les réponses des moteurs
génératifs (ChatGPT, Perplexity, Claude, Google AI Overview).

Pour chaque site, génère une liste de requêtes pivot (issues des mots-clés
suivis), interroge chaque "surface" et détecte si :
- Triskell est cité (URL ou marque)
- Quels concurrents sont cités à la place
- Sur quelles formulations on peut s'insérer

Stocke les résultats dans phare_geo_mentions et propose des actions
correctives (enrichir contenu, ajouter source citable, schema.org).
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from . import agents, repo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Surfaces interrogeables
# ---------------------------------------------------------------------------
def _query_perplexity(query: str, api_key: str) -> dict:
    """Interroge Perplexity Sonar — renvoie {response_text, citations: [url]}."""
    if not api_key:
        return {}
    try:
        r = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": "llama-3.1-sonar-small-128k-online",
                "messages": [{"role": "user", "content": query}],
            },
            timeout=30,
        )
        if r.status_code >= 400:
            logger.warning("perplexity %s: %s", r.status_code, r.text[:200])
            return {}
        data = r.json()
        msg = data.get("choices", [{}])[0].get("message", {})
        return {
            "response_text": msg.get("content", ""),
            "citations": data.get("citations") or [],
        }
    except Exception as exc:
        logger.warning("perplexity exc: %s", exc)
        return {}


def _query_chatgpt(query: str, api_key: str) -> dict:
    """Interroge ChatGPT (gpt-4o-mini avec web search si dispo).
    Note : OpenAI n'expose pas directement le browsing en API à tous les
    plans. Fallback : on utilise la réponse texte sans citations."""
    if not api_key:
        return {}
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": query}],
            },
            timeout=30,
        )
        if r.status_code >= 400:
            return {}
        data = r.json()
        return {
            "response_text": data["choices"][0]["message"]["content"],
            "citations": [],
        }
    except Exception as exc:
        logger.warning("chatgpt exc: %s", exc)
        return {}


def _query_claude(query: str, api_key: str) -> dict:
    """Interroge Claude (Sonnet) via API Anthropic standard."""
    if not api_key:
        return {}
    try:
        from triskell_core.ai.providers import call_anthropic
        text = call_anthropic(query, "claude-sonnet-4-5", api_key)
        return {"response_text": text, "citations": []}
    except Exception as exc:
        logger.warning("claude exc: %s", exc)
        return {}


def _query_google_ai_overview(query: str) -> dict:
    """Pas d'API officielle Google AI Overview. À implémenter via SerpAPI
    ou DataForSEO SERP qui retournent le bloc AI Overview quand présent.

    Pour l'instant, fallback : utilise DataForSEO si configuré."""
    from . import dataforseo
    if not dataforseo.is_configured():
        return {}
    serp = dataforseo.serp_top10(query)
    if not serp:
        return {}
    return {
        "response_text": "[AI Overview non capturé — API officielle manquante]",
        "citations": [s.get("url") for s in serp[:5] if s.get("url")],
    }


SURFACES = {
    "perplexity": _query_perplexity,
    "chatgpt": _query_chatgpt,
    "claude": _query_claude,
    "google_ai_overview": _query_google_ai_overview,
}


# ---------------------------------------------------------------------------
def _credentials() -> dict:
    """Récupère les clés API par surface depuis shared_settings.ai_keys
    et phare_config."""
    sb = repo._sb()
    creds = {}
    if sb is None:
        return creds
    try:
        rows = (sb.table("shared_settings").select("value")
                .eq("key", "ai_keys").limit(1).execute().data)
        ai = (rows or [{}])[0].get("value") or {}
        creds["perplexity"] = ai.get("perplexity") or ""
        creds["chatgpt"] = ai.get("openai") or ""
        creds["claude"] = ai.get("anthropic") or ""
    except Exception:
        pass
    return creds


def _detect_mention(response_text: str, citations: list[str],
                     domain: str, brand_name: str) -> dict:
    """Détecte si notre site/marque est mentionné dans la réponse."""
    response_low = (response_text or "").lower()
    domain_low = domain.lower()
    brand_low = brand_name.lower()
    mentioned_url = ""
    for c in citations or []:
        if domain_low in c.lower():
            mentioned_url = c
            break
    mentioned = bool(mentioned_url) or domain_low in response_low or brand_low in response_low
    excerpt = ""
    if mentioned:
        idx = response_low.find(domain_low)
        if idx < 0:
            idx = response_low.find(brand_low)
        if idx >= 0:
            excerpt = response_text[max(0, idx - 60):idx + 200]
    competitors_mentioned = []
    for c in citations or []:
        host = c.split("/")[2] if c.startswith("http") and "/" in c[8:] else ""
        if host and domain_low not in host.lower():
            competitors_mentioned.append(host)
    return {"mentioned": mentioned, "mention_url": mentioned_url,
            "mention_excerpt": excerpt,
            "competitors_mentioned": competitors_mentioned[:10]}


# ---------------------------------------------------------------------------
def run_geo_check(site_id: str, *, max_queries: int = 5,
                  surfaces: Optional[list[str]] = None,
                  app_state=None) -> dict:
    """Interroge les surfaces LLM sur les top mots-clés du site."""
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    cfg = repo.get_config()
    surfaces = surfaces or cfg.get("geo_check_surfaces") or ["perplexity"]
    creds = _credentials()
    domain = site.get("domain") or ""
    brand = site.get("name") or domain.split(".")[0]

    keywords = repo.list_keywords(site_id, limit=max_queries)
    if not keywords:
        return {"ok": True, "checked": 0,
                "message": "aucun mot-clé suivi (lance d'abord la veille)"}

    sb = repo._sb()
    checked = 0
    mentioned_count = 0
    for kw in keywords[:max_queries]:
        query = f"{kw['keyword']} (cite tes sources françaises de référence)"
        for surface in surfaces:
            fn = SURFACES.get(surface)
            if not fn:
                continue
            api_key = creds.get(surface, "")
            if surface == "google_ai_overview":
                result = fn(query)
            else:
                if not api_key:
                    continue
                result = fn(query, api_key)
            if not result:
                continue
            detected = _detect_mention(
                result.get("response_text", ""),
                result.get("citations", []),
                domain, brand,
            )
            if sb is not None:
                try:
                    sb.table("phare_geo_mentions").insert({
                        "site_id": site_id,
                        "surface": surface,
                        "query": kw["keyword"],
                        "mentioned": detected["mentioned"],
                        "mention_url": detected["mention_url"],
                        "mention_excerpt": detected["mention_excerpt"],
                        "competitors_mentioned": detected["competitors_mentioned"],
                        "raw_response": (result.get("response_text") or "")[:4000],
                    }).execute()
                except Exception as exc:
                    logger.warning("geo_mentions insert: %s", exc)
            checked += 1
            if detected["mentioned"]:
                mentioned_count += 1

    # 18/06/2026 (demande Jordan) : le GEO a SON propre outil dédié. On ne crée
    # donc plus AUCUNE carte « conseil » GEO dans Le Phare (l'outil SEO) — ça
    # faisait doublon et encombrait la pile « à toi de le faire » que Jordan ne
    # veut plus voir. La MESURE continue (elle a déjà été écrite dans
    # phare_geo_mentions plus haut, et alimente l'écran GEO) : seule la carte-
    # tâche disparaît. Avant : une carte « 0/0 — 0% » à impact 4 sur tous les
    # sites + une carte « GEO check » à chaque passage = pur bruit.
    if not checked:
        return {"ok": True, "checked": 0, "mentioned": 0, "coverage_pct": 0.0}
    coverage_pct = round(mentioned_count / checked * 100, 1)
    return {"ok": True, "checked": checked, "mentioned": mentioned_count,
            "coverage_pct": coverage_pct}
