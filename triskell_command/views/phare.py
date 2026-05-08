"""Le Phare — vue de pilotage de l'agence SEO autonome multi-sites.

4 onglets internes :
  1. Écosystème  → KPI globaux + table des 13 sites
  2. Site        → focus 1 site : audits, mots-clés, pages, missions à lancer
  3. Bac à PRs   → actions en attente de validation
  4. Bulletins   → derniers rapports Analyste + plan stratégique mensuel

Chaque action lourde (audit, full cycle) tourne en thread pour ne pas geler
l'UI ; un statut s'affiche en bas pendant l'exécution.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Optional

import customtkinter as ctk

from tkinter import messagebox

from .. import theme as T
from ..integrations.phare import client_report, orchestrator, repo, scheduler
from ..widgets.components import (
    Card,
    EmptyState,
    PrimaryButton,
    SecondaryButton,
    StatCard,
    ViewHeader,
)
from ..widgets.components_pro import HeroQuestion, KpiHero
from ..widgets.phare_client_dialog import PhareClientDialog
from ..widgets.phare_site_dialog import PhareSiteDialog
from .base import BaseView

logger = logging.getLogger(__name__)


def _fmt_int(n) -> str:
    if n is None:
        return "—"
    try:
        return f"{int(n):,}".replace(",", " ")
    except (ValueError, TypeError):
        return str(n)


def _fmt_score(n) -> str:
    if n is None:
        return "—"
    try:
        return str(int(n))
    except (ValueError, TypeError):
        return "—"


def _fmt_dt(iso: str) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m %Hh%M")
    except ValueError:
        return iso[:16]


class PhareView(BaseView):
    title = "Le Phare"
    subtitle = (
        "Ton agence SEO embarquée. Audite, optimise et enrichit en continu "
        "tous les sites de l'écosystème Triskell."
    )

    TABS = [
        ("ecosystem", "Écosystème"),
        ("site",      "Site"),
        ("advanced",  "Avancé"),
        ("inbox",     "Modifications en attente"),
        ("bulletin",  "Bulletins"),
    ]

    def __init__(self, master, *, app_state, colors):
        super().__init__(master, app_state=app_state, colors=colors)
        self._active_tab = "ecosystem"
        self._selected_site_id: Optional[str] = None
        self._tab_frames: dict[str, ctk.CTkFrame] = {}
        self._tab_buttons: dict[str, ctk.CTkButton] = {}

    # ------------------------------------------------------------------
    # Build (1 seule fois)
    # ------------------------------------------------------------------
    def build(self) -> None:
        c = self.colors
        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_MD))

        SecondaryButton(header.actions, colors=c, icon="refresh",
                        text="Rafraîchir", command=self._refresh_all
                        ).pack(side="left", padx=(0, T.SPACE_SM))
        PrimaryButton(header.actions, colors=c, icon="sparkle",
                      text="Lancer cycle complet",
                      command=self._open_full_cycle_dialog
                      ).pack(side="left")

        # Onglets
        tabs_bar = ctk.CTkFrame(self, fg_color="transparent")
        tabs_bar.pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))
        for tab_id, label in self.TABS:
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

        # Conteneur de contenu d'onglet
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True,
                            padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))

        # Status bar
        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
        ).pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

        # Construit les 4 frames d'onglets vides
        for tab_id, _ in self.TABS:
            f = ctk.CTkFrame(self._content, fg_color="transparent")
            self._tab_frames[tab_id] = f
        self._switch_tab("ecosystem")

    def on_show(self) -> None:
        self._refresh_all()
        # Démarre le scheduler en background s'il n'est pas déjà actif
        try:
            scheduler.start_worker(self.app_state)
        except Exception as exc:
            logger.debug("phare scheduler start: %s", exc)

    # ------------------------------------------------------------------
    # Onglets
    # ------------------------------------------------------------------
    def _switch_tab(self, tab_id: str) -> None:
        c = self.colors
        self._active_tab = tab_id
        for tid, btn in self._tab_buttons.items():
            if tid == tab_id:
                btn.configure(fg_color=c.accent, text_color=c.accent_text or "#fff",
                              border_color=c.accent)
            else:
                btn.configure(fg_color=c.panel, text_color=c.text_secondary,
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
        if self._active_tab == "ecosystem":
            self._build_ecosystem(f)
        elif self._active_tab == "site":
            self._build_site(f)
        elif self._active_tab == "advanced":
            self._build_advanced(f)
        elif self._active_tab == "inbox":
            self._build_inbox(f)
        elif self._active_tab == "bulletin":
            self._build_bulletin(f)

    # ------------------------------------------------------------------
    # ONGLET 1 — Écosystème
    # ------------------------------------------------------------------
    def _build_ecosystem(self, parent: ctk.CTkFrame) -> None:
        c = self.colors
        HeroQuestion(
            parent, colors=c,
            text="Comment se portent les 13 sites de l'écosystème ?",
        ).pack(fill="x", pady=(T.SPACE_LG, T.SPACE_MD))

        try:
            overview = orchestrator.ecosystem_overview()
        except Exception as exc:
            logger.warning("ecosystem_overview: %s", exc)
            overview = None

        if not overview or not overview.get("sites"):
            EmptyState(
                parent, colors=c, icon="settings",
                title="Aucun site visible",
                message=(
                    "Connecte-toi à la base partagée Triskell depuis les "
                    "Réglages, puis exécute la migration 06_phare.sql dans "
                    "Supabase pour activer Le Phare."
                ),
                cta_text="Aller dans Réglages",
                cta_command=lambda: self._navigate_to("config"),
            ).pack(fill="both", expand=True, pady=T.SPACE_2XL)
            self._status_var.set("Le Phare attend la configuration Supabase.")
            return

        totals = overview.get("totals", {})
        cfg_status = overview.get("config_status", {})

        # Bandeau KPI globaux (patch P1 : 4 → 3 KPIs).
        # « Performance 30 j » fusionne clics organiques + impressions
        # (delta) — un seul chiffre primaire, ratio en sous-texte.
        kpis = ctk.CTkFrame(parent, fg_color="transparent")
        kpis.pack(fill="x", pady=(0, T.SPACE_MD))
        for i in range(3):
            kpis.grid_columnconfigure(i, weight=1, uniform="phare_kpi")

        n_actions = totals.get("actions_pending", 0)
        clicks_30d = totals.get("organic_clicks_30d", 0)
        imps_30d = totals.get("impressions_30d", 0)

        KpiHero(
            kpis, colors=c,
            label="Sites surveillés",
            value=str(len(overview["sites"])),
        ).grid(row=0, column=0, sticky="nsew", padx=(0, T.SPACE_MD))

        KpiHero(
            kpis, colors=c,
            label="Performance 30 j",
            value=_fmt_int(clicks_30d),
            delta_value=f"sur {_fmt_int(imps_30d)} impressions",
            delta_kind="neutral",
        ).grid(row=0, column=1, sticky="nsew", padx=(0, T.SPACE_MD))

        KpiHero(
            kpis, colors=c,
            label="Actions en attente",
            value=str(n_actions),
            delta_value=("—" if n_actions == 0 else "à valider"),
            delta_kind="up" if n_actions else "neutral",
            accent=c.accent if n_actions else "",
        ).grid(row=0, column=2, sticky="nsew")

        # Bandeau de configuration (warnings si quelque chose manque)
        warns = []
        if not cfg_status.get("gsc"):
            warns.append("GSC non configuré (clics réels indisponibles)")
        if not cfg_status.get("dataforseo"):
            warns.append("DataForSEO non configuré (volumes mots-clés indisponibles)")
        if not cfg_status.get("github_token"):
            warns.append("Connexion à GitHub manquante (les modifications ne pourront pas être appliquées automatiquement)")
        if not cfg_status.get("netlify_token"):
            warns.append("Connexion à Netlify manquante (impossible de prévisualiser avant mise en ligne)")
        if warns:
            warn_card = Card(parent, colors=c)
            warn_card.pack(fill="x", pady=(0, T.SPACE_MD))
            ctk.CTkLabel(
                warn_card, text="Configuration à compléter (Réglages → Le Phare)",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
                text_color=c.warning, anchor="w",
            ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_XS))
            for w in warns:
                ctk.CTkLabel(
                    warn_card, text=f"  • {w}",
                    font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                    text_color=c.text_secondary, anchor="w",
                ).pack(fill="x", padx=T.SPACE_LG)
            ctk.CTkFrame(warn_card, fg_color="transparent",
                         height=T.SPACE_MD).pack()

        # Table des sites
        table = Card(parent, colors=c)
        table.pack(fill="both", expand=True)

        # Barre titre + bouton ajout
        title_bar = ctk.CTkFrame(table, fg_color="transparent")
        title_bar.pack(fill="x", padx=T.SPACE_LG,
                        pady=(T.SPACE_LG, T.SPACE_SM))
        ctk.CTkLabel(
            title_bar, text="Sites surveillés",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(side="left")
        PrimaryButton(
            title_bar, colors=c, text="Ajouter un site", icon="plus",
            command=self._open_site_form_dialog,
        ).pack(side="right")

        head = ctk.CTkFrame(table, fg_color="transparent")
        head.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_SM, T.SPACE_SM))
        for label, w in (("SITE", 220), ("PERF", 70), ("SEO", 70),
                          ("PAGES", 70), ("CLICS 30J", 100),
                          ("À VALIDER", 100), ("DERNIER AUDIT", 130),
                          ("ACTIONS", 200)):
            ctk.CTkLabel(
                head, text=label, width=w,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                text_color=c.text_muted, anchor="w",
            ).pack(side="left", padx=(0, T.SPACE_SM))

        rows = ctk.CTkScrollableFrame(table, fg_color="transparent",
                                       scrollbar_button_color=c.border_strong)
        rows.pack(fill="both", expand=True,
                  padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        for s in overview["sites"]:
            row = ctk.CTkFrame(rows, fg_color="transparent", height=44)
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)

            # Site name + domain
            site_block = ctk.CTkFrame(row, fg_color="transparent", width=220)
            site_block.pack(side="left", padx=(0, T.SPACE_SM))
            site_block.pack_propagate(False)
            ctk.CTkLabel(site_block, text=s["name"],
                          font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
                          text_color=c.text_primary, anchor="w"
                          ).pack(fill="x")
            ctk.CTkLabel(site_block, text=s["domain"],
                          font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                          text_color=c.text_muted, anchor="w"
                          ).pack(fill="x")

            for value, w, accent in (
                (_fmt_score(s.get("lighthouse_perf")), 70,
                 self._score_color(s.get("lighthouse_perf"))),
                (_fmt_score(s.get("lighthouse_seo")), 70,
                 self._score_color(s.get("lighthouse_seo"))),
                (str(s.get("pages_crawled") or 0), 70, ""),
                (_fmt_int(s.get("organic_clicks_30d")), 100, ""),
                (str(s.get("actions_pending") or 0), 100,
                 c.accent if s.get("actions_pending") else ""),
                (_fmt_dt(s.get("last_audit_at") or ""), 130, ""),
            ):
                ctk.CTkLabel(
                    row, text=value, width=w,
                    font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                    text_color=accent or c.text_primary, anchor="w",
                ).pack(side="left", padx=(0, T.SPACE_SM))

            actions_cell = ctk.CTkFrame(row, fg_color="transparent", width=200)
            actions_cell.pack(side="left")
            actions_cell.pack_propagate(False)
            SecondaryButton(
                actions_cell, colors=c, text="Ouvrir", icon="external",
                width=95,
                command=lambda sid=s["id"]: self._open_site(sid),
            ).pack(side="left", padx=(0, T.SPACE_XS))
            SecondaryButton(
                actions_cell, colors=c, text="Désactiver", icon="close",
                width=95,
                command=lambda sid=s["id"], nm=s["name"]:
                    self._deactivate_site(sid, nm),
            ).pack(side="left")

        self._status_var.set(
            f"{len(overview['sites'])} sites · "
            f"{totals.get('organic_clicks_30d', 0)} clics 30j · "
            f"{totals.get('actions_pending', 0)} actions en attente"
        )

    def _score_color(self, score) -> str:
        c = self.colors
        if score is None:
            return c.text_muted
        try:
            v = int(score)
        except (ValueError, TypeError):
            return c.text_muted
        if v >= 90:
            return c.success
        if v >= 70:
            return c.text_primary
        if v >= 50:
            return c.warning
        return c.danger

    def _open_site(self, site_id: str) -> None:
        self._selected_site_id = site_id
        self._switch_tab("site")

    def _open_site_form_dialog(self, site: Optional[dict] = None) -> None:
        """Ouvre la modale d'ajout / édition d'un site."""
        try:
            PhareSiteDialog(
                self.winfo_toplevel(),
                colors=self.colors,
                site=site,
                on_done=self._refresh_active_tab,
            )
        except Exception as exc:
            logger.exception("phare site dialog: %s", exc)
            messagebox.showerror(
                "Erreur",
                f"Impossible d'ouvrir le formulaire :\n{exc}",
            )

    # ------------------------------------------------------------------
    # Carte fiche client (site marqué `is_external_client`)
    # ------------------------------------------------------------------
    def _build_client_card(self, parent: ctk.CTkFrame, site: dict) -> None:
        c = self.colors
        client = repo.get_client_by_site(site["id"])

        card = Card(parent, colors=c)
        card.pack(fill="x", pady=(0, T.SPACE_MD))

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_XS))
        ctk.CTkLabel(
            head, text="FICHE CLIENT",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(side="left")

        if client is None:
            # Pas encore de fiche → CTA création
            body = ctk.CTkFrame(card, fg_color="transparent")
            body.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_XS, T.SPACE_LG))
            ctk.CTkLabel(
                body,
                text="Pas encore de fiche client. Crée-la pour configurer "
                     "l'envoi des rapports.",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_secondary, anchor="w",
            ).pack(fill="x", pady=(0, T.SPACE_SM))
            PrimaryButton(
                body, colors=c, text="Créer la fiche client", icon="plus",
                command=lambda: self._open_client_form_dialog(site, None),
            ).pack(anchor="w")
            return

        # Fiche existante : affichage compact
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_XS, T.SPACE_LG))

        # Ligne 1 : nom + société
        line1 = ctk.CTkFrame(body, fg_color="transparent")
        line1.pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(
            line1, text=client.get("contact_name") or "—",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(side="left")
        if client.get("company"):
            ctk.CTkLabel(
                line1, text=f"  ·  {client['company']}",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_muted, anchor="w",
            ).pack(side="left")

        # Ligne 2 : email + téléphone
        line2_parts = []
        if client.get("contact_email"):
            line2_parts.append(client["contact_email"])
        if client.get("phone"):
            line2_parts.append(client["phone"])
        if line2_parts:
            ctk.CTkLabel(
                body, text="  ·  ".join(line2_parts),
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_secondary, anchor="w",
            ).pack(fill="x", pady=(0, T.SPACE_XS))

        # Ligne 3 : cadence + dernier envoi
        cadence = client.get("report_cadence") or "manuel"
        cad_label = ("Envoi auto · 1× par mois" if cadence == "auto_mensuel"
                     else "Envoi manuel sur demande")
        last_sent = client.get("last_report_sent_at")
        last_sent_str = (f"  ·  Dernier envoi : {last_sent[:10]}"
                         if last_sent else "  ·  Aucun rapport envoyé")
        ctk.CTkLabel(
            body, text=cad_label + last_sent_str,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", pady=(0, T.SPACE_SM))

        # Boutons d'action
        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(fill="x")
        SecondaryButton(
            btns, colors=c, text="Modifier la fiche", icon="settings",
            command=lambda s=site, cl=client:
                self._open_client_form_dialog(s, cl),
        ).pack(side="left", padx=(0, T.SPACE_SM))
        PrimaryButton(
            btns, colors=c, text="Générer le rapport maintenant",
            icon="sparkle",
            command=lambda s=site, cl=client:
                self._generate_report_for_client(s, cl),
        ).pack(side="left")

    def _open_client_form_dialog(
        self, site: dict, client: Optional[dict],
    ) -> None:
        try:
            PhareClientDialog(
                self.winfo_toplevel(),
                colors=self.colors,
                site=site,
                client=client,
                on_done=self._refresh_active_tab,
            )
        except Exception as exc:
            logger.exception("phare client dialog: %s", exc)
            messagebox.showerror(
                "Erreur",
                f"Impossible d'ouvrir le formulaire :\n{exc}",
            )

    def _generate_report_for_client(self, site: dict, client: dict) -> None:
        """Génère le rapport mensuel client (HTML + PDF) et ouvre le résultat
        dans le navigateur. La modale de prévisualisation/envoi viendra à
        l'étape 6.
        """
        import threading
        import webbrowser

        self._status_var.set(f"Génération du rapport pour {site.get('name')}…")

        def worker():
            try:
                result = client_report.generate_for_client(
                    site["id"], client.get("id"),
                    app_state=self.app_state,
                )
            except Exception as exc:
                logger.exception("client_report failed: %s", exc)
                self.after(0, lambda:
                    messagebox.showerror("Erreur",
                        f"Génération échouée :\n{exc}"))
                self.after(0, lambda: self._status_var.set(""))
                return

            if not result.get("ok"):
                self.after(0, lambda:
                    messagebox.showerror("Erreur",
                        result.get("error") or "Échec de la génération."))
                self.after(0, lambda: self._status_var.set(""))
                return

            # Ouvre le résultat (PDF si dispo, sinon HTML)
            path = result.get("pdf_path") or result.get("html_path")
            if path:
                try:
                    webbrowser.open(f"file:///{path.replace(chr(92), '/')}")
                except Exception as exc:
                    logger.debug("webbrowser open: %s", exc)

            fmt = result["format"].upper()
            self.after(0, lambda: self._status_var.set(
                f"✓ Rapport {fmt} généré pour {site.get('name')} — "
                f"{result.get('pdf_path') or result.get('html_path')}"))
            self.after(0, lambda: messagebox.showinfo(
                "Rapport généré",
                f"Le rapport {fmt} a été généré et ouvert dans ton navigateur.\n\n"
                f"Chemin : {path}\n\n"
                f"L'envoi par email au client arrivera à l'étape suivante "
                f"(préversion + bouton « Envoyer »)."))

        threading.Thread(target=worker, daemon=True).start()

    def _deactivate_site(self, site_id: str, site_name: str) -> None:
        """Désactive un site après confirmation."""
        if not messagebox.askyesno(
            "Désactiver le site",
            f"Désactiver « {site_name} » ?\n\n"
            "Le site sera caché de la liste et plus aucune mission ne sera "
            "lancée. Les données passées (audits, mots-clés) restent en base.",
        ):
            return
        ok = repo.deactivate_site(site_id)
        if not ok:
            messagebox.showerror(
                "Erreur",
                "Impossible de désactiver le site. Vérifie la connexion "
                "Supabase.",
            )
            return
        self._refresh_active_tab()

    # ------------------------------------------------------------------
    # ONGLET 2 — Site (focus)
    # ------------------------------------------------------------------
    def _build_site(self, parent: ctk.CTkFrame) -> None:
        c = self.colors
        if not self._selected_site_id:
            EmptyState(
                parent, colors=c, icon="search",
                title="Aucun site sélectionné",
                message="Choisis un site dans l'onglet « Écosystème ».",
                cta_text="Voir l'écosystème",
                cta_command=lambda: self._switch_tab("ecosystem"),
            ).pack(fill="both", expand=True, pady=T.SPACE_2XL)
            return

        HeroQuestion(
            parent, colors=c,
            text="Que se passe-t-il sur ce site ?",
        ).pack(fill="x", pady=(T.SPACE_LG, T.SPACE_MD))

        site = repo.get_site(self._selected_site_id)
        if not site:
            EmptyState(parent, colors=c, icon="close",
                        title="Site introuvable",
                        message="Le site a peut-être été désactivé.",
                        cta_text="Revenir à l'écosystème",
                        cta_command=lambda: self._switch_tab("ecosystem")
                        ).pack(fill="both", expand=True, pady=T.SPACE_2XL)
            return

        latest = repo.latest_audit(site["id"])
        actions = repo.list_actions(site_id=site["id"], limit=20)
        keywords = repo.list_keywords(site["id"], limit=30)
        pages = repo.list_pages(site["id"], limit=30)

        # Header site
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", pady=(0, T.SPACE_MD))
        ctk.CTkLabel(header, text=site["name"],
                      font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_DISPLAY, "bold"),
                      text_color=c.text_primary, anchor="w"
                      ).pack(side="left")
        ctk.CTkLabel(header, text=f"  {site['domain']}",
                      font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
                      text_color=c.text_muted, anchor="w"
                      ).pack(side="left", padx=(T.SPACE_SM, 0))
        SecondaryButton(
            header, colors=c, text="Éditer le site", icon="settings",
            command=lambda s=site: self._open_site_form_dialog(s),
        ).pack(side="right")

        # Carte client (si site marqué comme client externe)
        if site.get("is_external_client"):
            self._build_client_card(parent, site)

        # Boutons missions
        actions_bar = ctk.CTkFrame(parent, fg_color="transparent")
        actions_bar.pack(fill="x", pady=(0, T.SPACE_MD))
        for label, mission in (
            ("Audit technique", "audit"),
            ("Veille mots-clés", "keywords"),
            ("Optim on-page", "optim_onpage"),
            ("Maillage", "tisseur"),
            ("Bulletin Analyste", "analyst"),
            ("Backlinks", "backlinks"),
            ("CTR booster", "ctr_optim"),
            ("Cycle complet", "full_cycle"),
        ):
            SecondaryButton(
                actions_bar, colors=c, text=label, icon="sparkle",
                command=lambda m=mission, sid=site["id"]: self._run_mission(m, sid),
            ).pack(side="left", padx=(0, T.SPACE_SM))

        # KPI du site
        kpi = ctk.CTkFrame(parent, fg_color="transparent")
        kpi.pack(fill="x", pady=(0, T.SPACE_MD))
        for i in range(4):
            kpi.grid_columnconfigure(i, weight=1, uniform="site_kpi")
        StatCard(kpi, label="Lighthouse perf",
                 value=_fmt_score((latest or {}).get("lighthouse_perf")),
                 accent=self._score_color((latest or {}).get("lighthouse_perf")),
                 colors=c).grid(row=0, column=0, sticky="nsew",
                                padx=(0, T.SPACE_MD))
        StatCard(kpi, label="Lighthouse SEO",
                 value=_fmt_score((latest or {}).get("lighthouse_seo")),
                 accent=self._score_color((latest or {}).get("lighthouse_seo")),
                 colors=c).grid(row=0, column=1, sticky="nsew",
                                padx=(0, T.SPACE_MD))
        StatCard(kpi, label="Pages crawlées",
                 value=str((latest or {}).get("pages_crawled", 0)),
                 colors=c).grid(row=0, column=2, sticky="nsew",
                                padx=(0, T.SPACE_MD))
        StatCard(kpi, label="Liens cassés",
                 value=str((latest or {}).get("broken_links", 0)),
                 accent=c.danger if (latest or {}).get("broken_links") else "",
                 colors=c).grid(row=0, column=3, sticky="nsew")

        # Mots-clés top
        if keywords:
            kw_card = Card(parent, colors=c)
            kw_card.pack(fill="x", pady=(0, T.SPACE_MD))
            ctk.CTkLabel(kw_card, text="MOTS-CLÉS SUIVIS (TOP 10)",
                          font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                          text_color=c.text_muted, anchor="w"
                          ).pack(fill="x", padx=T.SPACE_LG,
                                  pady=(T.SPACE_LG, T.SPACE_XS))
            for kw in keywords[:10]:
                row = ctk.CTkFrame(kw_card, fg_color="transparent")
                row.pack(fill="x", padx=T.SPACE_LG, pady=2)
                ctk.CTkLabel(row, text=kw["keyword"],
                              font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                              text_color=c.text_primary, anchor="w", width=300
                              ).pack(side="left")
                ctk.CTkLabel(row, text=f"vol {kw.get('volume') or 0}",
                              font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                              text_color=c.text_muted, anchor="w", width=100
                              ).pack(side="left")
                ctk.CTkLabel(row, text=f"intent: {kw.get('intent') or '—'}",
                              font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                              text_color=c.text_muted, anchor="w", width=160
                              ).pack(side="left")
                pos = kw.get("current_position")
                ctk.CTkLabel(row, text=f"pos {pos}" if pos else "non rankée",
                              font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                              text_color=c.text_muted, anchor="w"
                              ).pack(side="left")
            ctk.CTkFrame(kw_card, fg_color="transparent",
                          height=T.SPACE_MD).pack()

        # Actions récentes
        if actions:
            act_card = Card(parent, colors=c)
            act_card.pack(fill="both", expand=True)
            ctk.CTkLabel(act_card, text="DERNIÈRES MISSIONS / ACTIONS",
                          font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                          text_color=c.text_muted, anchor="w"
                          ).pack(fill="x", padx=T.SPACE_LG,
                                  pady=(T.SPACE_LG, T.SPACE_XS))
            scroll = ctk.CTkScrollableFrame(act_card, fg_color="transparent",
                                              scrollbar_button_color=c.border_strong)
            scroll.pack(fill="both", expand=True,
                        padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
            for a in actions:
                row = ctk.CTkFrame(scroll, fg_color="transparent")
                row.pack(fill="x", pady=2)
                ctk.CTkLabel(row, text=a.get("agent", "—"),
                              font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                              text_color=c.accent, anchor="w", width=120
                              ).pack(side="left")
                ctk.CTkLabel(row, text=a.get("title", ""),
                              font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                              text_color=c.text_primary, anchor="w", width=400
                              ).pack(side="left")
                status_label = a.get("status", "—")
                color = (c.warning if status_label in ("draft", "preview")
                         else c.success if status_label == "merged"
                         else c.danger if status_label == "rejected"
                         else c.text_muted)
                ctk.CTkLabel(row, text=status_label,
                              font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                              text_color=color, anchor="w", width=80
                              ).pack(side="left")
                ctk.CTkLabel(row, text=_fmt_dt(a.get("created_at") or ""),
                              font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                              text_color=c.text_muted, anchor="w"
                              ).pack(side="left")

    # ------------------------------------------------------------------
    # ONGLET 3 — Avancé (fonctions agence senior)
    # ------------------------------------------------------------------
    def _build_advanced(self, parent: ctk.CTkFrame) -> None:
        c = self.colors
        HeroQuestion(
            parent, colors=c,
            text="Quels outils avancés lancer cette semaine ?",
        ).pack(fill="x", pady=(T.SPACE_LG, T.SPACE_MD))
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent",
                                          scrollbar_button_color=c.border_strong)
        scroll.pack(fill="both", expand=True)

        sites = repo.list_sites()
        if not sites:
            EmptyState(scroll, colors=c, icon="search",
                        title="Aucun site",
                        message="Aucun site visible.",
                        cta_text="Ouvrir Écosystème",
                        cta_command=lambda: self._switch_tab("ecosystem")
                        ).pack(fill="both", expand=True, pady=T.SPACE_2XL)
            return

        # Sélecteur de site
        sel_card = Card(scroll, colors=c)
        sel_card.pack(fill="x", pady=(0, T.SPACE_MD))
        ctk.CTkLabel(sel_card, text="SITE CIBLE",
                      font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                      text_color=c.text_muted, anchor="w"
                      ).pack(fill="x", padx=T.SPACE_LG,
                              pady=(T.SPACE_LG, T.SPACE_XS))
        var = ctk.StringVar(value=(self._selected_site_id and
                                    next((s["name"] for s in sites
                                          if s["id"] == self._selected_site_id),
                                         sites[0]["name"]))
                                   or sites[0]["name"])
        for s in sites:
            ctk.CTkRadioButton(sel_card, text=f"{s['name']} ({s['domain']})",
                                variable=var, value=s["name"],
                                command=lambda v=s["id"]:
                                    setattr(self, "_selected_site_id", v)
                                ).pack(anchor="w", padx=T.SPACE_LG, pady=2)
        ctk.CTkFrame(sel_card, fg_color="transparent",
                      height=T.SPACE_MD).pack()

        # Bandeau missions avancées
        missions_card = Card(scroll, colors=c)
        missions_card.pack(fill="x", pady=(0, T.SPACE_MD))
        ctk.CTkLabel(missions_card, text="MISSIONS AVANCÉES",
                      font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                      text_color=c.text_muted, anchor="w"
                      ).pack(fill="x", padx=T.SPACE_LG,
                              pady=(T.SPACE_LG, T.SPACE_XS))

        missions = [
            ("CTR booster", "ctr_optim",
             "Détecte les pages très vues mais peu cliquées sur Google et "
             "réécrit titre + description pour booster le clic."),
            ("Featured snippets", "snippet_hunt",
             "Repère les snippets Google capturables sur tes mots-clés et "
             "écrit le paragraphe optimisé pour les piquer."),
            ("Présence dans ChatGPT/Perplexity", "geo_check",
             "Interroge les IA pour voir si tu es cité quand on parle de "
             "ton domaine, et compare aux concurrents."),
            ("Cannibalisation", "cannibalization",
             "Trouve les cas où plusieurs de tes pages se battent sur le "
             "même mot-clé, et propose fusion / redirection."),
            ("Pages zombies", "zombies",
             "Repère les pages sans trafic depuis 6 mois et propose : "
             "booster, rediriger, supprimer ou désindexer."),
            ("Image SEO", "image_seo",
             "Génère les alt manquants, repère les images trop lourdes, "
             "propose les conversions WebP/AVIF + lazy loading."),
            ("Refresh d'articles", "refresh",
             "Trouve les vieux articles qui perdent du trafic et écrit le "
             "brief pour les rafraîchir efficacement."),
            ("Suivi des concurrents", "competitors",
             "Détecte tes 5 concurrents directs et trace leurs positions "
             "sur tes mots-clés cibles. Alerte si l'un avance vite."),
            ("Sitemap + IndexNow", "sitemap",
             "Régénère le sitemap.xml et notifie Bing/Yandex que tes "
             "nouvelles pages existent."),
            ("Démarchage backlinks", "outreach_drafts",
             "Rédige les emails de démarchage pour les opportunités de "
             "liens détectées. Tu valides chaque mail avant envoi."),
            ("Mentions Triskell", "brand_scan",
             "Scanne le web pour les nouvelles mentions de ta marque. "
             "Si mention sans lien, propose un mail de démarchage."),
            ("Fiche Google (Eliks)", "local_seo",
             "Surveille la fiche Google Business, propose des réponses "
             "aux nouveaux avis, suggère les champs à compléter."),
            ("CRO via Clarity", "cro_check",
             "Repère les pages avec rage clicks ou retours rapides et "
             "propose des fixes UX concrets."),
            ("Veille algo Google", "algo_watch",
             "Lit les sources SEO du jour et résume si quelque chose bouge "
             "dans l'algo Google."),
            ("Bulletin PDF du mois", "bulletin_pdf",
             "Génère le rapport mensuel en PDF : KPI, bulletins, plan "
             "stratégique, lisible par un humain."),
        ]
        grid = ctk.CTkFrame(missions_card, fg_color="transparent")
        grid.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        for i in range(3):
            grid.grid_columnconfigure(i, weight=1, uniform="mission_g")
        for idx, (label, mission, descr) in enumerate(missions):
            r, col = divmod(idx, 3)
            cell = ctk.CTkFrame(grid, fg_color=c.panel_hover,
                                 corner_radius=T.RADIUS_SM)
            cell.grid(row=r, column=col, sticky="nsew",
                      padx=T.SPACE_SM, pady=T.SPACE_SM)
            ctk.CTkLabel(cell, text=label,
                          font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
                          text_color=c.text_primary, anchor="w"
                          ).pack(fill="x", padx=T.SPACE_MD,
                                  pady=(T.SPACE_MD, T.SPACE_XS))
            ctk.CTkLabel(cell, text=descr,
                          font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                          text_color=c.text_secondary, anchor="w",
                          justify="left", wraplength=280
                          ).pack(fill="x", padx=T.SPACE_MD)
            SecondaryButton(cell, colors=c, text="Lancer", icon="sparkle",
                             command=lambda m=mission, sn=var:
                                 self._run_advanced(m, sn.get(), sites)
                             ).pack(anchor="w", padx=T.SPACE_MD,
                                     pady=T.SPACE_MD)

    def _run_advanced(self, mission: str, site_name: str,
                      sites: list[dict]) -> None:
        chosen = next((s for s in sites if s["name"] == site_name), None)
        if not chosen:
            self._status_var.set("Aucun site sélectionné.")
            return
        self._selected_site_id = chosen["id"]
        self._run_mission(mission, chosen["id"])

    # ------------------------------------------------------------------
    # ONGLET 4 — Bac à PRs (validations en attente)
    # ------------------------------------------------------------------
    def _build_inbox(self, parent: ctk.CTkFrame) -> None:
        c = self.colors
        HeroQuestion(
            parent, colors=c,
            text="Qu'est-ce qui attend mon validateur ?",
        ).pack(fill="x", pady=(T.SPACE_LG, T.SPACE_MD))
        actions = repo.list_actions(status="preview", limit=50)
        drafts = repo.list_actions(status="draft", limit=50)

        if not actions and not drafts:
            EmptyState(parent, colors=c, icon="check",
                        title="Tout est à jour",
                        message=("Aucune modification n'attend ta validation. "
                                 "Lance un cycle complet sur un site pour "
                                 "voir des suggestions ici."),
                        cta_text="Voir l'écosystème",
                        cta_command=lambda: self._switch_tab("ecosystem")
                        ).pack(fill="both", expand=True, pady=T.SPACE_2XL)
            return

        if actions:
            ctk.CTkLabel(parent, text="PRÊTES À APPLIQUER",
                          font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                          text_color=c.text_muted, anchor="w"
                          ).pack(fill="x", pady=(0, T.SPACE_SM))
            for a in actions:
                self._render_action_card(parent, a, with_actions=True)

        if drafts:
            ctk.CTkLabel(parent, text="SUGGESTIONS À EXAMINER",
                          font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                          text_color=c.text_muted, anchor="w"
                          ).pack(fill="x", pady=(T.SPACE_LG, T.SPACE_SM))
            for a in drafts[:30]:
                self._render_action_card(parent, a, with_actions=False)

    def _render_action_card(self, parent, a: dict, *, with_actions: bool) -> None:
        c = self.colors
        card = Card(parent, colors=c)
        card.pack(fill="x", pady=(0, T.SPACE_SM))
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_XS))
        ctk.CTkLabel(head, text=a.get("agent", "—").upper(),
                      font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                      text_color=c.accent, anchor="w"
                      ).pack(side="left")
        ctk.CTkLabel(head, text=f"  ·  {_fmt_dt(a.get('created_at') or '')}",
                      font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                      text_color=c.text_muted, anchor="w"
                      ).pack(side="left")
        ctk.CTkLabel(card, text=a.get("title", ""),
                      font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
                      text_color=c.text_primary, anchor="w", justify="left",
                      wraplength=900,
                      ).pack(fill="x", padx=T.SPACE_LG)
        if a.get("detail_md"):
            ctk.CTkLabel(card, text=a["detail_md"][:600],
                          font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                          text_color=c.text_secondary, anchor="w",
                          justify="left", wraplength=900,
                          ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_XS, 0))
        if with_actions:
            bar = ctk.CTkFrame(card, fg_color="transparent")
            bar.pack(fill="x", padx=T.SPACE_LG, pady=T.SPACE_MD)
            PrimaryButton(bar, colors=c, text="Appliquer",
                           icon="check",
                           command=lambda aid=a["id"]: self._merge(aid)
                           ).pack(side="left", padx=(0, T.SPACE_SM))
            SecondaryButton(bar, colors=c, text="Rejeter", icon="close",
                             command=lambda aid=a["id"]: self._reject(aid)
                             ).pack(side="left")
            if a.get("github_pr_url"):
                SecondaryButton(bar, colors=c, text="Voir sur GitHub",
                                 icon="external",
                                 command=lambda url=a["github_pr_url"]:
                                     self._open_url(url)
                                 ).pack(side="left", padx=(T.SPACE_SM, 0))
        else:
            ctk.CTkFrame(card, fg_color="transparent",
                         height=T.SPACE_MD).pack()

    # ------------------------------------------------------------------
    # ONGLET 4 — Bulletins
    # ------------------------------------------------------------------
    def _build_bulletin(self, parent: ctk.CTkFrame) -> None:
        c = self.colors
        HeroQuestion(
            parent, colors=c,
            text="Qu'est-ce que Le Phare a appris ce mois-ci ?",
        ).pack(fill="x", pady=(T.SPACE_LG, T.SPACE_MD))
        bulletins = []
        for s in repo.list_sites():
            for a in repo.list_actions(site_id=s["id"], limit=10):
                if a.get("agent") in ("analyste", "chef_orchestre"):
                    bulletins.append((s, a))
        bulletins.sort(key=lambda t: t[1].get("created_at") or "", reverse=True)

        if not bulletins:
            EmptyState(parent, colors=c, icon="chart",
                        title="Aucun bulletin pour le moment",
                        message=("Lance un Bulletin Analyste sur un site "
                                 "ou un Plan stratégique mensuel."),
                        cta_text="Voir l'écosystème",
                        cta_command=lambda: self._switch_tab("ecosystem")
                        ).pack(fill="both", expand=True, pady=T.SPACE_2XL)
            return

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent",
                                          scrollbar_button_color=c.border_strong)
        scroll.pack(fill="both", expand=True)
        for s, b in bulletins[:30]:
            card = Card(scroll, colors=c)
            card.pack(fill="x", pady=(0, T.SPACE_SM))
            ctk.CTkLabel(card,
                          text=f"{s['name']} — {b.get('agent', '').replace('_', ' ').title()}",
                          font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
                          text_color=c.text_primary, anchor="w"
                          ).pack(fill="x", padx=T.SPACE_LG,
                                  pady=(T.SPACE_LG, T.SPACE_XS))
            ctk.CTkLabel(card, text=_fmt_dt(b.get("created_at") or ""),
                          font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                          text_color=c.text_muted, anchor="w"
                          ).pack(fill="x", padx=T.SPACE_LG)
            ctk.CTkLabel(card, text=b.get("title", ""),
                          font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
                          text_color=c.text_primary, anchor="w",
                          justify="left", wraplength=900,
                          ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_SM, 0))
            if b.get("detail_md"):
                ctk.CTkLabel(card, text=b["detail_md"][:1500],
                              font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                              text_color=c.text_secondary, anchor="w",
                              justify="left", wraplength=900,
                              ).pack(fill="x", padx=T.SPACE_LG,
                                      pady=(T.SPACE_XS, T.SPACE_LG))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _open_full_cycle_dialog(self) -> None:
        sites = repo.list_sites()
        if not sites:
            self._status_var.set("Aucun site disponible.")
            return
        # Fenêtre simple de sélection
        win = ctk.CTkToplevel(self.winfo_toplevel())
        win.title("Lancer un cycle complet")
        win.geometry("420x420")
        win.configure(fg_color=self.colors.bg)
        ctk.CTkLabel(win, text="Site cible :",
                      font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
                      text_color=self.colors.text_primary
                      ).pack(anchor="w", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))
        var = ctk.StringVar(value=sites[0]["name"])
        for s in sites:
            ctk.CTkRadioButton(win, text=f"{s['name']} ({s['domain']})",
                                variable=var, value=s["name"]).pack(
                anchor="w", padx=T.SPACE_LG, pady=2)

        def _go():
            chosen = next((s for s in sites if s["name"] == var.get()), None)
            win.destroy()
            if chosen:
                self._run_mission("full_cycle", chosen["id"])

        PrimaryButton(win, colors=self.colors, text="Lancer", icon="sparkle",
                       command=_go).pack(pady=T.SPACE_LG)

    def _run_mission(self, mission: str, site_id: Optional[str]) -> None:
        """Lance une mission Phare en thread + relais pulse-bus (patch B3).

        Le WorkerPulse en bas affiche la LED PHAR active pendant que la
        mission tourne. Plus de silence de 60 s pendant un audit.
        """
        from ..integrations import pulse_bus

        self._status_var.set(f"Mission « {mission } » en cours…")
        pulse_bus.report("phare", "active",
                         text=f"Mission « {mission} » en cours",
                         relative_time="à l'instant")

        def _go():
            try:
                r = scheduler.run_now(mission, site_id, app_state=self.app_state)
                ok = r.get("ok", False)
                msg = "Mission terminée" if ok else f"Échec : {r.get('error', '?')}"
                self.after(0, lambda: self._status_var.set(msg))
                self.after(0, self._refresh_active_tab)
                if ok:
                    pulse_bus.report("phare", "active",
                                     text=f"Mission « {mission} » terminée",
                                     relative_time="à l'instant")
                else:
                    pulse_bus.report("phare", "error",
                                     text=f"Mission « {mission} » a échoué",
                                     error=str(r.get("error", "?")))
            except Exception as exc:
                logger.exception("run_mission %s: %s", mission, exc)
                self.after(0, lambda: self._status_var.set(f"Erreur : {exc}"))
                pulse_bus.report("phare", "error",
                                 text=f"Mission « {mission} » plantée",
                                 error=str(exc))

        threading.Thread(target=_go, daemon=True).start()

    def _merge(self, action_id: str) -> None:
        """Valide une action Phare (merge GitHub) + relais pulse-bus."""
        from ..integrations import pulse_bus

        self._status_var.set("Validation en cours…")
        pulse_bus.report("phare", "active",
                         text="Validation d'une modification",
                         relative_time="à l'instant")

        def _go():
            r = orchestrator.merge_action(action_id)
            ok = bool(r.get("ok"))
            msg = ("Modification appliquée" if ok
                   else f"Bloqué : {r.get('decision') or r.get('error')}")
            self.after(0, lambda: self._status_var.set(msg))
            self.after(0, self._refresh_active_tab)
            if ok:
                pulse_bus.report("phare", "active",
                                 text="Modification appliquée",
                                 relative_time="à l'instant")
            else:
                pulse_bus.report(
                    "phare", "error",
                    text="Validation bloquée",
                    error=str(r.get("decision") or r.get("error") or "?"),
                )

        threading.Thread(target=_go, daemon=True).start()

    def _reject(self, action_id: str) -> None:
        orchestrator.reject_action(action_id, reason="Rejet manuel depuis l'UI")
        self._status_var.set("Action rejetée.")
        self._refresh_active_tab()

    def _open_url(self, url: str) -> None:
        import webbrowser
        try:
            webbrowser.open(url, new=2)
        except Exception:
            pass
