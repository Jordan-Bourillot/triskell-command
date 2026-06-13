"""Désinscription en 1 clic — liens signés + en-têtes + pied de mail.

But : offrir un VRAI mécanisme de désinscription, pas seulement l'en-tête
mailto historique (qui dépendait d'une réponse + classification IA, donc
fragile). Ici :

- chaque mail de prospection porte un lien HTTPS signé, unique au
  destinataire (impossible à falsifier sans le secret) ;
- les en-têtes `List-Unsubscribe` (URL + mailto) et
  `List-Unsubscribe-Post: List-Unsubscribe=One-Click` (RFC 8058) font
  apparaître le bouton « Se désabonner » natif de Gmail/Yahoo, en 1 clic ;
- un pied de mail discret donne le même lien, cliquable, dans le corps ;
- l'endpoint `/api/unsubscribe` traite le clic et passe le prospect en
  statut « unsubscribed » (définitif, plus jamais recontacté).

Sécurité du lien : `token = base64url(payload) + "." + hmac_sha256(payload)`.
On ne désinscrit que si la signature est valide. Le GET affiche une page
de confirmation (anti-préchargement par les antivirus/proxies) ; seul le
POST agit — c'est aussi celui qu'utilise le one-click des messageries.

Secret : `UNSUBSCRIBE_SECRET` ou, à défaut, `SESSION_SECRET` (déjà posé en
prod pour les cookies), ou, en dernier recours, un secret auto-généré
stocké dans shared_settings. JAMAIS de secret en dur.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets as _secrets

logger = logging.getLogger(__name__)

_SHARED_SECRET_KEY = "unsubscribe_secret"
_DEFAULT_BASE_URL = "https://command.triskell-studio.fr"

# Cache process-local du secret (évite de relire shared_settings à chaque
# mail). Rempli au premier appel de _secret().
_SECRET_CACHE: str = ""


# ---------------------------------------------------------------------------
# Secret & base URL
# ---------------------------------------------------------------------------
def _sb_client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        return c if getattr(c, "is_authenticated", False) else None
    except Exception:
        return None


def _secret() -> str:
    """Résout le secret de signature (stable). Voir docstring du module."""
    global _SECRET_CACHE
    if _SECRET_CACHE:
        return _SECRET_CACHE
    env = (os.environ.get("UNSUBSCRIBE_SECRET")
           or os.environ.get("SESSION_SECRET") or "").strip()
    if env:
        _SECRET_CACHE = env
        return env
    # Dernier recours : secret persistant dans shared_settings (auto-généré
    # une seule fois). Si Supabase est indispo, secret éphémère + warning :
    # les liens ne survivront pas à un redémarrage, mais rien ne casse.
    sb = _sb_client()
    if sb is not None:
        try:
            stored = (sb.get_shared_setting(_SHARED_SECRET_KEY, "") or "").strip()
            if stored:
                _SECRET_CACHE = stored
                return stored
            new_secret = _secrets.token_hex(32)
            try:
                from . import shared_settings_db
                shared_settings_db.upsert_setting(
                    sb.raw, _SHARED_SECRET_KEY, new_secret)
            except Exception:
                sb.set_shared_setting(_SHARED_SECRET_KEY, new_secret)
            _SECRET_CACHE = new_secret
            return new_secret
        except Exception as exc:
            logger.warning("unsubscribe._secret shared_settings KO: %s", exc)
    if not getattr(_secret, "_warned", False):
        logger.warning(
            "Aucun UNSUBSCRIBE_SECRET / SESSION_SECRET et shared_settings "
            "indisponible → secret de désinscription ÉPHÉMÈRE (les liens "
            "casseront au redémarrage). Définis SESSION_SECRET en prod.")
        _secret._warned = True  # type: ignore[attr-defined]
    _SECRET_CACHE = _secrets.token_hex(32)
    return _SECRET_CACHE


def base_url() -> str:
    """URL publique de base, sans slash final."""
    raw = (os.environ.get("PUBLIC_BASE_URL")
           or os.environ.get("APP_BASE_URL") or _DEFAULT_BASE_URL).strip()
    return raw.rstrip("/")


# ---------------------------------------------------------------------------
# Token signé
# ---------------------------------------------------------------------------
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(txt: str) -> bytes:
    pad = "=" * (-len(txt) % 4)
    return base64.urlsafe_b64decode(txt + pad)


def _sign(payload: str) -> str:
    return hmac.new(_secret().encode("utf-8"),
                    payload.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:24]


def make_token(email: str, prospect_id: str = "") -> str:
    """Jeton signé encodant l'adresse (et l'id de fiche si connu)."""
    payload = f"{(email or '').strip().lower()}|{(prospect_id or '').strip()}"
    return f"{_b64e(payload.encode('utf-8'))}.{_sign(payload)}"


def verify_token(token: str) -> dict | None:
    """Vérifie un jeton. Renvoie {'email', 'prospect_id'} ou None si KO."""
    try:
        b64, sig = (token or "").split(".", 1)
    except ValueError:
        return None
    try:
        payload = _b64d(b64).decode("utf-8")
    except Exception:
        return None
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    email, _, prospect_id = payload.partition("|")
    if not email:
        return None
    return {"email": email, "prospect_id": prospect_id}


def unsubscribe_url(email: str, prospect_id: str = "") -> str:
    """URL HTTPS de désinscription pour ce destinataire."""
    return f"{base_url()}/api/unsubscribe?u={make_token(email, prospect_id)}"


# ---------------------------------------------------------------------------
# En-têtes & pied de mail
# ---------------------------------------------------------------------------
def headers_for(from_email: str, to_email: str,
                prospect_id: str = "") -> dict:
    """En-têtes de désinscription pour un mail de prospection.

    Inclut le lien HTTPS (one-click) ET le mailto en repli. Si l'adresse
    destinataire manque, on retombe sur le mailto seul (comportement
    historique) — jamais de lien invalide.
    """
    addr = (from_email or "").strip()
    to = (to_email or "").strip()
    if not to:
        # Repli : en-tête mailto seul (comme avant la désinscription 1-clic).
        return ({"List-Unsubscribe": f"<mailto:{addr}?subject=unsubscribe>"}
                if addr else {})
    url = unsubscribe_url(to, prospect_id)
    mailto = f"<mailto:{addr}?subject=unsubscribe>" if addr else ""
    value = f"<{url}>" + (f", {mailto}" if mailto else "")
    return {
        "List-Unsubscribe": value,
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def footer_text(to_email: str, prospect_id: str = "") -> str:
    """Pied texte discret avec le lien de désinscription."""
    url = unsubscribe_url(to_email, prospect_id)
    return ("\n\n—\n"
            "Vous recevez ce message car votre activité professionnelle "
            "correspond à nos services. Pour ne plus jamais être contacté : "
            f"{url}")


def footer_html(to_email: str, prospect_id: str = "") -> str:
    """Pied HTML discret avec le lien de désinscription."""
    url = unsubscribe_url(to_email, prospect_id)
    return (
        '<div style="margin-top:24px;padding-top:12px;'
        'border-top:1px solid #e5e7eb;color:#9ca3af;'
        'font-size:12px;line-height:1.5;font-family:Arial,sans-serif;">'
        "Vous recevez ce message car votre activité professionnelle "
        "correspond à nos services.<br>"
        f'<a href="{url}" style="color:#9ca3af;text-decoration:underline;">'
        "Ne plus jamais être contacté</a>."
        "</div>")


def inject_footer(body_text: str, body_html: str,
                  to_email: str, prospect_id: str = "") -> tuple:
    """Ajoute le pied de désinscription au texte ET au HTML.

    Idempotent : si le lien est déjà présent (re-rendu, double appel), on
    ne l'ajoute pas deux fois.
    """
    to = (to_email or "").strip()
    if not to:
        return body_text, body_html
    txt = body_text or ""
    if "/api/unsubscribe?u=" not in txt:
        txt = f"{txt.rstrip()}{footer_text(to, prospect_id)}"
    html = body_html or ""
    if html and "/api/unsubscribe?u=" not in html:
        html = f"{html}{footer_html(to, prospect_id)}"
    return txt, html


# ---------------------------------------------------------------------------
# Traitement d'une désinscription
# ---------------------------------------------------------------------------
def process_unsubscribe(token: str) -> dict:
    """Vérifie le jeton et passe le(s) prospect(s) en 'unsubscribed'.

    Renvoie {"ok": bool, "email": str, "already": bool, "error": str}.
    Idempotent : un 2e clic renvoie ok=True (already=True).
    """
    info = verify_token(token)
    if not info:
        return {"ok": False, "error": "lien invalide ou expiré"}
    email = info["email"]
    prospect_id = info.get("prospect_id") or ""
    sb = _sb_client()
    if sb is None:
        return {"ok": False, "email": email,
                "error": "service indisponible, réessayez plus tard"}
    try:
        from . import prospect_status as PS
        if prospect_id:
            PS.mark_unsubscribed(sb, prospect_id,
                                 reason="clic lien de désinscription")
        n = PS.mark_unsubscribed_by_email(
            sb, email, reason="clic lien de désinscription")
        return {"ok": True, "email": email, "count": n}
    except Exception as exc:
        logger.warning("process_unsubscribe KO: %s", exc)
        return {"ok": False, "email": email,
                "error": "service indisponible, réessayez plus tard"}
