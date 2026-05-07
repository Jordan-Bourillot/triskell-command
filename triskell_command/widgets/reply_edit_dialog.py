"""Dialog d'édition d'un draft de réponse — subject + body."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from .. import theme as T
from .components import PrimaryButton, SecondaryButton


class ReplyEditDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        subject: str,
        body: str,
        on_save: Callable[[str, str], None],
    ):
        super().__init__(master)
        self._colors = colors
        self._on_save = on_save

        self.title("Modifier la réponse")
        self.geometry("720x520")
        self.configure(fg_color=colors.bg)
        try:
            self.grab_set()
            self.transient(master)
        except Exception:
            pass

        c = colors
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=T.SPACE_2XL, pady=T.SPACE_2XL)

        ctk.CTkLabel(
            wrap, text="Modifier la réponse",
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_TITLE, "bold"),
            text_color=c.text_primary,
        ).pack(anchor="w")
        ctk.CTkLabel(
            wrap,
            text="Édite le brouillon. Si tu modifies, le mode bascule en "
                 "Validation manuelle (pas d'envoi auto).",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, wraplength=640, justify="left",
        ).pack(anchor="w", pady=(2, T.SPACE_LG))

        # Subject
        ctk.CTkLabel(
            wrap, text="OBJET",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w")
        self._subject_entry = ctk.CTkEntry(
            wrap, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=38,
        )
        self._subject_entry.pack(fill="x", pady=(2, T.SPACE_MD))
        self._subject_entry.insert(0, subject or "")

        # Body
        ctk.CTkLabel(
            wrap, text="CORPS",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w")
        self._body = ctk.CTkTextbox(
            wrap, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=300, wrap="word",
        )
        self._body.pack(fill="both", expand=True, pady=(2, T.SPACE_LG))
        self._body.insert("1.0", body or "")

        actions = ctk.CTkFrame(wrap, fg_color="transparent")
        actions.pack(fill="x")
        SecondaryButton(actions, colors=c, text="Annuler",
                         command=self.destroy).pack(side="left")
        PrimaryButton(actions, colors=c, text="Enregistrer",
                       command=self._save).pack(side="right")

    def _save(self) -> None:
        subject = self._subject_entry.get().strip()
        body = self._body.get("1.0", "end").strip()
        try:
            self._on_save(subject, body)
        finally:
            self.destroy()
