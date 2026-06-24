"""Studio d'images — génération par IA (modèle FLUX, via Pollinations).

Transforme une description écrite en image. On passe par **Pollinations**
(image.pollinations.ai) qui sert le modèle FLUX **gratuitement, sans clé ni
compte** : une simple requête GET sur une URL renvoie directement l'image.
C'est la méthode déjà utilisée (et éprouvée) pour illustrer le livre de
Jordan — aucune carte bancaire, rien à configurer.

  GET https://image.pollinations.ai/prompt/<description>?width=..&height=..&seed=..&model=flux&nologo=true
  → renvoie directement un JPEG.

L'image est ensuite archivée sur Supabase Storage (bucket public déjà en
place) pour la galerie. Tout l'archivage est « best effort » : s'il échoue,
l'image est quand même renvoyée au navigateur (data URL) pour affichage et
téléchargement immédiats ; seul l'historique persistant est perdu.

Évolution possible (non branchée) : une qualité « premium » payante via
l'API officielle Black Forest Labs (clé requise). Pas nécessaire ici.
"""

from __future__ import annotations

import base64
import logging
import os
import random
from datetime import datetime, timezone
from urllib.parse import quote

logger = logging.getLogger(__name__)

# --- Pollinations (FLUX gratuit, sans clé) ---------------------------------

_POLL_BASE = (os.environ.get("POLLINATIONS_BASE")
              or "https://image.pollinations.ai").rstrip("/")
_POLL_MODEL = os.environ.get("POLLINATIONS_MODEL") or "flux"

# « Styles » = quelques mots-clés ajoutés discrètement à la description pour
# orienter le rendu. C'est plus parlant qu'un nom de modèle technique.
STYLES = [
    {"id": "photo", "label": "Photo réaliste",
     "suffix": "photorealistic, professional photography, natural light, sharp focus, high detail"},
    {"id": "illustration", "label": "Illustration / dessin",
     "suffix": "illustration, hand drawn, soft colors, artistic, clean lines"},
    {"id": "rendu3d", "label": "3D / rendu",
     "suffix": "3d render, octane render, cinematic lighting, highly detailed"},
    {"id": "aquarelle", "label": "Aquarelle douce",
     "suffix": "soft watercolor on textured paper, warm muted palette, gentle, painterly"},
    {"id": "aucun", "label": "Aucun (tel quel)", "suffix": ""},
]
DEFAULT_STYLE = "photo"

# Formats proposés → pixels. Pollinations accepte n'importe quelle taille ;
# on reste sur des valeurs rondes et nettes.
FORMATS = [
    {"id": "paysage",  "label": "Paysage (3:2)",         "w": 1216, "h": 832},
    {"id": "carre",    "label": "Carré (1:1)",           "w": 1024, "h": 1024},
    {"id": "portrait", "label": "Portrait (2:3)",        "w": 832,  "h": 1216},
    {"id": "large",    "label": "Bannière large (16:9)", "w": 1344, "h": 768},
]
DEFAULT_FORMAT = "paysage"

_HISTORY_KEY = "flux_history"
_HISTORY_MAX = 60
_BUCKET = "pp-client-photos"  # bucket public déjà en place — réutilisé


# --- Helpers ---------------------------------------------------------------

def list_styles() -> list[dict]:
    return [{"id": s["id"], "label": s["label"]} for s in STYLES]


def list_formats() -> list[dict]:
    return [dict(f) for f in FORMATS]


def _style(style_id) -> dict:
    for s in STYLES:
        if s["id"] == style_id:
            return s
    for s in STYLES:
        if s["id"] == DEFAULT_STYLE:
            return s
    return STYLES[0]


def _format(format_id) -> dict:
    for f in FORMATS:
        if f["id"] == format_id:
            return f
    for f in FORMATS:
        if f["id"] == DEFAULT_FORMAT:
            return f
    return FORMATS[0]


def compose_prompt(prompt: str, style: dict) -> str:
    """Description finale envoyée au modèle (description + style)."""
    prompt = (prompt or "").strip()
    suffix = (style or {}).get("suffix") or ""
    full = f"{prompt}. {suffix}".strip() if suffix else prompt
    return full[:1500]


def build_url(prompt: str, style: dict, fmt: dict, seed: int) -> str:
    """Construit l'URL Pollinations (fonction pure, testable)."""
    full = compose_prompt(prompt, style)
    return (f"{_POLL_BASE}/prompt/{quote(full, safe='')}"
            f"?width={fmt['w']}&height={fmt['h']}&seed={int(seed)}"
            f"&model={_POLL_MODEL}&nologo=true")


# --- Supabase (archivage + historique) -------------------------------------

def _sb_client(client=None):
    if client is not None:
        return client if getattr(client, "is_authenticated", False) else None
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        return c if getattr(c, "is_authenticated", False) else None
    except Exception:
        return None


def _public_url(path: str) -> str:
    base = (os.environ.get("SUPABASE_URL")
            or os.environ.get("PIXEL_PROS_SUPABASE_URL") or "").rstrip("/")
    return f"{base}/storage/v1/object/public/{_BUCKET}/{path}" if base else ""


def _archive(img_bytes: bytes, img_id: str, ext: str, client=None) -> str:
    """Archive l'image sur Supabase Storage. Renvoie l'URL publique ou ""."""
    c = _sb_client(client)
    if c is None:
        return ""
    path = f"flux/{img_id}.{ext}"
    ctype = "image/png" if ext == "png" else "image/jpeg"
    try:
        c.raw.storage.from_(_BUCKET).upload(
            path=path, file=img_bytes,
            file_options={"content-type": ctype, "upsert": "true"})
    except Exception as exc:
        logger.warning("flux archive upload: %s", exc)
        return ""
    return _public_url(path)


def _load_history(client=None) -> list:
    c = _sb_client(client)
    if c is None:
        return []
    try:
        raw = c.get_shared_setting(_HISTORY_KEY, []) or []
        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        return raw if isinstance(raw, list) else []
    except Exception as exc:
        logger.debug("flux load history: %s", exc)
        return []


def _save_history(items: list, client=None) -> None:
    c = _sb_client(client)
    if c is None:
        return
    try:
        c.set_shared_setting(_HISTORY_KEY, items[:_HISTORY_MAX])
    except Exception as exc:
        logger.warning("flux save history: %s", exc)


def list_history(client=None) -> list:
    return _load_history(client)[:_HISTORY_MAX]


def delete_history_item(img_id: str, client=None) -> dict:
    img_id = (img_id or "").strip()
    items = _load_history(client)
    kept = [it for it in items if it.get("id") != img_id]
    _save_history(kept, client)
    c = _sb_client(client)
    if c is not None and img_id:
        for ext in ("jpg", "png"):
            try:
                c.raw.storage.from_(_BUCKET).remove([f"flux/{img_id}.{ext}"])
            except Exception:
                pass
    return {"ok": True, "history": kept}


# --- Cœur : la génération --------------------------------------------------

def generate(prompt, *, style_id=DEFAULT_STYLE, format_id=DEFAULT_FORMAT,
             seed=None, client=None, app_state=None) -> dict:
    """Génère une image (gratuit, Pollinations). Renvoie
    {ok, image:{id, prompt, url, data_url, ...}} ou {ok:False, error}."""
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "Décris d'abord l'image que tu veux."}

    try:
        import requests
    except Exception:
        return {"ok": False, "error": "Module réseau indisponible côté serveur."}

    style = _style(style_id)
    fmt = _format(format_id)
    if seed in (None, ""):
        seed = random.randint(1, 2_000_000_000)   # varie à chaque génération
    else:
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            seed = random.randint(1, 2_000_000_000)

    img_url = build_url(prompt, style, fmt, seed)

    # Pollinations peut être lent sous charge : on réessaie quelques fois.
    img_bytes = b""
    last_err = ""
    for attempt in range(1, 4):
        try:
            r = requests.get(img_url, timeout=120)
        except Exception as exc:
            last_err = str(exc)
            logger.debug("flux pollinations GET (essai %s): %s", attempt, exc)
            continue
        if r.status_code == 429:
            last_err = "429"
            continue
        if r.status_code >= 400:
            last_err = f"HTTP {r.status_code}"
            logger.info("flux pollinations HTTP %s", r.status_code)
            continue
        ct = (r.headers.get("content-type") or "").lower()
        if "image" not in ct or len(r.content) < 5000:
            last_err = "réponse non-image"
            continue
        img_bytes = r.content
        break

    if not img_bytes:
        if last_err == "429":
            return {"ok": False,
                    "error": "Le service gratuit est très demandé là. Réessaie dans une minute."}
        return {"ok": False,
                "error": "L'image n'a pas pu être générée. Réessaie dans un instant."}

    ext = "png" if "png" in (r.headers.get("content-type", "")) else "jpg"
    img_id = "%x%04x" % (seed, random.randint(0, 0xFFFF))
    public_url = _archive(img_bytes, img_id, ext, client=client)

    b64 = base64.b64encode(img_bytes).decode("ascii")
    mime = "image/png" if ext == "png" else "image/jpeg"
    data_url = f"data:{mime};base64,{b64}"

    entry = {
        "id": img_id,
        "prompt": prompt,
        "style": style["id"],
        "style_label": style["label"],
        "format": fmt["id"],
        "seed": seed,
        "url": public_url,                       # Supabase (persistant) ou ""
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if public_url:
        try:
            items = _load_history(client)
            items.insert(0, entry)
            _save_history(items, client)
        except Exception as exc:
            logger.debug("flux history insert: %s", exc)

    out = dict(entry)
    out["data_url"] = data_url   # pour affichage/téléchargement immédiat
    return {"ok": True, "image": out}
