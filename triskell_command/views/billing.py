"""Facturation — vue Triskell Command.

DESTINATION FINALE :
    Triskell\\triskell-command\\triskell_command\\views\\billing.py

Vue minimaliste pour gérer les factures Triskell. La création se fait
en automatique via l'orchestrateur post-paiement (Étape 3 du plan
d'automatisation), donc cette vue est surtout en lecture + actions de
maintenance :

  • Liste des factures (filtre par année, par email client)
  • Téléchargement PDF
  • Émission d'avoir sur une facture sélectionnée
  • Export FEC annuel

Pas de création manuelle pour l'instant — si Jordan en a besoin, on
ajoutera un PhareClientDialog-like, mais d'abord il faut prouver que
la chaîne auto fonctionne.

Pattern aligné sur `views/phare.py`.
"""
from __future__ import annotations

import logging
import threading
import webbrowser
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

from .. import theme as T
from ..integrations.billing import BillingError, get_provider
from ..integrations.billing import repo as billing_repo
from ..widgets.components import (
    Card, EmptyState, PrimaryButton, SecondaryButton, ViewHeader,
)
from .base import BaseView

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers de format
# ---------------------------------------------------------------------------
def _fmt_money_cents(cents: int) -> str:
    if cents is None:
        return "—"
    negative = cents < 0
    cents = abs(int(cents))
    euros, c = divmod(cents, 100)
    return f"{'-' if negative else ''}{euros:,} €".replace(",", " ") + f",{c:02d}"


def _fmt_date(iso: str) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except ValueError:
        return iso[:10]


# ---------------------------------------------------------------------------
# Vue
# ---------------------------------------------------------------------------
class BillingView(BaseView):
    title = "Facturation"
    subtitle = (
        "Factures émises par Triskell. Numérotation continue, mentions "
        "légales auto, export FEC. Tout est versionné en archive immuable."
    )

    def __init__(self, master, *, app_state, colors):
        super().__init__(master, app_state=app_state, colors=colors)
        self._invoices: list[dict] = []
        self._selected_id: Optional[str] = None

    def on_show(self):
        self._refresh()

    # -----------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------
    def build(self):
        ViewHeader(self, title=self.title, subtitle=self.subtitle).pack(
            fill="x", padx=24, pady=(16, 8)
        )

        # Barre filtres + actions
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24, pady=(0, 12))

        ctk.CTkLabel(bar, text="Année :").pack(side="left", padx=(0, 6))
        self._year_var = ctk.StringVar(value=str(date.today().year))
        self._year_entry = ctk.CTkEntry(bar, width=80, textvariable=self._year_var)
        self._year_entry.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(bar, text="Email client :").pack(side="left", padx=(0, 6))
        self._email_var = ctk.StringVar(value="")
        self._email_entry = ctk.CTkEntry(bar, width=220, textvariable=self._email_var)
        self._email_entry.pack(side="left", padx=(0, 12))

        SecondaryButton(bar, text="Filtrer", command=self._refresh).pack(side="left")
        SecondaryButton(bar, text="Exporter FEC", command=self._export_fec).pack(side="right", padx=4)

        # Carte liste
        self._list_card = Card(self, title="Factures")
        self._list_card.pack(fill="both", expand=True, padx=24, pady=(0, 16))
        self._list_body = ctk.CTkScrollableFrame(self._list_card.body, fg_color="transparent")
        self._list_body.pack(fill="both", expand=True)

        # Carte actions détail
        self._detail_card = Card(self, title="Action")
        self._detail_card.pack(fill="x", padx=24, pady=(0, 16))
        actions = ctk.CTkFrame(self._detail_card.body, fg_color="transparent")
        actions.pack(fill="x", padx=8, pady=8)
        PrimaryButton(actions, text="Télécharger PDF",
                      command=self._download_pdf).pack(side="left", padx=4)
        SecondaryButton(actions, text="Émettre un avoir",
                        command=self._issue_credit_note).pack(side="left", padx=4)
        self._status = ctk.CTkLabel(actions, text="", text_color=self.colors.text_muted)
        self._status.pack(side="left", padx=12)

    def _set_status(self, msg: str, *, error: bool = False):
        self._status.configure(
            text=msg,
            text_color=self.colors.danger if error else self.colors.text_muted,
        )

    # -----------------------------------------------------------------
    # Données
    # -----------------------------------------------------------------
    def _refresh(self):
        year_str = (self._year_var.get() or "").strip()
        email = (self._email_var.get() or "").strip()
        year = int(year_str) if year_str.isdigit() else None
        try:
            self._invoices = get_provider().list_invoices(
                year=year, client_email=email or None, limit=200,
            )
        except Exception as exc:
            logger.warning("billing list_invoices failed: %s", exc)
            self._invoices = []
            self._set_status(f"Erreur de chargement : {exc}", error=True)
        else:
            self._set_status(f"{len(self._invoices)} facture(s) chargée(s).")

        for child in self._list_body.winfo_children():
            child.destroy()

        if not self._invoices:
            EmptyState(self._list_body,
                        text="Aucune facture pour ce filtre.").pack(fill="both", expand=True, pady=24)
            return

        # En-tête
        header = ctk.CTkFrame(self._list_body, fg_color="transparent")
        header.pack(fill="x", padx=4, pady=(0, 4))
        for label, w in (("Numéro", 140), ("Date", 90), ("Client", 240),
                         ("Total TTC", 110), ("Statut", 90)):
            ctk.CTkLabel(header, text=label, width=w, anchor="w",
                         text_color=self.colors.text_muted,
                         font=ctk.CTkFont(size=11, weight="bold")
                         ).pack(side="left")

        for inv in self._invoices:
            self._render_row(inv)

    def _render_row(self, inv: dict):
        row = ctk.CTkFrame(self._list_body, fg_color=self.colors.panel,
                            corner_radius=4)
        row.pack(fill="x", padx=4, pady=2)
        snap = inv.get("client_snapshot") or {}

        status = "Avoir" if inv.get("is_credit_note") else (
            "Annulée" if inv.get("is_cancelled") else "Émise"
        )
        client_label = (snap.get("name") or snap.get("email") or "—")[:38]

        for value, w in (
            (inv.get("invoice_number", ""), 140),
            (_fmt_date(inv.get("issued_at", "")), 90),
            (client_label, 240),
            (_fmt_money_cents(inv.get("total_ttc_cents")), 110),
            (status, 90),
        ):
            ctk.CTkLabel(row, text=str(value), width=w, anchor="w",
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=6, pady=6)

        def _select(_=None, _id=inv["id"]):
            self._selected_id = _id
            self._set_status(f"Sélectionné : {inv.get('invoice_number', '')}.")

        row.bind("<Button-1>", _select)
        for child in row.winfo_children():
            child.bind("<Button-1>", _select)

    # -----------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------
    def _download_pdf(self):
        if not self._selected_id:
            self._set_status("Sélectionne d'abord une facture dans la liste.", error=True)
            return
        try:
            url = get_provider().get_invoice_pdf_url(self._selected_id, signed_ttl_seconds=600)
        except Exception as exc:
            self._set_status(f"PDF indisponible : {exc}", error=True)
            return
        if not url:
            self._set_status("PDF introuvable (pas encore généré ?).", error=True)
            return
        webbrowser.open(url)
        self._set_status("Lien ouvert dans le navigateur.")

    def _issue_credit_note(self):
        if not self._selected_id:
            self._set_status("Sélectionne d'abord une facture.", error=True)
            return
        reason = ctk.CTkInputDialog(
            text="Motif de l'avoir (visible sur le PDF) :",
            title="Émettre un avoir",
        ).get_input()
        if not reason:
            return

        def _run():
            try:
                result = get_provider().generate_credit_note(
                    self._selected_id, reason=reason,
                )
                self.after(0, lambda: self._on_credit_note_done(result))
            except BillingError as exc:
                self.after(0, lambda: self._set_status(f"Erreur : {exc}", error=True))
            except Exception as exc:
                logger.exception("credit note failed")
                self.after(0, lambda: self._set_status(f"Erreur : {exc}", error=True))

        self._set_status("Émission de l'avoir en cours…")
        threading.Thread(target=_run, daemon=True).start()

    def _on_credit_note_done(self, result):
        self._set_status(f"Avoir {result.invoice_number} émis.")
        messagebox.showinfo("Avoir émis",
                             f"Avoir {result.invoice_number} créé avec succès.\n"
                             f"Facture d'origine marquée annulée.")
        self._refresh()

    def _export_fec(self):
        year_str = (self._year_var.get() or "").strip()
        if not year_str.isdigit():
            self._set_status("Saisir une année valide pour exporter le FEC.", error=True)
            return
        year = int(year_str)
        path = filedialog.asksaveasfilename(
            title=f"Exporter FEC {year}",
            defaultextension=".txt",
            initialfile=f"FEC_{year}.txt",
            filetypes=[("Fichier FEC", "*.txt")],
        )
        if not path:
            return

        def _run():
            try:
                payload = get_provider().export_fec(year)
                Path(path).write_bytes(payload)
                self.after(0, lambda: self._set_status(
                    f"FEC {year} exporté → {path} ({len(payload)} octets)."))
            except Exception as exc:
                logger.exception("FEC export failed")
                self.after(0, lambda: self._set_status(f"Erreur FEC : {exc}", error=True))

        self._set_status(f"Génération du FEC {year}…")
        threading.Thread(target=_run, daemon=True).start()
