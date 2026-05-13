"""Studio WoW — vue de validation manuelle des demandes client.

Chaque demande reçue via le formulaire WoW arrive en `pending_validation`.
Jordan ou Thomas regarde le brief, vérifie qu'il s'agit d'un prospect
sérieux (anti-spam + cible premium) et clique :

  • Approuver et lancer la preview → status passe à `approved`, le cron
    Netlify ramasse l'intake dans les 5 minutes et déclenche Claude
    Code (~15 € de tokens consommés).
  • Refuser → status passe à `rejected`. Aucune génération.

L'objectif est d'éviter de cramer 15 €/intake sur des soumissions
spam ou hors-cible.

Pattern aligné sur `views/billing.py`.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk

from .. import theme as T
from ..integrations.wow import repo as wow_repo
from ..widgets.components import (
    Card, EmptyState, PrimaryButton, SecondaryButton, ViewHeader,
)
from .base import BaseView

logger = logging.getLogger(__name__)


STATUS_LABELS = {
    "pending_validation": "À valider",
    "approved": "Approuvé · en attente du cron",
    "processing": "Génération en cours",
    "sent": "Preview envoyée",
    "rejected": "Refusé",
    "failed": "Échec",
}


def _fmt_dt(iso: str) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m %Hh%M")
    except ValueError:
        return iso[:16]


class WowIntakesView(BaseView):
    title = "Studio WoW — validations"
    subtitle = (
        "Chaque demande client WoW doit être approuvée manuellement avant "
        "génération de la preview (coût ~15 €/run Claude Opus). Anti-spam et "
        "tri premium."
    )

    def __init__(self, master, *, app_state, colors):
        super().__init__(master, app_state=app_state, colors=colors)
        self._intakes: list[dict] = []
        self._selected_id: Optional[str] = None
        self._status_filter: str = "pending_validation"

    def on_show(self):
        self._refresh()

    # -----------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------
    def build(self):
        ViewHeader(self, title=self.title, subtitle=self.subtitle).pack(
            fill="x", padx=24, pady=(16, 8)
        )

        # Barre filtres
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24, pady=(0, 12))
        ctk.CTkLabel(bar, text="Filtrer :",
                     text_color=self.colors.text_muted).pack(side="left", padx=(0, 8))
        self._status_var = ctk.StringVar(value="pending_validation")
        self._status_menu = ctk.CTkOptionMenu(
            bar,
            variable=self._status_var,
            values=list(STATUS_LABELS.keys()),
            command=self._on_filter_change,
            width=200,
        )
        self._status_menu.pack(side="left")
        SecondaryButton(bar, text="Rafraîchir",
                        command=self._refresh).pack(side="right")

        # Liste
        self._list_card = Card(self, title="Demandes")
        self._list_card.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        self._list_body = ctk.CTkScrollableFrame(
            self._list_card.body, fg_color="transparent"
        )
        self._list_body.pack(fill="both", expand=True)

        # Actions
        self._detail_card = Card(self, title="Action sur la demande sélectionnée")
        self._detail_card.pack(fill="x", padx=24, pady=(0, 16))
        actions = ctk.CTkFrame(self._detail_card.body, fg_color="transparent")
        actions.pack(fill="x", padx=8, pady=8)
        PrimaryButton(actions, text="Approuver et lancer la preview",
                      command=self._approve_and_dispatch).pack(side="left", padx=4)
        SecondaryButton(actions, text="Refuser",
                        command=self._reject).pack(side="left", padx=4)
        self._status_lbl = ctk.CTkLabel(actions, text="",
                                         text_color=self.colors.text_muted)
        self._status_lbl.pack(side="left", padx=12)

    def _set_status(self, msg: str, *, error: bool = False):
        self._status_lbl.configure(
            text=msg,
            text_color=self.colors.danger if error else self.colors.text_muted,
        )

    def _on_filter_change(self, choice: str):
        self._status_filter = choice
        self._refresh()

    # -----------------------------------------------------------------
    # Data
    # -----------------------------------------------------------------
    def _refresh(self):
        try:
            self._intakes = wow_repo.list_intakes(status=self._status_filter, limit=100)
        except Exception as exc:
            logger.warning("wow.list_intakes failed: %s", exc)
            self._intakes = []
            self._set_status(f"Erreur : {exc}", error=True)
            return
        self._set_status(f"{len(self._intakes)} demande(s) en « {STATUS_LABELS.get(self._status_filter, self._status_filter)} ».")

        for child in self._list_body.winfo_children():
            child.destroy()

        if not self._intakes:
            EmptyState(self._list_body,
                        text="Aucune demande dans ce statut."
                        ).pack(fill="both", expand=True, pady=24)
            return

        for intake in self._intakes:
            self._render_row(intake)

    def _render_row(self, intake: dict):
        row = ctk.CTkFrame(self._list_body, fg_color=self.colors.panel,
                            corner_radius=6)
        row.pack(fill="x", padx=4, pady=4)

        # Header de la card : nom + société + date
        header = ctk.CTkFrame(row, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 4))

        name = intake.get("client_first_name") or intake.get("client_last_name") or "(anonyme)"
        first = intake.get("client_first_name") or ""
        last = intake.get("client_last_name") or ""
        full_name = f"{first} {last}".strip() or "(nom non fourni)"
        company = intake.get("company_name") or "(société non fournie)"
        email = intake.get("client_email") or "—"

        ctk.CTkLabel(
            header, text=f"{full_name}  ·  {company}",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            header, text=_fmt_dt(intake.get("created_at", "")),
            text_color=self.colors.text_muted,
            font=ctk.CTkFont(size=10),
            anchor="e",
        ).pack(side="right")

        # Métadonnées qualifying
        payload = intake.get("payload") or {}
        meta_parts = [
            f"📧 {email}",
        ]
        if payload.get("fonction"):
            meta_parts.append(f"Fonction : {payload['fonction']}")
        if payload.get("budget"):
            meta_parts.append(f"Budget : {payload['budget']}")
        if payload.get("echeance"):
            meta_parts.append(f"Échéance : {payload['echeance']}")
        if payload.get("nature_client"):
            meta_parts.append(f"Nature : {payload['nature_client']}")
        if payload.get("type_site"):
            meta_parts.append(f"Site : {payload['type_site']}")
        if payload.get("ambiance"):
            meta_parts.append(f"Ambiance : {payload['ambiance']}")

        meta = ctk.CTkLabel(row, text="  ·  ".join(meta_parts),
                             text_color=self.colors.text_muted,
                             font=ctk.CTkFont(size=10),
                             justify="left", anchor="w", wraplength=900)
        meta.pack(fill="x", padx=12, pady=(0, 6))

        # Domaine demandé
        domain = (payload.get("domain") or {})
        if domain.get("option") == "deja" and domain.get("existing"):
            domain_str = f"🌐 Domaine existant : {domain['existing']}"
        elif domain.get("option") == "reserver" and domain.get("propositions"):
            domain_str = f"🌐 À réserver : {', '.join(domain['propositions'])}"
        else:
            domain_str = "🌐 Domaine : non précisé"
        ctk.CTkLabel(row, text=domain_str,
                     text_color=self.colors.text_muted,
                     font=ctk.CTkFont(size=10),
                     justify="left", anchor="w").pack(fill="x", padx=12, pady=(0, 6))

        # Brief
        brief = intake.get("description") or "(pas de brief)"
        ctk.CTkLabel(row, text=brief,
                     font=ctk.CTkFont(size=11),
                     justify="left", anchor="w", wraplength=900
                     ).pack(fill="x", padx=12, pady=(0, 6))

        # NDA si demandé
        if payload.get("nda_souhaite"):
            ctk.CTkLabel(row, text="⚠️  NDA demandé avant premier échange",
                         text_color=self.colors.warning,
                         font=ctk.CTkFont(size=10, weight="bold"),
                         anchor="w").pack(fill="x", padx=12, pady=(0, 8))
        else:
            ctk.CTkFrame(row, height=4, fg_color="transparent").pack()

        # Click pour sélectionner
        def _select(_=None, _id=intake["id"]):
            self._selected_id = _id
            self._set_status(f"Sélectionné : {full_name} · {company}")
        row.bind("<Button-1>", _select)
        for child in row.winfo_children():
            child.bind("<Button-1>", _select)
            for sub in child.winfo_children():
                sub.bind("<Button-1>", _select)

    # -----------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------
    def _approve_and_dispatch(self):
        if not self._selected_id:
            self._set_status("Sélectionne d'abord une demande.", error=True)
            return
        intake = next((i for i in self._intakes if i["id"] == self._selected_id), None)
        if intake is None:
            self._set_status("Demande introuvable.", error=True)
            return

        # Confirmation explicite (coût ~15€)
        full_name = f"{intake.get('client_first_name', '')} {intake.get('client_last_name', '')}".strip()
        confirm = messagebox.askyesno(
            "Confirmation",
            f"Approuver et lancer la preview Claude Code pour :\n\n"
            f"  {full_name} · {intake.get('company_name', '')}\n\n"
            f"Coût estimé : ~15 € HT en tokens Claude Opus.\n"
            f"Cette action n'est pas réversible.",
        )
        if not confirm:
            return

        self._set_status("Approbation et déclenchement en cours…")

        def _run():
            ok_approve = wow_repo.approve_intake(self._selected_id)
            if not ok_approve:
                self.after(0, lambda: self._set_status("Échec MAJ status.", error=True))
                return
            ok_dispatch, msg = wow_repo.dispatch_now(self._selected_id)
            if ok_dispatch:
                self.after(0, lambda: (
                    self._set_status(f"Preview déclenchée. {msg}"),
                    self._refresh(),
                ))
            else:
                self.after(0, lambda: self._set_status(
                    f"Approuvé mais dispatch immédiat échoué ({msg}). "
                    f"Le cron Netlify reprendra dans 5 min.",
                    error=False))

        threading.Thread(target=_run, daemon=True).start()

    def _reject(self):
        if not self._selected_id:
            self._set_status("Sélectionne d'abord une demande.", error=True)
            return
        reason = ctk.CTkInputDialog(
            text="Motif du refus (visible dans la base, optionnel) :",
            title="Refuser la demande",
        ).get_input()
        if reason is None:
            return

        def _run():
            ok = wow_repo.reject_intake(self._selected_id, reason or "")
            if ok:
                self.after(0, lambda: (
                    self._set_status("Demande refusée."),
                    self._refresh(),
                ))
            else:
                self.after(0, lambda: self._set_status("Échec refus.", error=True))

        self._set_status("Refus en cours…")
        threading.Thread(target=_run, daemon=True).start()
