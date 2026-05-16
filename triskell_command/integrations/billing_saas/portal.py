"""Crée des sessions Stripe Customer Portal pour la gestion d'abonnement.

Le Customer Portal Stripe permet à l'utilisateur de :
- voir ses factures
- mettre à jour son moyen de paiement
- changer de plan
- résilier (= cancel_at_period_end)

Tout ça sans qu'on ait à coder une seule UI côté nous.
"""

from __future__ import annotations

from .checkout import _stripe
from . import config


def create_session(stripe_customer_id: str, *, return_url: str = "") -> str:
    """Renvoie l'URL Customer Portal pour un client donné."""
    if not stripe_customer_id:
        raise ValueError("stripe_customer_id requis")

    stripe = _stripe()
    return_url = return_url or config.stripe_keys()["success_url"]

    session = stripe.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=return_url,
    )
    return session.url
