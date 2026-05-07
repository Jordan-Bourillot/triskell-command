"""Dialog de création / édition d'une fiche client Le Phare.

Une fiche client est liée à un seul site (1:1 via `phare_clients.site_id`
unique). On y stocke les coordonnées, la cadence d'envoi des rapports
(auto mensuel ou manuel) et les dates clés de la mission.
"""
from __future__ import annotations

import logging
import re
from tkinter import messagebox
from typing import Callable, Optional

import customtkinter as ctk

from .. import theme as T
from ..integrations.phare import repo
from .components import PrimaryButton, SecondaryButton

logger = logging.getLogger(__name__)


CADENCE_LABELS = {
    "auto_mensuel": "Envoi auto · 1× par mois (1er du mois)",
    "manuel":       "Envoi manuel · je clique pour générer",
}


class PhareClientDialog(ctk.CTkToplevel):
    """Modale d'ajout / édition d'une fiche client liée à un site."""

    def __init__(
        self,
        master,
        *,
        colors,
        site: dict,
        client: Optional[dict] = None,
        on_done: Optional[Callable[[], None]] = None,
    ):
        super().__init__(master)
        self._colors = colors
        self._site = dict(site)
        self._client = dict(client or {})
        self._on_done = on_done
        self._is_edit = bool(self._client.get("id"))

        self.title("Fiche client Le Phare")
        self.geometry("680x780")
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
            text="Modifier la fiche client" if self._is_edit
                 else "Nouvelle fiche client",
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_TITLE, "bold"),
            text_color=c.text_primary,
        ).pack(anchor="w")

        # Site rappel (lecture seule)
        ctk.CTkLabel(
            outer,
            text=f"Site : {self._site.get('name', '?')} · "
                 f"{self._site.get('domain', '?')}",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, anchor="w",
        ).pack(anchor="w", pady=(2, T.SPACE_LG))

        # ---- Coordonnées ----
        self._contact_name = self._field(
            outer, "Nom du contact (requis)",
            placeholder="ex: Marie Dupont",
            value=self._client.get("contact_name") or "",
        )
        self._contact_email = self._field(
            outer, "Email (requis · destinataire des rapports)",
            placeholder="marie@cabinet-dupont.fr",
            value=self._client.get("contact_email") or "",
        )
        self._phone = self._field(
            outer, "Téléphone",
            placeholder="ex: 06 12 34 56 78",
            value=self._client.get("phone") or "",
        )
        self._company = self._field(
            outer, "Société",
            placeholder="ex: Cabinet Dupont SARL",
            value=self._client.get("company") or "",
        )

        # Adresse facturation (textarea)
        ctk.CTkLabel(
            outer, text="ADRESSE DE FACTURATION",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, T.SPACE_XS))
        self._billing = ctk.CTkTextbox(
            outer, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=80, wrap="word",
        )
        self._billing.pack(fill="x", pady=(2, T.SPACE_MD))
        if self._client.get("billing_address"):
            self._billing.insert("1.0", self._client["billing_address"])

        # ---- Mission ----
        ctk.CTkLabel(
            outer, text="LIVRAISON DES RAPPORTS",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_LG, T.SPACE_XS))

        self._cadence_var = ctk.StringVar(
            value=self._client.get("report_cadence") or "manuel",
        )
        for value, label in CADENCE_LABELS.items():
            ctk.CTkRadioButton(
                outer, variable=self._cadence_var, value=value, text=label,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_primary,
                fg_color=c.accent, hover_color=c.accent,
                border_color=c.border,
            ).pack(fill="x", anchor="w", pady=(T.SPACE_XS, 0))

        # Date démarrage mission
        self._mission_started = self._field(
            outer, "Date de démarrage de la mission (YYYY-MM-DD)",
            placeholder="ex: 2026-05-01",
            value=str(self._client.get("mission_started_at") or ""),
        )

        # Indicateur lecture seule : dernier envoi
        last_sent = self._client.get("last_report_sent_at")
        if last_sent:
            ctk.CTkLabel(
                outer,
                text=f"Dernier rapport envoyé : {last_sent[:10]}",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                text_color=c.text_muted, anchor="w",
            ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, 0))

        # Notes
        ctk.CTkLabel(
            outer, text="NOTES INTERNES",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_LG, T.SPACE_XS))
        self._notes = ctk.CTkTextbox(
            outer, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=80, wrap="word",
        )
        self._notes.pack(fill="x", pady=(2, T.SPACE_MD))
        if self._client.get("notes"):
            self._notes.insert("1.0", self._client["notes"])

        # ---- Actions ----
        actions = ctk.CTkFrame(outer, fg_color="transparent")
        actions.pack(fill="x", pady=(T.SPACE_LG, 0))
        SecondaryButton(actions, colors=c, text="Annuler",
                         command=self.destroy).pack(side="left")
        if self._is_edit:
            SecondaryButton(
                actions, colors=c, text="Supprimer la fiche", icon="close",
                command=self._delete,
            ).pack(side="left", padx=(T.SPACE_SM, 0))
        PrimaryButton(actions, colors=c, text="Enregistrer",
                       command=self._save).pack(side="right")

    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    def _save(self) -> None:
        name = self._contact_name.get().strip()
        email = self._contact_email.get().strip()

        if not name:
            messagebox.showerror("Champ requis",
                                  "Le nom du contact est requis.")
            return
        if not email or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            messagebox.showerror("Email invalide",
                                  "Un email valide est requis "
                                  "(c'est le destinataire des rapports).")
            return

        mission_started = self._mission_started.get().strip() or None
        if mission_started and not re.match(r'^\d{4}-\d{2}-\d{2}$', mission_started):
            messagebox.showerror(
                "Date invalide",
                "Format attendu : YYYY-MM-DD (ex: 2026-05-01).",
            )
            return

        payload = {
            "site_id": self._site["id"],
            "contact_name": name,
            "contact_email": email,
            "phone": self._phone.get().strip(),
            "company": self._company.get().strip(),
            "billing_address": self._billing.get("1.0", "end").rstrip(),
            "report_cadence": self._cadence_var.get(),
            "mission_started_at": mission_started,
            "notes": self._notes.get("1.0", "end").rstrip(),
        }
        if self._is_edit and self._client.get("id"):
            payload["id"] = self._client["id"]

        result = repo.upsert_client(payload)
        if not result:
            messagebox.showerror(
                "Erreur",
                "Impossible d'enregistrer la fiche client. "
                "Vérifie que la migration `08_phare_clients.sql` a été lancée "
                "dans Supabase.",
            )
            return

        if self._on_done:
            try:
                self._on_done()
            except Exception as exc:
                logger.debug("phare client dialog on_done: %s", exc)
        self.destroy()

    def _delete(self) -> None:
        if not self._client.get("id"):
            return
        if not messagebox.askyesno(
            "Supprimer la fiche client",
            "Supprimer définitivement la fiche client ?\n\n"
            "Le site reste, mais les coordonnées et la cadence d'envoi sont "
            "perdues.",
        ):
            return
        if not repo.delete_client(self._client["id"]):
            messagebox.showerror("Erreur",
                                  "Suppression impossible.")
            return
        if self._on_done:
            try:
                self._on_done()
            except Exception:
                pass
        self.destroy()
