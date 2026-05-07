"""Dialog de création / édition d'un projet client."""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from .. import theme as T
from ..integrations import clients_repo
from .components import PrimaryButton, SecondaryButton


PRODUCT_OPTIONS = (
    ("eliks",         "Eliks Studio (Growth)"),
    ("triskell-sites","Triskell Studio Sites"),
    ("custom-dev",    "Dev custom"),
    ("other",         "Autre"),
)
STATUS_LABELS = {
    "briefing":    "Briefing",
    "in_progress": "En cours",
    "delivered":   "Livré",
    "closed":      "Clôturé",
}


class ClientDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        project: Optional[dict] = None,
        on_done: Callable[[], None] | None = None,
    ):
        super().__init__(master)
        self._colors = colors
        self._project = project or {}
        self._on_done = on_done

        self.title("Projet client")
        self.geometry("680x720")
        self.configure(fg_color=colors.bg)
        try:
            self.grab_set()
            self.transient(master)
        except Exception:
            pass

        c = colors
        outer = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        outer.pack(fill="both", expand=True, padx=T.SPACE_LG, pady=T.SPACE_LG)

        ctk.CTkLabel(
            outer,
            text="Modifier" if project else "Nouveau projet client",
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_TITLE, "bold"),
            text_color=c.text_primary,
        ).pack(anchor="w")
        ctk.CTkLabel(
            outer,
            text="Crée une carte dans le tableau Clients. "
                 "Visible automatiquement par Jordan et Thomas.",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, wraplength=600, justify="left",
        ).pack(anchor="w", pady=(2, T.SPACE_LG))

        self._title = self._field(outer, "Titre du projet",
                                   placeholder="ex: Site Despiertos Shop",
                                   value=self._project.get("title") or "")

        # Produit
        ctk.CTkLabel(
            outer, text="PRODUIT / SERVICE",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, T.SPACE_XS))
        self._product_var = ctk.StringVar(
            value=next((lbl for k, lbl in PRODUCT_OPTIONS
                        if k == self._project.get("product_key")),
                        PRODUCT_OPTIONS[0][1])
        )
        ctk.CTkOptionMenu(
            outer, variable=self._product_var,
            values=[lbl for _k, lbl in PRODUCT_OPTIONS],
            fg_color=c.panel, button_color=c.panel,
            button_hover_color=c.panel_hover, dropdown_fg_color=c.panel,
            text_color=c.text_primary,
        ).pack(fill="x")

        # Status
        ctk.CTkLabel(
            outer, text="STATUT",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, T.SPACE_XS))
        self._status_var = ctk.StringVar(
            value=STATUS_LABELS.get(self._project.get("status") or "briefing",
                                     "Briefing")
        )
        ctk.CTkOptionMenu(
            outer, variable=self._status_var,
            values=list(STATUS_LABELS.values()),
            fg_color=c.panel, button_color=c.panel,
            button_hover_color=c.panel_hover, dropdown_fg_color=c.panel,
            text_color=c.text_primary,
        ).pack(fill="x")

        self._client_name = self._field(outer, "Nom du client",
                                          placeholder="ex: Marie Dupont",
                                          value=self._project.get("client_name") or "")
        self._client_email = self._field(outer, "Email client",
                                           placeholder="marie@exemple.fr",
                                           value=self._project.get("client_email") or "")
        self._client_company = self._field(outer, "Société client",
                                             placeholder="(optionnel)",
                                             value=self._project.get("client_company") or "")
        self._amount = self._field(outer, "Montant (€)",
                                     placeholder="ex: 490",
                                     value=str(int((self._project.get("amount_cents") or 0) / 100) or ""))
        self._due_date = self._field(outer, "Échéance (YYYY-MM-DD, optionnel)",
                                       placeholder="",
                                       value=str(self._project.get("due_date") or ""))

        # Brief
        ctk.CTkLabel(
            outer, text="BRIEF",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, T.SPACE_XS))
        self._brief = ctk.CTkTextbox(
            outer, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=120, wrap="word",
        )
        self._brief.pack(fill="x", pady=(2, T.SPACE_MD))
        self._brief.insert("1.0", self._project.get("brief") or "")

        # Notes
        ctk.CTkLabel(
            outer, text="NOTES INTERNES",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, T.SPACE_XS))
        self._notes = ctk.CTkTextbox(
            outer, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=80, wrap="word",
        )
        self._notes.pack(fill="x", pady=(2, T.SPACE_MD))
        self._notes.insert("1.0", self._project.get("notes") or "")

        actions = ctk.CTkFrame(outer, fg_color="transparent")
        actions.pack(fill="x", pady=(T.SPACE_LG, 0))
        SecondaryButton(actions, colors=c, text="Annuler",
                         command=self.destroy).pack(side="left")
        PrimaryButton(actions, colors=c, text="Enregistrer",
                       command=self._save).pack(side="right")

    def _field(self, master, label: str, *,
                placeholder: str = "", value: str = "") -> ctk.CTkEntry:
        c = self._colors
        ctk.CTkLabel(
            master, text=label.upper(),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, T.SPACE_XS))
        entry = ctk.CTkEntry(
            master, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=36,
            placeholder_text=placeholder,
        )
        entry.pack(fill="x")
        if value:
            entry.insert(0, value)
        return entry

    def _save(self) -> None:
        # Map labels back
        product_label = self._product_var.get()
        product_key = next((k for k, lbl in PRODUCT_OPTIONS
                             if lbl == product_label), "other")
        status_label = self._status_var.get()
        status_key = next((k for k, lbl in STATUS_LABELS.items()
                             if lbl == status_label), "briefing")

        amount = (self._amount.get() or "").strip()
        try:
            amount_cents = int(float(amount.replace(",", ".")) * 100) if amount else 0
        except Exception:
            amount_cents = 0

        due = (self._due_date.get() or "").strip() or None

        payload = {
            "title": self._title.get().strip(),
            "product_key": product_key,
            "product_name": product_label,
            "status": status_key,
            "client_name": self._client_name.get().strip(),
            "client_email": self._client_email.get().strip(),
            "client_company": self._client_company.get().strip(),
            "amount_cents": amount_cents,
            "due_date": due,
            "brief": self._brief.get("1.0", "end").rstrip(),
            "notes": self._notes.get("1.0", "end").rstrip(),
        }

        if self._project.get("id"):
            ok = clients_repo.update_project(self._project["id"], payload)
        else:
            ok = bool(clients_repo.create_project(payload))
        if not ok:
            from tkinter import messagebox
            messagebox.showerror("Erreur",
                                  "Impossible de sauver le projet.")
            return
        if self._on_done:
            try:
                self._on_done()
            except Exception:
                pass
        self.destroy()
