"""Vue Publier — détecte ton service Réseaux local et permet de publier."""

from __future__ import annotations

import threading

import customtkinter as ctk
import requests

from .. import theme as T
from ..widgets.components import Card, PrimaryButton, SecondaryButton, ViewHeader
from .base import BaseView


class PublishView(BaseView):
    title = "Publier"
    subtitle = "Pilote ton service Réseaux local — LinkedIn, X, Bluesky, YouTube."

    def build(self) -> None:
        c = self.colors
        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_LG))

        SecondaryButton(header.actions, colors=c, icon="check",
                        text="Tester la connexion",
                        command=self._check_health).pack(side="left")

        # État service
        self._health_card = Card(self, colors=c)
        self._health_card.pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))

        self._health_label = ctk.CTkLabel(
            self._health_card,
            text="Service Réseaux : statut inconnu",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        )
        self._health_label.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))

        self._health_detail = ctk.CTkLabel(
            self._health_card,
            text=(f"URL : {self.app_state.get('social', 'reseaux_api_url', default='http://localhost:3001')}\n"
                  "Cliquez 'Tester la connexion' pour vérifier."),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, anchor="w", justify="left",
        )
        self._health_detail.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        # Body : zone de composition de post
        body = Card(self, colors=c)
        body.pack(fill="both", expand=True, padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))

        ctk.CTkLabel(
            body, text="✏️ Composer un post",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))

        # Sélecteur plateformes (chips)
        plat_frame = ctk.CTkFrame(body, fg_color="transparent")
        plat_frame.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))
        ctk.CTkLabel(plat_frame, text="Plateforme :",
                     text_color=c.text_secondary,
                     font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL)
                     ).pack(side="left", padx=(0, T.SPACE_SM))
        self._platform_var = ctk.StringVar(value="linkedin")
        ctk.CTkOptionMenu(
            plat_frame,
            values=["linkedin", "x", "bluesky", "youtube"],
            variable=self._platform_var,
            fg_color=c.bg_alt,
            button_color=c.accent, button_hover_color=c.accent_hover,
            text_color=c.text_primary,
            corner_radius=T.RADIUS_SM, height=32,
        ).pack(side="left")

        # Zone texte
        ctk.CTkLabel(body, text="Contenu :",
                     text_color=c.text_secondary,
                     font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                     anchor="w",
                     ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_XS))
        self._content_text = ctk.CTkTextbox(
            body, height=200,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            wrap="word",
        )
        self._content_text.pack(fill="both", expand=True,
                                padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Boutons
        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        SecondaryButton(btns, colors=c, icon="copy", text="Copier",
                        command=self._copy).pack(side="right", padx=(T.SPACE_SM, 0))
        self._publish_btn = PrimaryButton(
            btns, colors=c, icon="broadcast", text="Publier",
            command=self._publish,
        )
        self._publish_btn.pack(side="right")
        self._publish_btn.configure(state="disabled")

        # Status
        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
        ).pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

    def on_show(self) -> None:
        # Auto-check au 1er affichage
        self._check_health()

    # ------------------------------------------------------------------
    def _check_health(self) -> None:
        url = self.app_state.get("social", "reseaux_api_url",
                                 default="http://localhost:3001").rstrip("/")

        def worker():
            try:
                r = requests.get(f"{url}/health", timeout=3)
                ok = r.status_code == 200
            except Exception:
                ok = False

            def apply():
                if ok:
                    self._health_label.configure(
                        text="✅ Service Réseaux : connecté",
                        text_color=self.colors.success,
                    )
                    self._health_detail.configure(
                        text=f"URL : {url} — endpoint /health répond.",
                    )
                    self._publish_btn.configure(state="normal")
                else:
                    self._health_label.configure(
                        text="⚠ Service Réseaux : injoignable",
                        text_color=self.colors.warning,
                    )
                    self._health_detail.configure(
                        text=(f"URL testée : {url}\n"
                              "Lance ton service Réseaux séparément (npm run dev) "
                              "puis re-clique sur Tester."),
                    )
                    self._publish_btn.configure(state="disabled")
            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

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
        self._status_var.set("✓ Copié.")

    def _publish(self) -> None:
        url = self.app_state.get("social", "reseaux_api_url",
                                 default="http://localhost:3001").rstrip("/")
        token = self.app_state.get("social", "reseaux_jwt", default="")
        platform = self._platform_var.get()
        content = self._content_text.get("1.0", "end").strip()

        if not content:
            self._status_var.set("⚠ Contenu vide.")
            return
        if not token:
            self._status_var.set("⚠ JWT Réseaux manquant — Réglages > Service Réseaux.")
            return

        self._publish_btn.configure(state="disabled", text="…")
        self._status_var.set(f"Publication sur {platform}…")

        def worker():
            try:
                r = requests.post(
                    f"{url}/api/v1/generate",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={"platform": platform, "content": content},
                    timeout=15,
                )
                r.raise_for_status()
                data = r.json()
                msg = f"✓ Publié : {data.get('id', 'OK')}"
            except Exception as e:
                msg = f"✗ {e}"
            def apply():
                self._status_var.set(msg)
                self._publish_btn.configure(state="normal", text="Publier")
            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()
