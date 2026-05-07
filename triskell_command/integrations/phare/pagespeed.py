"""Wrapper Google PageSpeed Insights API.

API gratuite (quota 25k requêtes/jour avec clé, 100/jour sans). Ramène
Lighthouse + Core Web Vitals (terrain CrUX si disponible, sinon lab).

Pas d'OAuth, juste une clé API publique optionnelle. Sans clé, ça marche
quand même (quota plus serré).
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from . import repo

logger = logging.getLogger(__name__)

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PSI_TIMEOUT = 60


def _api_key() -> str:
    cfg = repo.get_config()
    return cfg.get("pagespeed_api_key") or ""


def audit_url(url: str, *, strategy: str = "mobile") -> dict:
    """Lance un audit PSI sur une URL.

    Renvoie un dict simplifié :
        {
          "ok": bool,
          "url": str,
          "strategy": "mobile"|"desktop",
          "lighthouse": {"perf": int, "seo": int, "a11y": int, "bp": int},
          "cwv": {"lcp": float, "inp": float, "cls": float},  # ms / score
          "raw_size_kb": int,
          "error": str (si ok=False)
        }
    """
    params = {"url": url, "strategy": strategy,
              "category": ["performance", "seo", "accessibility", "best-practices"]}
    key = _api_key()
    if key:
        params["key"] = key
    try:
        r = requests.get(PSI_ENDPOINT, params=params, timeout=PSI_TIMEOUT)
    except requests.RequestException as exc:
        return {"ok": False, "url": url, "error": f"réseau: {exc}"}
    if r.status_code >= 400:
        return {"ok": False, "url": url,
                "error": f"HTTP {r.status_code}: {r.text[:200]}"}

    try:
        data = r.json()
    except ValueError:
        return {"ok": False, "url": url, "error": "JSON invalide"}

    lr = data.get("lighthouseResult", {}) or {}
    cats = lr.get("categories", {}) or {}

    def _score(cat_key: str) -> Optional[int]:
        c = cats.get(cat_key) or {}
        sc = c.get("score")
        return None if sc is None else int(round(sc * 100))

    audits = lr.get("audits", {}) or {}

    def _audit_value(audit_key: str) -> Optional[float]:
        a = audits.get(audit_key) or {}
        return a.get("numericValue")

    cwv = {
        "lcp": _audit_value("largest-contentful-paint"),
        "inp": (_audit_value("interaction-to-next-paint")
                or _audit_value("experimental-interaction-to-next-paint")),
        "cls": _audit_value("cumulative-layout-shift"),
    }

    return {
        "ok": True,
        "url": url,
        "strategy": strategy,
        "lighthouse": {
            "perf": _score("performance"),
            "seo": _score("seo"),
            "a11y": _score("accessibility"),
            "bp": _score("best-practices"),
        },
        "cwv": cwv,
        "raw_size_kb": len(r.content) // 1024,
    }


def audit_two_versions(url_a: str, url_b: str) -> dict:
    """Audit comparé (preview vs main) — utilisé par git_pipeline."""
    a = audit_url(url_a)
    b = audit_url(url_b)
    if not a.get("ok") or not b.get("ok"):
        return {"ok": False,
                "a": a, "b": b,
                "error": a.get("error") or b.get("error") or "audit incomplet"}
    diff = {}
    for k in ("perf", "seo", "a11y", "bp"):
        va = a["lighthouse"].get(k)
        vb = b["lighthouse"].get(k)
        if va is None or vb is None:
            diff[k] = None
        else:
            diff[k] = va - vb
    return {"ok": True, "a": a, "b": b, "diff": diff}
