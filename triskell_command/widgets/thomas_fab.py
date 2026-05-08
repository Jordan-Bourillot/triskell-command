"""ThomasFAB — bulle flottante de chat avec Thomas (ou Jordan, selon le user
loggé). Placée juste au-dessus du ClaudeFAB, même style mais en vert pour
distinguer la couleur instantanément.

- Au repos : respiration verte calme.
- Quand l'autre user a écrit (messages non lus) : pulse rapide + petit
  badge avec le compteur en haut-droit.
- Click : ouvre `ThomasDialog` (chat 1-à-1).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import customtkinter as ctk

from .. import theme as T
from . import icons as I

logger = logging.getLogger(__name__)


SIZE = 60
ICON_SIZE = 28
ICON_SIZE_HOVER = 32
DOT_SIZE = 18                        # un peu plus gros que sur Claude pour le compteur
PULSE_INTERVAL_MS = 1900
PULSE_INTERVAL_ATTENTION_MS = 650
HOVER_BORDER_WIDTH = 5
RESTING_BORDER_WIDTH = 2


class ThomasFAB(ctk.CTkFrame):
    """Bouton flottant rond pour le chat Jordan ↔ Thomas."""

    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        on_click: Callable[[], None],
        peer_name: Optional[str] = None,
    ):
        super().__init__(
            master,
            fg_color=colors.success,
            width=SIZE, height=SIZE,
            corner_radius=SIZE // 2,
            border_color=colors.success,
            border_width=RESTING_BORDER_WIDTH,
        )
        self.pack_propagate(False)
        self._colors = colors
        self._on_click = on_click
        self._peer_name = peer_name or "Thomas"
        self._unread = 0
        self._last_preview: Optional[str] = None
        self._last_from_me: bool = False
        self._pulse_job: Optional[str] = None
        self._pulse_phase = 0
        self._tooltip: Optional[ctk.CTkToplevel] = None

        # Icône vectorielle (bulle de chat, dessinée en PIL — pas un emoji système).
        self._icon_img_rest = I.get_icon("chat_bubble", "#FFFFFF", size=ICON_SIZE)
        self._icon_img_hover = I.get_icon("chat_bubble", "#FFFFFF", size=ICON_SIZE_HOVER)
        self._icon = ctk.CTkLabel(
            self, text="",
            image=self._icon_img_rest,
            fg_color="transparent",
        )
        self._icon.place(relx=0.5, rely=0.5, anchor="center")

        # Badge compteur (caché au repos)
        self._badge = ctk.CTkFrame(
            self, fg_color=colors.danger,
            width=DOT_SIZE, height=DOT_SIZE,
            corner_radius=DOT_SIZE // 2,
            border_color=colors.bg, border_width=2,
        )
        self._badge_label = ctk.CTkLabel(
            self._badge, text="",
            font=(T.FONT_FAMILY_FALLBACK, 10, "bold"),
            text_color="#FFFFFF", fg_color="transparent",
        )
        self._badge_label.place(relx=0.5, rely=0.5, anchor="center")

        for w in (self, self._icon):
            w.bind("<Button-1>", self._handle_click)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

        self._start_pulse()

    # ------------------------------------------------------------------
    def _handle_click(self, _evt=None) -> None:
        try:
            self._on_click()
        except Exception as exc:
            logger.warning("ThomasFAB click: %s", exc)

    def _on_enter(self, _evt=None) -> None:
        try:
            self.configure(border_width=HOVER_BORDER_WIDTH)
            self._icon.configure(image=self._icon_img_hover)
        except Exception:
            pass
        self._show_tooltip()

    def _on_leave(self, _evt=None) -> None:
        try:
            self.configure(border_width=RESTING_BORDER_WIDTH)
            self._icon.configure(image=self._icon_img_rest)
        except Exception:
            pass
        self._hide_tooltip()

    # ------------------------------------------------------------------
    def _start_pulse(self) -> None:
        if self._pulse_job is not None:
            try:
                self.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None
        self._pulse_phase = 0
        self._tick_pulse()

    def _tick_pulse(self) -> None:
        c = self._colors
        if self._unread > 0:
            if self._pulse_phase == 0:
                try:
                    self.configure(border_color=c.danger,
                                    border_width=HOVER_BORDER_WIDTH)
                except Exception:
                    pass
            else:
                try:
                    self.configure(border_color=c.success,
                                    border_width=RESTING_BORDER_WIDTH)
                except Exception:
                    pass
            interval = PULSE_INTERVAL_ATTENTION_MS
        else:
            if self._pulse_phase == 0:
                try:
                    self.configure(border_color=c.success,
                                    border_width=RESTING_BORDER_WIDTH)
                except Exception:
                    pass
            else:
                try:
                    self.configure(border_color=c.success,
                                    border_width=RESTING_BORDER_WIDTH + 1)
                except Exception:
                    pass
            interval = PULSE_INTERVAL_MS
        self._pulse_phase = 1 - self._pulse_phase
        try:
            self._pulse_job = self.after(interval, self._tick_pulse)
        except Exception:
            self._pulse_job = None

    # ------------------------------------------------------------------
    def set_unread(self, n: int) -> None:
        """Met à jour le compteur de non-lus. 0 → cache le badge."""
        n = max(0, int(n or 0))
        if n == self._unread:
            return
        self._unread = n
        if n <= 0:
            try:
                self._badge.place_forget()
            except Exception:
                pass
        else:
            label = str(n) if n < 10 else "9+"
            try:
                self._badge_label.configure(text=label)
                self._badge.place(relx=1.0, rely=0.0,
                                   x=-2, y=2, anchor="ne")
            except Exception:
                pass

    def set_peer_name(self, name: str) -> None:
        self._peer_name = name or self._peer_name

    def set_last_preview(self, body: str | None,
                          *, is_from_me: bool = False) -> None:
        """Met en cache le dernier message (affiché dans le tooltip)."""
        if body:
            body = body.strip().replace("\n", " ")
            if len(body) > 90:
                body = body[:87] + "…"
        self._last_preview = body or None
        self._last_from_me = bool(is_from_me)

    # ------------------------------------------------------------------
    def _show_tooltip(self) -> None:
        if self._tooltip is not None:
            return
        c = self._colors
        try:
            tip = ctk.CTkToplevel(self)
            tip.overrideredirect(True)
            tip.configure(fg_color=c.panel_elevated)
            tip.attributes("-topmost", True)
            # Titre
            if self._unread > 0:
                title = f"{self._peer_name} t'a écrit !"
                title_color = c.danger
            else:
                title = f"Chat {self._peer_name} · F11"
                title_color = c.text_primary
            ctk.CTkLabel(
                tip, text=title,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
                text_color=title_color,
                fg_color="transparent",
            ).pack(padx=12, pady=(8, 2), anchor="w")
            # Aperçu du dernier message (si dispo)
            if self._last_preview:
                prefix = "Toi : " if self._last_from_me else f"{self._peer_name} : "
                preview = f"{prefix}{self._last_preview}"
                ctk.CTkLabel(
                    tip, text=preview,
                    font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                    text_color=c.text_secondary,
                    fg_color="transparent",
                    justify="left", wraplength=260,
                    anchor="w",
                ).pack(padx=12, pady=(0, 8), anchor="w", fill="x")
            else:
                # Padding bottom équivalent si pas d'aperçu
                ctk.CTkLabel(
                    tip, text="", height=2, fg_color="transparent",
                ).pack(padx=12, pady=(0, 6))
            self.update_idletasks()
            tip.update_idletasks()
            x = self.winfo_rootx() - tip.winfo_reqwidth() - 12
            y = self.winfo_rooty() + (SIZE - tip.winfo_reqheight()) // 2
            tip.geometry(f"+{x}+{y}")
            self._tooltip = tip
        except Exception as exc:
            logger.debug("tooltip thomas: %s", exc)
            self._tooltip = None

    def _hide_tooltip(self) -> None:
        if self._tooltip is None:
            return
        try:
            self._tooltip.destroy()
        except Exception:
            pass
        self._tooltip = None

    def destroy(self) -> None:
        if self._pulse_job is not None:
            try:
                self.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None
        self._hide_tooltip()
        super().destroy()
