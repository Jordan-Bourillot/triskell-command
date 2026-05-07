"""Wrapper Google Search Console API.

Utilise un service account (JSON path stocké dans phare_config.gsc_credentials_path).
Tant que le path n'est pas configuré, toutes les fonctions renvoient un état
vide et logguent en debug — pas d'exception.

Quand configuré, requête /searchanalytics/query pour chaque site et remonte :
  - clicks, impressions, position moyenne, CTR par jour
  - top requêtes par site
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from . import repo

logger = logging.getLogger(__name__)


def _credentials():
    """Charge les credentials Google service account, ou None."""
    cfg = repo.get_config()
    path = cfg.get("gsc_credentials_path") or ""
    if not path:
        return None
    try:
        from google.oauth2 import service_account  # type: ignore
    except ImportError:
        logger.debug("gsc: google-auth pas installé")
        return None
    try:
        return service_account.Credentials.from_service_account_file(
            path,
            scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
        )
    except Exception as exc:
        logger.warning("gsc credentials %s : %s", path, exc)
        return None


def _service():
    creds = _credentials()
    if creds is None:
        return None
    try:
        from googleapiclient.discovery import build  # type: ignore
    except ImportError:
        logger.debug("gsc: google-api-python-client pas installé")
        return None
    try:
        return build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    except Exception as exc:
        logger.warning("gsc service: %s", exc)
        return None


def is_configured() -> bool:
    return _service() is not None


def fetch_daily_metrics(domain: str,
                        *,
                        start: Optional[date] = None,
                        end: Optional[date] = None) -> list[dict]:
    """Renvoie une liste de dicts {date, clicks, impressions, position, ctr}.

    Vide si GSC non configuré.
    """
    svc = _service()
    if svc is None:
        return []
    end = end or (date.today() - timedelta(days=2))  # GSC retarde de 2 jours
    start = start or (end - timedelta(days=29))
    site_url = f"sc-domain:{domain}"  # property au format domaine
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["date"],
        "rowLimit": 500,
    }
    try:
        resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
    except Exception as exc:
        # Fallback : property URL-prefix
        try:
            site_url = f"https://{domain}/"
            resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
        except Exception as exc2:
            logger.warning("gsc query %s: %s / %s", domain, exc, exc2)
            return []
    out = []
    for row in resp.get("rows", []) or []:
        keys = row.get("keys", [])
        out.append({
            "date": keys[0] if keys else None,
            "clicks": int(row.get("clicks", 0)),
            "impressions": int(row.get("impressions", 0)),
            "position": float(row.get("position", 0.0)),
            "ctr": float(row.get("ctr", 0.0)),
        })
    return out


def fetch_top_queries(domain: str, *, days: int = 28, limit: int = 50) -> list[dict]:
    """Top requêtes Google sur la fenêtre. Vide si GSC non configuré."""
    svc = _service()
    if svc is None:
        return []
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["query"],
        "rowLimit": limit,
    }
    site_url = f"sc-domain:{domain}"
    try:
        resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
    except Exception:
        try:
            site_url = f"https://{domain}/"
            resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
        except Exception as exc2:
            logger.warning("gsc top queries %s: %s", domain, exc2)
            return []
    out = []
    for row in resp.get("rows", []) or []:
        out.append({
            "query": (row.get("keys") or [""])[0],
            "clicks": int(row.get("clicks", 0)),
            "impressions": int(row.get("impressions", 0)),
            "position": float(row.get("position", 0.0)),
            "ctr": float(row.get("ctr", 0.0)),
        })
    return out


def fetch_top_pages(domain: str, *, days: int = 28, limit: int = 50) -> list[dict]:
    svc = _service()
    if svc is None:
        return []
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["page"],
        "rowLimit": limit,
    }
    site_url = f"sc-domain:{domain}"
    try:
        resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
    except Exception:
        try:
            site_url = f"https://{domain}/"
            resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
        except Exception as exc2:
            logger.warning("gsc top pages %s: %s", domain, exc2)
            return []
    out = []
    for row in resp.get("rows", []) or []:
        out.append({
            "page": (row.get("keys") or [""])[0],
            "clicks": int(row.get("clicks", 0)),
            "impressions": int(row.get("impressions", 0)),
            "position": float(row.get("position", 0.0)),
            "ctr": float(row.get("ctr", 0.0)),
        })
    return out
