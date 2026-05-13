"""Facturation Triskell — point d'entrée unique.

DESTINATION FINALE :
    Triskell\\triskell-command\\triskell_command\\integrations\\billing\\__init__.py

Usage côté reste du repo :

    from triskell_command.integrations.billing import (
        get_provider, InvoiceRequest, InvoiceLine, ClientInfo,
    )

    provider = get_provider()
    result = provider.generate_invoice(InvoiceRequest(
        client=ClientInfo(name="...", email="..."),
        lines=[InvoiceLine(description="...", quantity=1, unit_price_ht_cents=29900)],
        payment_method="stripe", payment_reference=session_id,
        paid_at=datetime.now(timezone.utc),
    ))

Aucun appelant ne doit importer `triskell_native.py` directement.
"""
from .interface import (
    BillingProvider,
    ClientInfo,
    InvoiceLine,
    InvoiceRequest,
    InvoiceResult,
)
from .triskell_native import BillingError, TriskellNativeProvider

_PROVIDER: BillingProvider | None = None


def get_provider() -> BillingProvider:
    """Renvoie l'instance partagée du provider de facturation."""
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = TriskellNativeProvider()
    return _PROVIDER


__all__ = [
    "BillingProvider",
    "BillingError",
    "ClientInfo",
    "InvoiceLine",
    "InvoiceRequest",
    "InvoiceResult",
    "get_provider",
]
