"""Tokens v2 — extensions du design system Triskell Command.

Complète `theme.py` (couleurs, espacement, typo de base) sans le remplacer.
À importer en parallèle :

    from .. import theme as T
    from ..tokens_v2 import elevation, motion, density, ttype

Trois ajouts essentiels que le système v1 n'avait pas :

1. **Élévation** — CustomTkinter ne supporte pas les vraies ombres. On
   émule la profondeur par combinaison `bg` + `border_width` + `inset`
   (cf. `surface_for(level)`).

2. **Motion** — durées canoniques en millisecondes pour les transitions
   `.after()` et les pulsations workers.

3. **Density** — deux modes (CONFORTABLE / COMPACT). Les vues data-heavy
   (Phare, Funnel, Dashboard) passent en COMPACT, le reste reste en
   CONFORTABLE.

4. **Typographie étendue** (`ttype`) — variantes spécialisées : KPI
   géant, tabular nums pour colonnes chiffrées, mono code, label compact,
   timestamp log.

5. **Z-axis** — niveaux logiques pour overlays, drawers, modals,
   tooltips. Pas de vrai z-index en Tk, mais cohérence sémantique.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from . import theme as T


# ---------------------------------------------------------------------------
# Élévation — émulation 4 niveaux via combinaison bg + bordure
# ---------------------------------------------------------------------------
ElevationLevel = Literal[0, 1, 2, 3]


@dataclass(frozen=True)
class Surface:
    """Spécification d'une surface à un niveau d'élévation donné.

    Pas une vraie ombre (Tk ne sait pas faire). Plutôt un trio
    (couleur de fond, épaisseur de bordure, couleur de bordure) qui crée
    une hiérarchie perceptive.
    """
    fg_color: str
    border_color: str
    border_width: int


def surface_for(level: ElevationLevel, colors: T.ThemeColors) -> Surface:
    """Renvoie la spécification de surface pour un niveau d'élévation.

    Niveau 0 : fond de vue plat (`bg`).
    Niveau 1 : carte standard posée sur la vue (`panel`).
    Niveau 2 : panneau qui domine (modal, drawer, popover) (`panel_elevated`).
    Niveau 3 : élément flottant qui doit se détacher fortement (tooltip,
               menu contextuel) — bord plus marqué.
    """
    if level == 0:
        return Surface(colors.bg, colors.border, 0)
    if level == 1:
        return Surface(colors.panel, colors.border, 1)
    if level == 2:
        return Surface(colors.panel_elevated, colors.border_strong, 1)
    if level == 3:
        return Surface(colors.panel_elevated, colors.border_strong, 2)
    return Surface(colors.bg, colors.border, 0)


# ---------------------------------------------------------------------------
# Motion — durées canoniques pour after() / animations Tk
# ---------------------------------------------------------------------------
class motion:
    """Durées de transitions, en millisecondes.

    Tk ne fait pas de vraie animation interpolée, mais on peut chaîner
    des `.after()` pour simuler. Trois vitesses canoniques :
    """
    QUICK = 80          # micro-feedback : hover, ripple, focus ring
    STANDARD = 160      # transitions standard : tab change, modal fade
    SLOW = 320          # transitions narratives : drawer slide, vue swap

    # Pulsations workers : cycle complet pour 1 LED qui "respire"
    PULSE_IDLE = 2400   # respiration lente quand worker au repos
    PULSE_ACTIVE = 600  # rotation rapide quand worker en activité


# ---------------------------------------------------------------------------
# Densité — deux modes pour adapter espacement et taille de police
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DensityProfile:
    """Profil d'espacement et tailles selon le mode de densité actif.

    Pas un simple multiplicateur : chaque vue choisit sa densité selon
    sa nature (rituel vs data-heavy).
    """
    name: str
    row_height: int
    cell_padding_x: int
    cell_padding_y: int
    section_gap: int
    font_size_body: int
    font_size_small: int
    font_size_label: int


CONFORTABLE = DensityProfile(
    name="confortable",
    row_height=44,
    cell_padding_x=16,
    cell_padding_y=12,
    section_gap=T.SPACE_XL,
    font_size_body=T.FONT_SIZE_BODY,        # 13
    font_size_small=T.FONT_SIZE_SMALL,      # 11
    font_size_label=T.FONT_SIZE_BODY_LG,    # 14
)

COMPACT = DensityProfile(
    name="compact",
    row_height=32,
    cell_padding_x=10,
    cell_padding_y=6,
    section_gap=T.SPACE_LG,
    font_size_body=12,
    font_size_small=10,
    font_size_label=T.FONT_SIZE_BODY,       # 13
)


def density_for(view_kind: str) -> DensityProfile:
    """Mappe un type de vue vers son profil de densité par défaut.

    Les vues "rituelles" (Matinale, Drafts, Compose) restent en
    CONFORTABLE. Les vues "data-heavy" (Phare, Funnel, Dashboard,
    Prospects, Campaigns) passent en COMPACT.
    """
    DATA_HEAVY = {"phare", "funnel", "dashboard", "prospects", "campaigns"}
    return COMPACT if view_kind in DATA_HEAVY else CONFORTABLE


# ---------------------------------------------------------------------------
# Typographie étendue — variantes spécialisées
# ---------------------------------------------------------------------------
class ttype:
    """Tuples de police prêts à passer à `font=` dans CustomTkinter.

    Convention : `(family, size, weight)`. Réutilise les constantes de
    `theme.py` (FONT_FAMILY, FONT_FAMILY_DISPLAY, FONT_FAMILY_MONO,
    FONT_SIZE_*).

    Garantie : chaque tuple est immuable, on les passe directement aux
    widgets sans re-créer.
    """

    # KPI — chiffre géant, lecture instantanée
    KPI_HERO = (T.FONT_FAMILY, 44, "bold")          # KPI primaire matinale
    KPI_LARGE = (T.FONT_FAMILY, 32, "bold")         # KPI carte standard
    KPI_MEDIUM = (T.FONT_FAMILY, 22, "bold")        # KPI compact
    KPI_DELTA = (T.FONT_FAMILY, 12, "normal")       # delta sous le chiffre

    # Hero / display — moments de cérémonie (Cinzel)
    HERO = (T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_HERO, "bold")
    DISPLAY = (T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_DISPLAY, "bold")
    DISPLAY_THIN = (T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_DISPLAY, "normal")

    # Titres standards (Inter)
    H1 = (T.FONT_FAMILY, T.FONT_SIZE_TITLE, "bold")
    H2 = (T.FONT_FAMILY, T.FONT_SIZE_HEADING, "bold")
    H3 = (T.FONT_FAMILY, T.FONT_SIZE_BODY_LG, "bold")

    # Corps
    BODY = (T.FONT_FAMILY, T.FONT_SIZE_BODY, "normal")
    BODY_BOLD = (T.FONT_FAMILY, T.FONT_SIZE_BODY, "bold")
    BODY_LG = (T.FONT_FAMILY, T.FONT_SIZE_BODY_LG, "normal")
    BODY_SM = (T.FONT_FAMILY, T.FONT_SIZE_SMALL, "normal")

    # Labels et caps
    LABEL = (T.FONT_FAMILY, T.FONT_SIZE_SMALL, "bold")
    LABEL_TINY = (T.FONT_FAMILY, T.FONT_SIZE_TINY, "bold")
    SECTION_CAP = (T.FONT_FAMILY, T.FONT_SIZE_TINY, "bold")  # CAPS sidebar

    # Mono — code, IDs, hashes
    MONO = (T.FONT_FAMILY_MONO, T.FONT_SIZE_BODY, "normal")
    MONO_SM = (T.FONT_FAMILY_MONO, T.FONT_SIZE_SMALL, "normal")

    # Logs / timestamps — alignement vertical de chiffres
    LOG = (T.FONT_FAMILY_MONO, T.FONT_SIZE_SMALL, "normal")
    TIMESTAMP = (T.FONT_FAMILY_MONO, T.FONT_SIZE_TINY, "normal")


# ---------------------------------------------------------------------------
# Z-axis — niveaux d'empilement logique
# ---------------------------------------------------------------------------
class z:
    """Niveaux logiques d'empilement pour overlays.

    Tk n'a pas de z-index réel ; on utilise `lift()` et l'ordre de
    création. Mais maintenir une hiérarchie claire évite les bugs de
    "ce truc est passé sous le drawer".
    """
    BASE = 0          # fond, sidebar, header
    CONTENT = 10      # vues principales
    POPOVER = 50      # menus contextuels, dropdown
    DRAWER = 100      # drawer droite/gauche
    MODAL = 200       # modale plein écran
    TOAST = 300       # toasts notification
    TOOLTIP = 400     # tooltips (toujours au-dessus)


# ---------------------------------------------------------------------------
# Largeurs canoniques — alignement cross-vues
# ---------------------------------------------------------------------------
class widths:
    """Largeurs de référence pour composants partagés."""
    DRAWER_RIGHT = 380          # panneau coulissant droit (Phare avancé)
    MODAL_SM = 480
    MODAL_MD = 640
    MODAL_LG = 880
    KPI_CARD_MIN = 220          # largeur minimale d'une carte KPI
    LOG_TIMESTAMP = 64          # colonne timestamp dans les logs
    LOG_LEVEL = 56              # colonne niveau (INFO/WARN/ERR)


# ---------------------------------------------------------------------------
# Hauteurs canoniques
# ---------------------------------------------------------------------------
class heights:
    """Hauteurs de référence."""
    STATUS_BAR = 28             # status bar workers en bas d'app
    HEADER_VIEW = 104           # header de vue (déjà utilisé dans ViewHeader)
    KPI_CARD = 132              # carte KPI standard
    KPI_CARD_HERO = 168         # carte KPI matinale (plus généreuse)
    LOG_ROW = 24                # ligne de log compacte
    DIVIDER = 1                 # séparateur fin
    GOLD_DIVIDER = 1            # séparateur or (signature de section noble)


# ---------------------------------------------------------------------------
# Bordures — épaisseurs canoniques
# ---------------------------------------------------------------------------
class borders:
    """Épaisseurs et tokens de bordures."""
    NONE = 0
    HAIRLINE = 1                # bordure standard discrète
    EMPHASIZED = 2              # bordure marquée (focus, état actif)
    FOCUS_RING = 2              # anneau de focus accessibilité


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def font_with_size(base: tuple, size: int) -> tuple:
    """Retourne un tuple police avec une taille différente."""
    if len(base) == 3:
        return (base[0], size, base[2])
    return (base[0], size)


def is_dark_mode(colors: T.ThemeColors) -> bool:
    """Détecte si on est sur un thème sombre (utile pour ajuster contrastes)."""
    return colors is T.DARK or colors is T.MID


__all__ = [
    "Surface", "surface_for", "ElevationLevel",
    "motion", "z",
    "DensityProfile", "CONFORTABLE", "COMPACT", "density_for",
    "ttype",
    "widths", "heights", "borders",
    "font_with_size", "is_dark_mode",
]
