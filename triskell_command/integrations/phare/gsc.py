"""Wrapper Google Search Console API.

Authentification : OAuth2 user (flow Desktop) en priorité, service account
en fallback legacy.

Pourquoi OAuth user d'abord : Google refuse d'ajouter un service account
comme membre des Domain properties Search Console (erreur "adresse e-mail
introuvable"). Seul un user OAuth a accès. Le service account reste utile
uniquement pour les properties URL-prefix.

Setup OAuth2 (1 seule fois) :
  1. Console GCP → APIs & Services → Credentials → Create OAuth client ID
     → Application type "Desktop". Télécharger le JSON.
  2. Enregistrer le JSON sous `~/.triskell-command/gsc-oauth-client.json`.
  3. Au 1er appel d'une fonction GSC : un onglet navigateur s'ouvre, on
     consent, le token est persisté dans `gsc-oauth-token.json`. Plus rien
     à faire ensuite.

Tant qu'aucune méthode (OAuth ou service account) n'est configurée, toutes
les fonctions renvoient un état vide et logguent en debug — pas d'exception.

Quand configuré, requête /searchanalytics/query pour chaque site et remonte :
  - clicks, impressions, position moyenne, CTR par jour
  - top requêtes par site
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from . import repo

logger = logging.getLogger(__name__)


_OAUTH_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
_OAUTH_CLIENT_PATH = Path.home() / ".triskell-command" / "gsc-oauth-client.json"
_OAUTH_TOKEN_PATH = Path.home() / ".triskell-command" / "gsc-oauth-token.json"


def _oauth_credentials():
    """Charge ou crée les credentials OAuth2 user (Desktop flow).

    Renvoie None si :
    - le client_secrets n'est pas posé (mode pas encore configuré),
    - une dépendance `google-auth-oauthlib` n'est pas installée,
    - le flow échoue (erreur réseau, refus utilisateur).

    ⚠️ Le 1er appel ouvre un navigateur (run_local_server) et BLOQUE le
    thread courant jusqu'au consentement. À déclencher depuis un script CLI
    ou un thread dédié, jamais depuis le thread UI.
    """
    if not _OAUTH_CLIENT_PATH.exists():
        return None
    try:
        from google.oauth2.credentials import Credentials  # type: ignore
        from google.auth.transport.requests import Request  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    except ImportError:
        logger.debug("gsc oauth: google-auth-oauthlib pas installé")
        return None

    creds = None
    if _OAUTH_TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(
                str(_OAUTH_TOKEN_PATH), _OAUTH_SCOPES)
        except Exception as exc:
            logger.warning("gsc oauth token load: %s", exc)
            creds = None

    if creds and not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:
                logger.warning("gsc oauth refresh: %s", exc)
                creds = None
        else:
            creds = None

    if not creds:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(_OAUTH_CLIENT_PATH), _OAUTH_SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)
        except Exception as exc:
            logger.warning("gsc oauth flow: %s", exc)
            return None

    try:
        _OAUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        _OAUTH_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    except Exception as exc:
        logger.debug("gsc oauth token save: %s", exc)

    return creds


def _service_account_credentials():
    """Fallback legacy : credentials Google service account.

    Limité aux properties URL-prefix (sc-domain refusé par Google pour les
    service accounts). Conservé pour compat avec config existante.
    """
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
            path, scopes=_OAUTH_SCOPES)
    except Exception as exc:
        logger.warning("gsc service account %s : %s", path, exc)
        return None


def _credentials():
    """Préférence OAuth user (couvre Domain properties), sinon service account."""
    creds = _oauth_credentials()
    if creds is not None:
        return creds
    return _service_account_credentials()


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
