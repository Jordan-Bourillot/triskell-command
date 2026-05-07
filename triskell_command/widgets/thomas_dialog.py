"""Dialog de chat 1-à-1 Jordan ↔ Thomas.

- Liste scrollable des messages : bulles à gauche pour ce qu'on a reçu,
  à droite pour ce qu'on a envoyé.
- Champ de saisie + bouton « Envoyer » (Entrée envoie).
- À l'ouverture : marque tous les reçus comme lus, charge l'historique.
- Refresh auto toutes les 5 s tant que le dialog est ouvert (pour voir
  arriver les nouveaux messages sans devoir fermer/rouvrir).

Si Supabase n'est pas configuré ou si l'autre user n'existe pas, on
affiche un état d'attente clair plutôt qu'un dialog vide.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Callable, Optional

import customtkinter as ctk

from .. import theme as T
from ..integrations import messages as M
from .components import PrimaryButton, SecondaryButton

logger = logging.getLogger(__name__)


REFRESH_MS = 5_000
TYPING_POLL_MS = 3_000              # poll typing_status toutes les 3 s
TYPING_EMIT_THROTTLE_S = 2.0        # max 1 set_typing(True) toutes les 2 s


class ThomasDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        app_state,
        on_closed: Optional[Callable[[], None]] = None,
    ):
        super().__init__(master)
        self._colors = colors
        self._app_state = app_state
        self._on_closed = on_closed
        self._destroyed = False
        self._refresh_job: Optional[str] = None
        self._typing_job: Optional[str] = None
        self._last_typing_emit: float = 0.0
        self._peer_typing: bool = False
        self._known_message_ids: set[str] = set()

        # Détermine l'autre user pour le titre
        peer = M.other_user() or {}
        peer_name = peer.get("display_name") or "ton équipier"
        self._peer_name = peer_name

        self.title(f"Chat — {peer_name}")
        self.geometry("560x680")
        self.minsize(440, 480)
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
        self.protocol("WM_DELETE_WINDOW", self._handle_close)

        c = colors
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ---- Header ----
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew",
                     padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_SM))

        bar = ctk.CTkFrame(header, fg_color=c.success, width=32, height=3,
                            corner_radius=2)
        bar.pack(anchor="w", pady=(0, T.SPACE_XS))
        bar.pack_propagate(False)

        ctk.CTkLabel(
            header, text="CHAT",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w")
        ctk.CTkLabel(
            header, text=peer_name,
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_TITLE, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_XS, 0))

        # ---- Body : liste de messages ----
        self._body = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        self._body.grid(row=1, column=0, sticky="nsew",
                         padx=T.SPACE_LG, pady=(T.SPACE_SM, 0))

        # ---- Indicateur "X est en train d'écrire" ----
        self._typing_label = ctk.CTkLabel(
            self, text="",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "italic"),
            text_color=c.text_muted, anchor="w",
        )
        # Hauteur fixe pour ne pas faire sauter le layout quand vide
        self._typing_label.grid(row=2, column=0, sticky="ew",
                                 padx=T.SPACE_2XL, pady=(2, 0))

        # ---- Footer : input + bouton ----
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew",
                     padx=T.SPACE_2XL, pady=(T.SPACE_SM, T.SPACE_LG))

        row = ctk.CTkFrame(footer, fg_color="transparent")
        row.pack(fill="x")
        self._entry = ctk.CTkEntry(
            row, fg_color=c.panel, border_color=c.border,
            border_width=1, text_color=c.text_primary, height=40,
            placeholder_text=f"Écris à {peer_name}…",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
        )
        self._entry.pack(side="left", fill="x", expand=True,
                          padx=(0, T.SPACE_SM))
        self._entry.bind("<Return>", lambda _e: self._send())
        self._entry.bind("<KeyRelease>", self._on_keystroke)
        PrimaryButton(
            row, colors=c, text="Envoyer", icon="play",
            command=self._send,
        ).pack(side="left")

        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.pack(fill="x", pady=(T.SPACE_SM, 0))
        SecondaryButton(actions, colors=c, text="Fermer",
                         command=self._handle_close).pack(side="left")

        # Premier rendu + boucle de refresh
        self._render_loading()
        self._reload_async()
        self._schedule_refresh()
        self._schedule_typing_poll()
        # Mise à jour des reçus comme lus (best-effort, async)
        threading.Thread(target=M.mark_all_read, daemon=True,
                         name="ChatMarkRead").start()

        try:
            self._entry.focus_set()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _handle_close(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        for job_attr in ("_refresh_job", "_typing_job"):
            job = getattr(self, job_attr, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                setattr(self, job_attr, None)
        # Annonce qu'on n'écrit plus (best-effort)
        threading.Thread(
            target=lambda: M.set_typing(False),
            daemon=True, name="ChatTypingOff",
        ).start()
        try:
            self.destroy()
        except Exception:
            pass
        if self._on_closed is not None:
            try:
                self._on_closed()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _schedule_refresh(self) -> None:
        if self._destroyed:
            return
        try:
            self._refresh_job = self.after(REFRESH_MS, self._on_refresh_tick)
        except Exception:
            self._refresh_job = None

    def _on_refresh_tick(self) -> None:
        if self._destroyed:
            return
        self._reload_async()
        self._schedule_refresh()

    def _reload_async(self) -> None:
        def worker():
            msgs = M.list_messages(limit=200)
            try:
                self.after(0, lambda m=msgs: self._render_messages(m))
            except Exception:
                pass
            # On marque comme lus en passant (côté DB) — le poller signalera
            # le changement aux autres machines.
            try:
                M.mark_all_read()
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True,
                         name="ChatReload").start()

    # ------------------------------------------------------------------
    # Indicateur "X est en train d'écrire"
    # ------------------------------------------------------------------
    def _on_keystroke(self, _evt=None) -> None:
        """À chaque relâchement de touche : envoie set_typing(True), mais
        throttlé pour ne pas spammer Supabase."""
        import time
        now = time.monotonic()
        if now - self._last_typing_emit < TYPING_EMIT_THROTTLE_S:
            return
        self._last_typing_emit = now
        threading.Thread(
            target=lambda: M.set_typing(True),
            daemon=True, name="ChatTypingOn",
        ).start()

    def _schedule_typing_poll(self) -> None:
        if self._destroyed:
            return
        try:
            self._typing_job = self.after(TYPING_POLL_MS, self._poll_typing)
        except Exception:
            self._typing_job = None

    def _poll_typing(self) -> None:
        if self._destroyed:
            return

        def worker():
            try:
                v = M.peer_is_typing()
            except Exception:
                v = False
            try:
                self.after(0, lambda val=v: self._render_typing(val))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True,
                         name="ChatTypingPoll").start()
        self._schedule_typing_poll()

    def _render_typing(self, is_typing: bool) -> None:
        if self._destroyed:
            return
        if is_typing == self._peer_typing:
            return
        self._peer_typing = is_typing
        try:
            if is_typing:
                self._typing_label.configure(
                    text=f"{self._peer_name} est en train d'écrire…")
            else:
                self._typing_label.configure(text="")
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _render_loading(self) -> None:
        for w in self._body.winfo_children():
            w.destroy()
        c = self._colors
        ctk.CTkLabel(
            self._body, text="…",
            font=(T.FONT_FAMILY_DISPLAY, 32, "bold"),
            text_color=c.success,
        ).pack(pady=(T.SPACE_2XL, T.SPACE_SM))
        ctk.CTkLabel(
            self._body, text="Chargement de la conversation…",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_secondary,
        ).pack()

    def _render_unavailable(self, reason: str) -> None:
        for w in self._body.winfo_children():
            w.destroy()
        c = self._colors
        ctk.CTkLabel(
            self._body, text=reason,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_secondary, justify="left", wraplength=460,
        ).pack(pady=T.SPACE_2XL, padx=T.SPACE_LG)

    def _render_messages(self, msgs: list[dict]) -> None:
        if self._destroyed:
            return
        # Si on n'est pas loggé / pas d'autre user → état "indisponible"
        peer = M.other_user()
        if peer is None:
            self._render_unavailable(
                "Le chat a besoin que tu sois connecté à Supabase et que "
                "ton équipier ait aussi un compte. Renseigne tes accès "
                "dans Réglages → Cloud."
            )
            return

        # Diff doux : si rien n'a changé, on ne reconstruit pas (évite le
        # scintillement et les sauts de scrollbar).
        ids = {m["id"] for m in msgs}
        if ids == self._known_message_ids:
            return
        self._known_message_ids = ids

        for w in self._body.winfo_children():
            w.destroy()
        if not msgs:
            self._render_unavailable(
                f"Aucun message pour le moment. Lance la conversation — "
                f"{peer.get('display_name') or 'ton équipier'} verra ton "
                f"message apparaître chez lui."
            )
            return

        c = self._colors
        try:
            from triskell_core.db import get_client
            me = get_client().user_id
        except Exception:
            me = None

        last_day = ""
        for m in msgs:
            day = (m.get("created_at") or "")[:10]
            if day and day != last_day:
                last_day = day
                self._add_day_separator(day)
            mine = (m.get("sender_id") == me)
            self._add_bubble(m, mine=mine)

        # Scroll en bas
        try:
            self._body.update_idletasks()
            self._body._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _add_day_separator(self, day_iso: str) -> None:
        c = self._colors
        try:
            d = datetime.fromisoformat(day_iso)
            label = d.strftime("%d %b %Y")
        except Exception:
            label = day_iso
        row = ctk.CTkFrame(self._body, fg_color="transparent")
        row.pack(fill="x", pady=(T.SPACE_MD, T.SPACE_SM))
        ctk.CTkLabel(
            row, text=label.upper(),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, fg_color=c.panel,
            corner_radius=T.RADIUS_PILL, padx=10, pady=2,
        ).pack(anchor="center")

    def _add_bubble(self, m: dict, *, mine: bool) -> None:
        c = self._colors
        body = (m.get("body") or "").strip() or " "
        ts = m.get("created_at") or ""
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            time_label = t.astimezone().strftime("%H:%M")
        except Exception:
            time_label = ""

        row = ctk.CTkFrame(self._body, fg_color="transparent")
        row.pack(fill="x", pady=(2, 2))

        bubble = ctk.CTkFrame(
            row,
            fg_color=(c.accent if mine else c.panel),
            corner_radius=14,
        )
        side = "right" if mine else "left"
        bubble.pack(side=side, padx=T.SPACE_SM)

        text_color = (c.accent_text if mine else c.text_primary)
        ctk.CTkLabel(
            bubble, text=body,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=text_color, justify="left",
            wraplength=380, anchor="w",
        ).pack(padx=12, pady=(8, 2), anchor="w")

        if time_label:
            ctk.CTkLabel(
                bubble, text=time_label,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                text_color=(text_color if mine else c.text_muted),
            ).pack(padx=12, pady=(0, 6), anchor="e" if mine else "w")

    # ------------------------------------------------------------------
    def _send(self) -> None:
        text = self._entry.get().strip()
        if not text:
            return
        self._entry.delete(0, "end")

        def worker():
            sent = M.send_message(text)
            # Le message est parti → on n'écrit plus
            try:
                M.set_typing(False)
            except Exception:
                pass
            try:
                self.after(0, lambda: self._after_send(sent, text))
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True,
                         name="ChatSend").start()

    def _after_send(self, sent: dict | None, original: str) -> None:
        if self._destroyed:
            return
        if sent is None:
            # Échec → restaure le texte pour ne pas le perdre
            try:
                cur = self._entry.get()
                if not cur:
                    self._entry.insert(0, original)
            except Exception:
                pass
            return
        self._reload_async()

    # ------------------------------------------------------------------
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
