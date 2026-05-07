"""Tokens de design — palette canonique Triskell Studio.

Trois modes : LIGHT (par défaut, Apple-clear), MID (graphite intermédiaire,
chaleureux et reposant), DARK (cockpit nuit).

Inspiration : AlphaCast (Réseaux/) — surfaces blanches sobres, indigo +
violet en accents, slate pour les nuances, or réservé aux séparateurs fins
et au branding (sceau Table Ronde).

Esprit : héraldique sobre, large white space, hiérarchie visuelle nette.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Palette canonique Triskell (constantes partagées)
# ---------------------------------------------------------------------------
TRISKELL_INDIGO = "#6366F1"
TRISKELL_INDIGO_DARK = "#4F46E5"
TRISKELL_INDIGO_LIGHT = "#818CF8"
TRISKELL_VIOLET = "#A78BFA"
TRISKELL_VIOLET_LIGHT = "#C4B5FD"
TRISKELL_ORANGE = "#F97316"
TRISKELL_GOLD = "#C9A032"          # or sobre, un peu désaturé
TRISKELL_GOLD_SOFT = "#D4B35A"     # or signature historique

# Sémantique (partagée 3 modes — variantes ajustées par mode si besoin)
SUCCESS = "#10B981"
WARNING = "#F59E0B"
DANGER = "#EF4444"
INFO = "#0EA5E9"


@dataclass(frozen=True)
class ThemeColors:
    bg: str
    bg_alt: str
    bg_hero: str
    panel: str
    panel_hover: str
    panel_elevated: str
    border: str
    border_strong: str
    border_focus: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_glow: str
    accent_text: str
    accent_secondary: str
    accent_tertiary: str
    gold: str
    gold_soft: str
    success: str
    danger: str
    warning: str
    info: str
    sidebar_bg: str
    sidebar_item_hover: str
    sidebar_item_active: str
    sidebar_text: str
    sidebar_text_active: str


# ---------------------------------------------------------------------------
# LIGHT — slate / blanc, indigo en accents, large white space (Apple-light)
# ---------------------------------------------------------------------------
LIGHT = ThemeColors(
    bg="#F8FAFC",                # slate-50
    bg_alt="#FFFFFF",
    bg_hero="#F1F5F9",           # slate-100
    panel="#FFFFFF",
    panel_hover="#F8FAFC",
    panel_elevated="#FFFFFF",
    border="#E2E8F0",            # slate-200
    border_strong="#CBD5E1",     # slate-300
    border_focus=TRISKELL_INDIGO,
    text_primary="#0F172A",      # slate-900
    text_secondary="#475569",    # slate-600
    text_muted="#64748B",        # slate-500
    accent=TRISKELL_INDIGO,
    accent_hover=TRISKELL_INDIGO_DARK,
    accent_glow=TRISKELL_VIOLET,
    accent_text="#FFFFFF",
    accent_secondary=TRISKELL_VIOLET,
    accent_tertiary=TRISKELL_ORANGE,
    gold=TRISKELL_GOLD,
    gold_soft=TRISKELL_GOLD_SOFT,
    success=SUCCESS,
    danger=DANGER,
    warning=WARNING,
    info=INFO,
    sidebar_bg="#FFFFFF",
    sidebar_item_hover="#F1F5F9",
    sidebar_item_active="#EEF2FF",   # indigo-50
    sidebar_text="#64748B",
    sidebar_text_active=TRISKELL_INDIGO,
)


# ---------------------------------------------------------------------------
# MID — graphite chaud, ni clair ni sombre, reposant (sweet spot)
# ---------------------------------------------------------------------------
MID = ThemeColors(
    bg="#2A2F3D",                # graphite chaud
    bg_alt="#252A37",
    bg_hero="#323847",
    panel="#2F3543",
    panel_hover="#373D4D",
    panel_elevated="#3C4354",
    border="#3D4454",
    border_strong="#4F5668",
    border_focus=TRISKELL_INDIGO_LIGHT,
    text_primary="#F1F5F9",      # slate-100
    text_secondary="#CBD5E1",    # slate-300
    text_muted="#94A3B8",        # slate-400
    accent=TRISKELL_INDIGO_LIGHT,
    accent_hover="#A5B4FC",      # indigo-300
    accent_glow=TRISKELL_VIOLET_LIGHT,
    accent_text="#0F172A",
    accent_secondary=TRISKELL_VIOLET,
    accent_tertiary=TRISKELL_ORANGE,
    gold=TRISKELL_GOLD_SOFT,
    gold_soft="#E8CC7E",
    success="#34D399",
    danger="#F87171",
    warning="#FBBF24",
    info="#38BDF8",
    sidebar_bg="#1F2433",
    sidebar_item_hover="#2F3543",
    sidebar_item_active="#3C4354",
    sidebar_text="#94A3B8",
    sidebar_text_active="#F1F5F9",
)


# ---------------------------------------------------------------------------
# DARK — cockpit nuit (adouci par rapport à v0.3)
# ---------------------------------------------------------------------------
DARK = ThemeColors(
    bg="#0F1218",
    bg_alt="#161A23",
    bg_hero="#1D222E",
    panel="#181C27",
    panel_hover="#202530",
    panel_elevated="#22283A",
    border="#262C39",
    border_strong="#353C4D",
    border_focus=TRISKELL_INDIGO_LIGHT,
    text_primary="#ECEBF5",
    text_secondary="#9DA3B3",
    text_muted="#6B7180",
    accent=TRISKELL_INDIGO_LIGHT,
    accent_hover="#A5B4FC",
    accent_glow=TRISKELL_VIOLET_LIGHT,
    accent_text="#0F172A",
    accent_secondary=TRISKELL_VIOLET,
    accent_tertiary=TRISKELL_ORANGE,
    gold=TRISKELL_GOLD,
    gold_soft=TRISKELL_GOLD_SOFT,
    success="#34D399",
    danger="#F87171",
    warning="#FBBF24",
    info="#38BDF8",
    sidebar_bg="#0B0E13",
    sidebar_item_hover="#202530",
    sidebar_item_active="#22283A",
    sidebar_text="#9DA3B3",
    sidebar_text_active="#ECEBF5",
)


# ---------------------------------------------------------------------------
# Sélection du thème
# ---------------------------------------------------------------------------
THEME_MODES = ("light", "mid", "dark")


def get_theme(mode: str) -> ThemeColors:
    """Renvoie l'instance ThemeColors pour le mode demandé.
    `mode` ∈ {'light', 'mid', 'dark'}. Tout autre valeur retombe sur 'light'."""
    m = (mode or "").lower()
    if m == "mid":
        return MID
    if m == "dark":
        return DARK
    return LIGHT  # défaut Apple-clear


def normalize_mode(mode: str) -> str:
    """Normalise une valeur de mode en {'light','mid','dark'}."""
    m = (mode or "").lower()
    return m if m in THEME_MODES else "light"


def cycle_mode(current: str) -> str:
    """Cycle light → mid → dark → light. Pour raccourci clavier."""
    order = ["light", "mid", "dark"]
    cur = normalize_mode(current)
    try:
        i = order.index(cur)
    except ValueError:
        return "mid"
    return order[(i + 1) % len(order)]


# Alias rétro-compat : dans l'ancien code on faisait `T.DARK if mode == 'dark'
# else T.LIGHT`. On garde DARK et LIGHT exportés ; MID est nouveau.
__all__ = [
    "ThemeColors", "LIGHT", "MID", "DARK",
    "THEME_MODES", "get_theme", "normalize_mode", "cycle_mode",
    # Tokens
    "TRISKELL_INDIGO", "TRISKELL_INDIGO_DARK", "TRISKELL_INDIGO_LIGHT",
    "TRISKELL_VIOLET", "TRISKELL_VIOLET_LIGHT",
    "TRISKELL_ORANGE", "TRISKELL_GOLD", "TRISKELL_GOLD_SOFT",
    "SUCCESS", "WARNING", "DANGER", "INFO",
    # Tous les autres exportés ci-dessous (typo, espacements, brand)
]


# ---------------------------------------------------------------------------
# Typographie — Inter pour le corps, Cinzel pour la signature
# ---------------------------------------------------------------------------
FONT_FAMILY = "Inter"
FONT_FAMILY_DISPLAY = "Cinzel"
FONT_FAMILY_FALLBACK = "Segoe UI"
FONT_FAMILY_MONO = "Consolas"

# Hiérarchie typo allégée (un peu plus généreuse à la Apple)
FONT_SIZE_HERO = 36          # +4 vs v0.3
FONT_SIZE_DISPLAY = 26
FONT_SIZE_TITLE = 19
FONT_SIZE_HEADING = 15
FONT_SIZE_BODY = 13
FONT_SIZE_BODY_LG = 14
FONT_SIZE_SMALL = 11
FONT_SIZE_TINY = 10


# ---------------------------------------------------------------------------
# Espacements — base 4px, plus généreux (Apple-like)
# ---------------------------------------------------------------------------
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 18
SPACE_XL = 28           # +4 pour aérer
SPACE_2XL = 40          # +4
SPACE_3XL = 56          # +8

RADIUS_SM = 8
RADIUS_MD = 14          # +2 pour cards plus douces
RADIUS_LG = 20          # +2
RADIUS_XL = 28          # +4
RADIUS_PILL = 100

# Tailles fenêtre
WINDOW_WIDTH = 1320
WINDOW_HEIGHT = 860
WINDOW_MIN_WIDTH = 1140
WINDOW_MIN_HEIGHT = 740

SIDEBAR_WIDTH = 232


# ---------------------------------------------------------------------------
# Branding — alignement Table Ronde / site officiel
# ---------------------------------------------------------------------------
BRAND_NAME = "Triskell"
BRAND_PRODUCT = "Command"
BRAND_TAGLINE = "Le tableau de bord de Triskell."
BRAND_LOCATION = "🌊 Bretagne · 100 % français"
BRAND_WEB = "triskell-studio.fr"
APP_VERSION_LABEL = "v0.4"

# Microcopie signature (tutoiement, ton chaleureux)
COPY_LOADING_GENERIC = "Préparation en cours…"
COPY_EMPTY_DEFAULT = "Rien ici pour l'instant."
COPY_OWNER_AFFIRM = "On te suit pas à pas."
