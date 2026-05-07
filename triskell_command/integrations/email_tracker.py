"""Tracking des ouvertures de mail via pixel transparent.

Comment ça marche :
  1. Avant d'envoyer un mail, on génère un ID unique (`tracking_id`).
  2. On injecte un <img> 1x1 transparent dans le HTML du mail, pointant
     vers `https://<endpoint>/pix?id=<tracking_id>`.
  3. L'endpoint Netlify Function (cf. `netlify_functions/track-pixel.js`)
     reçoit le hit quand le client charge l'image (= ouvre le mail), et
     écrit une ligne dans `email_history` avec kind='email_opened'.
  4. La vue Funnel et la Santé peuvent lire ces opens.

Limites connues :
  - Outlook desktop charge les images (open détecté).
  - Apple Mail Privacy Protection précharge tout (faux positifs ~30%).
  - Gmail webmail charge via leur proxy (open détecté mais IP du proxy).
  - Si le client bloque les images → pas de détection (faux négatifs).

C'est imparfait mais c'est le standard de l'industrie (Mailchimp,
HubSpot, lemlist le font tous comme ça).
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from typing import Optional

logger = logging.getLogger(__name__)


SHARED_KEY = "email_tracker"


DEFAULT_CONFIG = {
    "enabled": False,
    # URL publique de la Netlify Function déployée par Jordan
    # ex: "https://triskell-track.netlify.app/.netlify/functions/track-pixel"
    "pixel_endpoint": "",
}


def load_config(client=None) -> dict:
    if client:
        try:
            raw = client.get_shared_setting(SHARED_KEY, {}) or {}
            if isinstance(raw, str):
                try: raw = json.loads(raw)
                except Exception: raw = {}
            if isinstance(raw, dict) and raw:
                return {**DEFAULT_CONFIG, **raw}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config: dict, client=None) -> None:
    if client:
        client.set_shared_setting(SHARED_KEY, config)


def generate_tracking_id() -> str:
    """ID opaque, non-devinable, court (URL-safe)."""
    return secrets.token_urlsafe(12)


def build_pixel_html(tracking_id: str, endpoint: str,
                      *, prospect_id: str = "") -> str:
    """Renvoie le snippet HTML <img> à coller à la fin du body."""
    if not endpoint or not tracking_id:
        return ""
    qs = f"?id={tracking_id}"
    if prospect_id:
        qs += f"&p={prospect_id}"
    # Style invisible (1x1 transparent) + alt vide
    return (
        f'<img src="{endpoint}{qs}" '
        f'width="1" height="1" border="0" '
        f'style="height:1px!important;width:1px!important;border-width:0!important;'
        f'margin:0!important;padding:0!important;display:block!important" '
        f'alt="" />'
    )


def inject_into_html(html_body: str, pixel_snippet: str) -> str:
    """Injecte le pixel juste avant </body> ou en fin de string."""
    if not pixel_snippet:
        return html_body
    if "</body>" in html_body.lower():
        return re.sub(
            r"</body>", pixel_snippet + r"</body>",
            html_body, count=1, flags=re.IGNORECASE,
        )
    return html_body + pixel_snippet


def wrap_plain_in_html(plain_body: str) -> str:
    """Convertit un mail plain text en HTML minimal pour pouvoir
    injecter le pixel. Conserve les sauts de ligne."""
    import html as _html
    escaped = _html.escape(plain_body).replace("\n", "<br>")
    return f"<html><body>{escaped}</body></html>"


def prepare_tracked_body(body: str, *,
                         tracking_id: str, endpoint: str,
                         prospect_id: str = "",
                         already_html: bool = False) -> str:
    """Prend un body (plain ou html), injecte le pixel et renvoie le HTML.

    Si `already_html=False`, on convertit d'abord le plain en HTML.
    """
    pixel = build_pixel_html(tracking_id, endpoint, prospect_id=prospect_id)
    if not pixel:
        return body
    if not already_html:
        body = wrap_plain_in_html(body)
    return inject_into_html(body, pixel)
