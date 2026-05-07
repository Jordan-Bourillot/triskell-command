"""Vue Funnel — visualise la conversion Prospects → Envoyés → Réponses →
Intéressés → Gagnés, par segment et par période.

Lit funnel_metrics qui agrège prospects + email_history. Pas de tracking
externe : c'est une vue purement basée sur les données déjà en Supabase.
"""

from __future__ import annotations

import logging

import customtkinter as ctk

from .. import theme as T
from ..integrations import funnel_metrics
from ..widgets.components import (
    Card,
    Chip,
    EmptyState,
    SecondaryButton,
    StatCard,
    ViewHeader,
)
from .base import BaseView

logger = logging.getLogger(__name__)


PERIOD_LABELS = {
    "7d":  "7 jours",
    "30d": "30 jours",
    "90d": "90 jours",
    "all": "Tout",
}
SEGMENT_LABELS = {
    "all":       "Tous",
    "creators":  "Créateurs",
    "b2b_local": "B2B local",
}
STAGE_LABELS = [
    ("prospects",  "Prospects"),
    ("sent",       "Envoyés"),
    ("replies",    "Réponses"),
    ("interested", "Intéressés"),
    ("won",        "Gagnés"),
]


class FunnelView(BaseView):
    title = "Conversions"
    subtitle = (
        "Tes taux de transformation par type de prospect et par période. "
        "Tu vois en un coup d'œil ce qui marche et ce qui coince."
    )

    def build(self) -> None:
        c = self.colors
        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_MD))

        SecondaryButton(header.actions, colors=c, icon="refresh",
                         text="Rafraîchir",
                         command=self._refresh).pack(side="left")

        # Filtres en deux lignes pour respirer
        filters_wrap = ctk.CTkFrame(self, fg_color="transparent")
        filters_wrap.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_SM, T.SPACE_LG))

        # Période
        period_block = ctk.CTkFrame(filters_wrap, fg_color="transparent")
        period_block.pack(fill="x", anchor="w", pady=(0, T.SPACE_SM))
        ctk.CTkLabel(
            period_block, text="PÉRIODE",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted,
        ).pack(side="left", padx=(0, T.SPACE_MD))
        self._period = "30d"
        self._period_chips: dict[str, Chip] = {}
        for k, label in PERIOD_LABELS.items():
            chip = Chip(period_block, text=label, colors=c,
                         is_active=(k == self._period),
                         on_toggle=lambda _v, kk=k: self._set_period(kk))
            chip.pack(side="left", padx=(0, T.SPACE_SM))
            self._period_chips[k] = chip

        # Segment (sur sa propre ligne)
        seg_block = ctk.CTkFrame(filters_wrap, fg_color="transparent")
        seg_block.pack(fill="x", anchor="w")
        ctk.CTkLabel(
            seg_block, text="TYPE DE PROSPECT",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted,
        ).pack(side="left", padx=(0, T.SPACE_MD))
        self._segment = "all"
        self._seg_chips: dict[str, Chip] = {}
        for k, label in SEGMENT_LABELS.items():
            chip = Chip(seg_block, text=label, colors=c,
                         is_active=(k == self._segment),
                         on_toggle=lambda _v, kk=k: self._set_segment(kk))
            chip.pack(side="left", padx=(0, T.SPACE_SM))
            self._seg_chips[k] = chip

        # Container scroll
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        self._scroll.pack(fill="both", expand=True,
                          padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))

        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
        ).pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

    def on_show(self) -> None:
        self._refresh()

    def _set_period(self, period: str) -> None:
        self._period = period
        for k, chip in self._period_chips.items():
            chip.set_active(k == period)
        self._refresh()

    def _set_segment(self, segment: str) -> None:
        self._segment = segment
        for k, chip in self._seg_chips.items():
            chip.set_active(k == segment)
        self._refresh()

    def _refresh(self) -> None:
        for w in self._scroll.winfo_children():
            w.destroy()
        c = self.colors

        data = funnel_metrics.compute_funnel(period=self._period,
                                              segment=self._segment)
        if not data.get("ok"):
            EmptyState(
                self._scroll, colors=c, icon="settings",
                title="Connexion à la base partagée requise",
                message="Les chiffres de conversion viennent de la base "
                        "partagée Triskell. Connecte-toi depuis les Réglages.",
                cta_text="Aller dans Réglages",
                cta_command=lambda: self._navigate_to("config"),
            ).pack(fill="both", expand=True)
            self._status_var.set("Connexion requise.")
            return

        stages = data["stages"]

        # ---- Funnel principal (5 cartes) ----
        grid = ctk.CTkFrame(self._scroll, fg_color="transparent")
        grid.pack(fill="x", pady=(0, T.SPACE_LG))
        for col in range(len(STAGE_LABELS)):
            grid.grid_columnconfigure(col, weight=1, uniform="funnel")

        prev = None
        for i, (key, label) in enumerate(STAGE_LABELS):
            value = stages.get(key, 0)
            delta = ""
            accent = ""
            if prev is not None and prev > 0:
                pct = round(100 * value / prev, 1)
                delta = f"{pct}% du précédent"
                if key == "won" and pct >= 5:
                    accent = c.success
                elif key == "interested" and pct >= 5:
                    accent = c.success
            elif key == "prospects":
                delta = f"sur {self._period}"
            StatCard(
                grid, label=label, value=str(value),
                delta=delta, accent=accent, colors=c,
            ).grid(row=0, column=i,
                    padx=(0 if i == 0 else T.SPACE_SM,
                            0 if i == len(STAGE_LABELS) - 1 else T.SPACE_SM),
                    sticky="ew")
            prev = value

        # ---- Répartition par catégorie de réponse ----
        by_cat = data.get("by_category") or {}
        if by_cat:
            self._section_label("Types de réponses reçues")
            self._horizontal_bar(by_cat, color=c.accent_secondary)

        # ---- Répartition par statut prospect ----
        by_status = data.get("by_status") or {}
        if by_status:
            self._section_label("Où en sont tes prospects")
            self._horizontal_bar(by_status, color=c.accent)

        # ---- Top produits / templates ----
        by_prod = data.get("by_product") or {}
        if by_prod:
            self._section_label("Produits les plus mis en avant")
            self._horizontal_bar(by_prod, color=c.text_secondary)

        # Status bar
        sent = stages["sent"]
        won = stages["won"]
        interested = stages["interested"]
        denom = max(sent, 1)
        self._status_var.set(
            f"Période : {PERIOD_LABELS.get(self._period)} · "
            f"Type : {SEGMENT_LABELS.get(self._segment)} · "
            f"Taux de réponse {round(100*stages['replies']/denom, 1)}% · "
            f"Taux d'intérêt {round(100*interested/denom, 1)}% · "
            f"Taux de gain {round(100*won/max(stages['prospects'],1), 1)}%"
        )

    def _section_label(self, text: str) -> None:
        c = self.colors
        wrap = ctk.CTkFrame(self._scroll, fg_color="transparent")
        wrap.pack(fill="x", pady=(T.SPACE_2XL, T.SPACE_MD))
        bar = ctk.CTkFrame(wrap, fg_color=c.accent, width=24, height=2,
                            corner_radius=1)
        bar.pack(side="left", padx=(0, T.SPACE_SM))
        bar.pack_propagate(False)
        ctk.CTkLabel(
            wrap, text=text.upper(),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(side="left", fill="x")

    def _horizontal_bar(self, data: dict, *, color: str) -> None:
        """Petit graphe : labels + barres proportionnelles."""
        c = self.colors
        if not data:
            return
        max_val = max(data.values()) or 1
        card = Card(self._scroll, colors=c)
        card.pack(fill="x", pady=(0, T.SPACE_MD))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=T.SPACE_LG, pady=T.SPACE_LG)
        for k, v in sorted(data.items(), key=lambda kv: -kv[1]):
            row = ctk.CTkFrame(inner, fg_color="transparent")
            row.pack(fill="x", pady=(0, 2))
            ctk.CTkLabel(
                row, text=str(k),
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_secondary, anchor="w", width=180,
            ).pack(side="left")
            # Barre
            bar_wrap = ctk.CTkFrame(row, fg_color=c.panel,
                                     corner_radius=T.RADIUS_SM, height=14)
            bar_wrap.pack(side="left", fill="x", expand=True,
                           padx=(T.SPACE_SM, T.SPACE_SM))
            bar_wrap.pack_propagate(False)
            try:
                pct = max(2, int(100 * v / max_val))
            except Exception:
                pct = 2
            inner_bar = ctk.CTkFrame(
                bar_wrap, fg_color=color,
                width=int(pct * 4), height=14, corner_radius=T.RADIUS_SM,
            )
            inner_bar.pack(side="left")
            inner_bar.pack_propagate(False)
            ctk.CTkLabel(
                row, text=str(v),
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
                text_color=c.text_primary, width=40,
            ).pack(side="left")
