"""La Forge du Web — vue intégrée à Triskell Command.

Tant que l'app autonome (Tauri 2 + React + Rust) n'est pas codée, la vue
sert de cockpit minimal :
  · Onglet « Briefs reçus » → demandes de site captées par Teddy via le
    formulaire RankUs (cf. teddy_to_forge.py)
  · Onglet « Projets »      → projets en cours, statut workflow 14 étapes
  · Onglet « Workflow »     → carte des 14 étapes prévues
  · Onglet « À propos »     → état d'avancement de la spec + écosystème

Quand l'app autonome existera, le bouton « Ouvrir l'app autonome » lancera
le binaire Tauri.
"""

from __future__ import annotations

import logging
import threading

import customtkinter as ctk
from tkinter import messagebox

from .. import theme as T
from ..integrations.forge import repo as forge_repo
from ..widgets.components import (
    Card,
    EmptyState,
    PrimaryButton,
    SecondaryButton,
    ViewHeader,
)
from ..widgets.components_pro import HeroQuestion, KpiHero
from .base import BaseView

logger = logging.getLogger(__name__)


# Les 14 étapes du workflow La Forge (cf. docs/spec-v0.2.md §3).
WORKFLOW_STEPS: list[tuple[int, str, str]] = [
    (1,  "Brief",         "Sujet, audience, ton et objectifs du site."),
    (2,  "Identité",      "Nom, logo, palette (tokens v2), typo, dark mode."),
    (3,  "Structure",     "Sitemap, pages et navigation."),
    (4,  "Contenu",       "Textes générés ou importés (.md, .docx)."),
    (5,  "Médias",        "Photos, vidéos, IA, compression, alt-text, lazy."),
    (6,  "Responsive",    "Mobile-first / desktop-first, cohérent partout."),
    (7,  "Multilingue",   "Langues, hreflang (optionnel)."),
    (8,  "Technique",     "Stack, base de données, auth, formulaires."),
    (9,  "SEO",           "Métadonnées, sitemap, hook automatique Le Phare."),
    (10, "Écosystème",    "Registre central, liens entre sites, analytics."),
    (11, "Légal",         "Mentions, confidentialité, cookies, RGPD."),
    (12, "Build & preview", "Aperçu local du site avant publication."),
    (13, "Déploiement",   "Domaine, hébergeur, CI, repo Git."),
    (14, "Post-launch",   "Monitoring + alimentation continue Le Phare."),
]


TABS = [
    ("briefs",   "Briefs reçus"),
    ("projects", "Projets"),
    ("workflow", "Workflow"),
    ("about",    "À propos"),
]


def _fmt_dt(iso: str) -> str:
    """Formate une date ISO en court FR (ou — si vide / invalide)."""
    if not iso:
        return "—"
    try:
        from datetime import datetime
        return datetime.fromisoformat(
            iso.replace("Z", "+00:00")
        ).strftime("%d/%m %Hh%M")
    except (ValueError, TypeError):
        return iso[:16]


class LaForgeView(BaseView):
    title = "La Forge du Web"
    subtitle = (
        "Ton atelier de création de sites web, piloté par IA. "
        "Tu décris le site, La Forge du Web l'exécute — du brief au "
        "déploiement."
    )

    def __init__(self, master, *, app_state, colors):
        super().__init__(master, app_state=app_state, colors=colors)
        self._active_tab = "briefs"
        self._tab_frames: dict[str, ctk.CTkFrame] = {}
        self._tab_buttons: dict[str, ctk.CTkButton] = {}

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------
    def build(self) -> None:
        c = self.colors

        # Header
        header = ViewHeader(self, title=self.title, subtitle=self.subtitle,
                            colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_MD))

        SecondaryButton(
            header.actions, colors=c, icon="refresh",
            text="Rafraîchir",
            command=self._refresh_all,
        ).pack(side="left", padx=(0, T.SPACE_SM))
        SecondaryButton(
            header.actions, colors=c, icon="external",
            text="Voir la spec",
            command=self._open_spec,
        ).pack(side="left", padx=(0, T.SPACE_SM))
        self._launch_btn = PrimaryButton(
            header.actions, colors=c, icon="play",
            text="Ouvrir l'app autonome",
            command=self._launch_app,
        )
        self._launch_btn.pack(side="left")

        # Onglets
        tabs_bar = ctk.CTkFrame(self, fg_color="transparent")
        tabs_bar.pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))
        for tab_id, label in TABS:
            btn = ctk.CTkButton(
                tabs_bar, text=label, width=140, height=32,
                corner_radius=T.RADIUS_SM,
                fg_color=c.panel, text_color=c.text_secondary,
                hover_color=c.panel_hover,
                border_color=c.border, border_width=1,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
                command=lambda t=tab_id: self._switch_tab(t),
            )
            btn.pack(side="left", padx=(0, T.SPACE_SM))
            self._tab_buttons[tab_id] = btn

        # Conteneur d'onglet
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True,
                           padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

        for tab_id, _ in TABS:
            f = ctk.CTkFrame(self._content, fg_color="transparent")
            self._tab_frames[tab_id] = f

        # Status bar
        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

        self._switch_tab("briefs")

    def on_show(self) -> None:
        self._refresh_all()

    # ------------------------------------------------------------------
    # Onglets
    # ------------------------------------------------------------------
    def _switch_tab(self, tab_id: str) -> None:
        c = self.colors
        self._active_tab = tab_id
        for tid, btn in self._tab_buttons.items():
            if tid == tab_id:
                btn.configure(fg_color=c.accent,
                              text_color=c.accent_text or "#fff",
                              border_color=c.accent)
            else:
                btn.configure(fg_color=c.panel,
                              text_color=c.text_secondary,
                              border_color=c.border)
        for tid, f in self._tab_frames.items():
            f.pack_forget()
        self._tab_frames[tab_id].pack(fill="both", expand=True)
        self._refresh_active_tab()

    def _refresh_all(self) -> None:
        self._refresh_active_tab()

    def _refresh_active_tab(self) -> None:
        f = self._tab_frames[self._active_tab]
        for w in f.winfo_children():
            w.destroy()
        if self._active_tab == "briefs":
            self._build_briefs(f)
        elif self._active_tab == "projects":
            self._build_projects(f)
        elif self._active_tab == "workflow":
            self._build_workflow(f)
        elif self._active_tab == "about":
            self._build_about(f)

    # ------------------------------------------------------------------
    # ONGLET — Briefs reçus
    # ------------------------------------------------------------------
    def _build_briefs(self, parent: ctk.CTkFrame) -> None:
        c = self.colors
        HeroQuestion(
            parent, colors=c,
            text="Quelles demandes de création de site sont arrivées ?",
        ).pack(fill="x", pady=(T.SPACE_LG, T.SPACE_MD))

        # Bandeau d'actions : check now + KPIs
        actions_bar = ctk.CTkFrame(parent, fg_color="transparent")
        actions_bar.pack(fill="x", pady=(0, T.SPACE_MD))
        SecondaryButton(
            actions_bar, colors=c, icon="refresh",
            text="Vérifier la boîte mail maintenant",
            command=self._poll_intake_now,
        ).pack(side="left")

        # KPIs
        new_count = forge_repo.count_briefs(status="new")
        imported_count = forge_repo.count_briefs(status="imported")
        rejected_count = forge_repo.count_briefs(status="rejected")

        kpis = ctk.CTkFrame(parent, fg_color="transparent")
        kpis.pack(fill="x", pady=(0, T.SPACE_MD))
        for i in range(3):
            kpis.grid_columnconfigure(i, weight=1, uniform="forge_brief_kpi")
        KpiHero(
            kpis, colors=c, label="Nouveaux briefs",
            value=str(new_count),
            accent=c.accent if new_count else "",
        ).grid(row=0, column=0, sticky="nsew", padx=(0, T.SPACE_MD))
        KpiHero(
            kpis, colors=c, label="Importés en projet",
            value=str(imported_count),
        ).grid(row=0, column=1, sticky="nsew", padx=(0, T.SPACE_MD))
        KpiHero(
            kpis, colors=c, label="Rejetés",
            value=str(rejected_count),
        ).grid(row=0, column=2, sticky="nsew")

        briefs = forge_repo.list_briefs(limit=30)
        if not briefs:
            EmptyState(
                parent, colors=c, icon="mail",
                title="Aucun brief reçu pour l'instant",
                message=(
                    "Quand un mail arrive sur la boîte partagée avec le "
                    "sujet « Demande de création de site », Teddy le "
                    "détecte et le dépose ici. Pour tester, remplis le "
                    "formulaire sur rankus.triskell-studio.fr/demande-site."
                ),
                cta_text="Ouvrir le formulaire de test",
                cta_command=lambda: self._open_url(
                    "https://rankus.triskell-studio.fr/demande-site"),
            ).pack(fill="both", expand=True, pady=T.SPACE_2XL)
            self._status_var.set("La Forge attend son premier brief.")
            return

        # Table des briefs
        table = Card(parent, colors=c)
        table.pack(fill="both", expand=True)
        head = ctk.CTkFrame(table, fg_color="transparent")
        head.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))
        for label, w in (("CLIENT", 200), ("EMAIL", 220),
                         ("REÇU LE", 110), ("STATUT", 90),
                         ("ACTIONS", 200)):
            ctk.CTkLabel(
                head, text=label, width=w,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                text_color=c.text_muted, anchor="w",
            ).pack(side="left", padx=(0, T.SPACE_SM))

        rows = ctk.CTkScrollableFrame(
            table, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        rows.pack(fill="both", expand=True,
                  padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        for b in briefs:
            self._render_brief_row(rows, b)

        self._status_var.set(
            f"{len(briefs)} brief{'s' if len(briefs) > 1 else ''} affichés "
            f"· {new_count} en attente d'import"
        )

    def _render_brief_row(self, parent, b: dict) -> None:
        c = self.colors
        row = ctk.CTkFrame(parent, fg_color="transparent", height=44)
        row.pack(fill="x", pady=2)
        row.pack_propagate(False)

        full_name = f"{b.get('first_name', '')} {b.get('last_name', '')}".strip() \
                    or "(sans nom)"
        ctk.CTkLabel(
            row, text=full_name, width=200,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(side="left", padx=(0, T.SPACE_SM))
        ctk.CTkLabel(
            row, text=b.get("email") or "—", width=220,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w",
        ).pack(side="left", padx=(0, T.SPACE_SM))
        ctk.CTkLabel(
            row, text=_fmt_dt(b.get("received_at") or ""), width=110,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
            text_color=c.text_muted, anchor="w",
        ).pack(side="left", padx=(0, T.SPACE_SM))

        status = b.get("status") or "new"
        status_color = (c.accent if status == "new"
                        else c.success if status == "imported"
                        else c.text_muted)
        ctk.CTkLabel(
            row, text=status, width=90,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=status_color, anchor="w",
        ).pack(side="left", padx=(0, T.SPACE_SM))

        actions_cell = ctk.CTkFrame(row, fg_color="transparent", width=200)
        actions_cell.pack(side="left")
        actions_cell.pack_propagate(False)
        SecondaryButton(
            actions_cell, colors=c, text="Détails", icon="external",
            width=90,
            command=lambda bid=b["id"]: self._open_brief_dialog(bid),
        ).pack(side="left", padx=(0, T.SPACE_XS))
        if status == "new":
            PrimaryButton(
                actions_cell, colors=c, text="Importer", icon="check",
                width=95,
                command=lambda brief=b: self._import_brief(brief),
            ).pack(side="left")
        elif status == "imported" and b.get("project_id"):
            SecondaryButton(
                actions_cell, colors=c, text="Voir projet", icon="external",
                width=95,
                command=lambda: self._switch_tab("projects"),
            ).pack(side="left")

    def _open_brief_dialog(self, brief_id: str) -> None:
        b = forge_repo.get_brief(brief_id)
        if not b:
            messagebox.showerror("Erreur", "Brief introuvable.")
            return
        c = self.colors
        win = ctk.CTkToplevel(self.winfo_toplevel())
        win.title(f"Brief — {b.get('first_name','')} {b.get('last_name','')}")
        win.geometry("640x640")
        win.configure(fg_color=c.bg)

        scroll = ctk.CTkScrollableFrame(win, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=T.SPACE_LG, pady=T.SPACE_LG)

        def _line(label: str, value: str) -> None:
            ctk.CTkLabel(scroll, text=label.upper(),
                         font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                         text_color=c.text_muted, anchor="w").pack(
                fill="x", pady=(T.SPACE_SM, 2))
            ctk.CTkLabel(scroll, text=value or "—",
                         font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                         text_color=c.text_primary, anchor="w",
                         justify="left", wraplength=580).pack(fill="x")

        _line("Prénom", b.get("first_name", ""))
        _line("Nom", b.get("last_name", ""))
        _line("Email", b.get("email", ""))
        _line("Téléphone", b.get("phone", ""))
        _line("Adresse", b.get("address", ""))
        _line("Description du site", b.get("description", ""))
        _line("Audience", b.get("audience", ""))
        _line("Ton", b.get("tone", ""))
        _line("Reçu le", _fmt_dt(b.get("received_at", "")))
        _line("Sujet du mail", b.get("raw_email_subject", ""))
        _line("Statut", b.get("status", ""))

        bar = ctk.CTkFrame(win, fg_color="transparent")
        bar.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        if b.get("status") == "new":
            PrimaryButton(
                bar, colors=c, text="Importer en projet", icon="check",
                command=lambda: (self._import_brief(b), win.destroy()),
            ).pack(side="left", padx=(0, T.SPACE_SM))
            SecondaryButton(
                bar, colors=c, text="Marquer comme spam", icon="trash",
                command=lambda: (self._reject_brief(b), win.destroy()),
            ).pack(side="left")
        else:
            SecondaryButton(
                bar, colors=c, text="Fermer", icon="close",
                command=win.destroy,
            ).pack(side="left")

    def _import_brief(self, brief: dict) -> None:
        """Crée le projet associé en mode auto (14 étapes enchaînées)."""
        project = forge_repo.create_project_from_brief(brief, auto_run=True)
        if not project:
            messagebox.showerror(
                "Erreur",
                "Impossible de créer le projet. Vérifie la connexion "
                "Supabase et la migration 09_forge.sql.",
            )
            return
        self._status_var.set(
            f"✓ Projet créé pour {brief.get('first_name','')} "
            f"{brief.get('last_name','')} — en attente de l'exécuteur 14 étapes."
        )
        self._refresh_active_tab()

    def _reject_brief(self, brief: dict) -> None:
        if not messagebox.askyesno(
            "Marquer comme spam",
            f"Marquer le brief de {brief.get('first_name','')} "
            f"{brief.get('last_name','')} comme spam ?",
        ):
            return
        forge_repo.mark_brief_rejected(brief["id"], note="Rejeté manuellement")
        self._status_var.set("Brief rejeté.")
        self._refresh_active_tab()

    def _poll_intake_now(self) -> None:
        """Force un cycle de poll IMAP (utile en démo / test E2E)."""
        from ..integrations import teddy_to_forge

        self._status_var.set("Vérification IMAP en cours…")

        def worker():
            try:
                result = teddy_to_forge.poll_now(self.app_state)
            except Exception as exc:
                logger.exception("poll_intake_now: %s", exc)
                self.after(0, lambda:
                           self._status_var.set(f"Erreur : {exc}"))
                return
            written = (result or {}).get("written", 0)
            err = (result or {}).get("error")
            if err:
                msg = f"Échec : {err}"
            elif written:
                msg = (f"✓ {written} nouveau brief reçu" if written == 1
                       else f"✓ {written} nouveaux briefs reçus")
            else:
                msg = "Aucun nouveau mail détecté."
            self.after(0, lambda: self._status_var.set(msg))
            self.after(0, self._refresh_active_tab)

        threading.Thread(target=worker, daemon=True,
                         name="ForgePollNow").start()

    # ------------------------------------------------------------------
    # ONGLET — Projets
    # ------------------------------------------------------------------
    def _build_projects(self, parent: ctk.CTkFrame) -> None:
        c = self.colors
        HeroQuestion(
            parent, colors=c,
            text="Quels sites La Forge fabrique-t-elle en ce moment ?",
        ).pack(fill="x", pady=(T.SPACE_LG, T.SPACE_MD))

        projects = forge_repo.list_projects(limit=30)
        if not projects:
            EmptyState(
                parent, colors=c, icon="globe",
                title="Aucun projet en cours",
                message=(
                    "Les projets apparaîtront ici quand tu importes un "
                    "brief depuis l'onglet « Briefs reçus »."
                ),
                cta_text="Voir les briefs",
                cta_command=lambda: self._switch_tab("briefs"),
            ).pack(fill="both", expand=True, pady=T.SPACE_2XL)
            return

        # Table
        table = Card(parent, colors=c)
        table.pack(fill="both", expand=True)
        head = ctk.CTkFrame(table, fg_color="transparent")
        head.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))
        for label, w in (("CLIENT", 220), ("ÉTAPE", 90), ("MODE", 90),
                         ("STATUT", 100), ("CRÉÉ LE", 110), ("", 1)):
            ctk.CTkLabel(
                head, text=label, width=w,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                text_color=c.text_muted, anchor="w",
            ).pack(side="left", padx=(0, T.SPACE_SM))

        rows = ctk.CTkScrollableFrame(
            table, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        rows.pack(fill="both", expand=True,
                  padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        for p in projects:
            self._render_project_row(rows, p)

        self._status_var.set(
            f"{len(projects)} projet{'s' if len(projects) > 1 else ''} "
            f"en base."
        )

    def _render_project_row(self, parent, p: dict) -> None:
        c = self.colors
        row = ctk.CTkFrame(parent, fg_color="transparent", height=44)
        row.pack(fill="x", pady=2)
        row.pack_propagate(False)

        full_name = (
            f"{p.get('client_first_name','')} {p.get('client_last_name','')}"
        ).strip() or "(sans nom)"
        ctk.CTkLabel(
            row, text=full_name, width=220,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(side="left", padx=(0, T.SPACE_SM))

        step = int(p.get("current_step") or 0)
        step_label = "—" if step == 0 else (f"{step}/14" if step <= 14 else "✓")
        ctk.CTkLabel(
            row, text=step_label, width=90,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color=c.accent, anchor="w",
        ).pack(side="left", padx=(0, T.SPACE_SM))

        mode = "Auto" if p.get("auto_run") else "Manuel"
        ctk.CTkLabel(
            row, text=mode, width=90,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
            text_color=c.text_secondary, anchor="w",
        ).pack(side="left", padx=(0, T.SPACE_SM))

        status = p.get("status", "queued")
        status_color = {
            "queued":    c.text_muted,
            "running":   c.accent,
            "done":      c.success,
            "error":     c.danger,
            "paused":    c.warning,
            "cancelled": c.text_muted,
        }.get(status, c.text_muted)
        ctk.CTkLabel(
            row, text=status, width=100,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=status_color, anchor="w",
        ).pack(side="left", padx=(0, T.SPACE_SM))

        ctk.CTkLabel(
            row, text=_fmt_dt(p.get("created_at") or ""), width=110,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
            text_color=c.text_muted, anchor="w",
        ).pack(side="left", padx=(0, T.SPACE_SM))

        # Indicateur "moteur 14 étapes pas encore codé"
        if status == "queued":
            ctk.CTkLabel(
                row, text="en attente du moteur (v0.5)",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                text_color=c.text_muted, anchor="w",
            ).pack(side="left", padx=(T.SPACE_SM, 0))

    # ------------------------------------------------------------------
    # ONGLET — Workflow (carte des 14 étapes)
    # ------------------------------------------------------------------
    def _build_workflow(self, parent: ctk.CTkFrame) -> None:
        c = self.colors
        HeroQuestion(
            parent, colors=c,
            text="Comment La Forge fabriquera-t-elle un site complet ?",
        ).pack(fill="x", pady=(T.SPACE_LG, T.SPACE_MD))

        scroll = ctk.CTkScrollableFrame(
            parent, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        scroll.pack(fill="both", expand=True)

        grid = ctk.CTkFrame(scroll, fg_color="transparent")
        grid.pack(fill="x", pady=(0, T.SPACE_MD))
        cols = 3
        for i in range(cols):
            grid.grid_columnconfigure(i, weight=1, uniform="forge_step")

        for idx, (num, label, descr) in enumerate(WORKFLOW_STEPS):
            r, col = divmod(idx, cols)
            cell = ctk.CTkFrame(
                grid, fg_color=c.panel_hover,
                corner_radius=T.RADIUS_SM,
                border_color=c.border, border_width=1,
            )
            cell.grid(row=r, column=col, sticky="nsew",
                      padx=T.SPACE_SM, pady=T.SPACE_SM)
            head = ctk.CTkFrame(cell, fg_color="transparent")
            head.pack(fill="x", padx=T.SPACE_MD,
                      pady=(T.SPACE_MD, T.SPACE_XS))
            ctk.CTkLabel(
                head, text=f"{num:02d}",
                font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_HEADING, "bold"),
                text_color=c.accent, anchor="w",
            ).pack(side="left", padx=(0, T.SPACE_SM))
            ctk.CTkLabel(
                head, text=label,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
                text_color=c.text_primary, anchor="w",
            ).pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(
                cell, text=descr,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_secondary, anchor="w",
                justify="left", wraplength=280,
            ).pack(fill="x", padx=T.SPACE_MD,
                   pady=(0, T.SPACE_MD))

    # ------------------------------------------------------------------
    # ONGLET — À propos
    # ------------------------------------------------------------------
    def _build_about(self, parent: ctk.CTkFrame) -> None:
        c = self.colors

        # État du projet
        status_card = Card(parent, colors=c)
        status_card.pack(fill="x", pady=(T.SPACE_LG, T.SPACE_MD))

        head = ctk.CTkFrame(status_card, fg_color="transparent")
        head.pack(fill="x", padx=T.SPACE_LG,
                  pady=(T.SPACE_LG, T.SPACE_XS))
        ctk.CTkLabel(
            head, text="ÉTAT DU PROJET",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(side="left")
        self._make_pill(head, text="Spec v0.2 figée",
                        text_color=c.info, bg_color=c.panel
                        ).pack(side="left", padx=(T.SPACE_SM, 0))
        self._make_pill(head, text="Intake actif",
                        text_color=c.success, bg_color=c.panel
                        ).pack(side="left", padx=(T.SPACE_SM, 0))
        self._make_pill(head, text="Moteur 14 étapes — à venir (v0.5)",
                        text_color=c.warning, bg_color=c.panel
                        ).pack(side="left", padx=(T.SPACE_SM, 0))

        ctk.CTkLabel(
            status_card,
            text=(
                "L'intake mail (Teddy → forge_pending_briefs) est "
                "fonctionnel : un mail capté sur la boîte partagée crée "
                "automatiquement un brief, puis un projet. L'exécution "
                "automatique des 14 étapes attend le moteur Rust de "
                "l'app autonome (planifié v0.5)."
            ),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w",
            justify="left", wraplength=900,
        ).pack(fill="x", padx=T.SPACE_LG,
               pady=(T.SPACE_XS, T.SPACE_LG))

        # Connexions
        eco_card = Card(parent, colors=c)
        eco_card.pack(fill="x", pady=(0, T.SPACE_MD))
        ctk.CTkLabel(
            eco_card, text="CONNEXIONS DANS L'ÉCOSYSTÈME",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG,
               pady=(T.SPACE_LG, T.SPACE_XS))

        for label, descr in (
            ("Teddy Mail (intake)",
             "Détecte les mails « Demande de création de site » sur la "
             "boîte IMAP partagée et dépose les briefs ici. Cycle de "
             "poll : 5 min."),
            ("Le Phare (SEO)",
             "Sera notifié au déploiement de chaque site (étape 9 + "
             "étape 14 du workflow)."),
            ("Triskell Command",
             "Tu vois ici la vue intégrée. Quand l'app autonome existera, "
             "tu pourras la lancer en un clic."),
        ):
            row = ctk.CTkFrame(eco_card, fg_color="transparent")
            row.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_XS))
            ctk.CTkLabel(
                row, text=f"  ·  {label}",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
                text_color=c.text_primary, anchor="w", width=180,
            ).pack(side="left")
            ctk.CTkLabel(
                row, text=descr,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_secondary, anchor="w",
                justify="left", wraplength=700,
            ).pack(side="left", fill="x", expand=True)
        ctk.CTkFrame(eco_card, fg_color="transparent",
                     height=T.SPACE_MD).pack()

    # ------------------------------------------------------------------
    # Helpers UI
    # ------------------------------------------------------------------
    @staticmethod
    def _make_pill(parent, *, text: str, text_color: str,
                   bg_color: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent, text=text,
            text_color=text_color, fg_color=bg_color,
            corner_radius=T.RADIUS_PILL,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            padx=10, pady=2,
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _launch_app(self) -> None:
        """Lance le binaire Tauri (à venir)."""
        # TODO(v0.5) : remplacer par subprocess.Popen vers l'exe.
        messagebox.showinfo(
            "La Forge du Web — bientôt disponible",
            "Le code de l'app autonome n'a pas encore démarré.\n\n"
            "La spec v0.2 a été figée le 8 mai 2026, et le développement "
            "est planifié en trois temps : MVP v0.1, v0.5 (intégration "
            "Triskell Command), v1.0.\n\n"
            "Quand l'app sera installée, ce bouton la lancera "
            "directement.",
        )
        self._status_var.set(
            "L'app autonome arrive — pour l'instant, l'intake fonctionne."
        )

    def _open_spec(self) -> None:
        from pathlib import Path
        candidates = [
            Path.home() / "repos" / "triskell-la-forge"
                / "docs" / "spec-v0.2.md",
        ]
        for p in candidates:
            if p.exists():
                self._open_url(p.as_uri())
                self._status_var.set(f"Spec ouverte : {p}")
                return
        self._status_var.set(
            "Spec introuvable — vérifie ~/repos/triskell-la-forge."
        )

    def _open_url(self, url: str) -> None:
        import webbrowser
        try:
            webbrowser.open(url, new=2)
        except Exception as exc:
            logger.debug("open_url: %s", exc)
