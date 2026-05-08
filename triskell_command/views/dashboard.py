"""Vue Tableau de bord — KPIs lus en temps réel depuis le CRM."""

from __future__ import annotations

from collections import Counter

import customtkinter as ctk

from .. import theme as T
from ..widgets.components import Card, SecondaryButton, ViewHeader
from ..widgets.components_pro import KpiHero
from .base import BaseView


class DashboardView(BaseView):
    title = "Tableau de bord"
    subtitle = "Vue d'ensemble en temps réel de ton activité de prospection."

    def build(self) -> None:
        c = self.colors
        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_MD))

        SecondaryButton(header.actions, colors=c, icon="refresh", text="Rafraîchir",
                        command=self._refresh).pack(side="left")

        # Bloc 1 : 4 KPIs principaux (entonnoir : total → email → contactés → réponses)
        self._stat_cards: dict[str, KpiHero] = {}
        stats_row = ctk.CTkFrame(self, fg_color="transparent")
        stats_row.pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))
        for key, label, accent in [
            ("total",     "Prospects total", c.text_primary),
            ("with_email","Avec email",      c.info),
            ("contacted", "Contactés",       c.warning),
            ("replied",   "Réponses",        c.success),
        ]:
            card = KpiHero(stats_row, colors=c, label=label, value="—",
                           accent=accent)
            card.pack(side="left", expand=True, fill="x", padx=T.SPACE_SM)
            self._stat_cards[key] = card

        # Bloc 2 : breakdown par source + par statut
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))

        # Card sources
        src_card = Card(body, colors=c)
        src_card.pack(side="left", fill="both", expand=True, padx=(0, T.SPACE_MD))
        ctk.CTkLabel(
            src_card, text="Par source",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))
        self._sources_text = ctk.CTkTextbox(
            src_card, fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_MONO, T.FONT_SIZE_BODY),
            height=150,
        )
        self._sources_text.pack(fill="both", expand=True,
                                padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        # Card statuts
        st_card = Card(body, colors=c)
        st_card.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(
            st_card, text="Par statut",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))
        self._status_text = ctk.CTkTextbox(
            st_card, fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_MONO, T.FONT_SIZE_BODY),
            height=150,
        )
        self._status_text.pack(fill="both", expand=True,
                               padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        # Status bar
        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
        ).pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

    def on_show(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        try:
            from triskell_core.prospect.core.crm import CRM
            crm = CRM()
            prospects = crm.all()
        except Exception as e:
            self._status_var.set(f"⚠ {e}")
            return

        total = len(prospects)
        with_email = sum(1 for p in prospects if p.emails)
        contacted = sum(1 for p in prospects
                        if p.status in ("contacted", "replied", "won"))
        replied = sum(1 for p in prospects if p.status in ("replied", "won"))

        self._set_stat("total", str(total))
        self._set_stat("with_email", str(with_email))
        self._set_stat("contacted", str(contacted))
        self._set_stat("replied", str(replied))

        # Deltas % d'entonnoir : chaque KPI rapporté à l'étape précédente.
        def _pct(num: int, denom: int) -> str:
            return f"{round(100 * num / denom)}%" if denom else ""

        self._stat_cards["with_email"].set_delta(
            _pct(with_email, total), "neutral")
        self._stat_cards["contacted"].set_delta(
            _pct(contacted, with_email), "neutral")
        self._stat_cards["replied"].set_delta(
            _pct(replied, contacted), "up" if replied else "neutral")

        # Breakdown par source
        by_source = Counter()
        for p in prospects:
            for s in (p.sources or []):
                by_source[s.name] += 1
        self._sources_text.delete("1.0", "end")
        if not by_source:
            self._sources_text.insert("1.0", "Aucun prospect.")
        else:
            for src, count in by_source.most_common():
                bar = "█" * min(20, count // max(1, total // 20))
                self._sources_text.insert("end", f"{src:14s} {count:5d}  {bar}\n")

        # Breakdown par statut
        by_status = Counter(p.status or "new" for p in prospects)
        self._status_text.delete("1.0", "end")
        if not by_status:
            self._status_text.insert("1.0", "Aucun prospect.")
        else:
            for status, count in by_status.most_common():
                bar = "█" * min(20, count // max(1, total // 20))
                self._status_text.insert("end", f"{status:14s} {count:5d}  {bar}\n")

        self._status_var.set("✓ KPIs à jour.")

    def _set_stat(self, key: str, value: str) -> None:
        card = self._stat_cards.get(key)
        if card is not None:
            card.set_value(value)
