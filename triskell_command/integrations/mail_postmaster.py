"""Note de réputation Gmail — via Google Postmaster Tools (source officielle).

C'est le SEUL moyen de connaître la réputation telle que Gmail la voit vraiment
(note du domaine, taux de spam constaté, taux de réussite SPF/DKIM/DMARC sur les
mails réellement reçus par Gmail). Tout le reste n'est qu'indice extérieur.

Ce que ça exige de Jordan (incompressible — c'est SON domaine, SON Google) :
  1. ajouter le domaine dans Postmaster Tools (postmaster.google.com) ;
  2. créer des identifiants OAuth (client_id + client_secret) ;
  3. autoriser une fois pour obtenir un « refresh_token » (script fourni :
     scripts/postmaster_token.py).
On stocke ces 3 valeurs dans les réglages. Tant qu'elles manquent, on affiche
« à activer » — jamais une note inventée.

Le branchement réseau (OAuth + appel API) est isolé. Le passage « réponse API →
note en français » est PUR et testé sans réseau (summarize).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://gmailpostmastertools.googleapis.com/v1"

# Note de réputation Gmail → libellé français + couleur.
_REPUTATION = {
    "HIGH":   ("Bonne", "success"),
    "MEDIUM": ("Moyenne", "warning"),
    "LOW":    ("Basse", "warning"),
    "BAD":    ("Mauvaise", "danger"),
}


def summarize(stats: dict, *, date: str = "") -> dict:
    """Transforme la réponse trafficStats de Postmaster en note lisible (PUR).

    Renvoie {reputation, reputation_label, tone, spam_rate_pct, dkim_pct,
    spf_pct, dmarc_pct, date}. Les champs absents deviennent None (jamais 0
    inventé)."""
    stats = stats or {}

    def _pct(v, nd=1):
        try:
            return round(float(v) * 100, nd)
        except (TypeError, ValueError):
            return None

    rep = (stats.get("domainReputation") or "").upper()
    label, tone = _REPUTATION.get(rep, ("non communiquée", "muted"))
    return {
        "reputation": rep or None,
        "reputation_label": label,
        "tone": tone,
        # Le taux de spam se joue autour de 0,1 % / 0,3 % (seuils Gmail) :
        # 2 décimales, sinon un 0,05 % s'afficherait à tort 0,1 % (ou 0 %).
        "spam_rate_pct": _pct(stats.get("userReportedSpamRatio"), 2),
        "dkim_pct": _pct(stats.get("dkimSuccessRatio")),
        "spf_pct": _pct(stats.get("spfSuccessRatio")),
        "dmarc_pct": _pct(stats.get("dmarcSuccessRatio")),
        "date": date,
    }


def _access_token(creds: dict, timeout: float = 10.0) -> Optional[str]:
    """Échange le refresh_token contre un access_token. None si échec."""
    import requests
    try:
        r = requests.post(TOKEN_URL, timeout=timeout, data={
            "client_id": creds.get("client_id", ""),
            "client_secret": creds.get("client_secret", ""),
            "refresh_token": creds.get("refresh_token", ""),
            "grant_type": "refresh_token",
        })
        if r.status_code != 200:
            logger.debug("postmaster token: HTTP %s %s", r.status_code, r.text[:200])
            return None
        return (r.json() or {}).get("access_token")
    except Exception as exc:
        logger.debug("postmaster _access_token: %s", exc)
        return None


def _fetch_traffic_stats(domain: str, token: str, *, days_back: int = 7,
                         timeout: float = 10.0) -> Optional[tuple[dict, str]]:
    """Récupère les stats du jour le plus récent disponible (les données de
    Postmaster ont 2-3 jours de retard). Renvoie (stats, 'YYYY-MM-DD') ou None.
    """
    import requests
    headers = {"Authorization": f"Bearer {token}"}
    today = datetime.now().date()
    for delta in range(2, days_back + 1):
        d = today - timedelta(days=delta)
        ymd = d.strftime("%Y%m%d")
        url = f"{API_BASE}/domains/{domain}/trafficStats/{ymd}"
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                body = r.json() or {}
                if body:
                    return body, d.isoformat()
        except Exception as exc:
            logger.debug("postmaster trafficStats %s : %s", ymd, exc)
    return None


def assess_domain(domain: str, creds: Optional[dict]) -> dict:
    """Note de réputation Gmail d'un domaine. Réseau.

    state ∈ {ok, unconfigured, no_data, inconclusive} :
    - unconfigured : pas d'identifiants → « à activer » ;
    - no_data      : Gmail n'a pas (encore) de données (volume trop faible) ;
    - inconclusive : identifiants invalides / API injoignable ;
    - ok           : note disponible (champ 'data').
    """
    domain = (domain or "").strip().lower().lstrip("@")
    creds = creds or {}
    if not (creds.get("client_id") and creds.get("client_secret")
            and creds.get("refresh_token")):
        return {"ok": True, "state": "unconfigured",
                "detail": "Postmaster Google non configuré"}
    if not domain or "." not in domain:
        return {"ok": False, "state": "inconclusive", "detail": "domaine invalide"}
    token = _access_token(creds)
    if not token:
        return {"ok": True, "state": "inconclusive",
                "detail": "connexion à Google refusée (identifiants à vérifier)"}
    found = _fetch_traffic_stats(domain, token)
    if found is None:
        return {"ok": True, "state": "no_data",
                "detail": ("Gmail n'a pas encore de données pour ce domaine "
                           "(volume trop faible ou domaine récent)")}
    stats, date = found
    return {"ok": True, "state": "ok", "data": summarize(stats, date=date)}
