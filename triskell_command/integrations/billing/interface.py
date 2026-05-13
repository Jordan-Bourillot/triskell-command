"""Contrat abstrait pour la facturation Triskell.

DESTINATION FINALE :
    Triskell\\triskell-command\\triskell_command\\integrations\\billing\\interface.py

Une seule implémentation est en service (`triskell_native.py`). L'interface
existe par hygiène : si un jour on devait basculer sur un autre fournisseur
(éventualité actuellement écartée par Jordan), le code appelant n'aurait
rien à changer.

Aucun import direct du SDK ou de la table Supabase ne doit fuir hors de
`triskell_native.py`. Le reste du repo passe par `get_provider()`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


# =====================================================================
# Types valeurs (immutables, sérialisables JSON)
# =====================================================================
@dataclass
class InvoiceLine:
    description: str
    quantity: float
    unit_price_ht_cents: int      # prix unitaire HT en centimes
    vat_rate: float = 0.0         # 0.20 pour 20%, 0.0 si franchise

    @property
    def total_ht_cents(self) -> int:
        return round(self.quantity * self.unit_price_ht_cents)

    @property
    def total_vat_cents(self) -> int:
        return round(self.total_ht_cents * self.vat_rate)

    @property
    def total_ttc_cents(self) -> int:
        return self.total_ht_cents + self.total_vat_cents

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "quantity": self.quantity,
            "unit_price_ht_cents": self.unit_price_ht_cents,
            "vat_rate": self.vat_rate,
            "total_ht_cents": self.total_ht_cents,
            "total_vat_cents": self.total_vat_cents,
            "total_ttc_cents": self.total_ttc_cents,
        }


@dataclass
class ClientInfo:
    name: str                                # raison sociale ou nom complet
    email: str
    address_line1: str = ""
    address_line2: str = ""
    address_zip: str = ""
    address_city: str = ""
    address_country: str = "France"
    siret: str = ""                          # SIRET si pro
    tva_intra: str = ""                      # numéro TVA intracom si applicable

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class InvoiceRequest:
    """Tout ce qu'il faut pour émettre une facture."""
    client: ClientInfo
    lines: list[InvoiceLine]
    payment_method: str = "manuel"          # "stripe" | "sepa" | "manuel" | "carte"
    payment_reference: str = ""
    paid_at: Optional[datetime] = None       # si déjà payé (Stripe)
    service_executed_at: Optional[date] = None  # défaut = aujourd'hui
    due_date: Optional[date] = None         # défaut = aujourd'hui si déjà payé, sinon +30j
    deal_id: Optional[str] = None
    client_id: Optional[str] = None
    is_subscription: bool = False
    subscription_period: Optional[str] = None  # "2026-05"
    free_text_top: str = ""                 # zone libre haut de facture (ex: "Référence devis...")
    free_text_bottom: str = ""              # zone libre bas (conditions particulières)


@dataclass
class InvoiceResult:
    invoice_id: str
    invoice_number: str
    pdf_url: str                            # URL signée Supabase Storage
    pdf_bytes: bytes
    pdf_sha256: str
    issued_at: datetime
    subtotal_ht_cents: int
    total_vat_cents: int
    total_ttc_cents: int


# =====================================================================
# Provider
# =====================================================================
class BillingProvider(ABC):
    @abstractmethod
    def generate_invoice(self, request: InvoiceRequest) -> InvoiceResult:
        """Émet une nouvelle facture. Numérotation réservée atomiquement,
        PDF généré, stocké, archivé. Idempotent uniquement si l'appelant
        garantit l'idempotence (ex : check préalable sur stripe_session_id).
        """
        ...

    @abstractmethod
    def generate_credit_note(self, invoice_id: str, reason: str) -> InvoiceResult:
        """Émet un avoir lié à une facture existante. Crée une nouvelle
        entrée série "AV" avec montants négatifs, marque la facture
        originale `is_cancelled=true`.
        """
        ...

    @abstractmethod
    def get_invoice(self, invoice_id: str) -> Optional[dict]:
        ...

    @abstractmethod
    def get_invoice_pdf_url(self, invoice_id: str, *, signed_ttl_seconds: int = 3600) -> str:
        """Renvoie une URL Supabase Storage signée temporaire vers le PDF."""
        ...

    @abstractmethod
    def list_invoices(
        self,
        *,
        client_id: Optional[str] = None,
        client_email: Optional[str] = None,
        year: Optional[int] = None,
        limit: int = 100,
    ) -> list[dict]:
        ...

    @abstractmethod
    def export_fec(self, year: int) -> bytes:
        """Exporte le Fichier des Écritures Comptables pour une année
        donnée, au format légal DGFiP (TXT pipe-separated, UTF-8 BOM).
        """
        ...
