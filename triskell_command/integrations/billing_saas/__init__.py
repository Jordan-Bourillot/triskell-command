"""Facturation SaaS de Triskell Command.

Ne PAS confondre avec `integrations/billing/` qui facture les CLIENTS de
Triskell Studio (leurs propres factures à eux).

Ce package-ci gère l'abonnement que CHAQUE workspace paie à Triskell
Command lui-même (Stripe Customer + Subscription + webhooks).

Trois fichiers :
  - config.py       : lecture des secrets Stripe (depuis env vars ou settings)
  - checkout.py     : créer une session de checkout (nouveau client)
  - portal.py       : créer une session Customer Portal (gestion abonnement)
  - webhook.py      : recevoir et traiter les events Stripe
  - plans.py        : catalogue des plans (Essentiel, +Pro, +Le Phare, …)
"""

from .plans import PLANS, plan_for_modules
from .config import is_configured, stripe_keys

__all__ = ["PLANS", "plan_for_modules", "is_configured", "stripe_keys"]
