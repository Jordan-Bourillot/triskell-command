"""Création d'un abonnement Stripe pour un client final de Triskell.

Usage côté Command (depuis la fiche client ou un script) :

    from triskell_command.integrations.billing_clients import (
        create_subscription_for_client,
    )

    result = create_subscription_for_client(
        client_id="<uuid clients>",
        amount_monthly_eur=490,
        description="Référencement SEO mensuel (RankUs Studio)",
        product_kind="seo",
    )
    # → renvoie {ok, checkout_url, client_subscription_id, ...}
    # → on envoie checkout_url au client par email, il rentre sa carte une fois.

Le client clique le lien, paie son premier mois → Stripe nous renvoie
`invoice.payment_succeeded` → notre webhook génère la facture FR
conforme et l'envoie par mail. Chaque mois suivant, idem en automatique.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def create_subscription_for_client(
    *,
    client_id: str,
    amount_monthly_eur: float,
    description: str,
    product_kind: str = "seo",
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
    trial_days: int = 0,
) -> dict[str, Any]:
    """Crée un abonnement Stripe mensuel pour un client.

    Étapes :
    1. Récupère ou crée le Stripe Customer pour ce client (par email).
    2. Crée à la volée un Price récurrent mensuel pour ce montant.
    3. Crée une Stripe Checkout Session en mode subscription.
    4. Pose la ligne client_subscriptions (status=incomplete) avec la metadata.
    5. Renvoie l'URL de checkout à envoyer au client.

    Renvoie un dict :
        {ok, checkout_url, client_subscription_id, stripe_customer_id,
         price_id, error?}
    """
    if amount_monthly_eur <= 0:
        return {"ok": False, "error": "Montant doit être > 0"}
    amount_cents = int(round(amount_monthly_eur * 100))

    client = _get_client(client_id)
    if client is None:
        return {"ok": False,
                "error": f"Client introuvable : {client_id}"}

    email = (client.get("email") or "").strip()
    if not email:
        return {"ok": False, "error": "Client sans email — impossible."}

    workspace_id = client.get("workspace_id")

    # 1. Stripe Customer (réutilise s'il existe, sinon crée)
    try:
        customer_id = _get_or_create_stripe_customer(client)
    except Exception as exc:
        logger.exception("Stripe customer KO")
        return {"ok": False, "error": f"stripe customer: {exc}"}

    # 2. Price récurrent à la volée
    try:
        price_id = _create_recurring_price(
            amount_cents=amount_cents,
            description=description,
        )
    except Exception as exc:
        logger.exception("Stripe price KO")
        return {"ok": False, "error": f"stripe price: {exc}"}

    # 3. Pose la ligne client_subscriptions (status=incomplete jusqu'au paiement)
    try:
        sub_row_id = _insert_client_subscription(
            client_id=client_id,
            workspace_id=workspace_id,
            description=description,
            product_kind=product_kind,
            amount_monthly_cents=amount_cents,
            stripe_customer_id=customer_id,
            stripe_price_id=price_id,
        )
    except Exception as exc:
        logger.exception("Insert client_subscriptions KO")
        return {"ok": False, "error": f"db insert: {exc}"}

    # 4. Checkout Session
    try:
        checkout_url = _create_checkout_session(
            customer_id=customer_id,
            price_id=price_id,
            client_id=client_id,
            client_subscription_id=sub_row_id,
            workspace_id=workspace_id,
            success_url=success_url,
            cancel_url=cancel_url,
            trial_days=trial_days,
        )
    except Exception as exc:
        logger.exception("Stripe checkout KO")
        return {"ok": False, "error": f"stripe checkout: {exc}",
                "client_subscription_id": sub_row_id}

    return {
        "ok": True,
        "checkout_url": checkout_url,
        "client_subscription_id": sub_row_id,
        "stripe_customer_id": customer_id,
        "price_id": price_id,
    }


def cancel_subscription(client_subscription_id: str, *,
                         at_period_end: bool = True) -> dict[str, Any]:
    """Annule un abonnement.

    `at_period_end=True` : continue jusqu'à la fin du mois payé (recommandé).
    `at_period_end=False` : annulation immédiate, sans remboursement auto.
    """
    sub_row = _get_subscription_row(client_subscription_id)
    if sub_row is None:
        return {"ok": False, "error": "Abonnement introuvable."}
    stripe_sub_id = sub_row.get("stripe_subscription_id") or ""
    if not stripe_sub_id:
        return {"ok": False, "error": "Pas d'id Stripe sur cette ligne."}

    try:
        stripe = _stripe()
        if at_period_end:
            stripe.Subscription.modify(stripe_sub_id, cancel_at_period_end=True)
        else:
            stripe.Subscription.cancel(stripe_sub_id)
    except Exception as exc:
        logger.exception("Stripe cancel KO")
        return {"ok": False, "error": f"stripe: {exc}"}

    return {"ok": True, "stripe_subscription_id": stripe_sub_id,
            "at_period_end": at_period_end}


# ---------------------------------------------------------------------------
# Helpers Stripe
# ---------------------------------------------------------------------------
def _stripe():
    """Lazy-import du SDK Stripe avec la même clé que billing_saas."""
    from ..billing_saas.checkout import _stripe as _stripe_saas
    return _stripe_saas()


def _get_or_create_stripe_customer(client: dict) -> str:
    """Renvoie le stripe_customer_id du client (créé si besoin).

    Si client.stripe_customer_id existe → on le réutilise.
    Sinon → on crée un nouveau Customer Stripe et on patch la ligne.
    """
    existing = (client.get("stripe_customer_id") or "").strip()
    if existing:
        return existing

    stripe = _stripe()

    full_name = " ".join(filter(None, [
        client.get("first_name") or "",
        client.get("last_name") or "",
    ])).strip() or (client.get("company_name") or "Client")

    customer_params: dict[str, Any] = {
        "email": client["email"],
        "name": full_name,
        "metadata": {
            "client_id": client["id"],
            "source": "triskell_command",
        },
    }
    if client.get("phone"):
        customer_params["phone"] = client["phone"]

    addr = {
        "line1": client.get("address_line1") or "",
        "line2": client.get("address_line2") or "",
        "postal_code": client.get("address_zip") or "",
        "city": client.get("address_city") or "",
        "country": _country_code(client.get("address_country") or "France"),
    }
    if addr["line1"]:
        customer_params["address"] = addr

    customer = stripe.Customer.create(**customer_params)
    customer_id = customer.id

    # Patch la ligne clients pour la prochaine fois
    try:
        sb = _sb()
        if sb is not None:
            sb.table("clients").update(
                {"stripe_customer_id": customer_id}
            ).eq("id", client["id"]).execute()
    except Exception as exc:
        logger.debug("update clients.stripe_customer_id: %s", exc)

    return customer_id


def _create_recurring_price(*, amount_cents: int, description: str) -> str:
    """Crée un Price Stripe mensuel à la volée.

    Pour Triskell, chaque abonnement client a son propre Price (montants
    parfois sur-mesure). On ne réutilise pas — la simplicité prime sur
    la dédup Stripe.
    """
    stripe = _stripe()
    product = stripe.Product.create(
        name=description[:120] or "Abonnement Triskell",
    )
    price = stripe.Price.create(
        unit_amount=amount_cents,
        currency="eur",
        recurring={"interval": "month"},
        product=product.id,
    )
    return price.id


def _create_checkout_session(
    *,
    customer_id: str,
    price_id: str,
    client_id: str,
    client_subscription_id: str,
    workspace_id: Optional[str],
    success_url: Optional[str],
    cancel_url: Optional[str],
    trial_days: int = 0,
) -> str:
    """Crée la Checkout Session Stripe et renvoie l'URL.

    La metadata `client_id` + `client_subscription_id` permet au webhook
    de router cet abonnement vers la facturation client (pas SaaS).
    """
    stripe = _stripe()
    success_url = success_url or "https://command.triskell-studio.fr/?stripe=ok"
    cancel_url = cancel_url or "https://command.triskell-studio.fr/?stripe=cancel"

    metadata = {
        "client_id": client_id,
        "client_subscription_id": client_subscription_id,
    }
    if workspace_id:
        metadata["workspace_id"] = workspace_id  # pour les requêtes scopées

    kwargs: dict[str, Any] = {
        "mode": "subscription",
        "customer": customer_id,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": client_id,
        "metadata": metadata,
        "subscription_data": {
            "metadata": metadata,
        },
        "billing_address_collection": "required",
        "tax_id_collection": {"enabled": True},
        "allow_promotion_codes": True,
    }
    if trial_days and trial_days > 0:
        kwargs["subscription_data"]["trial_period_days"] = int(trial_days)

    session = stripe.checkout.Session.create(**kwargs)
    return session.url


# ---------------------------------------------------------------------------
# Helpers DB (Supabase)
# ---------------------------------------------------------------------------
def _sb():
    """Renvoie un client Supabase service_role (write-capable)."""
    try:
        from ..billing import repo as billing_repo
        return billing_repo._sb()
    except Exception as exc:
        logger.debug("_sb: %s", exc)
        return None


def _get_client(client_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("clients").select("*")
                .eq("id", client_id).limit(1).execute().data) or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("_get_client: %s", exc)
        return None


def _insert_client_subscription(
    *,
    client_id: str,
    workspace_id: Optional[str],
    description: str,
    product_kind: str,
    amount_monthly_cents: int,
    stripe_customer_id: str,
    stripe_price_id: str,
) -> str:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase indisponible.")
    row = {
        "client_id": client_id,
        "description": description,
        "product_kind": product_kind,
        "amount_monthly_cents": amount_monthly_cents,
        "stripe_customer_id": stripe_customer_id,
        "stripe_price_id": stripe_price_id,
        "status": "incomplete",
    }
    if workspace_id:
        row["workspace_id"] = workspace_id
    result = sb.table("client_subscriptions").insert(row).execute()
    data = result.data or []
    if not data:
        raise RuntimeError("Insert client_subscriptions a renvoyé vide.")
    return data[0]["id"]


def _get_subscription_row(client_subscription_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("client_subscriptions").select("*")
                .eq("id", client_subscription_id).limit(1).execute().data) or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("_get_subscription_row: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Pays → code ISO 2 lettres (suffisant pour Stripe)
# ---------------------------------------------------------------------------
_COUNTRY_TO_ISO = {
    "france": "FR", "belgique": "BE", "suisse": "CH", "luxembourg": "LU",
    "canada": "CA", "espagne": "ES", "italie": "IT", "allemagne": "DE",
    "portugal": "PT", "royaume-uni": "GB", "etats-unis": "US",
    "états-unis": "US",
}


def _country_code(country: str) -> str:
    """Renvoie un code ISO 2 lettres pour Stripe (défaut FR)."""
    if not country:
        return "FR"
    c = country.strip().lower()
    if len(c) == 2:
        return c.upper()
    return _COUNTRY_TO_ISO.get(c, "FR")
