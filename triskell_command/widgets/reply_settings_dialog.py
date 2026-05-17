"""Dialog de configuration des modes de réponse auto.

Permet à Jordan de choisir, par catégorie de réponse :
  - manual     → validation manuelle (rien ne part sans clic)
  - delay_30m  → envoi auto 30 min après génération
  - instant    → envoi auto immédiat dès détection

Plus l'édition des templates par catégorie et des liens (Stripe par produit).
Tout est stocké dans shared_settings 'reply_responder' Supabase
→ synchro automatique entre Jordan et Thomas.
"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from .. import theme as T
from ..integrations import reply_responder
from .components import PrimaryButton, SecondaryButton


CATEGORY_ORDER = ("interested", "not_now", "no", "unsubscribe", "unknown")
CATEGORY_LABELS = {
    "interested":   "Intéressé",
    "not_now":      "Pas maintenant",
    "no":           "Refus",
    "unsubscribe":  "Désinscription",
    "unknown":      "À trier",
}
MODE_LABELS = {
    "manual":     "Validation manuelle",
    "delay_30m":  "Auto après 30 min",
    "instant":    "Auto immédiat",
}


class ReplySettingsDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        client,
        on_done: Callable[[], None] | None = None,
    ):
        super().__init__(master)
        self._colors = colors
        self._client = client
        self._on_done = on_done

        self.title("Niveau d'automatisation des réponses")
        self.geometry("780x720")
        self.configure(fg_color=colors.bg)
        try:
            self.grab_set()
            self.transient(master)
        except Exception:
            pass

        # Charge la config
        self._config = reply_responder.load_config(client)
        self._mode_vars: dict[str, ctk.StringVar] = {}
        self._template_boxes: dict[str, ctk.CTkTextbox] = {}
        self._link_entries: dict[str, ctk.CTkEntry] = {}
        self._product_entries: dict[str, ctk.CTkEntry] = {}

        c = colors
        outer = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        outer.pack(fill="both", expand=True, padx=T.SPACE_LG, pady=T.SPACE_LG)

        ctk.CTkLabel(
            outer, text="Niveau d'automatisation des réponses",
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_TITLE, "bold"),
            text_color=c.text_primary,
        ).pack(anchor="w")
        ctk.CTkLabel(
            outer,
            text="Choisis pour chaque type de réponse comment l'app doit "
                 "agir : valider à la main, partir tout seul après un délai, "
                 "ou partir tout de suite. Le réglage est partagé "
                 "automatiquement entre toi et Thomas.",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, wraplength=700, justify="left",
        ).pack(anchor="w", pady=(2, T.SPACE_LG))

        # Section : niveau par type de réponse
        self._section(outer, "PAR TYPE DE RÉPONSE")
        for cat in CATEGORY_ORDER:
            self._mode_row(outer, cat)

        # Section : modèles de mails
        self._section(
            outer,
            "MODÈLES DE MAILS  (tu peux utiliser : {name} = nom du prospect, "
            "{product_link} = lien produit, {product_name} = nom produit, "
            "{signature} = ta signature)"
        )
        for cat in CATEGORY_ORDER:
            self._template_block(outer, cat)

        # Section : liens
        self._section(outer, "LIENS À INSÉRER DANS LES MAILS")
        self._link_field(outer, "default_product_key",
                          "Produit mis en avant par défaut",
                          placeholder="ex: obelisk")

        # Liste des produits (raccourci → URL d'achat)
        ctk.CTkLabel(
            outer, text="LIENS D'ACHAT PAR PRODUIT  (raccourci → URL)",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_MD, T.SPACE_XS))
        existing_products = (self._config.get("links") or {}).get("products") or {}
        # On affiche les existants + 3 lignes vides pour ajouter
        rows_keys = list(existing_products.keys()) + ["", "", ""]
        for key in rows_keys:
            self._product_row(outer, key, existing_products.get(key, ""))

        # Section : signature
        self._section(outer, "TA SIGNATURE")
        sig_box = ctk.CTkTextbox(
            outer, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=80, wrap="word",
        )
        sig_box.pack(fill="x", pady=(T.SPACE_XS, T.SPACE_MD))
        sig_box.insert("1.0", self._config.get("signature") or "")
        self._signature_box = sig_box

        # Actions
        actions = ctk.CTkFrame(outer, fg_color="transparent")
        actions.pack(fill="x", pady=(T.SPACE_LG, 0))
        SecondaryButton(actions, colors=c, text="Annuler",
                         command=self.destroy).pack(side="left")
        PrimaryButton(actions, colors=c, text="Enregistrer",
                       command=self._save).pack(side="right")

    # ------------------------------------------------------------------
    def _section(self, master, label: str) -> None:
        c = self._colors
        ctk.CTkLabel(
            master, text=label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.accent, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_LG, T.SPACE_SM))

    def _mode_row(self, master, cat: str) -> None:
        c = self._colors
        row = ctk.CTkFrame(master, fg_color="transparent")
        row.pack(fill="x", pady=(0, T.SPACE_XS))
        ctk.CTkLabel(
            row, text=CATEGORY_LABELS.get(cat, cat),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_primary, anchor="w", width=180,
        ).pack(side="left")
        current = (self._config.get("per_category") or {}).get(cat, "manual")
        var = ctk.StringVar(value=MODE_LABELS.get(current, "Validation manuelle"))
        self._mode_vars[cat] = var
        opt = ctk.CTkOptionMenu(
            row, variable=var,
            values=list(MODE_LABELS.values()),
            fg_color=c.panel, button_color=c.panel, button_hover_color=c.panel_hover,
            dropdown_fg_color=c.panel,
            text_color=c.text_primary,
        )
        opt.pack(side="left", fill="x", expand=True, padx=(T.SPACE_MD, 0))

    def _template_block(self, master, key: str,
                         *, label: str | None = None) -> None:
        c = self._colors
        templates = self._config.get("templates") or {}
        ctk.CTkLabel(
            master, text=label or CATEGORY_LABELS.get(key, key),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, T.SPACE_XS))
        box = ctk.CTkTextbox(
            master, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=100, wrap="word",
        )
        box.pack(fill="x")
        box.insert("1.0", templates.get(key, "") or "")
        self._template_boxes[key] = box

    def _link_field(self, master, key: str, label: str,
                     *, placeholder: str = "") -> None:
        c = self._colors
        ctk.CTkLabel(
            master, text=label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, T.SPACE_XS))
        entry = ctk.CTkEntry(
            master, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=36,
            placeholder_text=placeholder,
        )
        entry.pack(fill="x")
        existing = (self._config.get("links") or {}).get(key, "") or ""
        if existing:
            entry.insert(0, existing)
        self._link_entries[key] = entry

    def _product_row(self, master, key: str, url: str) -> None:
        c = self._colors
        row = ctk.CTkFrame(master, fg_color="transparent")
        row.pack(fill="x", pady=(0, T.SPACE_XS))
        key_e = ctk.CTkEntry(
            row, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=32, width=160,
            placeholder_text="ex: obelisk",
        )
        key_e.pack(side="left", padx=(0, T.SPACE_SM))
        if key:
            key_e.insert(0, key)
        url_e = ctk.CTkEntry(
            row, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=32,
            placeholder_text="https://...",
        )
        url_e.pack(side="left", fill="x", expand=True)
        if url:
            url_e.insert(0, url)
        # Stocke avec une clé unique (objet entry, par sécurité)
        self._product_entries[id(key_e)] = (key_e, url_e)  # type: ignore

    # ------------------------------------------------------------------
    def _save(self) -> None:
        # 1) Modes par catégorie
        per_cat = {}
        # Mapping label → key
        label_to_key = {v: k for k, v in MODE_LABELS.items()}
        for cat, var in self._mode_vars.items():
            per_cat[cat] = label_to_key.get(var.get(), "manual")
        self._config["per_category"] = per_cat

        # 2) Templates
        templates = self._config.get("templates") or {}
        for key, box in self._template_boxes.items():
            templates[key] = box.get("1.0", "end").rstrip()
        self._config["templates"] = templates

        # 3) Liens (top-level)
        links = self._config.get("links") or {}
        for key, entry in self._link_entries.items():
            links[key] = entry.get().strip()

        # 4) Produits (clé → URL)
        products: dict[str, str] = {}
        for _, (k_e, u_e) in self._product_entries.items():
            k = k_e.get().strip()
            u = u_e.get().strip()
            if k and u:
                products[k] = u
        links["products"] = products
        self._config["links"] = links

        # 5) Signature
        self._config["signature"] = self._signature_box.get("1.0", "end").rstrip()

        # 6) Persiste
        try:
            reply_responder.save_config(self._client, self._config)
        except Exception as exc:
            # Affichage minimal d'erreur — le dialog reste ouvert
            from tkinter import messagebox
            messagebox.showerror("Erreur", f"Impossible de sauver : {exc}")
            return

        if self._on_done:
            try:
                self._on_done()
            except Exception:
                pass
        self.destroy()
