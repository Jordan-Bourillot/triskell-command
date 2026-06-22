"""Wrapper DataForSEO (pay-per-use, alternative économique à Ahrefs/Semrush).

Fonctions exposées :
- search_volume(keywords)        → volumes mensuels FR
- keyword_difficulty(keywords)   → difficulté SEO réelle (0-100) par mot-clé
- keyword_suggestions(seed)      → idées de mots-clés long-traîne
- serp_competitors(keyword)      → top 10 SERP Google.fr
- backlinks_summary(domain)      → résumé profil backlinks d'un domaine

Si login/password non configurés (phare_config), fonctions retournent des
listes vides en logguant en debug — pas d'exception.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from . import repo

logger = logging.getLogger(__name__)

DFS_BASE = "https://api.dataforseo.com/v3"
DFS_TIMEOUT = 30
DFS_LOCATION_FR = 2250  # France
DFS_LANGUAGE_FR = "fr"


def _auth() -> Optional[tuple[str, str]]:
    cfg = repo.get_config()
    login = cfg.get("dataforseo_login") or ""
    pwd = cfg.get("dataforseo_password") or ""
    if not login or not pwd:
        return None
    return (login, pwd)


def is_configured() -> bool:
    return _auth() is not None


def _post(endpoint: str, body: list[dict]) -> Optional[dict]:
    auth = _auth()
    if auth is None:
        return None
    try:
        r = requests.post(f"{DFS_BASE}/{endpoint}", auth=auth, json=body,
                          timeout=DFS_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("dfs network %s: %s", endpoint, exc)
        return None
    if r.status_code >= 400:
        logger.warning("dfs HTTP %s on %s: %s", r.status_code, endpoint,
                       r.text[:200])
        return None
    try:
        return r.json()
    except ValueError:
        return None


def search_volume(keywords: list[str]) -> list[dict]:
    """Volumes mensuels FR (exact match) pour une liste de mots-clés."""
    if not keywords:
        return []
    body = [{
        "keywords": keywords[:1000],
        "location_code": DFS_LOCATION_FR,
        "language_code": DFS_LANGUAGE_FR,
    }]
    data = _post("keywords_data/google_ads/search_volume/live", body)
    if not data:
        return []
    out: list[dict] = []
    for task in data.get("tasks", []) or []:
        for res in task.get("result", []) or []:
            out.append({
                "keyword": res.get("keyword", ""),
                "volume": int(res.get("search_volume") or 0),
                "competition": res.get("competition") or "",
                "cpc": float(res.get("cpc") or 0.0),
            })
    return out


def keyword_difficulty(keywords: list[str]) -> dict[str, int]:
    """Difficulté SEO réelle (0-100) par mot-clé, via DataForSEO Labs.

    La difficulté = à quel point c'est dur d'entrer dans le top 10 Google
    pour ce mot. Un seul appel groupé pour toute la liste (jusqu'à 1000 mots),
    pas un appel par mot → coût minime.

    Renvoie un dict {mot_clé_minuscule: difficulté}. Vide si non configuré ou
    si l'API ne répond pas — l'appelant retombe alors sur l'estimation, jamais
    sur un 0 trompeur.
    """
    if not keywords:
        return {}
    body = [{
        "keywords": keywords[:1000],
        "location_code": DFS_LOCATION_FR,
        "language_code": DFS_LANGUAGE_FR,
    }]
    data = _post("dataforseo_labs/google/bulk_keyword_difficulty/live", body)
    if not data:
        return {}
    out: dict[str, int] = {}
    for task in data.get("tasks", []) or []:
        for res in task.get("result", []) or []:
            for item in res.get("items", []) or []:
                kw = (item.get("keyword") or "").lower()
                kd = item.get("keyword_difficulty")
                if kw and kd is not None:
                    out[kw] = int(kd)
    return out


def keyword_suggestions(seed: str, limit: int = 100) -> list[dict]:
    """Suggestions long-traîne autour d'un seed."""
    if not seed:
        return []
    body = [{
        "keyword": seed,
        "location_code": DFS_LOCATION_FR,
        "language_code": DFS_LANGUAGE_FR,
        "limit": min(limit, 1000),
    }]
    data = _post("keywords_data/google_ads/keywords_for_keywords/live", body)
    if not data:
        return []
    out = []
    for task in data.get("tasks", []) or []:
        for res in task.get("result", []) or []:
            out.append({
                "keyword": res.get("keyword", ""),
                "volume": int(res.get("search_volume") or 0),
                "competition": res.get("competition") or "",
                "cpc": float(res.get("cpc") or 0.0),
            })
    return out


def serp_top10(keyword: str) -> list[dict]:
    """Top 10 SERP Google.fr pour un mot-clé."""
    if not keyword:
        return []
    body = [{
        "keyword": keyword,
        "location_code": DFS_LOCATION_FR,
        "language_code": DFS_LANGUAGE_FR,
        "depth": 10,
    }]
    data = _post("serp/google/organic/live/regular", body)
    if not data:
        return []
    out = []
    for task in data.get("tasks", []) or []:
        for res in task.get("result", []) or []:
            for item in res.get("items", []) or []:
                if item.get("type") != "organic":
                    continue
                out.append({
                    "rank": item.get("rank_absolute"),
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "domain": item.get("domain", ""),
                    "snippet": item.get("description", ""),
                })
    return out


def backlinks_summary(domain: str) -> dict:
    """Résumé profil backlinks d'un domaine."""
    if not domain:
        return {}
    body = [{"target": domain, "internal_list_limit": 0}]
    data = _post("backlinks/summary/live", body)
    if not data:
        return {}
    for task in data.get("tasks", []) or []:
        for res in task.get("result", []) or []:
            return {
                "target": res.get("target", domain),
                "backlinks": int(res.get("backlinks") or 0),
                "referring_domains": int(res.get("referring_domains") or 0),
                "rank": int(res.get("rank") or 0),
                "first_seen": res.get("first_seen", ""),
                "last_visited": res.get("last_visited", ""),
            }
    return {}


def referring_domains(domain: str, limit: int = 100) -> list[dict]:
    """Liste des domaines référents."""
    if not domain:
        return []
    body = [{
        "target": domain,
        "limit": min(limit, 1000),
        "order_by": ["rank,desc"],
    }]
    data = _post("backlinks/referring_domains/live", body)
    if not data:
        return []
    out = []
    for task in data.get("tasks", []) or []:
        for res in task.get("result", []) or []:
            for item in res.get("items", []) or []:
                out.append({
                    "domain": item.get("domain", ""),
                    "rank": int(item.get("rank") or 0),
                    "backlinks": int(item.get("backlinks") or 0),
                    "first_seen": item.get("first_seen", ""),
                })
    return out


def ranked_keywords(domain: str, limit: int = 700) -> dict[str, int]:
    """Positions RÉELLES du domaine sur Google, en UN seul appel.

    Renvoie tous les mots-clés sur lesquels le site est classé dans le top 100,
    avec leur place : {mot_clé_minuscule: position}. Bien moins cher qu'une
    requête par mot (1 appel couvre tout le site). Sert à combler les mots où
    Google Search Console est muet (site pas encore visible sur ces requêtes).

    Vide si non configuré, site classé nulle part, ou API muette.
    """
    if not domain:
        return {}
    body = [{
        "target": domain,
        "location_code": DFS_LOCATION_FR,
        "language_code": DFS_LANGUAGE_FR,
        "limit": min(limit, 1000),
    }]
    data = _post("dataforseo_labs/google/ranked_keywords/live", body)
    if not data:
        return {}
    out: dict[str, int] = {}
    for task in data.get("tasks", []) or []:
        for res in task.get("result", []) or []:
            for item in res.get("items", []) or []:
                kw = ((item.get("keyword_data") or {}).get("keyword") or "").lower()
                serp = (item.get("ranked_serp_element") or {}).get("serp_item") or {}
                rank = serp.get("rank_group")
                if kw and isinstance(rank, int) and rank > 0:
                    # un mot peut revenir (plusieurs pages classées) → garde la
                    # meilleure place.
                    if kw not in out or rank < out[kw]:
                        out[kw] = rank
    return out
