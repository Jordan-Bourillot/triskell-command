"""Dialog « Allô Claude » — demande à Claude la prochaine action à faire,
ou pose-lui une question libre.

Usage :
    ClaudeDialog(parent, colors=..., app_state=..., on_navigate=...)
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import customtkinter as ctk

from .. import theme as T
from ..integrations import claude_advisor
from .components import PrimaryButton, SecondaryButton

logger = logging.getLogger(__name__)


URGENCY_COLORS = {
    "low":    "text_muted",
    "medium": "warning",
    "high":   "danger",
}
URGENCY_LABELS = {
    "low":    "tranquille",
    "medium": "à faire dans la journée",
    "high":   "urgent",
}


class ClaudeDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        app_state,
        on_navigate: Callable[[str], None] | None = None,
        prefilled_advice: Optional[dict] = None,
    ):
        super().__init__(master)
        self._colors = colors
        self._app_state = app_state
        self._on_navigate = on_navigate

        self.title("Allô Claude")
        self.geometry("720x600")
        self.minsize(620, 480)
        self.configure(fg_color=colors.bg)
        try:
            self.grab_set()
            self.transient(master)
        except Exception:
            pass
        try:
            self._set_window_icon()
        except Exception:
            pass

        c = colors
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ---- Header ----
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew",
                     padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_SM))

        bar = ctk.CTkFrame(header, fg_color=c.accent, width=32, height=3,
                            corner_radius=2)
        bar.pack(anchor="w", pady=(0, T.SPACE_XS))
        bar.pack_propagate(False)

        ctk.CTkLabel(
            header, text="ALLÔ CLAUDE",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w")

        ctk.CTkLabel(
            header, text="Quelle est ma prochaine action ?",
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_TITLE, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_XS, 0))

        # ---- Body scrollable (avis Claude) ----
        body_wrap = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        body_wrap.grid(row=1, column=0, sticky="nsew",
                        padx=T.SPACE_2XL, pady=(T.SPACE_SM, T.SPACE_SM))
        self._body_wrap = body_wrap

        # ---- Footer : champ question + boutons ----
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew",
                     padx=T.SPACE_2XL, pady=(T.SPACE_SM, T.SPACE_LG))

        ctk.CTkLabel(
            footer, text="OU POSE-LUI UNE QUESTION LIBRE",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w")

        question_row = ctk.CTkFrame(footer, fg_color="transparent")
        question_row.pack(fill="x", pady=(T.SPACE_XS, T.SPACE_SM))

        self._question_entry = ctk.CTkEntry(
            question_row, fg_color=c.panel, border_color=c.border,
            border_width=1, text_color=c.text_primary, height=38,
            placeholder_text="ex: « comment je peux booster les "
                              "réponses cette semaine ? »",
        )
        self._question_entry.pack(side="left", fill="x", expand=True,
                                    padx=(0, T.SPACE_SM))
        self._question_entry.bind("<Return>", lambda _e: self._ask(self._question_entry.get()))

        PrimaryButton(
            question_row, colors=c, text="Demander",
            command=lambda: self._ask(self._question_entry.get()),
        ).pack(side="left")

        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.pack(fill="x")
        SecondaryButton(actions, colors=c, text="Fermer",
                         command=self.destroy).pack(side="left")
        SecondaryButton(actions, colors=c, icon="refresh",
                         text="Reposer la question (analyse à nouveau)",
                         command=lambda: self._ask(None)).pack(side="right")

        # Premier rendu
        if prefilled_advice:
            self._render_advice(prefilled_advice)
        else:
            self._render_loading()
            self._ask(None)

    # ------------------------------------------------------------------
    def _render_loading(self) -> None:
        for w in self._body_wrap.winfo_children():
            w.destroy()
        c = self._colors
        ctk.CTkLabel(
            self._body_wrap, text="…",
            font=(T.FONT_FAMILY_DISPLAY, 32, "bold"),
            text_color=c.accent,
        ).pack(pady=(T.SPACE_2XL, T.SPACE_SM))
        ctk.CTkLabel(
            self._body_wrap, text="Claude analyse l'état de ton app…",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_secondary,
        ).pack(pady=(0, T.SPACE_LG))

    def _ask(self, user_question: Optional[str]) -> None:
        question = (user_question or "").strip() or None
        self._render_loading()
        # On lance l'appel dans un thread pour ne pas bloquer l'UI
        def worker():
            advice = claude_advisor.ask_claude(
                self._app_state,
                mode="interactive",
                user_question=question,
            )
            try:
                self.after(0, lambda a=advice: self._render_advice(a))
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True,
                         name="ClaudeAdvisor").start()

    def _render_advice(self, advice: dict) -> None:
        for w in self._body_wrap.winfo_children():
            w.destroy()
        c = self._colors

        if not advice.get("ok"):
            err = advice.get("error", "")
            if err == "ai_not_configured":
                msg = ("Renseigne ta clé Anthropic (ou un autre fournisseur "
                        "IA) dans Réglages → Services IA, puis reviens "
                        "demander à Claude.")
            else:
                msg = f"Claude n'a pas pu répondre : {err}"
            ctk.CTkLabel(
                self._body_wrap, text=msg,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
                text_color=c.danger, anchor="w",
                justify="left", wraplength=620,
            ).pack(fill="x", padx=T.SPACE_LG, pady=T.SPACE_LG)
            return

        urgency = advice.get("urgency", "low")
        urg_color_attr = URGENCY_COLORS.get(urgency, "text_muted")
        urg_label = URGENCY_LABELS.get(urgency, urgency)
        try:
            urg_color = getattr(c, urg_color_attr)
        except AttributeError:
            urg_color = c.text_muted

        # Pastille urgence
        pill_row = ctk.CTkFrame(self._body_wrap, fg_color="transparent")
        pill_row.pack(fill="x", pady=(T.SPACE_LG, T.SPACE_SM))
        ctk.CTkLabel(
            pill_row, text=f"NIVEAU : {urg_label.upper()}",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=urg_color, fg_color=c.panel,
            corner_radius=T.RADIUS_PILL,
            padx=10, pady=4,
        ).pack(side="left")

        # Titre (headline)
        headline = advice.get("headline", "")
        if headline:
            ctk.CTkLabel(
                self._body_wrap, text=headline,
                font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_HEADING, "bold"),
                text_color=c.text_primary, anchor="w",
                justify="left", wraplength=620,
            ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_SM, T.SPACE_SM))

        # Corps du conseil
        body_text = advice.get("advice", "")
        if body_text:
            ctk.CTkLabel(
                self._body_wrap, text=body_text,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
                text_color=c.text_secondary, anchor="w",
                justify="left", wraplength=620,
            ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        # CTA "Aller voir la vue suggérée"
        view = advice.get("suggested_view")
        label = advice.get("suggested_action_label") or "Y aller"
        if view and self._on_navigate:
            cta_row = ctk.CTkFrame(self._body_wrap, fg_color="transparent")
            cta_row.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
            PrimaryButton(
                cta_row, colors=c, text=label,
                command=lambda v=view: self._goto(v),
            ).pack(side="left")

    def _goto(self, view_id: str) -> None:
        if self._on_navigate is None:
            return
        try:
            self._on_navigate(view_id)
        except Exception as exc:
            logger.debug("claude goto: %s", exc)

    def _set_window_icon(self) -> None:
        import sys
        from pathlib import Path
        meipass = getattr(sys, "_MEIPASS", None)
        candidates = []
        if meipass:
            candidates.append(Path(meipass) / "assets" / "triskell.ico")
        here = Path(__file__).resolve()
        for parent in (here.parent.parent.parent,
                        here.parent.parent.parent.parent):
            candidates.append(parent / "assets" / "triskell.ico")
        for p in candidates:
            if p.exists():
                self.iconbitmap(str(p))
                return
