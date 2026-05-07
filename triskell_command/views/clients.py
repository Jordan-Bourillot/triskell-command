"""Vue Clients — kanban interne pour piloter la livraison des services
post-paiement (Eliks Studio, Triskell Studio sites, dev custom).

4 colonnes : Briefing → En cours → Livré → Clôturé.
Cartes draggable (clic sur les chevrons pour avancer / reculer le statut),
édition, paiements importés depuis Stripe (futur).
"""

from __future__ import annotations

import logging

import customtkinter as ctk

from .. import theme as T
from ..integrations import clients_repo
from ..widgets.components import (
    Card,
    EmptyState,
    PrimaryButton,
    SecondaryButton,
    ViewHeader,
)
from .base import BaseView

logger = logging.getLogger(__name__)


COLUMNS = [
    ("briefing",    "Briefing"),
    ("in_progress", "En cours"),
    ("delivered",   "Livré"),
    ("closed",      "Clôturé"),
]


class ClientsView(BaseView):
    title = "Clients"
    subtitle = (
        "Chaque projet client, de la commande à la clôture. "
        "Tu fais avancer les cartes au fil du travail."
    )

    def build(self) -> None:
        c = self.colors
        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_MD))

        SecondaryButton(header.actions, colors=c, icon="refresh",
                         text="Rafraîchir",
                         command=self._refresh).pack(side="left",
                                                      padx=(0, T.SPACE_SM))
        PrimaryButton(header.actions, colors=c, icon="pen",
                       text="Nouveau projet",
                       command=self._new_project).pack(side="left")

        # Le tableau (4 colonnes)
        self._kanban = ctk.CTkFrame(self, fg_color="transparent")
        self._kanban.pack(fill="both", expand=True,
                          padx=T.SPACE_2XL, pady=(T.SPACE_SM, T.SPACE_LG))
        for i in range(len(COLUMNS)):
            self._kanban.grid_columnconfigure(i, weight=1, uniform="kanban")
        self._kanban.grid_rowconfigure(0, weight=1)

        self._cols: dict[str, ctk.CTkScrollableFrame] = {}
        for i, (status, label) in enumerate(COLUMNS):
            col = ctk.CTkFrame(
                self._kanban, fg_color=c.panel,
                corner_radius=T.RADIUS_MD,
                border_color=c.border, border_width=1,
            )
            col.grid(row=0, column=i,
                      padx=(0 if i == 0 else T.SPACE_MD,
                              0 if i == len(COLUMNS) - 1 else T.SPACE_MD),
                      sticky="nsew")
            head = ctk.CTkFrame(col, fg_color="transparent")
            head.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))
            ctk.CTkLabel(
                head, text=label.upper(),
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                text_color=c.text_muted, anchor="w",
            ).pack(side="left")
            counter = ctk.CTkLabel(
                head, text="0",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
                text_color=c.accent,
            )
            counter.pack(side="right")
            setattr(self, f"_counter_{status}", counter)
            scroll = ctk.CTkScrollableFrame(
                col, fg_color="transparent",
                scrollbar_button_color=c.border_strong,
            )
            scroll.pack(fill="both", expand=True,
                         padx=T.SPACE_MD, pady=(0, T.SPACE_MD))
            self._cols[status] = scroll

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
        # Vide chaque colonne
        for status, scroll in self._cols.items():
            for w in scroll.winfo_children():
                w.destroy()

        c = self.colors
        # Garde de connexion
        if not self._is_connected():
            self._status_var.set(
                "Connecte-toi à la base partagée Triskell pour voir tes "
                "projets clients (Réglages → Connexion)."
            )
            return

        grouped = clients_repo.list_grouped()
        total = sum(len(v) for v in grouped.values())
        self._status_var.set(f"{total} projet(s) au total.")

        for status, _label in COLUMNS:
            counter_lbl = getattr(self, f"_counter_{status}")
            counter_lbl.configure(text=str(len(grouped.get(status, []))))
            for proj in grouped.get(status, []):
                self._make_card(self._cols[status], proj)
            if not grouped.get(status):
                ctk.CTkLabel(
                    self._cols[status], text="—",
                    font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                    text_color=c.text_muted,
                ).pack(pady=T.SPACE_LG)

    def _make_card(self, master, proj: dict) -> None:
        c = self.colors
        card = Card(master, colors=c)
        card.pack(fill="x", pady=(0, T.SPACE_SM))

        title = (proj.get("title") or proj.get("product_name")
                 or "(sans titre)")
        ctk.CTkLabel(
            card, text=title,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            text_color=c.text_primary, anchor="w",
            justify="left", wraplength=240,
        ).pack(fill="x", padx=T.SPACE_SM, pady=(T.SPACE_SM, 0))

        # Sub-line : client + montant
        client_line = (proj.get("client_name") or "").strip()
        if proj.get("client_company"):
            client_line = (client_line + " · " + proj["client_company"]).strip(" ·")
        amt = int((proj.get("amount_cents") or 0) / 100)
        amt_text = f"{amt} €" if amt else ""
        meta = "  ·  ".join(x for x in [client_line, amt_text] if x)
        if meta:
            ctk.CTkLabel(
                card, text=meta,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                text_color=c.text_muted, anchor="w",
                justify="left", wraplength=240,
            ).pack(fill="x", padx=T.SPACE_SM, pady=(0, T.SPACE_XS))

        # Échéance
        if proj.get("due_date"):
            ctk.CTkLabel(
                card, text=f"Échéance : {proj['due_date']}",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                text_color=c.warning, anchor="w",
            ).pack(fill="x", padx=T.SPACE_SM, pady=(0, T.SPACE_XS))

        # Footer : actions de transition + édition
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=T.SPACE_SM, pady=(T.SPACE_XS, T.SPACE_SM))
        prev_status, next_status = self._neighbors(proj.get("status") or "briefing")
        if prev_status:
            ctk.CTkButton(
                actions, text="<", width=28, height=24,
                fg_color="transparent", hover_color=c.panel_hover,
                text_color=c.text_secondary,
                command=lambda pid=proj["id"], s=prev_status: self._transition(pid, s),
            ).pack(side="left", padx=(0, 2))
        ctk.CTkButton(
            actions, text="Édit", width=44, height=24,
            fg_color="transparent", hover_color=c.panel_hover,
            text_color=c.text_secondary,
            command=lambda p=proj: self._edit(p),
        ).pack(side="left", padx=(0, 2))
        if next_status:
            ctk.CTkButton(
                actions, text=">", width=28, height=24,
                fg_color=c.accent, hover_color=c.accent_hover,
                text_color=c.accent_text,
                command=lambda pid=proj["id"], s=next_status: self._transition(pid, s),
            ).pack(side="right")

    def _neighbors(self, status: str) -> tuple[str | None, str | None]:
        keys = [k for k, _ in COLUMNS]
        try:
            i = keys.index(status)
        except ValueError:
            return (None, keys[0] if keys else None)
        prev = keys[i - 1] if i - 1 >= 0 else None
        nxt = keys[i + 1] if i + 1 < len(keys) else None
        return (prev, nxt)

    def _transition(self, project_id: str, new_status: str) -> None:
        if clients_repo.transition(project_id, new_status):
            self._refresh()
        else:
            self._status_var.set("Impossible de changer la colonne.")

    def _edit(self, proj: dict) -> None:
        from ..widgets.client_dialog import ClientDialog
        ClientDialog(self.winfo_toplevel(), colors=self.colors,
                      project=proj, on_done=self._refresh)

    def _new_project(self) -> None:
        from ..widgets.client_dialog import ClientDialog
        ClientDialog(self.winfo_toplevel(), colors=self.colors,
                      on_done=self._refresh)

    def _is_connected(self) -> bool:
        try:
            from triskell_core.db import get_client, SupabaseNotConfigured
        except ImportError:
            return False
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return False
        return bool(c.is_authenticated)
