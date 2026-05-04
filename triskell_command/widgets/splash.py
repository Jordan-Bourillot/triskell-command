"""Splash screen — courte fenêtre de démarrage avec logo Triskell."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import customtkinter as ctk

from .. import theme as T

logger = logging.getLogger(__name__)


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


class SplashScreen(ctk.CTkToplevel):
    """Petit splash 360×420 avec logo + tagline + microcopie chargement."""

    def __init__(self, master=None, *, duration_ms: int = 1400):
        super().__init__(master)
        c = T.DARK  # splash toujours en sombre, c'est plus chic

        # Window setup
        self.overrideredirect(True)  # pas de barre titre
        self.configure(fg_color=c.bg)
        self.attributes("-topmost", True)
        try:
            from .window_icon import apply_window_icon
            apply_window_icon(self)
        except Exception:
            pass

        W, H = 380, 440
        # Centre l'écran
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = (screen_w - W) // 2
        y = (screen_h - H) // 2
        self.geometry(f"{W}x{H}+{x}+{y}")

        # Logo
        self._logo_ref = None
        logo_path = _resolve_asset("triskell.png")
        if logo_path:
            try:
                from PIL import Image
                img = Image.open(logo_path).convert("RGBA")
                self._logo_ref = ctk.CTkImage(
                    light_image=img, dark_image=img, size=(160, 160),
                )
                ctk.CTkLabel(self, image=self._logo_ref, text="").pack(
                    pady=(60, 30),
                )
            except Exception as exc:
                logger.debug("Splash logo : %s", exc)

        # Brand
        ctk.CTkLabel(
            self,
            text=T.BRAND_NAME,
            font=(T.FONT_FAMILY_DISPLAY, 28, "bold"),
            text_color=c.text_primary,
        ).pack(pady=(0, 0))

        ctk.CTkLabel(
            self,
            text=T.BRAND_PRODUCT.upper(),
            font=(T.FONT_FAMILY_FALLBACK, 12, "bold"),
            text_color=c.gold,
        ).pack(pady=(0, 16))

        # Microcopie chargement
        ctk.CTkLabel(
            self,
            text=T.COPY_LOADING_GENERIC,
            font=(T.FONT_FAMILY_FALLBACK, 11, "italic"),
            text_color=c.text_muted,
        ).pack()

        # Footer
        ctk.CTkLabel(
            self,
            text=T.BRAND_LOCATION,
            font=(T.FONT_FAMILY_FALLBACK, 9),
            text_color=c.text_muted,
        ).pack(side="bottom", pady=(0, 20))

        # Auto-destroy
        self.after(duration_ms, self._close_safely)
        # Force redraw
        self.update_idletasks()

    def _close_safely(self) -> None:
        try:
            self.destroy()
        except Exception:
            pass
