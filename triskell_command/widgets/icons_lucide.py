"""Loader Lucide — système d'icônes basé sur les SVG officiels.

Coexiste avec `widgets/icons.py` (dessin PIL custom, déjà excellent). Ce
loader est une **alternative** activable, pas un remplacement.

Pourquoi un second système ? Pour donner le choix :

- `icons.py` (custom)   : icônes dessinées au pixel près en PIL. Rendu
                          excellent en petite taille (16/20 px), mais
                          chaque nouvelle icône demande du code Python.
- `icons_lucide.py`     : 1 600 icônes Lucide à dispo via SVG. Demande
                          `cairosvg` pour le rendu. Pas de code à
                          écrire — il suffit de poser le `.svg` dans
                          `assets/icons_lucide/`.

Stratégie par défaut : `get_icon()` essaie d'abord Lucide, retombe sur
le custom si le SVG ou cairosvg manquent. Aucune régression possible.

---

## Activation

1. Installer cairosvg (optionnel mais recommandé pour Lucide) :
       pip install cairosvg

2. Télécharger les SVG nécessaires dans `assets/icons_lucide/` :
       python scripts/fetch_lucide_icons.py

3. Forcer Lucide (sinon fallback custom transparent) :
       from .widgets.icons_lucide import set_default_strategy
       set_default_strategy("lucide")

---

## Mapping interne → noms Lucide officiels

Les noms internes utilisés dans le code (`sidebar.py` : "chart",
"sparkle", "convoy", etc.) sont stables. On les mappe ici vers les
noms Lucide officiels (cf. https://lucide.dev/icons).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Literal, Optional

import customtkinter as ctk
from PIL import Image

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mapping interne (Triskell Command) → Lucide officiel
# ---------------------------------------------------------------------------
# Doit couvrir tout ce que `sidebar.py`, `components.py` et les vues
# utilisent. Source de vérité : grep "icon=" dans le code.
ICON_MAP: dict[str, str] = {
    # Sidebar
    "chart":     "bar-chart-3",
    "sparkle":   "sparkles",
    "convoy":    "upload",
    "check":     "check-circle-2",
    "mail":      "mail",
    "search":    "search",
    "pen":       "pencil",
    "doc":       "file-text",
    "broadcast": "radio-tower",
    "external":  "external-link",
    "settings":  "settings",

    # Composants & actions
    "send":      "send",
    "trash":     "trash-2",
    "duplicate": "copy",
    "copy":      "clipboard",
    "play":      "play",
    "pause":     "pause",
    "refresh":   "refresh-cw",
    "download":  "download",
    "upload":    "upload",
    "filter":    "filter",
    "calendar":  "calendar",
    "clock":     "clock",
    "user":      "user",
    "users":     "users",
    "tag":       "tag",
    "alert":     "alert-triangle",
    "info":      "info",
    "x":         "x",
    "plus":      "plus",
    "edit":      "edit-3",
    "eye":       "eye",
    "eye_off":   "eye-off",

    # Vues spécifiques
    "kanban":    "kanban",
    "funnel":    "filter",
    "lightbulb": "lightbulb",
    "target":    "target",
    "compass":   "compass",
    "map_pin":   "map-pin",
    "shield":    "shield-check",
    "trending":  "trending-up",
    "trending_down": "trending-down",

    # Le Phare
    "antenna":   "radio-tower",
    "globe":     "globe",
    "link":      "link-2",
    "git_branch": "git-branch",
    "git_pull":  "git-pull-request",
}


# ---------------------------------------------------------------------------
# Stratégie globale de rendu
# ---------------------------------------------------------------------------
Strategy = Literal["auto", "lucide", "custom"]
_DEFAULT_STRATEGY: Strategy = "auto"


def set_default_strategy(strategy: Strategy) -> None:
    """Force la stratégie de rendu pour toute l'app.

    - "auto"   : essaie Lucide → fallback custom (par défaut)
    - "lucide" : Lucide uniquement (échec silencieux si manquant)
    - "custom" : utilise toujours `icons.py` custom
    """
    global _DEFAULT_STRATEGY
    _DEFAULT_STRATEGY = strategy


def get_default_strategy() -> Strategy:
    return _DEFAULT_STRATEGY


# ---------------------------------------------------------------------------
# Détection des dépendances optionnelles
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _has_cairosvg() -> bool:
    try:
        import cairosvg  # noqa: F401
        return True
    except ImportError:
        return False


@lru_cache(maxsize=1)
def _icons_dir() -> Optional[Path]:
    """Localise le dossier `assets/icons_lucide/`. Retourne None si absent."""
    here = Path(__file__).resolve()
    for ancestor in (here.parent.parent.parent, here.parent.parent.parent.parent):
        candidate = ancestor / "assets" / "icons_lucide"
        if candidate.is_dir():
            return candidate
    return None


# ---------------------------------------------------------------------------
# API principale
# ---------------------------------------------------------------------------
def get_icon(
    name: str,
    color_hex: str,
    *,
    size: int = 16,
    strategy: Optional[Strategy] = None,
) -> Optional[ctk.CTkImage]:
    """Retourne une CTkImage prête à passer à `image=` d'un widget.

    `name` : nom interne (cf. ICON_MAP). Si pas dans la map, `name` est
             traité comme un nom Lucide direct.
    `color_hex` : couleur effective (`text_secondary`, `accent`, etc.)
    `size` : taille en pixels. Le rendu est fait à la taille demandée.

    Retourne None si l'icône n'est trouvable nulle part. Le code appelant
    doit gérer ce cas (généralement : afficher un texte de fallback).
    """
    strat = strategy or _DEFAULT_STRATEGY

    if strat == "custom":
        return _from_custom(name, color_hex, size)

    image = _from_lucide(name, color_hex, size)
    if image is not None:
        return image

    if strat == "lucide":
        return None  # mode strict : pas de fallback

    # auto : fallback sur le custom
    return _from_custom(name, color_hex, size)


# ---------------------------------------------------------------------------
# Backend Lucide (SVG → PIL → CTkImage)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=512)
def _from_lucide(name: str, color_hex: str, size: int) -> Optional[ctk.CTkImage]:
    if not _has_cairosvg():
        return None
    icons_dir = _icons_dir()
    if icons_dir is None:
        return None

    lucide_name = ICON_MAP.get(name, name)
    svg_path = icons_dir / f"{lucide_name}.svg"
    if not svg_path.exists():
        # Tentative noms alternatifs courants
        for alt in (lucide_name + ".svg", lucide_name.replace("_", "-") + ".svg"):
            p = icons_dir / alt
            if p.exists():
                svg_path = p
                break
        else:
            return None

    try:
        svg_bytes = _retint_svg(svg_path.read_bytes(), color_hex)
        png_bytes = _svg_to_png(svg_bytes, size=size)
        img = Image.open(BytesIO(png_bytes)).convert("RGBA")
        return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    except Exception as exc:
        logger.warning("Lucide rendering failed for %r: %s", name, exc)
        return None


def _retint_svg(svg_bytes: bytes, color_hex: str) -> bytes:
    """Force `stroke=color` sur le SVG Lucide.

    Lucide standard : `stroke="currentColor"`. On remplace par la couleur
    demandée pour que cairosvg rende avec la bonne teinte.
    """
    svg = svg_bytes.decode("utf-8", errors="ignore")
    svg = svg.replace('stroke="currentColor"', f'stroke="{color_hex}"')
    svg = svg.replace("stroke='currentColor'", f"stroke='{color_hex}'")
    # Si fill explicite (rare en Lucide), idem
    svg = svg.replace('fill="currentColor"', f'fill="{color_hex}"')
    return svg.encode("utf-8")


def _svg_to_png(svg_bytes: bytes, *, size: int) -> bytes:
    import cairosvg  # type: ignore
    return cairosvg.svg2png(
        bytestring=svg_bytes,
        output_width=size,
        output_height=size,
    )


# ---------------------------------------------------------------------------
# Backend custom (délègue à icons.py)
# ---------------------------------------------------------------------------
def _from_custom(name: str, color_hex: str, size: int) -> Optional[ctk.CTkImage]:
    try:
        from . import icons as _icons
    except ImportError:
        return None
    fn = getattr(_icons, "get_icon", None)
    if fn is None:
        return None
    try:
        return fn(name, color_hex, size=size)
    except Exception as exc:
        logger.warning("Custom icon rendering failed for %r: %s", name, exc)
        return None


# ---------------------------------------------------------------------------
# Diagnostic
# ---------------------------------------------------------------------------
def diagnostic() -> dict:
    """Retourne un état du système iconographique pour debug."""
    icons_dir = _icons_dir()
    available = []
    if icons_dir is not None:
        available = sorted(p.stem for p in icons_dir.glob("*.svg"))
    return {
        "default_strategy": _DEFAULT_STRATEGY,
        "cairosvg_available": _has_cairosvg(),
        "icons_dir": str(icons_dir) if icons_dir else None,
        "lucide_svg_count": len(available),
        "lucide_svg_examples": available[:10],
        "internal_names_mapped": len(ICON_MAP),
    }


__all__ = [
    "ICON_MAP",
    "Strategy",
    "set_default_strategy",
    "get_default_strategy",
    "get_icon",
    "diagnostic",
]
