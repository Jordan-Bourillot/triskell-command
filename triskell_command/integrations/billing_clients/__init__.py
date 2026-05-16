"""Facturation des CLIENTS FINAUX de Triskell Studio (recurring Stripe).

À ne pas confondre avec `billing_saas/` :

- `billing_saas/`     : facture les WORKSPACES qui paient pour utiliser
                       Triskell Command lui-même (= notre SaaS).
- `billing_clients/`  : facture les CLIENTS FINAUX de Triskell Studio
                       (acheteurs de sites, abonnés SEO RankUs / Le Phare,
                       etc.) en mode abonnement mensuel récurrent.

Les deux flows passent par Stripe, mais utilisent des metadata
différentes (`workspace_id` vs `client_id` et `client_subscription_id`)
pour que le webhook dispatch sache où router.

Point d'entrée principal :
    from triskell_command.integrations.billing_clients import (
        create_subscription_for_client,
        cancel_subscription,
    )
"""
from .subscription_create import (
    create_subscription_for_client,
    cancel_subscription,
)

__all__ = [
    "create_subscription_for_client",
    "cancel_subscription",
]
