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
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Cache court de la version base partagée (relue à chaque envoi sinon).
_SHARED_CACHE: dict = {"at": 0.0, "sigs": None}
_SHARED_TTL = 60.0


def _load_app_state():
    """Crée une instance AppState (relit settings.json à chaque appel)."""
    from ..state import AppState
    return AppState()


def _load_from_shared() -> Optional[list[dict]]:
    """Lit outreach.signatures depuis la BASE PARTAGÉE (shared_settings).

    Indispensable depuis la séparation site/robots : la boîte robots (qui
    ENVOIE) a son propre settings.json local ; la seule source vue par tout
    le monde est shared_settings. Cache 60 s pour ne pas marteler la base.
    None = base injoignable (l'appelant retombe sur le local).
    """
    now = time.time()
    if _SHARED_CACHE["sigs"] is not None and now - _SHARED_CACHE["at"] < _SHARED_TTL:
        return _SHARED_CACHE["sigs"]
    try:
        from .lagriffe.repo import _sb
        sb = _sb()
        if sb is None:
            return None
        rows = (sb.table("shared_settings").select("value")
                .eq("key", "outreach").limit(1).execute().data) or []
        val = (rows[0].get("value") if rows else {}) or {}
        raw = val.get("signatures")
        sigs = ([s for s in raw if isinstance(s, dict) and s.get("id")]
                if isinstance(raw, list) else [])
        _SHARED_CACHE["sigs"] = sigs
        _SHARED_CACHE["at"] = now
        return sigs
    except Exception as exc:
        logger.debug("signatures shared read: %s", exc)
        return None


def load_signatures(app_state=None) -> list[dict]:
    """Renvoie toutes les signatures configurées.

    Priorité à la BASE PARTAGÉE (cohérente entre site et robots), repli sur
    le fichier local (desktop, hors-ligne). Fallback ancienne version
    mono-signature : `outreach.signature` (texte) converti en liste.
    """
    shared = _load_from_shared()
    if shared:  # liste non vide en base partagée -> elle fait foi
        return shared
    if app_state is None:
        app_state = _load_app_state()
    raw = app_state.get("outreach", "signatures", default=None)
    if isinstance(raw, list) and raw:
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


def append_signature_to_html(body_html: str, account_id: str = "primary",
                             app_state=None) -> str:
    """Injecte la signature HTML de la boîte expéditrice dans un corps HTML
    de MODÈLE (celui qui garde l'aperçu du site).

    Nécessaire parce que `append_signature_to_body` ne touche QUE la version
    texte : sans ça, un mail HTML dont on a retiré la signature du modèle
    partirait sans signature chez Gmail. On insère le bloc signature juste
    avant la dernière balise fermante `</div>` du modèle (pour rester dans le
    conteneur stylé) ; à défaut, on l'ajoute à la fin.

    - Pas de signature (ou pas de version HTML) → corps HTML tel quel.
    """
    if not body_html:
        return body_html
    sig = signature_for_account(account_id, app_state=app_state)
    if not sig:
        return body_html
    sig_html = (sig.get("body_html") or "").strip()
    if not sig_html:
        # Repli : dérive un bloc HTML minimal depuis la version texte.
        sig_text = (sig.get("body_text") or "").strip()
        if not sig_text:
            return body_html
        lines = [l for l in sig_text.splitlines() if l.strip()]
        if not lines:
            return body_html
        esc = lambda s: (s.replace("&", "&amp;").replace("<", "&lt;")
                         .replace(">", "&gt;"))
        first = (f'<p style="margin-top:24px;margin-bottom:0;font-weight:600;'
                 f'color:#2a2a2a;">{esc(lines[0])}</p>')
        rest = "".join(
            f'<p style="margin-top:2px;color:#999;font-size:13px;">{esc(l)}</p>'
            for l in lines[1:])
        sig_html = first + rest
    marker = "</div>"
    idx = body_html.rfind(marker)
    if idx == -1:
        return f"{body_html.rstrip()}{sig_html}"
    return body_html[:idx] + sig_html + body_html[idx:]
