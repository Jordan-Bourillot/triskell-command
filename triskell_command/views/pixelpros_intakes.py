"""Pixel Pros — pipeline des commandes client.

Contrairement à Lagriffe/RankUs/WoW, Pixel Pros n'a PAS de phase de
validation manuelle ni de preview client : le paiement Stripe valide
automatiquement la commande et le builder Python génère le site.

Statuts :
  - draft     : formulaire rempli, paiement Stripe en attente
  - paid      : paiement reçu, prêt à être construit
  - building  : builder Python en cours
  - live      : site en ligne
  - failed    : build échoué (relançable)

Pattern aligné sur `views/rankus_intakes.py`.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from tkinter import messagebox
from typing import Optional
import webbrowser

import customtkinter as ctk

from .. import theme as T
from ..integrations.pixelpros import repo as pixelpros_repo
from ..widgets.components import (
    Card, EmptyState, PrimaryButton, SecondaryButton, ViewHeader,
)
from .base import BaseView

logger = logging.getLogger(__name__)


STATUS_LABELS = {
    "draft":    "Brouillon · paiement en attente",
    "paid":     "Payé · prêt à construire",
    "building": "Build en cours…",
    "live":     "Site en ligne",
    "failed":   "Build échoué (à relancer)",
}

OPTION_LABELS = {
    "base":        "Site seul (24,90€)",
    "base_domain": "Site + domaine (33,90€)",
    "base_seo":    "Site + SEO (59,80€)",
    "base_all":    "Site + domaine + SEO (68,80€)",
    "combo":       "Pack TOUT-EN-UN (49,90€)",
}


def _fmt_dt(iso: str) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m %Hh%M")
    except ValueError:
        return iso[:16]


class PixelProsIntakesView(BaseView):
    title = "Pixel Pros — pipeline"
    subtitle = (
        "Commandes client venues de pixel-pros.fr. Le paiement Stripe les bascule "
        "automatiquement en 'paid', il ne reste plus qu'à lancer le build."
    )

    def __init__(self, master, *, app_state, colors):
        super().__init__(master, app_state=app_state, colors=colors)
        self._intakes: list[dict] = []
        self._selected_id: Optional[str] = None
        self._status_filter: str = "paid"

    def on_show(self):
        self._refresh()

    # -----------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------
    def build(self):
        ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=self.colors).pack(
            fill="x", padx=24, pady=(16, 8)
        )

        # Barre filtres
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24, pady=(0, 12))
        ctk.CTkLabel(bar, text="Filtrer :",
                     text_color=self.colors.text_muted).pack(side="left", padx=(0, 8))
        self._status_var = ctk.StringVar(value="paid")
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
        self._list_card = Card(self, title="Commandes")
        self._list_card.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        self._list_body = ctk.CTkScrollableFrame(
            self._list_card.body, fg_color="transparent"
        )
        self._list_body.pack(fill="both", expand=True)

        # Actions
        self._detail_card = Card(self, title="Actions sur la commande sélectionnée")
        self._detail_card.pack(fill="x", padx=24, pady=(0, 16))
        actions = ctk.CTkFrame(self._detail_card.body, fg_color="transparent")
        actions.pack(fill="x", padx=8, pady=8)
        PrimaryButton(actions, text="Lancer / Relancer le build",
                      command=self._dispatch_build).pack(side="left", padx=4)
        SecondaryButton(actions, text="Ouvrir le site live",
                        command=self._open_site).pack(side="left", padx=4)
        SecondaryButton(actions, text="Marquer comme failed",
                        command=self._mark_failed).pack(side="left", padx=4)
        SecondaryButton(actions, text="🗑 Supprimer",
                        command=self._delete_draft).pack(side="left", padx=4)
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
            self._intakes = pixelpros_repo.list_intakes(
                status=self._status_filter, limit=100,
            )
        except Exception as exc:
            logger.warning("pixelpros.list_intakes failed: %s", exc)
            self._intakes = []
            self._set_status(f"Erreur : {exc}", error=True)
            return
        self._set_status(
            f"{len(self._intakes)} commande(s) en "
            f"« {STATUS_LABELS.get(self._status_filter, self._status_filter)} »."
        )

        for child in self._list_body.winfo_children():
            child.destroy()

        if not self._intakes:
            EmptyState(self._list_body,
                        text="Aucune commande dans ce statut."
                        ).pack(fill="both", expand=True, pady=24)
            return

        for intake in self._intakes:
            self._render_row(intake)

    def _render_row(self, intake: dict):
        row = ctk.CTkFrame(self._list_body, fg_color=self.colors.panel,
                            corner_radius=6)
        row.pack(fill="x", padx=4, pady=4)

        # Header : business_name + email + date
        header = ctk.CTkFrame(row, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 4))

        business = intake.get("business_name") or "(nom non fourni)"
        email = intake.get("email") or "—"

        ctk.CTkLabel(
            header, text=f"{business}",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            header, text=_fmt_dt(intake.get("created_at", "")),
            text_color=self.colors.text_muted,
            font=ctk.CTkFont(size=10),
            anchor="e",
        ).pack(side="right")

        # Métadonnées
        option = intake.get("selected_option") or "base"
        option_label = OPTION_LABELS.get(option, option)
        photos_count = len(intake.get("photos") or [])
        slug = intake.get("slug") or "(slug ?)"

        meta_parts = [
            f"📧 {email}",
            f"🎁 {option_label}",
            f"📷 {photos_count} photo(s)",
            f"🔗 slug : {slug}",
        ]
        ctk.CTkLabel(row, text="  ·  ".join(meta_parts),
                     text_color=self.colors.text_muted,
                     font=ctk.CTkFont(size=10),
                     justify="left", anchor="w", wraplength=900
                     ).pack(fill="x", padx=12, pady=(0, 6))

        # Infos paiement / site
        info_parts = []
        if intake.get("stripe_session_id"):
            info_parts.append(
                f"💳 Stripe session : {intake['stripe_session_id'][:20]}…"
            )
        if intake.get("stripe_paid_at"):
            info_parts.append(f"Payé le {_fmt_dt(intake['stripe_paid_at'])}")
        if intake.get("site_url"):
            info_parts.append(f"🌐 {intake['site_url']}")
        if info_parts:
            ctk.CTkLabel(row, text="  ·  ".join(info_parts),
                         text_color=self.colors.text_muted,
                         font=ctk.CTkFont(size=10),
                         justify="left", anchor="w", wraplength=900
                         ).pack(fill="x", padx=12, pady=(0, 6))

        # Erreur si failed
        data = intake.get("data") or {}
        if intake.get("status") == "failed" and data.get("error"):
            ctk.CTkLabel(row, text=f"⚠️  Erreur : {data['error']}",
                         text_color=self.colors.danger,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         anchor="w", wraplength=900
                         ).pack(fill="x", padx=12, pady=(0, 8))
        else:
            ctk.CTkFrame(row, height=4, fg_color="transparent").pack()

        # Click pour sélectionner
        def _select(_=None, _id=intake["id"]):
            self._selected_id = _id
            self._set_status(f"Sélectionné : {business} · {email}")
        row.bind("<Button-1>", _select)
        for child in row.winfo_children():
            child.bind("<Button-1>", _select)
            for sub in child.winfo_children():
                sub.bind("<Button-1>", _select)

    # -----------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------
    def _selected(self) -> Optional[dict]:
        if not self._selected_id:
            return None
        return next((i for i in self._intakes if i["id"] == self._selected_id), None)

    def _dispatch_build(self):
        intake = self._selected()
        if intake is None:
            self._set_status("Sélectionne d'abord une commande.", error=True)
            return

        # Garde-fou : draft doit être en status 'paid' ou 'failed'
        if intake.get("status") not in ("paid", "failed"):
            self._set_status(
                f"Build impossible depuis le status '{intake.get('status')}'. "
                f"Attendu 'paid' ou 'failed'.",
                error=True,
            )
            return

        business = intake.get("business_name") or "(?)"
        email = intake.get("email") or "(?)"
        confirm = messagebox.askyesno(
            "Confirmation",
            f"Lancer le build du site pour :\n\n"
            f"  {business} · {email}\n\n"
            f"Le builder Python va tourner ~1 minute, puis le draft passera "
            f"automatiquement en 'live' ou 'failed'.",
        )
        if not confirm:
            return

        self._set_status("Lancement du build…")

        def _run():
            ok, msg = pixelpros_repo.dispatch_build(self._selected_id)
            if ok:
                self.after(0, lambda: (
                    self._set_status(f"Build lancé. {msg}"),
                    self._refresh(),
                ))
            else:
                self.after(0, lambda: self._set_status(
                    f"Échec lancement : {msg}", error=True,
                ))

        threading.Thread(target=_run, daemon=True).start()

    def _open_site(self):
        intake = self._selected()
        if intake is None:
            self._set_status("Sélectionne d'abord une commande.", error=True)
            return
        url = intake.get("site_url")
        if not url:
            self._set_status("Pas d'URL de site (build pas terminé ?).", error=True)
            return
        webbrowser.open(url)

    def _delete_draft(self):
        intake = self._selected()
        if intake is None:
            self._set_status("Sélectionne d'abord une commande.", error=True)
            return

        business = intake.get("business_name") or "(sans nom)"
        email = intake.get("email") or "(sans email)"
        status = intake.get("status") or "?"

        # On bloque la suppression d'un site déjà en ligne (sécurité),
        # sauf si Jordan force vraiment (double confirmation).
        if status == "live":
            confirm = messagebox.askyesno(
                "⚠️  Site en ligne",
                f"Cette commande est en statut 'live' (site déployé).\n\n"
                f"  {business} · {email}\n\n"
                f"Supprimer cette ligne va perdre l'historique mais ne fermera "
                f"PAS le site en ligne (à faire à la main séparément).\n\n"
                f"Continuer quand même ?",
            )
            if not confirm:
                return

        confirm = messagebox.askyesno(
            "Confirmer la suppression",
            f"Supprimer définitivement cette commande ?\n\n"
            f"  {business}\n"
            f"  {email}\n"
            f"  Statut : {status}\n\n"
            f"Cette action est irréversible.",
        )
        if not confirm:
            return

        def _run():
            ok, msg = pixelpros_repo.delete_intake(self._selected_id)
            if ok:
                self.after(0, lambda: (
                    self._set_status(f"✓ {msg}"),
                    setattr(self, '_selected_id', None),
                    self._refresh(),
                ))
            else:
                self.after(0, lambda: self._set_status(
                    f"Échec suppression : {msg}", error=True,
                ))

        self._set_status("Suppression en cours…")
        threading.Thread(target=_run, daemon=True).start()

    def _mark_failed(self):
        intake = self._selected()
        if intake is None:
            self._set_status("Sélectionne d'abord une commande.", error=True)
            return
        reason = ctk.CTkInputDialog(
            text="Motif du marquage 'failed' (optionnel) :",
            title="Marquer comme failed",
        ).get_input()
        if reason is None:
            return

        def _run():
            ok = pixelpros_repo.mark_failed(self._selected_id, error_message=reason or "")
            if ok:
                self.after(0, lambda: (
                    self._set_status("Commande marquée 'failed'."),
                    self._refresh(),
                ))
            else:
                self.after(0, lambda: self._set_status("Échec marquage.", error=True))

        self._set_status("Marquage en cours…")
        threading.Thread(target=_run, daemon=True).start()
