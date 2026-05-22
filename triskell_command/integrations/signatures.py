"""Signatures mail — résolution + injection automatique au moment de l'envoi.

Source de vérité : settings.json → outreach.signatures (liste). Chaque
signature peut être liée à plusieurs comptes mail via `account_ids`.
Pour le compte principal, account_id = "primary".

Approche : avant d'envoyer un mail (ou de créer un draft), on appelle
`append_signature_to_body(body, account_id)` qui ajoute la signature
texte de la boîte expéditrice à la fin du corps du mail. L'IA n'a pas
à s'en occuper — elle écrit jusqu'à "Cordialement, {prénom}" et la
signature complète (entreprise, lien, etc.) est collée derrière.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _load_app_state():
    """Crée une instance AppState (relit settings.json à chaque appel)."""
    from ..state import AppState
    return AppState()


def load_signatures(app_state=None) -> list[dict]:
    """Renvoie toutes les signatures configurées.

    Fallback ancienne version mono-signature : si `outreach.signature`
    existe (ancien champ texte), on le convertit en liste à la volée.
    """
    if app_state is None:
        app_state = _load_app_state()
    raw = app_state.get("outreach", "signatures", default=None)
    if isinstance(raw, list):
        return [s for s in raw if isinstance(s, dict) and s.get("id")]
    legacy_text = app_state.get("outreach", "signature", default="") or ""
    legacy_html = app_state.get("outreach", "signature_html", default="") or ""
    if legacy_text or legacy_html:
        return [{
            "id": "default",
            "name": "Ma signature",
            "body_text": legacy_text,
            "body_html": legacy_html,
            "account_ids": [],
        }]
    return []


def signature_for_account(account_id: str = "primary",
                          app_state=None) -> Optional[dict]:
    """Renvoie la signature à utiliser pour un compte donné (dict ou None).

    Stratégie : 1ère signature dont account_ids contient le compte,
    sinon 1ère signature sans contrainte (account_ids vide), sinon None.
    """
    aid = (account_id or "primary").strip()
    sigs = load_signatures(app_state=app_state)
    match = next((s for s in sigs if aid in (s.get("account_ids") or [])), None)
    if match is None:
        match = next((s for s in sigs if not (s.get("account_ids") or [])), None)
    return match


def append_signature_to_body(body: str, account_id: str = "primary",
                              app_state=None) -> str:
    """Ajoute la signature liée au compte expéditeur à la fin du corps.

    - Pas de signature configurée → renvoie le corps tel quel.
    - Sinon : 2 sauts de ligne entre le corps et la signature.
    """
    sig = signature_for_account(account_id, app_state=app_state)
    if not sig:
        return body
    sig_text = (sig.get("body_text") or "").strip()
    if not sig_text:
        return body
    return f"{(body or '').rstrip()}\n\n{sig_text}"
