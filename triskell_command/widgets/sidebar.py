"""Sidebar de navigation premium — logo Triskell + items avec indicateur or."""

from __future__ import annotations

import logging
import sys
import webbrowser
from pathlib import Path
from typing import Callable

import customtkinter as ctk

from .. import theme as T
from . import icons as I

logger = logging.getLogger(__name__)

# Carte mentale interne de l'écosystème Triskell (Jordan + Thomas).
# Hébergée sur Netlify avec Basic Auth — voir reference_carte_ecosysteme dans
# la mémoire Claude pour les credentials.
ECOSYSTEME_URL = "https://triskell-ecosysteme.netlify.app"


def _resolve_asset(filename: str) -> Path | None:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / "assets" / filename
        if p.exists():
            return p
    here = Path(__file__).resolve()
    for parent in (here.parent.parent.parent, here.parent.parent.parent.parent):
        p = parent / "assets" / filename
        if p.exists():
            return p
    return None


# Définition statique des entrées de la sidebar
SIDEBAR_SECTIONS = [
    ("LE MATIN", [
        ("morning",    "chart",     "Matinale"),
    ]),
    ("L'APP TRAVAILLE POUR TOI", [
        ("autopilot",  "sparkle",   "Auto-pilote"),
        ("convoy",     "convoy",    "Importer une liste"),
        ("drafts",     "check",     "Brouillons à valider"),
        ("replies",    "mail",      "Réponses des prospects"),
    ]),
    ("À LA MAIN", [
        ("prospects",  "search",    "Chercher des prospects"),
        ("compose",    "pen",       "Écrire avec l'IA"),
        ("templates",  "doc",       "Modèles d'emails"),
        ("campaigns",  "mail",      "Envoyer des emails"),
        ("publish",    "broadcast", "Publier sur les réseaux"),
    ]),
    ("LIVRAISON", [
        ("clients_master", "search", "Fiches clients"),
        ("clients",    "doc",       "Projets clients"),
        ("billing",    "doc",       "Facturation"),
    ]),
    ("CHIFFRES", [
        ("funnel",     "chart",     "Conversions"),
        ("dashboard",  "chart",     "Tableau de bord"),
    ]),
    ("VISIBILITÉ", [
        ("phare",      "broadcast", "Le Phare — SEO"),
    ]),
    ("FABRICATION", [
        ("la_forge",          "globe",   "La Forge du Web"),
        ("lagriffe_intakes",  "sparkle", "Lagriffe — validations"),
        ("rankus_intakes",    "sparkle", "RankUs — validations"),
        ("wow_intakes",       "sparkle", "Studio WoW — validations"),
        ("pixelpros_intakes", "sparkle", "Pixel Pros — pipeline"),
    ]),
]
# Compat : on garde NAV_ITEMS comme la concat de toutes les sections
NAV_ITEMS = [item for _label, items in SIDEBAR_SECTIONS for item in items]

FOOTER_ITEMS = [
    # Allô Claude est désormais accessible via le bouton flottant en bas à
    # droite (le FAB) — pas besoin d'un item sidebar dédié.
    ("tutorial",   "sparkle",   "Tuto"),
    ("help",       "external",  "Aide"),
    ("config",     "settings",  "Réglages"),
]


class SidebarItem(ctk.CTkFrame):
    """Bouton de navigation avec indicateur latéral or quand actif."""

    HEIGHT = 44

    def __init__(
        self,
        master,
        *,
        view_id: str,
        icon_name: str,
        label: str,
        on_click: Callable[[str], None],
        colors: T.ThemeColors,
        is_active: bool = False,
    ):
        super().__init__(master, fg_color="transparent",
                          height=self.HEIGHT, corner_radius=0)
        self.pack_propagate(False)
        self.view_id = view_id
        self._on_click = on_click
        self._colors = colors
        self._is_active = is_active
        self._icon_name = icon_name

        # Indicateur latéral (barre verticale or, 3px) — révélé si actif
        self._indicator = ctk.CTkFrame(
            self, fg_color="transparent", width=3, corner_radius=0,
        )
        self._indicator.pack(side="left", fill="y")
        self._indicator.pack_propagate(False)

        # Conteneur cliquable (icône + label)
        self._row = ctk.CTkFrame(self, fg_color="transparent")
        self._row.pack(side="left", fill="both", expand=True,
                        padx=(T.SPACE_MD, T.SPACE_SM))

        self._icon_label = ctk.CTkLabel(self._row, text="", width=24)
        self._icon_label.pack(side="left", padx=(0, T.SPACE_MD))

        self._label = ctk.CTkLabel(
            self._row, text=label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=colors.sidebar_text,
            anchor="w",
        )
        self._label.pack(side="left", fill="x", expand=True)

        # Pastille « attention » : un point or qui s'affiche pour signaler
        # qu'un événement attend l'utilisateur (ex: Claude veut te parler).
        self._attention_dot = ctk.CTkFrame(
            self._row, fg_color="transparent",
            width=8, height=8, corner_radius=4,
        )
        self._attention_dot.pack(side="right", padx=(0, T.SPACE_SM))
        self._attention_dot.pack_propagate(False)
        self._has_attention = False
        self._attention_blink_job = None

        # Hover handlers (sur tous les widgets pour que la zone soit cliquable)
        for w in (self, self._row, self._icon_label, self._label):
            w.bind("<Button-1>", self._handle_click)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

        self.set_active(is_active)

    def _handle_click(self, _event=None):
        self._on_click(self.view_id)

    def _on_enter(self, _event=None):
        if not self._is_active:
            self._row.configure(fg_color=self._colors.panel)
            self._label.configure(text_color=self._colors.text_primary)
            self._refresh_icon(self._colors.text_primary)

    def _on_leave(self, _event=None):
        if not self._is_active:
            self._row.configure(fg_color="transparent")
            self._label.configure(text_color=self._colors.sidebar_text)
            self._refresh_icon(self._colors.sidebar_text)

    def _refresh_icon(self, color_hex: str) -> None:
        icon = I.get_icon(self._icon_name, color_hex, size=20)
        if icon is not None:
            self._icon_label.configure(image=icon)
            # Garde une ref pour empêcher le GC
            self._icon_label._icon_ref = icon  # type: ignore

    def set_active(self, active: bool) -> None:
        self._is_active = active
        c = self._colors
        active_color = c.sidebar_text_active
        if active:
            # Fond actif + indicateur accent + texte/icône accent (plus d'or)
            self._row.configure(fg_color=c.sidebar_item_active)
            self._indicator.configure(fg_color=c.accent)
            self._label.configure(
                text_color=active_color,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            )
            self._refresh_icon(active_color)
        else:
            self._row.configure(fg_color="transparent")
            self._indicator.configure(fg_color="transparent")
            self._label.configure(
                text_color=c.sidebar_text,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "normal"),
            )
            self._refresh_icon(c.sidebar_text)

    def set_attention(self, on: bool) -> None:
        """Active/désactive la pastille « événement à voir »."""
        self._has_attention = bool(on)
        # Stoppe le blink en cours
        if self._attention_blink_job is not None:
            try:
                self.after_cancel(self._attention_blink_job)
            except Exception:
                pass
            self._attention_blink_job = None
        if not self._has_attention:
            try:
                self._attention_dot.configure(fg_color="transparent")
            except Exception:
                pass
            return
        self._blink_attention(visible=True)

    def _blink_attention(self, *, visible: bool) -> None:
        if not self._has_attention:
            try:
                self._attention_dot.configure(fg_color="transparent")
            except Exception:
                pass
            return
        c = self._colors
        try:
            self._attention_dot.configure(
                fg_color=c.accent if visible else "transparent"
            )
        except Exception:
            return
        # Re-planifie l'inversion (clignote toutes les 700ms)
        self._attention_blink_job = self.after(
            700, lambda: self._blink_attention(visible=not visible)
        )


class Sidebar(ctk.CTkFrame):
    """Sidebar gauche premium : logo Triskell + nav + footer signature."""

    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        on_navigate: Callable[[str], None],
        active_view: str = "morning",
    ):
        super().__init__(
            master,
            width=T.SIDEBAR_WIDTH,
            fg_color=colors.sidebar_bg,
            corner_radius=0,
        )
        self.pack_propagate(False)
        self._colors = colors
        self._on_navigate = on_navigate
        self._items: dict[str, SidebarItem] = {}
        self._active = active_view

        # ----- Header (logo + nom) -----
        header = ctk.CTkFrame(self, fg_color="transparent", height=96)
        header.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG + 4, T.SPACE_LG))
        header.pack_propagate(False)

        # Logo
        self._logo_image_ref = None
        logo_path = _resolve_asset("triskell.png")
        if logo_path is not None:
            try:
                from PIL import Image
                pil_img = Image.open(logo_path).convert("RGBA")
                ctk_img = ctk.CTkImage(
                    light_image=pil_img, dark_image=pil_img, size=(56, 56),
                )
                self._logo_image_ref = ctk_img
                ctk.CTkLabel(header, image=ctk_img, text="").pack(
                    side="left", padx=(0, T.SPACE_MD),
                )
            except Exception as exc:
                logger.debug("Échec chargement logo : %s", exc)
                self._logo_image_ref = None

        if self._logo_image_ref is None:
            ctk.CTkLabel(
                header, text="⛯",
                font=(T.FONT_FAMILY_FALLBACK, 32, "bold"),
                text_color=colors.gold,
            ).pack(side="left", padx=(0, T.SPACE_MD))

        text_block = ctk.CTkFrame(header, fg_color="transparent")
        text_block.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            text_block, text=T.BRAND_NAME,
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_TITLE, "bold"),
            text_color=colors.text_primary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(8, 0))

        ctk.CTkLabel(
            text_block, text=T.BRAND_PRODUCT.upper(),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=colors.accent, anchor="w",
        ).pack(fill="x", anchor="w", pady=(2, 0))

        # Séparateur fin or sous le header
        sep = ctk.CTkFrame(self, fg_color=colors.border, height=1, corner_radius=0)
        sep.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # ----- Zone scrollable contenant Écosystème + Nav + Footer items -----
        # Permet d'avoir beaucoup d'items (FABRICATION x3, etc.) sans déborder
        # quand la fenêtre est petite.
        scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=colors.border,
            scrollbar_button_hover_color=colors.accent,
        )
        scroll.pack(fill="both", expand=True, padx=0, pady=0)

        # ----- Bouton CTA principal "+ Nouveau site" (Studio) -----
        # Bouton visuellement fort : rempli accent, plein-large, en haut.
        studio_btn = ctk.CTkButton(
            scroll,
            text="✦   + Nouveau site",
            command=lambda: self._handle_click("studio"),
            fg_color=colors.accent,
            hover_color=colors.accent_hover,
            text_color="#ffffff",
            height=44,
            corner_radius=10,
            anchor="w",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
        )
        studio_btn.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))
        ctk.CTkLabel(
            scroll, text="Studio · génération à partir d'un sujet",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "italic"),
            text_color=colors.text_muted, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        # ----- Bouton "Écosystème" -----
        eco_btn = ctk.CTkButton(
            scroll,
            text="🌟   Écosystème",
            command=lambda: webbrowser.open(ECOSYSTEME_URL),
            fg_color="transparent",
            hover_color=colors.gold_soft,
            text_color=colors.gold,
            border_width=1,
            border_color=colors.border,
            height=36,
            corner_radius=10,
            anchor="w",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
        )
        eco_btn.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        # ----- Sections de navigation regroupées -----
        for sec_idx, (section_label, items) in enumerate(SIDEBAR_SECTIONS):
            top_pad = T.SPACE_LG if sec_idx > 0 else 0
            ctk.CTkLabel(
                scroll, text=section_label,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                text_color=colors.text_muted, anchor="w",
            ).pack(fill="x", padx=T.SPACE_LG, pady=(top_pad, T.SPACE_SM))

            for view_id, icon_name, label in items:
                item = SidebarItem(
                    scroll, view_id=view_id, icon_name=icon_name, label=label,
                    on_click=self._handle_click, colors=colors,
                    is_active=(view_id == active_view),
                )
                item.pack(fill="x", pady=2)
                self._items[view_id] = item

        # ----- Section: système / réglages (dans le scroll, en bas) -----
        ctk.CTkLabel(
            scroll, text="SYSTÈME",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=colors.text_muted, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))

        for view_id, icon_name, label in FOOTER_ITEMS:
            item = SidebarItem(
                scroll, view_id=view_id, icon_name=icon_name, label=label,
                on_click=self._handle_click, colors=colors,
                is_active=(view_id == active_view),
            )
            item.pack(fill="x", pady=1)
            self._items[view_id] = item

        # Séparateur fin avant footer
        sep_bottom = ctk.CTkFrame(self, fg_color=colors.border,
                                   height=1, corner_radius=0)
        sep_bottom.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_MD, T.SPACE_MD))

        # Footer signature : "🌊 Bretagne · 100% français" + version
        ctk.CTkLabel(
            self, text=T.BRAND_LOCATION,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
            text_color=colors.text_muted,
            wraplength=T.SIDEBAR_WIDTH - 32,
            justify="center",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, 4))

        ctk.CTkLabel(
            self, text=T.APP_VERSION_LABEL,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=colors.text_muted,
        ).pack(fill="x", pady=(0, T.SPACE_LG))

    def _handle_click(self, view_id: str) -> None:
        if view_id == self._active:
            return
        self.set_active(view_id)
        self._on_navigate(view_id)

    def set_active(self, view_id: str) -> None:
        if view_id not in self._items:
            return
        if self._active in self._items:
            self._items[self._active].set_active(False)
        self._items[view_id].set_active(True)
        self._active = view_id

    def set_attention(self, view_id: str, on: bool = True) -> None:
        """Allume/éteint la pastille de notification sur un item de la sidebar.

        Utilisé par exemple pour signaler « Claude veut te parler » :
            sidebar.set_attention("claude", True)
        """
        item = self._items.get(view_id)
        if item is None:
            return
        try:
            item.set_attention(on)
        except Exception:
            pass
