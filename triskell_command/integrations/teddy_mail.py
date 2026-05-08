"""
Intégration Teddy Mail pour Triskell Command (anciennement Pirate Life Mail).

Écrit des commandes JSON dans le dossier queue de Teddy Mail.
Teddy Mail les ramasse automatiquement (FileSystemWatcher) et envoie les emails.

Usage standard :
    from triskell_command.integrations.teddy_mail import queue_purchase_email

    queue_purchase_email(
        product="pack-electricien-pro",
        customer_email="pierre.martin@gmail.com",
        customer_name="Pierre",
        download_link="https://pack-elec.triskell-studio.fr/dl/TOKEN",
        order_id="pi_3abc123",
    )
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Chemins ──────────────────────────────────────────────────────────────────

def _teddy_data_dir() -> Path:
    """Renvoie %APPDATA%\\TeddyMail (où Teddy Mail stocke ses données).

    Si Teddy Mail n'a jamais été lancé mais l'ancienne installation
    %APPDATA%\\PirateLifeMail existe, on l'utilise en attendant que la
    migration interne soit déclenchée au prochain lancement de Teddy Mail.
    """
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        raise EnvironmentError("Variable d'environnement APPDATA introuvable")
    new_dir = Path(appdata) / "TeddyMail"
    if not new_dir.exists():
        legacy = Path(appdata) / "PirateLifeMail"
        if legacy.exists():
            return legacy
    return new_dir

def _pending_dir() -> Path:
    d = _teddy_data_dir() / "pipeline" / "pending"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _templates_dir() -> Path:
    d = _teddy_data_dir() / "pipeline" / "templates"
    d.mkdir(parents=True, exist_ok=True)
    return d

# ── Check disponibilité ───────────────────────────────────────────────────────

def is_teddy_available() -> bool:
    """
    Retourne True si Teddy Mail semble installé.
    Vérifie l'existence du dossier de données (créé au premier lancement).
    """
    try:
        return _teddy_data_dir().exists()
    except Exception:
        return False

# ── API principale ────────────────────────────────────────────────────────────

def queue_email_command(
    *,
    trigger:       str,
    product:       str,
    template_id:   str,
    customer_email: str,
    customer_name:  str,
    customer_full_name: str = "",
    variables:     dict[str, str] | None = None,
    account_id:    str | None = None,
    delay_seconds: int = 0,
) -> str:
    """
    Dépose une commande d'envoi dans la queue Teddy Mail.

    Paramètres
    ----------
    trigger       : "purchase" | "followup" | "upsell" | "custom"
    product       : id produit Triskell (ex: "pack-electricien-pro")
    template_id   : id du template dans %APPDATA%\\TeddyMail\\pipeline\\templates\\
    customer_email: adresse du destinataire
    customer_name : prénom (utilisé dans {{customer.name}})
    variables     : dict de variables supplémentaires ({{variables.clé}})
    delay_seconds : délai avant envoi en secondes (0 = immédiat)

    Retourne l'id de la commande créée.
    """
    if not customer_email or "@" not in customer_email:
        raise ValueError(f"Email invalide : {customer_email!r}")

    cmd_id = str(uuid.uuid4())
    command: dict[str, Any] = {
        "id":           cmd_id,
        "trigger":      trigger,
        "product":      product,
        "templateId":   template_id,
        "accountId":    account_id,
        "customer": {
            "email":    customer_email,
            "name":     customer_name,
            "fullName": customer_full_name or customer_name,
        },
        "variables":     variables or {},
        "delaySeconds":  delay_seconds,
        "createdAt":    datetime.now(timezone.utc).isoformat(),
    }

    # Nom de fichier : timestamp + uuid → tri naturel + unicité garantie
    ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    fname = f"{ts}_{cmd_id[:8]}.json"
    dest  = _pending_dir() / fname

    dest.write_text(json.dumps(command, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[teddy_mail] Commande %s déposée → %s", cmd_id[:8], dest.name)
    return cmd_id

# ── Helpers métier ────────────────────────────────────────────────────────────

def queue_purchase_email(
    *,
    product:       str,
    customer_email: str,
    customer_name:  str,
    download_link:  str,
    order_id:      str = "",
    account_id:    str | None = None,
) -> str:
    """
    Email de livraison immédiat après achat Stripe.
    Utilise le template « delivery-v1 » par défaut.
    """
    return queue_email_command(
        trigger        = "purchase",
        product        = product,
        template_id    = "delivery-v1",
        customer_email = customer_email,
        customer_name  = customer_name,
        account_id     = account_id,
        variables      = {
            "download_link": download_link,
            "order_id":      order_id,
        },
        delay_seconds  = 0,
    )

def queue_followup_email(
    *,
    product:       str,
    customer_email: str,
    customer_name:  str,
    delay_days:    int = 3,
    account_id:    str | None = None,
) -> str:
    """
    Email de suivi J+N après achat.
    Utilise le template « followup-j3-v1 » par défaut.
    """
    return queue_email_command(
        trigger        = "followup",
        product        = product,
        template_id    = "followup-j3-v1",
        customer_email = customer_email,
        customer_name  = customer_name,
        account_id     = account_id,
        delay_seconds  = delay_days * 86_400,
    )

def queue_upsell_email(
    *,
    product:       str,
    customer_email: str,
    customer_name:  str,
    upsell_name:   str,
    upsell_link:   str,
    delay_days:    int = 7,
    account_id:    str | None = None,
) -> str:
    """
    Email d'upsell J+N après achat.
    Utilise le template « upsell-v1 » par défaut.
    """
    return queue_email_command(
        trigger        = "upsell",
        product        = product,
        template_id    = "upsell-v1",
        customer_email = customer_email,
        customer_name  = customer_name,
        account_id     = account_id,
        variables      = {
            "upsell_name": upsell_name,
            "upsell_link": upsell_link,
        },
        delay_seconds  = delay_days * 86_400,
    )

# ── Lecture des templates existants ──────────────────────────────────────────

def list_templates() -> list[dict[str, str]]:
    """
    Liste les templates disponibles dans le dossier Teddy Mail.
    Utile pour l'UI Triskell Command (ComboBox de sélection de template).
    Retourne [{"id": ..., "name": ..., "subject": ...}, ...]
    """
    templates = []
    try:
        for f in sorted(_templates_dir().glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                templates.append({
                    "id":      data.get("id", f.stem),
                    "name":    data.get("name", f.stem),
                    "subject": data.get("subject", ""),
                })
            except Exception:
                pass
    except Exception as e:
        logger.warning("[teddy_mail] Impossible de lister les templates : %s", e)
    return templates

def count_pending() -> int:
    """Nombre de commandes en attente dans la queue Teddy Mail."""
    try:
        return len(list(_pending_dir().glob("*.json")))
    except Exception:
        return 0
