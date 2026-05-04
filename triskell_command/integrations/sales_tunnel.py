"""Charge le catalogue de templates Sales Tunnel sans dépendre de son installation.

Sales Tunnel vit dans Prospection/triskell_sales_tunnel/. Comme ce n'est pas
installé pip, on l'importe via sys.path en allant chercher le dossier.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _candidate_paths() -> list[Path]:
    """Chemins potentiels où trouver Prospection/triskell_sales_tunnel/."""
    here = Path(__file__).resolve()
    candidates = []
    # On remonte jusqu'à trouver "Triskell Studio" puis on cherche Prospection
    for parent in here.parents:
        if parent.name in ("Triskell Studio", "Triskell-Studio"):
            candidates.append(parent / "Prospection")
            break
    # Fallback : sibling du Triskell Command directory
    candidates.append(here.parent.parent.parent.parent / "Prospection")
    return candidates


def load_catalog() -> Any | None:
    """Tente de charger le catalogue Sales Tunnel. Renvoie None si introuvable."""
    for prospection_dir in _candidate_paths():
        if not (prospection_dir / "triskell_sales_tunnel" / "catalog.py").exists():
            continue
        if str(prospection_dir) not in sys.path:
            sys.path.insert(0, str(prospection_dir))
        try:
            from triskell_sales_tunnel import catalog  # type: ignore
            return catalog
        except Exception as exc:
            logger.debug("Échec import sales_tunnel.catalog : %s", exc)
            continue
    return None


def is_available() -> bool:
    return load_catalog() is not None


def list_products() -> list[tuple[str, str]]:
    """Liste (key, label) des produits du catalogue."""
    cat = load_catalog()
    if not cat:
        return []
    out = []
    for product in getattr(cat, "PRODUCTS", []):
        out.append((product.key, product.label))
    return out


def list_clients(product_key: str) -> list[tuple[str, str]]:
    cat = load_catalog()
    if not cat:
        return []
    for product in getattr(cat, "PRODUCTS", []):
        if product.key == product_key:
            return [(c.key, c.label) for c in product.clients]
    return []


def list_channels(product_key: str, client_key: str) -> list[tuple[str, str]]:
    """(channel, channel_label) disponibles pour ce produit/client."""
    cat = load_catalog()
    if not cat:
        return []
    labels = getattr(cat, "CHANNEL_LABELS", {})
    for product in getattr(cat, "PRODUCTS", []):
        if product.key != product_key:
            continue
        for client in product.clients:
            if client.key != client_key:
                continue
            seen = []
            for tpl in client.templates:
                if tpl.channel not in seen:
                    seen.append(tpl.channel)
            return [(ch, labels.get(ch, ch)) for ch in seen]
    return []


def get_template(
    product_key: str, client_key: str, channel: str
) -> dict | None:
    """Renvoie un dict {channel, subject, body, product, client} ou None."""
    cat = load_catalog()
    if not cat:
        return None
    for product in getattr(cat, "PRODUCTS", []):
        if product.key != product_key:
            continue
        for client in product.clients:
            if client.key != client_key:
                continue
            for tpl in client.templates:
                if tpl.channel == channel:
                    return {
                        "channel": tpl.channel,
                        "subject": tpl.subject,
                        "body": tpl.body,
                        "product": product.label,
                        "client": client.label,
                    }
    return None
