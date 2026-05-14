"""La Forge du Web — vue en sommeil.

L'app autonome (Tauri 2 + React + Rust) vit dans le repo
`triskell-la-forge` (squelette uniquement, spec v0.2 figée 2026-05-08).
Le bridge mail Teddy est désactivé tant que l'app n'est pas codée.

La vue reste accessible depuis la sidebar mais n'affiche qu'un écran
calme indiquant que La Forge est en pause. Le code détaillé (4 onglets
Briefs / Projets / Workflow / À propos) est conservé en historique git
si besoin de réactiver plus tard.
"""

from __future__ import annotations

import logging
import webbrowser
from pathlib import Path

import customtkinter as ctk

from .. import theme as T
from ..widgets.components import Card, SecondaryButton, ViewHeader
from .base import BaseView

logger = logging.getLogger(__name__)


class LaForgeView(BaseView):
    title = "La Forge du Web"
    subtitle = (
        "Atelier de création de sites web piloté par IA — "
        "actuellement en pause."
    )

    def build(self) -> None:
        c = self.colors

        header = ViewHeader(self, title=self.title, subtitle=self.subtitle,
                            colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_MD))

        SecondaryButton(
            header.actions, colors=c, icon="external",
            text="Voir le repo squelette",
            command=self._open_repo,
        ).pack(side="left")

        # Carte centrale "en sommeil"
        card = Card(self, colors=c)
        card.pack(fill="both", expand=True,
                  padx=T.SPACE_2XL, pady=(0, T.SPACE_2XL))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(expand=True, padx=T.SPACE_2XL, pady=T.SPACE_2XL)

        ctk.CTkLabel(
            inner, text="💤",
            font=(T.FONT_FAMILY_DISPLAY, 72),
            text_color=c.text_muted,
        ).pack(pady=(0, T.SPACE_MD))

        ctk.CTkLabel(
            inner, text="La Forge dort.",
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary,
        ).pack(pady=(0, T.SPACE_SM))

        ctk.CTkLabel(
            inner,
            text=(
                "L'app autonome (Tauri + React + Rust) existe en squelette "
                "dans le repo triskell-la-forge — code non démarré.\n\n"
                "Le bridge mail (intake « Demande de création de site ») "
                "est désactivé. Aucun nouveau brief ne sera capté tant que "
                "le moteur d'exécution n'est pas construit.\n\n"
                "Cette vue est conservée pour pouvoir relancer le chantier "
                "facilement quand le moment sera venu."
            ),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_secondary,
            justify="center", wraplength=560,
        ).pack(pady=(0, T.SPACE_LG))

    def on_show(self) -> None:
        pass

    # ------------------------------------------------------------------
    def _open_repo(self) -> None:
        path = Path.home() / "Triskell" / "triskell-la-forge"
        if path.exists():
            try:
                webbrowser.open(path.as_uri(), new=2)
            except Exception as exc:
                logger.debug("open_repo: %s", exc)
        else:
            webbrowser.open(
                "https://github.com/Jordan-Bourillot/triskell-la-forge",
                new=2,
            )
