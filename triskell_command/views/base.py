"""Vue de base — toutes les vues héritent de BaseView."""

from __future__ import annotations

import customtkinter as ctk

from .. import theme as T
from ..state import AppState


class BaseView(ctk.CTkFrame):
    """Conteneur de vue. Reçoit l'état partagé et les couleurs courantes."""

    title: str = ""
    subtitle: str = ""

    def __init__(self, master, *, app_state: AppState, colors: T.ThemeColors):
        super().__init__(master, fg_color="transparent")
        self.app_state = app_state
        self.colors = colors
        self._built = False

    def show(self) -> None:
        """Appelée à chaque fois que la vue devient active."""
        if not self._built:
            self.build()
            self._built = True
        self.on_show()

    def build(self) -> None:
        """À surcharger : construit l'UI (1 seule fois)."""
        raise NotImplementedError

    def on_show(self) -> None:
        """À surcharger si besoin : appelé à chaque activation (rafraîchissement…)."""
        pass

    def _navigate_to(self, view_id: str) -> None:
        """Demande au TriskellCommandApp parent de basculer vers une autre vue."""
        try:
            self.winfo_toplevel().show_view(view_id)
        except Exception:
            pass
