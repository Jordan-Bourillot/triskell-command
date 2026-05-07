"""Vue Publier — détecte ton service Réseaux (AlphaCast) et pilote la file de drafts.

Trois zones :
  1. Statut service Réseaux + bouton "Tester la connexion"
  2. Drafts en attente d'approbation : liste cliquable, boutons Publier / Archiver
  3. Compose libre : génère un draft + publie en 1 clic (flow corrigé)
"""

from __future__ import annotations

import logging
import threading

import customtkinter as ctk

from .. import publish_auto
from .. import theme as T
from ..integrations import alphacast
from ..integrations.alphacast import AlphaCastError, Draft
from ..widgets.components import Card, PrimaryButton, SecondaryButton, ViewHeader
from .base import BaseView

logger = logging.getLogger(__name__)

PLATFORMS = ["linkedin", "x", "bluesky", "youtube"]


class PublishView(BaseView):
    title = "Publier sur les réseaux"
    subtitle = (
        "Tes brouillons en attente, leur publication, et la création "
        "libre — connectés à AlphaCast."
    )

    # ------------------------------------------------------------------ build
    def build(self) -> None:
        c = self.colors
        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_LG))

        SecondaryButton(header.actions, colors=c, icon="check",
                        text="Tester la connexion",
                        command=self._check_health).pack(side="left")

        # Zone scrollable pour empiler les sections (drafts peuvent être nombreux)
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))
        self._scroll = scroll

        self._build_health_section(scroll)
        self._build_automation_section(scroll)
        self._build_drafts_section(scroll)
        self._build_compose_section(scroll)

        # Status bar global en bas
        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=self.colors.text_muted,
        ).pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

    # ------------------------------------------------------------------ section 1 — health
    def _build_health_section(self, parent) -> None:
        c = self.colors
        self._health_card = Card(parent, colors=c)
        self._health_card.pack(fill="x", pady=(0, T.SPACE_LG))

        self._health_label = ctk.CTkLabel(
            self._health_card,
            text="AlphaCast : statut inconnu",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        )
        self._health_label.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))

        self._health_detail = ctk.CTkLabel(
            self._health_card,
            text=(f"URL : {self._base_url()}\n"
                  "Cliquez 'Tester la connexion' pour vérifier."),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, anchor="w", justify="left",
        )
        self._health_detail.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

    # ------------------------------------------------------------------ section 1bis — auto-publish dashboard
    def _build_automation_section(self, parent) -> None:
        c = self.colors
        card = Card(parent, colors=c)
        card.pack(fill="x", pady=(0, T.SPACE_LG))
        self._auto_card = card

        # Titre + master toggle
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))

        ctk.CTkLabel(
            head, text="🤖 Auto-publish — déclenché par tes campagnes",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(side="left")

        self._auto_enabled_var = ctk.BooleanVar(
            value=bool(self.app_state.get("publish_auto", "enabled", default=True)),
        )
        ctk.CTkSwitch(
            head, text="Activé", variable=self._auto_enabled_var,
            fg_color=c.bg_alt, progress_color=c.accent,
            button_color=c.text_primary, button_hover_color=c.text_primary,
            text_color=c.text_secondary,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            command=self._on_auto_toggle,
        ).pack(side="right")

        ctk.CTkLabel(
            card,
            text=("Quand tu envoies des 1ers contacts depuis Campagnes, "
                  "le compteur monte. Au seuil, un brouillon sort sur le réseau ciblé."),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, anchor="w", justify="left", wraplength=720,
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Rangée des thèmes
        ctk.CTkLabel(
            card, text="THÈME DU PROCHAIN DRAFT",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_XS))

        themes_row = ctk.CTkFrame(card, fg_color="transparent")
        themes_row.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_XS))

        self._theme_buttons: dict[str, ctk.CTkButton] = {}
        for key, label, _ in publish_auto.THEMES:
            btn = ctk.CTkButton(
                themes_row, text=label,
                fg_color=c.bg_alt, hover_color=c.border_strong,
                text_color=c.text_secondary,
                border_color=c.border, border_width=1,
                corner_radius=T.RADIUS_SM, height=30,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                command=lambda k=key: self._on_theme_pick(k),
            )
            btn.pack(side="left", padx=(0, T.SPACE_XS))
            self._theme_buttons[key] = btn

        ctk.CTkButton(
            themes_row, text="Aléatoire",
            fg_color="transparent", hover_color=c.bg_alt,
            text_color=c.text_muted,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM, height=30,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            command=lambda: self._on_theme_pick(""),
        ).pack(side="left")

        self._theme_status_label = ctk.CTkLabel(
            card, text="",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, anchor="w",
        )
        self._theme_status_label.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Cartes par plateforme
        platforms_frame = ctk.CTkFrame(card, fg_color="transparent")
        platforms_frame.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        self._platform_widgets: dict[str, dict] = {}
        for platform in publish_auto.PLATFORMS:
            self._build_platform_card(platforms_frame, platform)

        self._refresh_automation_ui()

    def _build_platform_card(self, parent, platform: str) -> None:
        c = self.colors
        sub = ctk.CTkFrame(
            parent, fg_color=c.bg_alt,
            corner_radius=T.RADIUS_SM,
            border_color=c.border, border_width=1,
        )
        sub.pack(side="left", fill="both", expand=True,
                 padx=(0, T.SPACE_SM if platform != publish_auto.PLATFORMS[-1] else 0))

        title = ctk.CTkLabel(
            sub, text=platform.upper(),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color=c.accent, anchor="w",
        )
        title.pack(fill="x", padx=T.SPACE_MD, pady=(T.SPACE_SM, 2))

        counter_label = ctk.CTkLabel(
            sub, text="—",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            text_color=c.text_primary, anchor="w",
        )
        counter_label.pack(fill="x", padx=T.SPACE_MD, pady=(0, 2))

        cap_label = ctk.CTkLabel(
            sub, text="—",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
            text_color=c.text_muted, anchor="w",
        )
        cap_label.pack(fill="x", padx=T.SPACE_MD, pady=(0, T.SPACE_SM))

        auto_var = ctk.BooleanVar(
            value=bool(self.app_state.get("publish_auto", "auto_publish",
                                          platform, default=False)),
        )
        ctk.CTkSwitch(
            sub, text="Auto-publier", variable=auto_var,
            fg_color=c.panel, progress_color=c.success,
            button_color=c.text_primary, button_hover_color=c.text_primary,
            text_color=c.text_secondary,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
            command=lambda p=platform: self._on_auto_publish_toggle(p),
        ).pack(fill="x", padx=T.SPACE_MD, pady=(0, T.SPACE_XS))

        gen_btn = SecondaryButton(
            sub, colors=c, icon="sparkles", text="Générer maintenant",
            command=lambda p=platform: self._trigger_manual(p),
        )
        gen_btn.pack(fill="x", padx=T.SPACE_MD, pady=(0, T.SPACE_SM))

        self._platform_widgets[platform] = {
            "counter": counter_label,
            "cap": cap_label,
            "auto_var": auto_var,
            "gen_btn": gen_btn,
        }

    def _refresh_automation_ui(self) -> None:
        c = self.colors
        # Thèmes : highlight celui qui est sélectionné (state partagé)
        next_theme = publish_auto.get_next_theme(self.app_state).strip()
        for key, btn in self._theme_buttons.items():
            if key == next_theme:
                btn.configure(fg_color=c.accent, text_color="#FFFFFF",
                              border_color=c.accent)
            else:
                btn.configure(fg_color=c.bg_alt, text_color=c.text_secondary,
                              border_color=c.border)

        if next_theme:
            label = publish_auto.theme_label(next_theme)
            self._theme_status_label.configure(
                text=f"→ Le prochain brouillon de chaque réseau utilisera : {label}.",
                text_color=c.text_secondary,
            )
        else:
            self._theme_status_label.configure(
                text="→ Mode aléatoire : un thème différent est tiré à chaque brouillon.",
                text_color=c.text_muted,
            )

        # Cartes plateformes
        for platform, w in self._platform_widgets.items():
            count, threshold = publish_auto.counter_status(self.app_state, platform)
            remaining = publish_auto.daily_cap_remaining(self.app_state, platform)
            cap = int(self.app_state.get("publish_auto", "daily_cap",
                                         platform, default=0) or 0)

            if threshold > 0:
                w["counter"].configure(
                    text=f"{count}/{threshold}",
                    text_color=c.success if count >= threshold else c.text_primary,
                )
            else:
                w["counter"].configure(text="off", text_color=c.text_muted)

            w["cap"].configure(
                text=f"Plafond du jour : {cap - remaining}/{cap} utilisés",
            )

    # callbacks ---------------------------------------------------------
    def _on_auto_toggle(self) -> None:
        self.app_state.set("publish_auto", "enabled",
                           value=bool(self._auto_enabled_var.get()))
        self.app_state.save()

    def _on_theme_pick(self, key: str) -> None:
        # Écriture dans le state partagé (Supabase) — visible côté Thomas
        publish_auto.set_next_theme(self.app_state, key)
        self._refresh_automation_ui()

    def _on_auto_publish_toggle(self, platform: str) -> None:
        var = self._platform_widgets[platform]["auto_var"]
        self.app_state.set("publish_auto", "auto_publish", platform,
                           value=bool(var.get()))
        self.app_state.save()

    def _trigger_manual(self, platform: str) -> None:
        if not bool(self.app_state.get("publish_auto", "enabled", default=True)):
            self._set_status("⚠ Auto-publish désactivé en haut.")
            return
        if publish_auto.daily_cap_remaining(self.app_state, platform) <= 0:
            self._set_status(f"⚠ Plafond {platform} atteint pour aujourd'hui.")
            return
        btn = self._platform_widgets[platform]["gen_btn"]
        btn.configure(state="disabled")
        self._set_status(f"Génération {platform}…")

        def on_done(ok: bool, msg: str) -> None:
            def apply():
                btn.configure(state="normal")
                self._set_status(msg)
                self._refresh_automation_ui()
                self._refresh_drafts()
            try:
                self.after(0, apply)
            except Exception:
                pass

        publish_auto.trigger_for_platform(
            self.app_state, platform, on_done=on_done,
        )

    # ------------------------------------------------------------------ section 2 — drafts
    def _build_drafts_section(self, parent) -> None:
        c = self.colors
        self._drafts_card = Card(parent, colors=c)
        self._drafts_card.pack(fill="x", pady=(0, T.SPACE_LG))

        # Header de la card
        head = ctk.CTkFrame(self._drafts_card, fg_color="transparent")
        head.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))

        ctk.CTkLabel(
            head, text="📋 Brouillons en attente d'approbation",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(side="left")

        SecondaryButton(head, colors=c, icon="refresh",
                        text="Rafraîchir",
                        command=self._refresh_drafts).pack(side="right")

        self._drafts_status = ctk.CTkLabel(
            self._drafts_card,
            text="Chargement…",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, anchor="w",
        )
        self._drafts_status.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))

        # Container des cartes draft (rempli dynamiquement)
        self._drafts_list = ctk.CTkFrame(self._drafts_card, fg_color="transparent")
        self._drafts_list.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

    def _render_draft_card(self, draft: Draft) -> None:
        """Construit une mini-card pour un draft, avec aperçu + boutons."""
        c = self.colors
        card = ctk.CTkFrame(
            self._drafts_list,
            fg_color=c.bg_alt,
            corner_radius=T.RADIUS_SM,
            border_color=c.border, border_width=1,
        )
        card.pack(fill="x", pady=(0, T.SPACE_SM))

        # Ligne 1 : plateforme + status + date
        line = ctk.CTkFrame(card, fg_color="transparent")
        line.pack(fill="x", padx=T.SPACE_MD, pady=(T.SPACE_SM, T.SPACE_XS))

        ctk.CTkLabel(
            line, text=f"{draft.platform.upper()}",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color=c.accent, anchor="w",
        ).pack(side="left")

        ctk.CTkLabel(
            line, text=f"  ·  {draft.status}",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, anchor="w",
        ).pack(side="left")

        if draft.created_at:
            ctk.CTkLabel(
                line, text=draft.created_at[:10],
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_muted, anchor="e",
            ).pack(side="right")

        # Aperçu du contenu (3 premières lignes max)
        preview = draft.content.strip()
        if len(preview) > 280:
            preview = preview[:277].rstrip() + "…"
        ctk.CTkLabel(
            card, text=preview,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w", justify="left",
            wraplength=720,
        ).pack(fill="x", padx=T.SPACE_MD, pady=(0, T.SPACE_SM))

        # Boutons d'action
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=T.SPACE_MD, pady=(0, T.SPACE_SM))

        PrimaryButton(
            btns, colors=c, icon="broadcast", text="Publier",
            command=lambda d=draft: self._publish_existing_draft(d),
        ).pack(side="right", padx=(T.SPACE_SM, 0))

        SecondaryButton(
            btns, colors=c, icon="trash", text="Archiver",
            command=lambda d=draft: self._archive_draft(d),
        ).pack(side="right")

    # ------------------------------------------------------------------ section 3 — compose libre
    def _build_compose_section(self, parent) -> None:
        c = self.colors
        body = Card(parent, colors=c)
        body.pack(fill="x", pady=(0, T.SPACE_LG))

        ctk.CTkLabel(
            body, text="✏️ Création libre — génère un brouillon et publie en 1 clic",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_XS))

        ctk.CTkLabel(
            body,
            text="L'IA d'AlphaCast reformule selon ton voice profile, "
                 "puis pousse sur la plateforme choisie après publication.",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, anchor="w", justify="left",
            wraplength=720,
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Sélecteur plateforme
        plat_frame = ctk.CTkFrame(body, fg_color="transparent")
        plat_frame.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))
        ctk.CTkLabel(plat_frame, text="Plateforme :",
                     text_color=c.text_secondary,
                     font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL)
                     ).pack(side="left", padx=(0, T.SPACE_SM))
        self._platform_var = ctk.StringVar(value="linkedin")
        ctk.CTkOptionMenu(
            plat_frame,
            values=PLATFORMS,
            variable=self._platform_var,
            fg_color=c.bg_alt,
            button_color=c.accent, button_hover_color=c.accent_hover,
            text_color=c.text_primary,
            corner_radius=T.RADIUS_SM, height=32,
        ).pack(side="left")

        # Zone texte
        ctk.CTkLabel(body, text="Contenu / brief :",
                     text_color=c.text_secondary,
                     font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                     anchor="w",
                     ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_XS))
        self._content_text = ctk.CTkTextbox(
            body, height=180,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            wrap="word",
        )
        self._content_text.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        SecondaryButton(btns, colors=c, icon="copy", text="Copier",
                        command=self._copy).pack(side="right", padx=(T.SPACE_SM, 0))

        self._gen_btn = SecondaryButton(
            btns, colors=c, icon="sparkles", text="Générer un brouillon",
            command=self._compose_generate_only,
        )
        self._gen_btn.pack(side="right", padx=(T.SPACE_SM, 0))

        self._publish_btn = PrimaryButton(
            btns, colors=c, icon="broadcast", text="Générer + Publier",
            command=self._compose_generate_and_publish,
        )
        self._publish_btn.pack(side="right")
        self._publish_btn.configure(state="disabled")
        self._gen_btn.configure(state="disabled")

    # ------------------------------------------------------------------ lifecycle
    def on_show(self) -> None:
        self._refresh_automation_ui()
        self._check_health()  # déclenche aussi _refresh_drafts si OK

    # ------------------------------------------------------------------ helpers
    def _base_url(self) -> str:
        return self.app_state.get("social", "reseaux_api_url",
                                  default="http://localhost:3001").rstrip("/")

    def _token(self) -> str:
        return self.app_state.get("social", "reseaux_jwt", default="") or ""

    def _set_status(self, msg: str) -> None:
        try:
            self._status_var.set(msg)
        except Exception:
            pass

    def _set_drafts_status(self, msg: str) -> None:
        try:
            self._drafts_status.configure(text=msg)
        except Exception:
            pass

    def _toggle_compose_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        try:
            self._publish_btn.configure(state=state)
            self._gen_btn.configure(state=state)
        except Exception:
            pass

    def _clear_drafts_list(self) -> None:
        for w in self._drafts_list.winfo_children():
            w.destroy()

    # ------------------------------------------------------------------ health check
    def _check_health(self) -> None:
        url = self._base_url()

        def worker():
            ok = alphacast.health_check(url)

            def apply():
                if ok:
                    self._health_label.configure(
                        text="✅ AlphaCast : connecté",
                        text_color=self.colors.success,
                    )
                    self._health_detail.configure(
                        text=f"URL : {url} — endpoint /health répond.",
                    )
                    self._toggle_compose_buttons(True)
                    self._refresh_drafts()
                else:
                    self._health_label.configure(
                        text="⚠ AlphaCast : injoignable",
                        text_color=self.colors.warning,
                    )
                    self._health_detail.configure(
                        text=(f"URL testée : {url}\n"
                              "Vérifie que l'URL est correcte dans Réglages, "
                              "ou que Railway est en ligne, puis re-clique sur Tester."),
                    )
                    self._toggle_compose_buttons(False)
                    self._set_drafts_status("Service hors-ligne — brouillons non chargés.")
                    self._clear_drafts_list()
            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ drafts list
    def _refresh_drafts(self) -> None:
        url = self._base_url()
        token = self._token()
        self._set_drafts_status("Chargement…")

        def worker():
            error: str | None = None
            drafts: list[Draft] = []
            try:
                drafts = alphacast.list_drafts(url, token, status="pending_review")
            except AlphaCastError as e:
                error = str(e)
            except Exception as e:  # noqa: BLE001
                error = f"Erreur inattendue : {e}"
                logger.exception("list_drafts")

            def apply():
                self._clear_drafts_list()
                if error:
                    self._set_drafts_status(f"⚠ {error}")
                    return
                if not drafts:
                    self._set_drafts_status(
                        "Aucun brouillon en attente. Génère-en un via Création libre "
                        "ou laisse l'auto-publish tourner depuis tes campagnes."
                    )
                    return
                self._set_drafts_status(f"{len(drafts)} brouillon(s) en attente.")
                for d in drafts:
                    self._render_draft_card(d)
            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ actions sur draft existant
    def _publish_existing_draft(self, draft: Draft) -> None:
        url, token = self._base_url(), self._token()
        self._set_status(f"Publication du brouillon {draft.id[:8]}…")

        def worker():
            try:
                alphacast.publish_draft(url, token, draft.id)
                msg = f"✓ Publié : {draft.platform} ({draft.id[:8]})"
            except AlphaCastError as e:
                msg = f"✗ {e}"
            except Exception as e:  # noqa: BLE001
                msg = f"✗ {e}"
                logger.exception("publish_draft")

            def apply():
                self._set_status(msg)
                self._refresh_drafts()
            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _archive_draft(self, draft: Draft) -> None:
        url, token = self._base_url(), self._token()
        self._set_status(f"Archivage du brouillon {draft.id[:8]}…")

        def worker():
            try:
                alphacast.delete_draft(url, token, draft.id)
                msg = f"✓ Brouillon archivé."
            except AlphaCastError as e:
                msg = f"✗ {e}"
            except Exception as e:  # noqa: BLE001
                msg = f"✗ {e}"
                logger.exception("delete_draft")

            def apply():
                self._set_status(msg)
                self._refresh_drafts()
            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ compose libre
    def _compose_generate_only(self) -> None:
        self._compose_run(publish=False)

    def _compose_generate_and_publish(self) -> None:
        self._compose_run(publish=True)

    def _compose_run(self, *, publish: bool) -> None:
        url, token = self._base_url(), self._token()
        platform = self._platform_var.get()
        content = self._content_text.get("1.0", "end").strip()

        if not content:
            self._set_status("⚠ Contenu vide.")
            return

        self._toggle_compose_buttons(False)
        self._set_status(f"Génération sur {platform}…")

        def worker():
            try:
                if publish:
                    alphacast.generate_and_publish(
                        url, token, platform=platform, content=content,
                    )
                    msg = f"✓ Publié sur {platform}."
                else:
                    draft = alphacast.generate_draft(
                        url, token, platform=platform, content=content,
                    )
                    msg = f"✓ Brouillon créé ({draft.id[:8]}) — visible dans la liste."
            except AlphaCastError as e:
                msg = f"✗ {e}"
            except Exception as e:  # noqa: BLE001
                msg = f"✗ {e}"
                logger.exception("compose_run")

            def apply():
                self._set_status(msg)
                self._toggle_compose_buttons(True)
                self._refresh_drafts()
            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ utility
    def _copy(self) -> None:
        text = self._content_text.get("1.0", "end").strip()
        if not text:
            return
        try:
            import pyperclip
            pyperclip.copy(text)
        except Exception:
            self.clipboard_clear()
            self.clipboard_append(text)
        self._set_status("✓ Copié.")
