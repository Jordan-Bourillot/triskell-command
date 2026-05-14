"""Health check Anthropic API — détecte clé valide / crédits épuisés.

Mode opératoire :
- Cache in-memory : un appel API toutes les 5 min max (économise tokens).
- Appel ultra-light : claude-haiku, max_tokens=1, prompt 1 char.
- Coût : <0.0001 € par check.

États renvoyés :
- "ok"                 → API répond, crédits dispos
- "not_configured"     → pas de clé dans settings
- "invalid_key"        → 401 (clé révoquée, mal formée)
- "insufficient_credit"→ 429 + "credit_balance_too_low" OU 400 + balance issue
- "rate_limited"       → 429 simple rate limit
- "offline"            → erreur réseau / DNS
- "unknown"            → autre erreur

Modes de défaillance et parades :
| Mode | Parade |
|------|--------|
| Appel coûte des tokens   | Cache 5 min entre check |
| API plante au lancement  | Thread isolé → status="unknown" mais l'app démarre |
| Clé manquante            | Pas d'appel API, status="not_configured" direct |
| Rate limit même au check | Cache prolongé à 15 min après un 429 |
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Cache global (process-wide)
_CACHE_LOCK = threading.Lock()
_CACHE: dict = {
    "status": "unknown",
    "checked_at": 0.0,
    "error_detail": "",
    "model_responded": "",
}
_CACHE_TTL_SECONDS = 5 * 60          # check max toutes les 5 min
_CACHE_TTL_AFTER_429 = 15 * 60       # après rate-limit, attendre plus
_TIMEOUT_SECONDS = 10                # appel API short timeout


def _load_api_key() -> Optional[str]:
    """Récupère la clé depuis settings.json ou env."""
    import os
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return env_key
    settings_path = Path.home() / ".triskell-command" / "settings.json"
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            keys = (data.get("ai") or {}).get("api_keys") or {}
            return keys.get("anthropic")
        except Exception as exc:
            logger.debug("anthropic_health._load_api_key: %s", exc)
    return None


def _do_check(api_key: str) -> dict:
    """Appel synchrone (ultra-light) à l'API Anthropic. Renvoie dict."""
    try:
        import anthropic
    except ImportError:
        return {"status": "unknown", "error_detail": "anthropic SDK non installé"}

    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=_TIMEOUT_SECONDS)
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1,
            messages=[{"role": "user", "content": "."}],
        )
        return {
            "status": "ok",
            "error_detail": "",
            "model_responded": msg.model if hasattr(msg, "model") else "claude-haiku-4-5",
        }
    except anthropic.AuthenticationError as e:
        return {"status": "invalid_key", "error_detail": str(e)[:200]}
    except anthropic.RateLimitError as e:
        # Distinction crédits épuisés vs rate limit
        msg = str(e).lower()
        if "credit" in msg or "balance" in msg or "billing" in msg:
            return {"status": "insufficient_credit", "error_detail": str(e)[:200]}
        return {"status": "rate_limited", "error_detail": str(e)[:200]}
    except anthropic.BadRequestError as e:
        msg = str(e).lower()
        if "credit" in msg or "balance" in msg or "billing" in msg:
            return {"status": "insufficient_credit", "error_detail": str(e)[:200]}
        return {"status": "unknown", "error_detail": str(e)[:200]}
    except anthropic.APIConnectionError as e:
        return {"status": "offline", "error_detail": str(e)[:200]}
    except Exception as exc:
        return {"status": "unknown", "error_detail": str(exc)[:200]}


def get_status(force_refresh: bool = False) -> dict:
    """Renvoie l'état (depuis cache si <5 min, sinon refresh).

    Toujours non-bloquant : si le cache est expiré, lance un refresh en
    background et renvoie l'ancien résultat immédiatement. Le prochain
    appel verra la valeur fraîche.
    """
    with _CACHE_LOCK:
        snapshot = dict(_CACHE)

    age = time.time() - snapshot["checked_at"]
    # TTL plus long après un 429 pour ne pas l'aggraver
    ttl = _CACHE_TTL_AFTER_429 if snapshot["status"] == "rate_limited" else _CACHE_TTL_SECONDS

    if force_refresh or age > ttl:
        # Lance refresh en background, renvoie l'ancien snapshot direct
        threading.Thread(target=_refresh_async, daemon=True,
                         name="AnthropicHealthCheck").start()
    return snapshot


def _refresh_async() -> None:
    """Refresh le cache en background. Idempotent : un seul appel à la fois."""
    # Verrou simple : évite des appels concurrents si on est appelé en boucle
    if not _CACHE_LOCK.acquire(blocking=False):
        return
    _CACHE_LOCK.release()

    api_key = _load_api_key()
    if not api_key:
        with _CACHE_LOCK:
            _CACHE.update({
                "status": "not_configured",
                "checked_at": time.time(),
                "error_detail": "Clé Anthropic absente dans settings.json",
                "model_responded": "",
            })
        return

    result = _do_check(api_key)
    with _CACHE_LOCK:
        _CACHE.update({
            "status": result.get("status", "unknown"),
            "checked_at": time.time(),
            "error_detail": result.get("error_detail", ""),
            "model_responded": result.get("model_responded", ""),
        })
    logger.info("anthropic_health: status=%s", _CACHE["status"])


def label_for_status(status: str) -> tuple[str, bool, str]:
    """Renvoie (texte_court, est_ok, couleur_indicative).

    couleur_indicative : 'success' | 'warning' | 'danger' (le widget choisit)
    """
    mapping = {
        "ok":                  ("prête",            True,  "success"),
        "not_configured":      ("clé manquante",    False, "warning"),
        "invalid_key":         ("clé invalide",     False, "danger"),
        "insufficient_credit": ("crédits épuisés",  False, "danger"),
        "rate_limited":        ("limite atteinte",  False, "warning"),
        "offline":             ("hors-ligne",       False, "warning"),
        "unknown":             ("inconnu",          False, "warning"),
    }
    return mapping.get(status, ("inconnu", False, "warning"))
