"""Configuration Stripe — lecture des secrets depuis env vars ou settings."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


SETTINGS_FILE = Path.home() / ".triskell-command" / "settings.json"


def _load_settings() -> dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("Lecture %s impossible : %s", SETTINGS_FILE, exc)
        return {}


def stripe_keys() -> dict[str, str]:
    """Renvoie les clés Stripe (vides si non configurées)."""
    env = lambda k, d="": (os.environ.get(k) or d).strip()
    s = _load_settings().get("stripe", {}) or {}

    return {
        "secret_key":     env("STRIPE_SECRET_KEY",     s.get("secret_key", "")),
        "publishable_key":env("STRIPE_PUBLISHABLE_KEY",s.get("publishable_key", "")),
        "webhook_secret": env("STRIPE_WEBHOOK_SECRET", s.get("webhook_secret", "")),
        "price_essential":env("STRIPE_PRICE_ESSENTIAL",s.get("price_essential", "")),
        "price_pro":      env("STRIPE_PRICE_PRO",      s.get("price_pro", "")),
        "price_phare":    env("STRIPE_PRICE_PHARE",    s.get("price_phare", "")),
        "success_url":    env("STRIPE_SUCCESS_URL",
                              s.get("success_url",
                                    "https://command.triskell-studio.fr/billing/success")),
        "cancel_url":     env("STRIPE_CANCEL_URL",
                              s.get("cancel_url",
                                    "https://command.triskell-studio.fr/billing/cancel")),
    }


def is_configured() -> bool:
    """True si on a au minimum la secret_key et le price Essentiel."""
    k = stripe_keys()
    return bool(k["secret_key"]) and bool(k["price_essential"])
