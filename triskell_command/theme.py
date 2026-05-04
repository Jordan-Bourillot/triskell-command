"""Tokens de design — palette canonique Triskell Studio.

Source de vérité : `Triskell 0 - Lanceur/style.css` (variables CSS officielles
du lanceur "La Table Ronde"), complétée par `Triskell 1 - Site officiel`
(palette site web).

Aligné avec :
- `--triskell-indigo: #6366F1` (univers du quotidien)
- `--triskell-violet: #A78BFA` (Atelier des Pros)
- `--triskell-orange: #F97316` (accent)
- `--gold: #D4B35A` (signature Table Ronde, sceaux)
- Fond sombre #0F1218, texte chaud #ECEBF5

Esprit : héraldique sobre, cockpit pro, pas alchimique excessif.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Trio Triskell (constantes officielles, partagées dark/light)
# ---------------------------------------------------------------------------
TRISKELL_INDIGO = "#6366F1"
TRISKELL_VIOLET = "#A78BFA"
TRISKELL_ORANGE = "#F97316"
TRISKELL_GOLD = "#D4B35A"
TRISKELL_GOLD_SOFT = "#E6CD87"

# ---------------------------------------------------------------------------
# Palette DARK (Table Ronde)
# ---------------------------------------------------------------------------
D_BG = "#0F1218"
D_BG_2 = "#161A23"
D_BG_3 = "#1D222E"
D_BG_CARD = "#181C27"
D_BG_CARD_HOVER = "#202530"
D_BG_ELEVATED = "#22283A"
D_BORDER = "#262C39"
D_BORDER_STRONG = "#353C4D"
D_TEXT = "#ECEBF5"
D_TEXT_DIM = "#9DA3B3"
D_TEXT_MUTED = "#6B7180"
D_ACCENT = "#7C7FE9"        # indigo doux principal (CTA)
D_ACCENT_HOT = "#9396F0"
D_ACCENT_GLOW = "#A78BFA"
D_GOLD = TRISKELL_GOLD
D_GOLD_SOFT = TRISKELL_GOLD_SOFT

# ---------------------------------------------------------------------------
# Palette LIGHT
# ---------------------------------------------------------------------------
L_BG = "#E9ECF2"
L_BG_2 = "#FFFFFF"
L_BG_3 = "#F3F4F8"
L_BG_CARD = "#FFFFFF"
L_BG_CARD_HOVER = "#F5F6FA"
L_BG_ELEVATED = "#EEF0FF"
L_BORDER = "#D4D7E0"
L_BORDER_STRONG = "#A8ACBA"
L_TEXT = "#14171F"
L_TEXT_DIM = "#4A4F5E"
L_TEXT_MUTED = "#6F7484"

# Sémantique
GREEN = "#4ADE80"
WARNING = "#F59E0B"
DANGER = "#EF4444"
INFO = "#60A5FA"


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


DARK = ThemeColors(
    bg=D_BG,
    bg_alt=D_BG_2,
    bg_hero=D_BG_3,
    panel=D_BG_CARD,
    panel_hover=D_BG_CARD_HOVER,
    panel_elevated=D_BG_ELEVATED,
    border=D_BORDER,
    border_strong=D_BORDER_STRONG,
    border_focus=D_ACCENT,
    text_primary=D_TEXT,
    text_secondary=D_TEXT_DIM,
    text_muted=D_TEXT_MUTED,
    accent=D_ACCENT,
    accent_hover=D_ACCENT_HOT,
    accent_glow=D_ACCENT_GLOW,
    accent_text="#FFFFFF",
    accent_secondary=TRISKELL_VIOLET,
    accent_tertiary=TRISKELL_ORANGE,
    gold=D_GOLD,
    gold_soft=D_GOLD_SOFT,
    success=GREEN,
    danger=DANGER,
    warning=WARNING,
    info=INFO,
    sidebar_bg="#0B0E13",
    sidebar_item_hover=D_BG_CARD_HOVER,
    sidebar_item_active=D_ACCENT,
    sidebar_text=D_TEXT_DIM,
    sidebar_text_active="#FFFFFF",
)


LIGHT = ThemeColors(
    bg=L_BG,
    bg_alt=L_BG_2,
    bg_hero=L_BG_ELEVATED,
    panel=L_BG_CARD,
    panel_hover=L_BG_CARD_HOVER,
    panel_elevated=L_BG_ELEVATED,
    border=L_BORDER,
    border_strong=L_BORDER_STRONG,
    border_focus=D_ACCENT,
    text_primary=L_TEXT,
    text_secondary=L_TEXT_DIM,
    text_muted=L_TEXT_MUTED,
    accent=D_ACCENT,
    accent_hover=D_ACCENT_HOT,
    accent_glow=TRISKELL_VIOLET,
    accent_text="#FFFFFF",
    accent_secondary=TRISKELL_VIOLET,
    accent_tertiary=TRISKELL_ORANGE,
    gold=D_GOLD,
    gold_soft=D_GOLD_SOFT,
    success=GREEN,
    danger=DANGER,
    warning=WARNING,
    info=INFO,
    sidebar_bg=L_BG_2,
    sidebar_item_hover=L_BG_3,
    sidebar_item_active=D_ACCENT,
    sidebar_text=L_TEXT_DIM,
    sidebar_text_active="#FFFFFF",
)


# ---------------------------------------------------------------------------
# Typographie — alignée Table Ronde + site officiel
# ---------------------------------------------------------------------------
# Cinzel : police signature Table Ronde (serif noble, héraldique). Si absente
# du système : Tk fallback automatique sur Segoe UI Bold.
# Inter : corps texte (site officiel + écosystème). Fallback : Segoe UI.
FONT_FAMILY = "Inter"
FONT_FAMILY_DISPLAY = "Cinzel"        # titres nobles (BRAND_NAME, vues)
FONT_FAMILY_FALLBACK = "Segoe UI"
FONT_FAMILY_MONO = "Consolas"

FONT_SIZE_HERO = 32
FONT_SIZE_DISPLAY = 24
FONT_SIZE_TITLE = 18
FONT_SIZE_HEADING = 15
FONT_SIZE_BODY = 13
FONT_SIZE_BODY_LG = 14
FONT_SIZE_SMALL = 11
FONT_SIZE_TINY = 10


# ---------------------------------------------------------------------------
# Espacements (4px base)
# ---------------------------------------------------------------------------
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 18
SPACE_XL = 24
SPACE_2XL = 36
SPACE_3XL = 48

RADIUS_SM = 8
RADIUS_MD = 12
RADIUS_LG = 18
RADIUS_XL = 24
RADIUS_PILL = 100

# Tailles fenêtre
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 820
WINDOW_MIN_WIDTH = 1100
WINDOW_MIN_HEIGHT = 720

SIDEBAR_WIDTH = 220


# ---------------------------------------------------------------------------
# Branding — alignement Table Ronde / site officiel
# ---------------------------------------------------------------------------
BRAND_NAME = "Triskell"
BRAND_PRODUCT = "Command"
BRAND_TAGLINE = "La Table Ronde de tes outils Triskell."
BRAND_LOCATION = "🌊 Agence bretonne · Fait en Bretagne · 100 % français"
BRAND_WEB = "triskell-studio.fr"
APP_VERSION_LABEL = "v0.1"

# Microcopie signature (esprit Table Ronde — tutoiement, ton chaleureux)
COPY_LOADING_GENERIC = "Allumage des chandelles…"
COPY_EMPTY_DEFAULT = "Aucun compagnon ne répond à cet appel pour le moment."
COPY_OWNER_AFFIRM = "Tu es proprio. On te lâche pas."
