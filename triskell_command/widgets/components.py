"""Composants UI réutilisables : header, card, primary button, chip, status pill."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from .. import theme as T


class ViewHeader(ctk.CTkFrame):
    """Header standardisé pour chaque vue (titre Cinzel + sous-titre + actions).

    Style 2026 : barre fine indigo (3 px de large, 28 px de long) au-dessus
    du titre. L'or est réservé au branding (Table Ronde, sceau).
    """

    def __init__(
        self, master, *, title: str, subtitle: str = "", colors: T.ThemeColors,
        logo_path: str | None = None, logo_size: int = 56,
    ):
        super().__init__(master, fg_color="transparent", height=104)
        self.pack_propagate(False)
        self._colors = colors

        # Logo optionnel (gauche)
        if logo_path:
            try:
                from pathlib import Path
                from PIL import Image
                p = Path(logo_path)
                if p.exists():
                    img = Image.open(str(p))
                    ctk_img = ctk.CTkImage(
                        light_image=img, dark_image=img,
                        size=(logo_size, logo_size),
                    )
                    logo = ctk.CTkLabel(
                        self, image=ctk_img, text="",
                        fg_color="transparent",
                    )
                    logo.pack(side="left", padx=(0, T.SPACE_MD),
                              pady=(T.SPACE_LG, T.SPACE_SM))
            except Exception:
                pass  # logo absent ou Pillow KO -> on continue sans

        # Bloc texte (gauche)
        text_block = ctk.CTkFrame(self, fg_color="transparent")
        text_block.pack(side="left", fill="both", expand=True,
                        pady=(T.SPACE_LG + 6, T.SPACE_SM))

        # Filet accent au-dessus du titre (signature de section)
        bar = ctk.CTkFrame(text_block, fg_color=colors.accent,
                           width=32, height=3, corner_radius=2)
        bar.pack(anchor="w", pady=(0, T.SPACE_SM))
        bar.pack_propagate(False)

        ctk.CTkLabel(
            text_block, text=title,
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_DISPLAY, "bold"),
            text_color=colors.text_primary, anchor="w",
        ).pack(fill="x", anchor="w")

        if subtitle:
            ctk.CTkLabel(
                text_block, text=subtitle,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY_LG),
                text_color=colors.text_secondary, anchor="w",
                justify="left", wraplength=860,
            ).pack(fill="x", anchor="w", pady=(T.SPACE_XS, 0))

        # Zone actions (droite)
        self.actions = ctk.CTkFrame(self, fg_color="transparent")
        self.actions.pack(side="right", pady=T.SPACE_LG, padx=(T.SPACE_MD, 0))


class Card(ctk.CTkFrame):
    """Carte avec fond panel + bordure douce."""

    def __init__(self, master, *, colors: T.ThemeColors, padding: int = T.SPACE_LG, **kwargs):
        super().__init__(
            master,
            fg_color=colors.panel,
            corner_radius=T.RADIUS_MD,
            border_color=colors.border,
            border_width=1,
            **kwargs,
        )
        self._padding = padding


def _resolve_icon(icon: str | None, color_hex: str, size: int = 16):
    """Charge une icône via le module icons (lazy import)."""
    if not icon:
        return None
    from . import icons as _icons
    return _icons.get_icon(icon, color_hex, size=size)


class PrimaryButton(ctk.CTkButton):
    """CTA premium : indigo plein avec hover plus chaud. Supporte icon=str."""
    def __init__(
        self, master, *,
        colors: T.ThemeColors,
        icon: str | None = None, icon_size: int = 16,
        **kwargs,
    ):
        if icon and "image" not in kwargs:
            kwargs["image"] = _resolve_icon(icon, colors.accent_text, icon_size)
            kwargs.setdefault("compound", "left")
        super().__init__(
            master,
            fg_color=colors.accent,
            hover_color=colors.accent_hover,
            text_color=colors.accent_text,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            height=38,
            border_spacing=10,
            **kwargs,
        )


class SecondaryButton(ctk.CTkButton):
    """Bouton secondaire : ghost avec border subtle. Supporte icon=str."""
    def __init__(
        self, master, *,
        colors: T.ThemeColors,
        icon: str | None = None, icon_size: int = 16,
        **kwargs,
    ):
        if icon and "image" not in kwargs:
            kwargs["image"] = _resolve_icon(icon, colors.text_secondary, icon_size)
            kwargs.setdefault("compound", "left")
        super().__init__(
            master,
            fg_color="transparent",
            hover_color=colors.panel,
            text_color=colors.text_secondary,
            corner_radius=T.RADIUS_SM,
            border_width=1,
            border_color=colors.border_strong,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            height=38,
            border_spacing=10,
            **kwargs,
        )


class GoldButton(ctk.CTkButton):
    """Bouton signature or — pour les actions premium / "noble" (rare)."""
    def __init__(
        self, master, *,
        colors: T.ThemeColors,
        icon: str | None = None, icon_size: int = 16,
        **kwargs,
    ):
        if icon and "image" not in kwargs:
            kwargs["image"] = _resolve_icon(icon, "#1a1a1a", icon_size)
            kwargs.setdefault("compound", "left")
        super().__init__(
            master,
            fg_color=colors.gold,
            hover_color=colors.gold_soft,
            text_color="#1a1a1a",
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            height=38,
            border_spacing=10,
            **kwargs,
        )


class StatusPill(ctk.CTkLabel):
    """Petite pastille colorée pour afficher un statut (new, contacted, replied…)."""

    STATUS_COLORS = {
        "new":        ("text_muted",   "panel"),
        "qualified":  ("info",         "panel"),
        "contacted":  ("warning",      "panel"),
        "replied":    ("success",      "panel"),
        "won":        ("success",      "panel"),
        "lost":       ("danger",       "panel"),
        "refused":    ("danger",       "panel"),
    }

    def __init__(self, master, *, status: str, colors: T.ThemeColors):
        text_attr, bg_attr = self.STATUS_COLORS.get(status, ("text_muted", "panel"))
        super().__init__(
            master,
            text=status,
            text_color=getattr(colors, text_attr),
            fg_color=getattr(colors, bg_attr),
            corner_radius=T.RADIUS_PILL,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            padx=10,
            pady=2,
        )


class Chip(ctk.CTkButton):
    """Chip cliquable (toggle on/off) pour filtres / sélections rapides."""

    def __init__(
        self,
        master,
        *,
        text: str,
        colors: T.ThemeColors,
        is_active: bool = False,
        on_toggle: Callable[[bool], None] | None = None,
    ):
        self._colors = colors
        self._is_active = is_active
        self._on_toggle = on_toggle
        super().__init__(
            master,
            text=text,
            fg_color=colors.chip_active_bg if hasattr(colors, "chip_active_bg") else colors.accent if is_active else colors.panel,
            hover_color=colors.accent_hover if is_active else colors.panel_hover,
            text_color="#FFFFFF" if is_active else colors.text_secondary,
            corner_radius=T.RADIUS_PILL,
            border_width=1,
            border_color=colors.border_strong,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            height=28,
            command=self._handle_click,
        )

    def _handle_click(self):
        self._is_active = not self._is_active
        self._update_visual()
        if self._on_toggle:
            self._on_toggle(self._is_active)

    def _update_visual(self):
        if self._is_active:
            self.configure(
                fg_color=self._colors.accent,
                text_color="#FFFFFF",
                hover_color=self._colors.accent_hover,
            )
        else:
            self.configure(
                fg_color=self._colors.panel,
                text_color=self._colors.text_secondary,
                hover_color=self._colors.panel_hover,
            )

    @property
    def is_active(self) -> bool:
        return self._is_active

    def set_active(self, active: bool) -> None:
        self._is_active = active
        self._update_visual()


class StatCard(ctk.CTkFrame):
    """Carte de KPI : grand chiffre + label + delta optionnel."""

    def __init__(
        self,
        master,
        *,
        label: str,
        value: str,
        delta: str = "",
        accent: str = "",
        colors: T.ThemeColors,
    ):
        super().__init__(
            master,
            fg_color=colors.panel,
            corner_radius=T.RADIUS_MD,
            border_color=colors.border,
            border_width=1,
        )

        ctk.CTkLabel(
            self,
            text=label.upper(),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=colors.text_muted,
            anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_XS))

        ctk.CTkLabel(
            self,
            text=value,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HERO, "bold"),
            text_color=accent or colors.text_primary,
            anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG)

        if delta:
            ctk.CTkLabel(
                self,
                text=delta,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=colors.text_secondary,
                anchor="w",
            ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        else:
            ctk.CTkFrame(self, height=T.SPACE_LG, fg_color="transparent").pack()


class EmptyState(ctk.CTkFrame):
    """Empty state premium : icône + titre + texte + CTA optionnel."""

    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        icon: str = "search",
        title: str = "Rien ici pour l'instant",
        message: str = "",
        cta_text: str = "",
        cta_command=None,
    ):
        super().__init__(master, fg_color="transparent")
        c = colors

        # Spacer haut
        ctk.CTkFrame(self, fg_color="transparent", height=60).pack()

        # Icône (tirée du module icons)
        try:
            from . import icons as _icons
            img = _icons.get_icon(icon, c.text_muted, size=64)
            if img is not None:
                ctk.CTkLabel(self, image=img, text="").pack(pady=(0, T.SPACE_LG))
        except Exception:
            pass

        # Titre
        ctk.CTkLabel(
            self, text=title,
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_TITLE, "bold"),
            text_color=c.text_primary,
        ).pack(pady=(0, T.SPACE_SM))

        # Message
        if message:
            ctk.CTkLabel(
                self, text=message,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
                text_color=c.text_secondary,
                justify="center", wraplength=480,
            ).pack(pady=(0, T.SPACE_LG))

        # CTA
        if cta_text and cta_command:
            PrimaryButton(
                self, colors=c, icon="send", text=cta_text,
                command=cta_command,
            ).pack(pady=(T.SPACE_SM, 0))


class Toast(ctk.CTkFrame):
    """Toast de notification éphémère (3 s par défaut)."""

    def __init__(
        self,
        master,
        *,
        text: str,
        kind: str = "info",   # info | success | warning | danger
        colors: T.ThemeColors,
        duration_ms: int = 3000,
    ):
        bg = {
            "info": colors.info,
            "success": colors.success,
            "warning": colors.warning,
            "danger": colors.danger,
        }.get(kind, colors.info)

        super().__init__(
            master,
            fg_color=bg,
            corner_radius=T.RADIUS_MD,
        )
        ctk.CTkLabel(
            self,
            text=text,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            text_color="#FFFFFF",
        ).pack(padx=T.SPACE_LG, pady=T.SPACE_MD)

        # Auto-destroy
        self.after(duration_ms, self.destroy)
