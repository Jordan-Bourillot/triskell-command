"""ClaudeFAB — bouton rond flottant qui suit l'utilisateur partout.

Conçu comme un copain toujours pas loin :
- Toujours visible en bas à droite, par-dessus toutes les vues.
- Au repos : respire doucement (variation de bordure indigo, lente, 4s).
- Hover : grossit + s'éclaire.
- Quand Claude veut te parler (veille proactive a détecté une urgence) :
  pulse rapide + petit point rouge en haut-droit.
- Click : ouvre la modale « Allô Claude ».
- Tooltip au survol : « Allô Claude · F12 ».

Pas de jargon, pas d'anxiété. Juste une présence amicale.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import customtkinter as ctk

from .. import theme as T
from . import icons as I

logger = logging.getLogger(__name__)


SIZE = 60                       # diamètre du bouton
ICON_SIZE = 28                  # icône au repos
ICON_SIZE_HOVER = 32            # icône au hover
DOT_SIZE = 14                   # taille du dot d'alerte
PULSE_INTERVAL_MS = 1700        # respiration calme
PULSE_INTERVAL_ATTENTION_MS = 600   # pulse rapide quand attention
HOVER_BORDER_WIDTH = 5
RESTING_BORDER_WIDTH = 2


class ClaudeFAB(ctk.CTkFrame):
    """Bouton flottant rond pour Allô Claude."""

    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        on_click: Callable[[], None],
    ):
        super().__init__(
            master,
            fg_color=colors.accent,
            width=SIZE, height=SIZE,
            corner_radius=SIZE // 2,
            border_color=colors.accent_glow,
            border_width=RESTING_BORDER_WIDTH,
        )
        self.pack_propagate(False)
        self._colors = colors
        self._on_click = on_click
        self._has_attention = False
        self._pulse_job: Optional[str] = None
        self._pulse_phase = 0
        self._tooltip: Optional[ctk.CTkToplevel] = None

        # Icône vectorielle (sparkle, dessinée en PIL — pas un emoji système).
        self._icon_color = "#FFFFFF"
        self._icon_img_rest = I.get_icon("sparkle", self._icon_color, size=ICON_SIZE)
        self._icon_img_hover = I.get_icon("sparkle", self._icon_color, size=ICON_SIZE_HOVER)
        self._icon = ctk.CTkLabel(
            self,
            text="",
            image=self._icon_img_rest,
            fg_color="transparent",
        )
        self._icon.place(relx=0.5, rely=0.5, anchor="center")

        # Dot d'alerte (caché au repos)
        self._alert_dot = ctk.CTkFrame(
            self,
            fg_color=colors.danger,
            width=DOT_SIZE, height=DOT_SIZE,
            corner_radius=DOT_SIZE // 2,
            border_color=colors.bg, border_width=2,
        )
        # Pas placé tant que pas d'attention
        # Quand on appelle set_attention(True), on le place en top-right

        # Bindings : tout l'ensemble est cliquable
        for w in (self, self._icon):
            w.bind("<Button-1>", self._handle_click)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

        # Démarre la respiration calme
        self._start_pulse()

    # ------------------------------------------------------------------
    # Click / hover
    # ------------------------------------------------------------------
    def _handle_click(self, _evt=None) -> None:
        # On éteint d'abord l'attention pour ne pas continuer à pulser
        # alors que l'utilisateur ouvre la modale.
        self.set_attention(False)
        try:
            self._on_click()
        except Exception as exc:
            logger.warning("ClaudeFAB click: %s", exc)

    def _on_enter(self, _evt=None) -> None:
        c = self._colors
        try:
            self.configure(
                border_width=HOVER_BORDER_WIDTH,
                fg_color=c.accent_hover,
            )
            self._icon.configure(image=self._icon_img_hover)
        except Exception:
            pass
        self._show_tooltip()

    def _on_leave(self, _evt=None) -> None:
        c = self._colors
        try:
            self.configure(
                border_width=RESTING_BORDER_WIDTH,
                fg_color=c.accent,
            )
            self._icon.configure(image=self._icon_img_rest)
        except Exception:
            pass
        self._hide_tooltip()

    # ------------------------------------------------------------------
    # Respiration / attention
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
        # Phase 0 : couleur calme. Phase 1 : couleur plus chaude.
        # Quand attention, on alterne plus vite + couleur danger.
        if self._has_attention:
            if self._pulse_phase == 0:
                try:
                    self.configure(border_color=c.danger,
                                    border_width=HOVER_BORDER_WIDTH)
                except Exception:
                    pass
            else:
                try:
                    self.configure(border_color=c.accent_glow,
                                    border_width=RESTING_BORDER_WIDTH)
                except Exception:
                    pass
            interval = PULSE_INTERVAL_ATTENTION_MS
        else:
            if self._pulse_phase == 0:
                try:
                    self.configure(border_color=c.accent_glow,
                                    border_width=RESTING_BORDER_WIDTH)
                except Exception:
                    pass
            else:
                try:
                    self.configure(border_color=c.accent,
                                    border_width=RESTING_BORDER_WIDTH + 1)
                except Exception:
                    pass
            interval = PULSE_INTERVAL_MS
        self._pulse_phase = 1 - self._pulse_phase
        try:
            self._pulse_job = self.after(interval, self._tick_pulse)
        except Exception:
            self._pulse_job = None

    def set_attention(self, on: bool = True) -> None:
        """Active/désactive le mode "Claude veut te parler" : pulse rapide
        + dot rouge en haut à droite."""
        if on == self._has_attention:
            return
        self._has_attention = bool(on)
        c = self._colors
        if on:
            # Affiche le dot
            try:
                self._alert_dot.place(relx=1.0, rely=0.0,
                                       x=-2, y=2, anchor="ne")
            except Exception:
                pass
        else:
            try:
                self._alert_dot.place_forget()
                self.configure(border_color=c.accent_glow,
                                border_width=RESTING_BORDER_WIDTH)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Tooltip
    # ------------------------------------------------------------------
    # Auto-destroy de sécurité si <Leave> ne se déclenche pas
    # (cas de switch rapide entre 2 FABs voisins).
    _TOOLTIP_TTL_MS = 2500

    def _show_tooltip(self) -> None:
        # Idempotent : détruit tout tooltip restant avant d'en créer un nouveau.
        self._hide_tooltip()
        c = self._colors
        try:
            tip = ctk.CTkToplevel(self)
            tip.overrideredirect(True)
            tip.configure(fg_color=c.bg)
            tip.attributes("-topmost", True)
            wrap = ctk.CTkFrame(
                tip, fg_color=c.bg_alt,
                corner_radius=10,
                border_color=c.accent, border_width=1,
            )
            wrap.pack(padx=0, pady=0)
            label_text = ("Claude veut te parler · F12"
                          if self._has_attention
                          else "Allô Claude · F12")
            ctk.CTkLabel(
                wrap, text=label_text,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
                text_color=c.text_primary,
                fg_color="transparent",
            ).pack(padx=14, pady=8)
            # Place à gauche du bouton, vertical center
            self.update_idletasks()
            tip.update_idletasks()
            x = self.winfo_rootx() - tip.winfo_reqwidth() - 14
            y = self.winfo_rooty() + (SIZE - tip.winfo_reqheight()) // 2
            tip.geometry(f"+{x}+{y}")
            self._tooltip = tip
            # Filet de sécurité : auto-destroy si on rate <Leave>
            self._tooltip_ttl_job = self.after(
                self._TOOLTIP_TTL_MS, self._hide_tooltip)
        except Exception as exc:
            logger.debug("tooltip: %s", exc)
            self._tooltip = None

    def _hide_tooltip(self) -> None:
        # Cancel le TTL en attente
        ttl = getattr(self, "_tooltip_ttl_job", None)
        if ttl is not None:
            try:
                self.after_cancel(ttl)
            except Exception:
                pass
            self._tooltip_ttl_job = None
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
