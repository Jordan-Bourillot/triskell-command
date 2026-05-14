"""Lagriffe Studio — vue de validation manuelle des demandes client.

Chaque demande reçue via le formulaire Lagriffe arrive en `pending_validation`.
Jordan ou Thomas regarde le brief, vérifie qu'il s'agit d'un prospect
sérieux (anti-spam + cible premium) et clique :

  • Approuver et lancer la preview → status passe à `approved`, le cron
    Netlify ramasse l'intake dans les 5 minutes et déclenche Claude
    Code (~5-7 € de tokens (1 page mockup) consommés).
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
from ..integrations.lagriffe import repo as lagriffe_repo
from ..widgets.components import (
    Card, EmptyState, PrimaryButton, SecondaryButton, ViewHeader,
)
from .base import BaseView

logger = logging.getLogger(__name__)


STATUS_LABELS = {
    "pending_validation": "À valider (avant preview)",
    "approved": "Approuvé · en attente du cron",
    "processing": "Génération preview en cours",
    "sent": "Preview envoyée · attente client",
    "paid": "Payé · à finaliser",
    "finalizing": "Finalisation en cours",
    "final_ready_review": "Site final prêt · À VALIDER avant envoi",
    "live": "Site final envoyé · live",
    "rejected": "Refusé",
    "failed": "Échec preview",
    "final_failed": "Échec finalisation",
}


def _fmt_dt(iso: str) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m %Hh%M")
    except ValueError:
        return iso[:16]


class LagriffeIntakesView(BaseView):
    title = "Lagriffe Studio — validation finale"
    subtitle = "Pipeline 100% auto. Ta seule action : valider le rendu du site final avant l'envoi du mail au client."

    def __init__(self, master, *, app_state, colors):
        super().__init__(master, app_state=app_state, colors=colors)
        self._intakes: list[dict] = []
        self._selected_id: Optional[str] = None
        # Filtre par défaut sur les sites prêts à valider (validation 3)
        self._status_filter: str = "final_ready_review"

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
        self._status_var = ctk.StringVar(value="final_ready_review")
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

        # ─── Carte "Relancer un pipeline en échec" ──────────────────────
        # À utiliser quand un intake est en status 'failed' (timeout Claude,
        # bug Puppeteer, etc.). Le brief reste intact ; on retente.
        self._retry_card = Card(self, title="Relancer un pipeline en échec")
        self._retry_card.pack(fill="x", padx=24, pady=(0, 12))
        retry_body = ctk.CTkFrame(self._retry_card.body, fg_color="transparent")
        retry_body.pack(fill="x", padx=8, pady=8)
        ctk.CTkLabel(
            retry_body,
            text="Filtre la vue sur « Échec preview » pour voir les intakes en panne.\n"
                 "Sélectionne-en un et clique « Relancer » : Claude reprendra le brief\n"
                 "tel quel et tentera à nouveau la génération.",
            anchor="w", justify="left", text_color=self.colors.text_muted,
        ).pack(fill="x", padx=4, pady=(0, 8))
        retry_btns = ctk.CTkFrame(retry_body, fg_color="transparent")
        retry_btns.pack(fill="x", padx=4)
        PrimaryButton(retry_btns, text="Relancer le pipeline",
                      command=self._retry_pipeline).pack(side="left", padx=4)

        # ─── Carte "Feedback client reçu par mail" ──────────────────────
        # À utiliser quand l'intake est en status 'sent' (preview envoyée,
        # en attente du retour mail) ou 'paid' (payé mais pas encore de
        # feedback). Sans feedback, la fabrication finale ne démarre PAS.
        self._feedback_card = Card(self, title="Feedback client reçu (par mail)")
        self._feedback_card.pack(fill="x", padx=24, pady=(0, 12))
        fb_body = ctk.CTkFrame(self._feedback_card.body, fg_color="transparent")
        fb_body.pack(fill="x", padx=8, pady=8)
        ctk.CTkLabel(
            fb_body,
            text="Le client a répondu au mail mockup (même un simple « OK ») ?\n"
                 "Marque-le ici. Si le paiement est déjà reçu, la fabrication finale\n"
                 "se déclenchera immédiatement. Sinon, on attendra Stripe.",
            anchor="w", justify="left", text_color=self.colors.text_muted,
        ).pack(fill="x", padx=4, pady=(0, 8))
        ctk.CTkLabel(fb_body, text="Texte du feedback (optionnel) :",
                     anchor="w", text_color=self.colors.text_muted,
                     font=ctk.CTkFont(size=10)).pack(fill="x", padx=4)
        self._fb_text = ctk.CTkTextbox(fb_body, height=60)
        self._fb_text.pack(fill="x", padx=4, pady=(2, 8))
        fb_btns = ctk.CTkFrame(fb_body, fg_color="transparent")
        fb_btns.pack(fill="x", padx=4)
        PrimaryButton(fb_btns, text="Marquer feedback reçu",
                      command=self._mark_feedback_received).pack(side="left", padx=4)

        # Validation 3 (et unique pour Lagriffe) : avant envoi du mail final au client
        self._review_card = Card(self, title="Validation finale — avant envoi au client")
        self._review_card.pack(fill="x", padx=24, pady=(0, 16))
        review_body = ctk.CTkFrame(self._review_card.body, fg_color="transparent")
        review_body.pack(fill="x", padx=8, pady=8)
        ctk.CTkLabel(
            review_body,
            text="Pipeline Lagriffe 100% auto. Ta seule action :\n"
                 "1. Ouvre l'URL du site final pour vérifier le rendu Claude.\n"
                 "2. Si OK → clique « Approuver et envoyer ». Le client reçoit le mail final.",
            anchor="w", justify="left", text_color=self.colors.text_muted,
        ).pack(fill="x", padx=4, pady=(0, 12))
        review_btns = ctk.CTkFrame(review_body, fg_color="transparent")
        review_btns.pack(fill="x", padx=4, pady=(0, 4))
        PrimaryButton(review_btns, text="Approuver et envoyer le mail final au client",
                      command=self._approve_final_and_send).pack(side="left", padx=4)
        SecondaryButton(review_btns, text="Ouvrir le site final",
                        command=self._open_final_site).pack(side="left", padx=4)
        self._status_lbl = ctk.CTkLabel(review_body, text="",
                                         text_color=self.colors.text_muted)
        self._status_lbl.pack(fill="x", padx=4, pady=(8, 0))

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
            self._intakes = lagriffe_repo.list_intakes(status=self._status_filter, limit=100)
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
            f"Coût estimé : ~5-7 € HT en tokens Claude Opus (1 page mockup).\n"
            f"Cette action n'est pas réversible.",
        )
        if not confirm:
            return

        self._set_status("Approbation et déclenchement en cours…")

        def _run():
            ok_approve = lagriffe_repo.approve_intake(self._selected_id)
            if not ok_approve:
                self.after(0, lambda: self._set_status("Échec MAJ status.", error=True))
                return
            ok_dispatch, msg = lagriffe_repo.dispatch_now(self._selected_id)
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
            ok = lagriffe_repo.reject_intake(self._selected_id, reason or "")
            if ok:
                self.after(0, lambda: (
                    self._set_status("Demande refusée."),
                    self._refresh(),
                ))
            else:
                self.after(0, lambda: self._set_status("Échec refus.", error=True))

        self._set_status("Refus en cours…")
        threading.Thread(target=_run, daemon=True).start()

    # -----------------------------------------------------------------
    # Bloc 4 : finalisation
    # -----------------------------------------------------------------
    def _save_feedback_only(self):
        """Enregistre feedback + assets sans déclencher la finalisation."""
        if not self._selected_id:
            self._set_status("Sélectionne d'abord une demande.", error=True)
            return
        feedback = self._feedback_txt.get("1.0", "end").strip()
        assets = self._assets_var.get().strip()
        if not feedback and not assets:
            self._set_status("Rien à enregistrer (feedback et URL vides).", error=True)
            return

        def _run():
            ok = lagriffe_repo.save_client_feedback(
                self._selected_id, feedback=feedback, assets_url=assets,
            )
            if ok:
                self.after(0, lambda: self._set_status("Retours enregistrés."))
            else:
                self.after(0, lambda: self._set_status("Échec enregistrement.", error=True))

        self._set_status("Enregistrement…")
        threading.Thread(target=_run, daemon=True).start()

    def _launch_finalization(self):
        """Lance le workflow de finalisation (TOUTES pages + retours + visuels)."""
        if not self._selected_id:
            self._set_status("Sélectionne d'abord une demande.", error=True)
            return
        intake = next((i for i in self._intakes if i["id"] == self._selected_id), None)
        if intake is None:
            self._set_status("Demande introuvable.", error=True)
            return

        # Garde-fou : intake doit être en status 'paid'
        if intake.get("status") not in ("paid", "final_failed"):
            self._set_status(
                f"Impossible : intake en status '{intake.get('status')}'. "
                f"Attendu 'paid' (paiement Stripe reçu).",
                error=True,
            )
            return

        feedback = self._feedback_txt.get("1.0", "end").strip()
        assets = self._assets_var.get().strip()

        # Confirmation explicite
        full_name = f"{intake.get('client_first_name', '')} {intake.get('client_last_name', '')}".strip()
        confirm = messagebox.askyesno(
            "Confirmation finalisation",
            f"Lancer la fabrication finale pour :\n\n"
            f"  {full_name} · {intake.get('company_name', '')}\n\n"
            f"Coût estimé : ~5-7 € HT en tokens Claude Opus (1 page mockup).\n"
            f"Cette action va CODER TOUTES LES PAGES et envoyer le site final\n"
            f"au client par mail à la fin.\n\n"
            f"Retours client : {len(feedback)} caractères\n"
            f"URL visuels : {'oui' if assets else 'non'}",
        )
        if not confirm:
            return

        self._set_status("Enregistrement feedback + lancement finalisation…")

        def _run():
            # 1. Enregistre feedback + assets (même vides)
            lagriffe_repo.save_client_feedback(
                self._selected_id, feedback=feedback, assets_url=assets,
            )
            # 2. Lance le workflow finalisation
            ok, msg = lagriffe_repo.launch_finalization(self._selected_id)
            if ok:
                self.after(0, lambda: (
                    self._set_status(f"Finalisation lancée. {msg}"),
                    self._refresh(),
                ))
            else:
                self.after(0, lambda: self._set_status(
                    f"Échec lancement : {msg}", error=True,
                ))

        threading.Thread(target=_run, daemon=True).start()

    # -----------------------------------------------------------------
    # Relance pipeline en échec
    # -----------------------------------------------------------------
    def _retry_pipeline(self):
        if not self._selected_id:
            self._set_status("Sélectionne d'abord une demande.", error=True)
            return
        intake = next((i for i in self._intakes if i["id"] == self._selected_id), None)
        if intake is None:
            self._set_status("Demande introuvable.", error=True)
            return

        if intake.get("status") not in ("failed", "final_failed"):
            self._set_status(
                f"Status '{intake.get('status')}' — la relance se fait sur 'failed'.",
                error=True,
            )
            return

        full_name = f"{intake.get('client_first_name', '')} {intake.get('client_last_name', '')}".strip()
        confirm = messagebox.askyesno(
            "Relance pipeline",
            f"Relancer la génération de la maquette pour :\n\n"
            f"  {full_name} · {intake.get('company_name') or '(particulier)'}\n\n"
            f"Erreur précédente :\n  {(intake.get('error_message') or '—')[:200]}\n\n"
            f"Le brief reste intact, Claude retente. Coût : ~5-7 € de tokens.",
        )
        if not confirm:
            return

        self._set_status("Reset status + dispatch en cours…")

        def _run():
            # 1. Reset status à 'approved' pour que process-intakes le ramasse
            ok_reset = lagriffe_repo.update_intake_status(self._selected_id, "approved")
            if not ok_reset:
                self.after(0, lambda: self._set_status("Échec reset status.", error=True))
                return
            # 2. Dispatch immédiat (sans attendre le cron 5 min)
            ok, msg = lagriffe_repo.dispatch_now(self._selected_id)
            if ok:
                self.after(0, lambda: (
                    self._set_status(f"Pipeline relancé. {msg}"),
                    self._refresh(),
                ))
            else:
                self.after(0, lambda: self._set_status(
                    f"Reset OK mais dispatch échoué ({msg}). Le cron reprendra dans 5 min.",
                ))

        threading.Thread(target=_run, daemon=True).start()

    # -----------------------------------------------------------------
    # Feedback client reçu par mail
    # -----------------------------------------------------------------
    def _mark_feedback_received(self):
        if not self._selected_id:
            self._set_status("Sélectionne d'abord une demande.", error=True)
            return
        intake = next((i for i in self._intakes if i["id"] == self._selected_id), None)
        if intake is None:
            self._set_status("Demande introuvable.", error=True)
            return

        if intake.get("status") not in ("sent", "paid"):
            self._set_status(
                f"Status '{intake.get('status')}' — le feedback se marque sur 'sent' ou 'paid'.",
                error=True,
            )
            return

        feedback = self._fb_text.get("1.0", "end").strip() or "OK reçu manuellement via Triskell Command"

        full_name = f"{intake.get('client_first_name', '')} {intake.get('client_last_name', '')}".strip()
        confirm = messagebox.askyesno(
            "Feedback client",
            f"Marquer le feedback client reçu pour :\n\n"
            f"  {full_name} · {intake.get('company_name') or '(particulier)'}\n\n"
            f"Statut actuel : {STATUS_LABELS.get(intake.get('status'), intake.get('status'))}\n"
            f"Si paiement déjà reçu → fabrication finale lancée tout de suite.\n"
            f"Sinon → en attente du paiement Stripe.\n\n"
            f"Feedback : {feedback[:100]}{'…' if len(feedback) > 100 else ''}",
        )
        if not confirm:
            return

        self._set_status("Enregistrement feedback…")

        def _run():
            ok, msg = lagriffe_repo.mark_feedback_received(
                self._selected_id, feedback_text=feedback,
            )
            if ok:
                self.after(0, lambda: (
                    self._set_status(msg),
                    self._fb_text.delete("1.0", "end"),
                    self._refresh(),
                ))
            else:
                self.after(0, lambda: self._set_status(
                    f"Échec : {msg}", error=True,
                ))

        threading.Thread(target=_run, daemon=True).start()

    # -----------------------------------------------------------------
    # Validation finale (avant envoi du mail au client)
    # -----------------------------------------------------------------
    def _open_final_site(self):
        if not self._selected_id:
            self._set_status("Sélectionne d'abord une demande.", error=True)
            return
        intake = next((i for i in self._intakes if i["id"] == self._selected_id), None)
        if intake is None:
            self._set_status("Demande introuvable.", error=True)
            return
        url = intake.get("final_site_url") or intake.get("mockup_url")
        if not url:
            self._set_status("Pas d'URL de site sur cet intake.", error=True)
            return
        import webbrowser
        webbrowser.open(url)
        self._set_status(f"Ouverture : {url}")

    def _approve_final_and_send(self):
        """Validation finale : envoie le mail final au client + bascule live."""
        if not self._selected_id:
            self._set_status("Sélectionne d'abord une demande.", error=True)
            return
        intake = next((i for i in self._intakes if i["id"] == self._selected_id), None)
        if intake is None:
            self._set_status("Demande introuvable.", error=True)
            return

        if intake.get("status") != "final_ready_review":
            self._set_status(
                f"Impossible : status '{intake.get('status')}'. "
                f"Attendu 'final_ready_review'.",
                error=True,
            )
            return

        full_name = f"{intake.get('client_first_name', '')} {intake.get('client_last_name', '')}".strip()
        confirm = messagebox.askyesno(
            "Validation finale",
            f"Envoyer le mail final au client :\n\n"
            f"  {full_name} <{intake.get('client_email', '')}>\n"
            f"  Site : {intake.get('final_site_url', '')}\n\n"
            f"Le client recevra un mail avec l'URL du site, la politique\n"
            f"satisfaction/remboursement, et l'info facture mensuelle.\n\n"
            f"Continuer ?",
        )
        if not confirm:
            return

        self._set_status("Envoi du mail final…")

        def _run():
            ok, msg = lagriffe_repo.approve_final_and_send(self._selected_id)
            if ok:
                self.after(0, lambda: (
                    self._set_status(msg),
                    self._refresh(),
                ))
            else:
                self.after(0, lambda: self._set_status(
                    f"Échec : {msg}", error=True,
                ))

        threading.Thread(target=_run, daemon=True).start()
