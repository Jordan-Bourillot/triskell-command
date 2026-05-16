"""Crée des sessions Stripe Checkout pour les inscriptions et upgrades.

Usage typique (depuis une route FastAPI) :

    from triskell_command.integrations.billing_saas import checkout
    url = checkout.create_session(
        workspace_id=ws_id,
        workspace_email="contact@acme.fr",
        modules=["essential", "phare"],
    )
    return RedirectResponse(url, status_code=303)
"""

from __future__ import annotations

import logging
from typing import Optional

from . import config
from .plans import PLANS

logger = logging.getLogger(__name__)


def _stripe():
    """Lazy-import du SDK Stripe, configure la secret_key."""
    try:
        import stripe  # type: ignore
    except ImportError:
        raise RuntimeError(
            "Le package 'stripe' n'est pas installé. Lance : pip install stripe"
        )
    keys = config.stripe_keys()
    if not keys["secret_key"]:
        raise RuntimeError(
            "STRIPE_SECRET_KEY manquante. Configure-la en variable "
            "d'environnement ou dans settings.json section 'stripe'."
        )
    stripe.api_key = keys["secret_key"]
    return stripe


def create_session(
    *,
    workspace_id: str,
    workspace_email: str,
    modules: list[str],
    stripe_customer_id: Optional[str] = None,
) -> str:
    """Crée une Checkout Session Stripe pour l'inscription au SaaS.

    `modules` est une liste comme ["essential"] ou ["essential", "phare"].
    Le socle "essential" est requis — si absent, on l'ajoute d'office.

    Renvoie l'URL Stripe vers laquelle rediriger l'utilisateur.
    """
    if "essential" not in modules:
        modules = ["essential", *modules]

    keys = config.stripe_keys()
    price_map = {
        "essential": keys["price_essential"],
        "pro":       keys["price_pro"],
        "phare":     keys["price_phare"],
    }

    line_items = []
    for m in modules:
        price_id = price_map.get(m, "")
        if not price_id:
            logger.warning("Module '%s' demandé mais STRIPE_PRICE_%s manquant",
                           m, m.upper())
            continue
        line_items.append({"price": price_id, "quantity": 1})

    if not line_items:
        raise RuntimeError("Aucun Stripe price configuré pour les modules demandés.")

    stripe = _stripe()
    kwargs: dict = {
        "mode": "subscription",
        "line_items": line_items,
        "success_url": keys["success_url"] + "?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url":  keys["cancel_url"],
        "client_reference_id": workspace_id,
        "metadata": {
            "workspace_id": workspace_id,
            "modules": ",".join(modules),
        },
        "subscription_data": {
            "metadata": {"workspace_id": workspace_id},
            "trial_period_days": 14,
        },
        "allow_promotion_codes": True,
        # Facturation EU + RGPD : on collecte l'adresse de facturation
        "billing_address_collection": "required",
        "tax_id_collection": {"enabled": True},
    }

    # Si on a déjà un Stripe Customer (cas d'un upgrade), on le réutilise.
    # Sinon Stripe en crée un sur la base de l'email saisi.
    if stripe_customer_id:
        kwargs["customer"] = stripe_customer_id
    else:
        kwargs["customer_email"] = workspace_email

    session = stripe.checkout.Session.create(**kwargs)
    return session.url
