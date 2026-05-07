"""Vue Templates — gérer ses templates de mail (sauvegardés dans templates.json)."""

from __future__ import annotations

import json
import customtkinter as ctk

from .. import theme as T
from ..widgets.components import (
    Card,
    PrimaryButton,
    SecondaryButton,
    ViewHeader,
)
from .base import BaseView


class TemplatesView(BaseView):
    title = "Modèles d'emails"
    subtitle = (
        "Tes modèles prêts à réutiliser. "
        "Duplique-les, édite-les, ou crée les tiens."
    )

    def build(self) -> None:
        c = self.colors

        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_MD))

        SecondaryButton(header.actions, colors=c, icon="refresh", text="Recharger",
                        command=self._refresh).pack(side="left", padx=(0, T.SPACE_SM))
        PrimaryButton(header.actions, colors=c, icon="plus", text="Nouveau",
                      command=self._new_template).pack(side="left")

        # Layout 2 colonnes : liste à gauche, éditeur à droite
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))

        # Col gauche : liste
        left = Card(body, colors=c)
        left.pack(side="left", fill="y", padx=(0, T.SPACE_MD))
        left.configure(width=280)
        left.pack_propagate(False)

        ctk.CTkLabel(
            left, text="Modèles disponibles",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))

        ctk.CTkLabel(
            left, text="Cliquer pour éditer, ou en créer un nouveau.",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, anchor="w", justify="left", wraplength=240,
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))

        self._list_scroll = ctk.CTkScrollableFrame(
            left, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        self._list_scroll.pack(fill="both", expand=True,
                               padx=T.SPACE_SM, pady=(0, T.SPACE_LG))

        # Col droite : éditeur
        self._right = Card(body, colors=c)
        self._right.pack(side="left", fill="both", expand=True)

        self._editor_frame = ctk.CTkFrame(self._right, fg_color="transparent")
        self._editor_frame.pack(fill="both", expand=True,
                                padx=T.SPACE_LG, pady=T.SPACE_LG)

        # Champs (créés à la volée par _show_editor)
        self._key_entry: ctk.CTkEntry | None = None
        self._channel_var: ctk.StringVar | None = None
        self._subject_entry: ctk.CTkEntry | None = None
        self._body_text: ctk.CTkTextbox | None = None
        self._current_key: str | None = None
        self._is_user_template: bool = False

        # Status
        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
        ).pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

        self._show_empty()

    def on_show(self) -> None:
        self._refresh()

    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        # Vide la liste
        for w in self._list_scroll.winfo_children():
            w.destroy()
        # Charge templates
        try:
            from triskell_core.prospect.outreach.templates import load_all, USER_TEMPLATES
        except Exception as e:
            self._status_var.set(f"⚠ {e}")
            return

        all_tpl = load_all()
        # Marque ceux qui sont user (= dans USER_TEMPLATES) vs default
        user_keys: set = set()
        if USER_TEMPLATES.exists():
            try:
                u = json.loads(USER_TEMPLATES.read_text(encoding="utf-8"))
                if isinstance(u, dict):
                    user_keys = set(u.keys())
            except Exception:
                pass

        for key, tpl in all_tpl.items():
            self._make_list_item(key, tpl, is_user=(key in user_keys))

        self._status_var.set(f"{len(all_tpl)} modèle(s) — "
                             f"{len(user_keys)} personnel(s), "
                             f"{len(all_tpl) - len(user_keys)} par défaut.")

    def _make_list_item(self, key: str, tpl: dict, is_user: bool) -> None:
        c = self.colors
        item = ctk.CTkFrame(
            self._list_scroll,
            fg_color=c.panel_hover if key == self._current_key else "transparent",
            corner_radius=T.RADIUS_SM,
        )
        item.pack(fill="x", pady=2)

        row = ctk.CTkFrame(item, fg_color="transparent")
        row.pack(fill="x", padx=T.SPACE_SM, pady=T.SPACE_SM)

        icon = "✎" if is_user else "📄"
        label_text = f"{icon} {key}"
        channel = tpl.get("channel", "")
        if channel:
            label_text += f"  ({channel})"

        lbl = ctk.CTkLabel(
            row, text=label_text,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_primary, anchor="w",
        )
        lbl.pack(side="left", fill="x", expand=True)

        for w in (item, row, lbl):
            w.bind("<Button-1>", lambda _e, k=key, t=tpl, u=is_user:
                   self._show_editor(k, t, u))

    # ------------------------------------------------------------------
    def _show_empty(self) -> None:
        for w in self._editor_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self._editor_frame,
            text="← Choisis un modèle à gauche, ou clique « + Nouveau ».",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=self.colors.text_muted,
        ).pack(expand=True)

    def _new_template(self) -> None:
        self._show_editor(
            "",
            {"channel": "email", "subject": "", "body": ""},
            is_user=True,
            is_new=True,
        )

    def _show_editor(self, key: str, tpl: dict, is_user: bool,
                     is_new: bool = False) -> None:
        c = self.colors
        self._current_key = key
        self._is_user_template = is_user

        for w in self._editor_frame.winfo_children():
            w.destroy()

        # Titre
        title_text = "✏️ Nouveau modèle" if is_new else (
            f"✏️ Éditer : {key}" if is_user else f"📄 Lire : {key} (par défaut)"
        )
        ctk.CTkLabel(
            self._editor_frame, text=title_text,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", pady=(0, T.SPACE_MD))

        # Clé
        ctk.CTkLabel(self._editor_frame, text="Clé (identifiant, sans espace)",
                     font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                     text_color=c.text_secondary, anchor="w",
                     ).pack(fill="x", pady=(0, 2))
        self._key_entry = ctk.CTkEntry(
            self._editor_frame,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM, height=30,
            font=(T.FONT_FAMILY_MONO, T.FONT_SIZE_BODY),
        )
        if key:
            self._key_entry.insert(0, key)
        if not is_user and not is_new:
            self._key_entry.configure(state="disabled")
        self._key_entry.pack(fill="x", pady=(0, T.SPACE_SM))

        # Canal
        ctk.CTkLabel(self._editor_frame, text="Canal",
                     font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                     text_color=c.text_secondary, anchor="w",
                     ).pack(fill="x", pady=(0, 2))
        self._channel_var = ctk.StringVar(value=tpl.get("channel", "email"))
        ctk.CTkOptionMenu(
            self._editor_frame,
            values=["email", "linkedin", "instagram_dm", "whatsapp",
                    "facebook_messenger", "twitter_dm"],
            variable=self._channel_var,
            fg_color=c.bg_alt, button_color=c.accent,
            button_hover_color=c.accent_hover, text_color=c.text_primary,
            corner_radius=T.RADIUS_SM, height=30,
        ).pack(fill="x", pady=(0, T.SPACE_SM))

        # Subject
        ctk.CTkLabel(self._editor_frame, text="Objet (vide pour les canaux DM)",
                     font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                     text_color=c.text_secondary, anchor="w",
                     ).pack(fill="x", pady=(0, 2))
        self._subject_entry = ctk.CTkEntry(
            self._editor_frame,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM, height=30,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
        )
        self._subject_entry.insert(0, tpl.get("subject", ""))
        if not is_user and not is_new:
            self._subject_entry.configure(state="disabled")
        self._subject_entry.pack(fill="x", pady=(0, T.SPACE_SM))

        # Body
        ctk.CTkLabel(
            self._editor_frame,
            text="Corps (placeholders : {prenom}, {nom_entreprise}, "
                 "{mon_prenom}, {region_secteur})",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w", justify="left",
        ).pack(fill="x", pady=(0, 2))
        self._body_text = ctk.CTkTextbox(
            self._editor_frame,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            wrap="word",
        )
        self._body_text.insert("1.0", tpl.get("body", ""))
        if not is_user and not is_new:
            self._body_text.configure(state="disabled")
        self._body_text.pack(fill="both", expand=True, pady=(0, T.SPACE_MD))

        # Actions
        actions = ctk.CTkFrame(self._editor_frame, fg_color="transparent")
        actions.pack(fill="x")
        if is_user or is_new:
            PrimaryButton(actions, colors=c, icon="save", text="Enregistrer",
                          command=self._save_current).pack(side="right",
                                                            padx=(T.SPACE_SM, 0))
            if is_user and not is_new:
                SecondaryButton(actions, colors=c, icon="trash", text="Supprimer",
                                command=self._delete_current
                                ).pack(side="right", padx=(T.SPACE_SM, 0))
        else:
            ctk.CTkLabel(
                actions,
                text="Modèle livré par défaut — duplique-le pour le modifier",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_muted,
            ).pack(side="left")
            SecondaryButton(actions, colors=c, icon="duplicate", text="Dupliquer",
                            command=self._duplicate_current
                            ).pack(side="right", padx=(T.SPACE_SM, 0))

    # ------------------------------------------------------------------
    def _save_current(self) -> None:
        key = (self._key_entry.get() or "").strip()
        if not key:
            self._status_var.set("⚠ Clé obligatoire.")
            return
        if " " in key:
            self._status_var.set("⚠ La clé ne doit pas contenir d'espace.")
            return
        body = self._body_text.get("1.0", "end").rstrip()
        if not body:
            self._status_var.set("⚠ Corps vide.")
            return

        try:
            from triskell_core.prospect.outreach.templates import USER_TEMPLATES
            from triskell_core.prospect.core.crm import ensure_dirs
            ensure_dirs()
            current = {}
            if USER_TEMPLATES.exists():
                try:
                    current = json.loads(USER_TEMPLATES.read_text(encoding="utf-8"))
                    if not isinstance(current, dict):
                        current = {}
                except Exception:
                    current = {}
            current[key] = {
                "channel": self._channel_var.get(),
                "subject": self._subject_entry.get(),
                "body": body,
            }
            USER_TEMPLATES.write_text(
                json.dumps(current, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._status_var.set(f"✓ Modèle '{key}' enregistré.")
            self._refresh()
        except Exception as e:
            self._status_var.set(f"✗ Erreur : {e}")

    def _delete_current(self) -> None:
        if not self._current_key or not self._is_user_template:
            return
        try:
            from triskell_core.prospect.outreach.templates import USER_TEMPLATES
            if not USER_TEMPLATES.exists():
                return
            data = json.loads(USER_TEMPLATES.read_text(encoding="utf-8"))
            if isinstance(data, dict) and self._current_key in data:
                del data[self._current_key]
                USER_TEMPLATES.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                self._status_var.set(f"✓ Modèle '{self._current_key}' supprimé.")
                self._current_key = None
                self._show_empty()
                self._refresh()
        except Exception as e:
            self._status_var.set(f"✗ Erreur : {e}")

    def _duplicate_current(self) -> None:
        if not self._current_key:
            return
        # Copie le template actuel dans le formulaire avec une nouvelle clé proposée
        new_key = self._current_key + "_copy"
        tpl = {
            "channel": self._channel_var.get(),
            "subject": self._subject_entry.get(),
            "body": self._body_text.get("1.0", "end").rstrip(),
        }
        self._show_editor(new_key, tpl, is_user=True, is_new=True)
