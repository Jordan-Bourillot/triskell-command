"""Vue Rédaction IA — méga-prompts + génération via Triskell Core.ai."""

from __future__ import annotations

import threading

import customtkinter as ctk

from .. import theme as T
from ..integrations import sales_tunnel as _st
from ..widgets.components import (
    Card,
    PrimaryButton,
    SecondaryButton,
    ViewHeader,
)
from ..widgets.window_icon import apply_window_icon
from .base import BaseView


class ComposeView(BaseView):
    title = "Écrire avec l'IA"
    subtitle = (
        "Tes règles d'écriture, tes assistants IA. "
        "Tu écris vite, et juste."
    )

    def build(self) -> None:
        c = self.colors
        # Header
        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_MD))

        # Sélecteur provider + modèle
        sel_block = ctk.CTkFrame(header.actions, fg_color="transparent")
        sel_block.pack(side="left", padx=(0, T.SPACE_SM))

        self._provider_var = ctk.StringVar(
            value=self.app_state.get("ai", "selected_provider", default="anthropic")
        )
        self._model_var = ctk.StringVar(
            value=self.app_state.get("ai", "selected_model", default="claude-sonnet-4-5")
        )

        # Provider dropdown
        try:
            from triskell_core.ai.providers import PROVIDERS
            providers = list(PROVIDERS.keys())
        except ImportError:
            providers = ["anthropic"]
        ctk.CTkOptionMenu(
            sel_block, values=providers, variable=self._provider_var,
            fg_color=c.bg_alt, button_color=c.accent,
            button_hover_color=c.accent_hover, text_color=c.text_primary,
            corner_radius=T.RADIUS_SM, width=140, height=32,
            command=self._on_provider_change,
        ).pack(side="left", padx=(0, T.SPACE_SM))

        # Modèle entry
        ctk.CTkEntry(
            sel_block, textvariable=self._model_var,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_MONO, T.FONT_SIZE_BODY),
            width=180, height=32,
        ).pack(side="left", padx=(0, T.SPACE_SM))

        SecondaryButton(header.actions, colors=c, icon="copy", text="Copier prompt",
                        command=self._copy_prompt).pack(side="left", padx=(0, T.SPACE_SM))
        if _st.is_available():
            SecondaryButton(
                header.actions, colors=c, icon="target",
                text="Charger un modèle",
                command=self._open_st_dialog,
            ).pack(side="left", padx=(0, T.SPACE_SM))
        self._send_btn = PrimaryButton(
            header.actions, colors=c, icon="sparkle", text="Générer",
            command=self._send,
        )
        self._send_btn.pack(side="left")

        # Body : 2 colonnes
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))

        # Col gauche : méga-prompts
        left = Card(body, colors=c)
        left.pack(side="left", fill="y", padx=(0, T.SPACE_MD))
        left.configure(width=320)
        left.pack_propagate(False)

        ctk.CTkLabel(
            left, text="Règles d'écriture",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_XS))
        ctk.CTkLabel(
            left, text="Coche celles à appliquer pour ce mail",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, anchor="w", justify="left", wraplength=280,
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))

        self._mp_scroll = ctk.CTkScrollableFrame(
            left, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        self._mp_scroll.pack(fill="both", expand=True, padx=T.SPACE_SM, pady=(0, T.SPACE_LG))

        self._mp_vars: dict[str, ctk.BooleanVar] = {}
        self._mp_metas: dict[str, dict] = {}
        try:
            from triskell_core.ai.library import load_packaged_library
            library = load_packaged_library()
        except Exception:
            library = []
        defaults = self.app_state.get("ai", "default_mega_prompts", default=[]) or []
        for mp in library:
            mp_id = mp.get("id", "?")
            name = mp.get("name", "Sans nom")
            self._mp_metas[mp_id] = mp
            var = ctk.BooleanVar(value=mp_id in defaults)
            self._mp_vars[mp_id] = var
            cb = ctk.CTkCheckBox(
                self._mp_scroll,
                text=f"[{mp_id}] {name}",
                variable=var,
                fg_color=c.accent, hover_color=c.accent_hover,
                text_color=c.text_primary, border_color=c.border_strong,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                checkbox_height=18, checkbox_width=18,
            )
            cb.pack(fill="x", padx=T.SPACE_SM, pady=2, anchor="w")

        # Col droite : prompt + résultat
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        prompt_card = Card(right, colors=c)
        prompt_card.pack(fill="x", pady=(0, T.SPACE_MD))
        ctk.CTkLabel(
            prompt_card, text="Ton prompt",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))
        self._prompt_text = ctk.CTkTextbox(
            prompt_card, height=140,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            wrap="word",
        )
        self._prompt_text.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        result_card = Card(right, colors=c)
        result_card.pack(fill="both", expand=True)
        result_header = ctk.CTkFrame(result_card, fg_color="transparent")
        result_header.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))
        ctk.CTkLabel(
            result_header, text="Réponse IA",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(side="left", fill="x", expand=True)
        SecondaryButton(
            result_header, colors=c, icon="copy", text="Copier",
            command=self._copy_result, width=110,
        ).pack(side="right")
        self._result_text = ctk.CTkTextbox(
            result_card,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            wrap="word",
        )
        self._result_text.pack(fill="both", expand=True,
                               padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        # Status
        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
        ).pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

    # ------------------------------------------------------------------
    def _on_provider_change(self, value: str) -> None:
        # Met à jour le model par défaut selon le provider
        try:
            from triskell_core.ai.providers import PROVIDERS
            models = PROVIDERS.get(value, {}).get("models", [])
            if models:
                self._model_var.set(models[0])
        except Exception:
            pass

    def _selected_megas(self) -> list[dict]:
        return [self._mp_metas[mp_id]
                for mp_id, var in self._mp_vars.items() if var.get()]

    def _build_full_prompt(self) -> str:
        from triskell_core.ai.builder import build_ultimate_prompt
        user = self._prompt_text.get("1.0", "end").strip()
        if not user:
            return ""
        return build_ultimate_prompt(user, self._selected_megas())

    def _copy_prompt(self) -> None:
        full = self._build_full_prompt()
        if not full:
            self._status_var.set("⚠ Prompt vide.")
            return
        try:
            import pyperclip
            pyperclip.copy(full)
            self._status_var.set("✓ Prompt copié dans le presse-papiers.")
        except Exception:
            self.clipboard_clear()
            self.clipboard_append(full)
            self._status_var.set("✓ Prompt copié.")

    def _copy_result(self) -> None:
        text = self._result_text.get("1.0", "end").strip()
        if not text:
            return
        try:
            import pyperclip
            pyperclip.copy(text)
        except Exception:
            self.clipboard_clear()
            self.clipboard_append(text)
        self._status_var.set("✓ Réponse copiée.")

    def _open_st_dialog(self) -> None:
        SalesTunnelTemplateDialog(self, on_pick=self._inject_template)

    def _inject_template(self, tpl: dict) -> None:
        """Insère un modèle Sales Tunnel dans la zone prompt avec consigne IA."""
        instruction = (
            f"Voici un modèle de prospection pour {tpl['client']} "
            f"(produit : {tpl['product']}, canal : {tpl['channel']}).\n\n"
            f"Personnalise-le pour un prospect précis (à toi de me dire qui), "
            f"en gardant le ton chaleureux et professionnel. "
            f"Remplace les placeholders {{prenom}}, {{nom_entreprise}}, etc. "
            f"si je te donne les valeurs, sinon laisse-les tels quels.\n\n"
        )
        if tpl.get("subject"):
            instruction += f"OBJET ORIGINAL : {tpl['subject']}\n\n"
        instruction += "MODÈLE ORIGINAL :\n" + tpl.get("body", "")

        self._prompt_text.delete("1.0", "end")
        self._prompt_text.insert("1.0", instruction)
        self._status_var.set(
            f"✓ Modèle chargé : {tpl['product']} → {tpl['client']} → {tpl['channel']}"
        )

    def _send(self) -> None:
        full = self._build_full_prompt()
        if not full:
            self._status_var.set("⚠ Prompt vide — saisis quelque chose.")
            return

        provider = self._provider_var.get()
        model = self._model_var.get()
        api_keys = self.app_state.get("ai", "api_keys", default={}) or {}

        if not api_keys.get(provider):
            self._status_var.set(
                f"⚠ Clé API manquante pour {provider} — Réglages > Providers IA"
            )
            return

        # Persiste la sélection
        self.app_state.set("ai", "selected_provider", value=provider)
        self.app_state.set("ai", "selected_model", value=model)
        self.app_state.save()

        self._send_btn.configure(state="disabled", text="…")
        self._status_var.set(f"Envoi à {provider} ({model})…")
        self._result_text.delete("1.0", "end")

        def worker():
            try:
                from triskell_core.ai.providers import send_to_provider
                response = send_to_provider(provider, model, full, api_keys)
                def apply():
                    self._result_text.insert("1.0", response)
                    self._status_var.set(
                        f"✓ Réponse reçue de {provider} ({len(response)} chars)"
                    )
                    self._send_btn.configure(state="normal", text="Générer")
                self.after(0, apply)
            except Exception as e:
                err = str(e)
                def apply():
                    self._status_var.set(f"✗ {err[:200]}")
                    self._send_btn.configure(state="normal", text="Générer")
                self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()


# ----------------------------------------------------------------------
# Dialog : sélecteur en cascade Produit → Cible → Canal
# ----------------------------------------------------------------------
class SalesTunnelTemplateDialog(ctk.CTkToplevel):
    def __init__(self, master, *, on_pick):
        super().__init__(master)
        self._on_pick = on_pick
        self._colors = master.colors
        c = self._colors

        self.title("Importer un modèle de mail")
        self.geometry("620x520")
        self.minsize(560, 460)
        self.configure(fg_color=c.bg)
        self.transient(master.winfo_toplevel())
        apply_window_icon(self)
        self.after(100, lambda: self.lift())

        ctk.CTkLabel(
            self, text="Choisir un modèle",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TITLE, "bold"),
            text_color=c.text_primary,
        ).pack(anchor="w", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))

        ctk.CTkLabel(
            self,
            text="Sélectionne en cascade : produit → cible → canal.\n"
                 "Le modèle sera inséré dans la zone d'écriture avec une "
                 "consigne pour que l'IA le personnalise.",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, justify="left", wraplength=560,
        ).pack(anchor="w", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Cascade
        self._product_var = ctk.StringVar()
        self._client_var = ctk.StringVar()
        self._channel_var = ctk.StringVar()

        # Cache produits et leurs labels
        self._products = _st.list_products()
        product_labels = [label for _, label in self._products]

        self._make_select("Produit", product_labels, self._product_var,
                          self._on_product_change)
        self._client_menu = self._make_select("Client cible", [],
                                              self._client_var, self._on_client_change)
        self._channel_menu = self._make_select("Canal", [],
                                               self._channel_var, self._on_channel_change)

        # Preview
        self._preview = ctk.CTkTextbox(
            self,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            wrap="word",
        )
        self._preview.pack(fill="both", expand=True,
                           padx=T.SPACE_LG, pady=(T.SPACE_SM, T.SPACE_MD))
        self._preview.insert("1.0", "(l'aperçu du modèle apparaîtra ici)")

        # Bottom
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        SecondaryButton(bottom, colors=c, icon="close", text="Annuler",
                        command=self.destroy).pack(side="right", padx=(T.SPACE_SM, 0))
        self._import_btn = PrimaryButton(
            bottom, colors=c, icon="download", text="Importer",
            command=self._do_import,
        )
        self._import_btn.pack(side="right")
        self._import_btn.configure(state="disabled")

        # Sélection initiale
        if product_labels:
            self._product_var.set(product_labels[0])
            self._on_product_change(product_labels[0])

    def _make_select(self, label, values, var, on_change):
        c = self._colors
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))
        ctk.CTkLabel(
            row, text=label, font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w", width=120,
        ).pack(side="left", padx=(0, T.SPACE_SM))
        menu = ctk.CTkOptionMenu(
            row,
            values=values or ["—"],
            variable=var,
            fg_color=c.bg_alt, button_color=c.accent,
            button_hover_color=c.accent_hover, text_color=c.text_primary,
            corner_radius=T.RADIUS_SM, height=30,
            command=on_change,
        )
        menu.pack(side="left", fill="x", expand=True)
        return menu

    def _label_to_key(self, items: list[tuple[str, str]], label: str) -> str:
        for k, l in items:
            if l == label:
                return k
        return ""

    def _on_product_change(self, label: str) -> None:
        product_key = self._label_to_key(self._products, label)
        clients = _st.list_clients(product_key)
        labels = [l for _, l in clients]
        self._client_menu.configure(values=labels or ["—"])
        if labels:
            self._client_var.set(labels[0])
            self._on_client_change(labels[0])
        else:
            self._client_var.set("—")
            self._channel_menu.configure(values=["—"])
            self._channel_var.set("—")

    def _on_client_change(self, label: str) -> None:
        product_key = self._label_to_key(self._products, self._product_var.get())
        clients = _st.list_clients(product_key)
        client_key = self._label_to_key(clients, label)
        channels = _st.list_channels(product_key, client_key)
        labels = [l for _, l in channels]
        self._channel_menu.configure(values=labels or ["—"])
        if labels:
            self._channel_var.set(labels[0])
            self._on_channel_change(labels[0])
        else:
            self._channel_var.set("—")
            self._preview.delete("1.0", "end")
            self._import_btn.configure(state="disabled")

    def _on_channel_change(self, label: str) -> None:
        product_key = self._label_to_key(self._products, self._product_var.get())
        clients = _st.list_clients(product_key)
        client_key = self._label_to_key(clients, self._client_var.get())
        channels = _st.list_channels(product_key, client_key)
        channel_key = self._label_to_key(channels, label)
        tpl = _st.get_template(product_key, client_key, channel_key)
        if not tpl:
            self._preview.delete("1.0", "end")
            self._import_btn.configure(state="disabled")
            return
        text = ""
        if tpl.get("subject"):
            text += f"OBJET : {tpl['subject']}\n\n"
        text += tpl.get("body", "")
        self._preview.delete("1.0", "end")
        self._preview.insert("1.0", text)
        self._import_btn.configure(state="normal")
        self._current_tpl = tpl

    def _do_import(self) -> None:
        if hasattr(self, "_current_tpl"):
            self._on_pick(self._current_tpl)
        self.destroy()
