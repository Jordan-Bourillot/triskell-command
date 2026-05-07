"""Dialogue de login Supabase — email + password.

Affiché au premier lancement (si Supabase configuré + pas de session) ou
quand l'utilisateur clique "se connecter" dans la status bar.

Comportement :
- Authentification réussie → ferme le dialogue, appelle `on_done`.
- Échec → message d'erreur affiché, dialogue reste ouvert.
- Si l'URL/clé Supabase n'est pas renseignée → on propose un champ pour
  les saisir et on les écrit dans settings.json.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import customtkinter as ctk

from .. import theme as T
from .components import PrimaryButton, SecondaryButton

logger = logging.getLogger(__name__)


class LoginDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        on_done: Callable[[], None] | None = None,
    ):
        super().__init__(master)
        self._colors = colors
        self._on_done = on_done

        self.title("Connexion — Triskell")
        self.geometry("440x420")
        self.configure(fg_color=colors.bg)
        self.resizable(False, False)
        try:
            self.grab_set()
            self.transient(master)
        except Exception:
            pass

        c = colors
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=T.SPACE_2XL, pady=T.SPACE_2XL)

        # Titre
        ctk.CTkLabel(
            wrap, text="Connexion à Triskell",
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_DISPLAY, "bold"),
            text_color=c.text_primary,
        ).pack(anchor="w")
        ctk.CTkLabel(
            wrap,
            text="Entre tes identifiants pour accéder à la base "
                 "partagée Triskell (carnet d'adresses commun à toi "
                 "et Thomas).",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, wraplength=380, justify="left",
        ).pack(anchor="w", pady=(2, T.SPACE_LG))

        # Si pas configuré : afficher 2 champs supplémentaires (URL + clé)
        self._needs_config = self._check_needs_config()

        if self._needs_config:
            self._url_entry = self._field(wrap, "Adresse de la base partagée",
                                          placeholder="https://xxxxx.supabase.co")
            self._key_entry = self._field(wrap, "Clé d'accès publique",
                                          placeholder="eyJhbGciOi...")
        else:
            self._url_entry = None
            self._key_entry = None

        self._email_entry = self._field(wrap, "Email",
                                        placeholder="ex: jordan@triskell-studio.fr")
        self._password_entry = self._field(wrap, "Mot de passe",
                                           placeholder="********",
                                           show="•")

        self._error_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            wrap, textvariable=self._error_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.danger, wraplength=380, justify="left",
        ).pack(anchor="w", pady=(T.SPACE_SM, 0))

        # Boutons
        btns = ctk.CTkFrame(wrap, fg_color="transparent")
        btns.pack(fill="x", pady=(T.SPACE_LG, 0))

        SecondaryButton(
            btns, colors=c, text="Annuler",
            command=self.destroy,
        ).pack(side="left")
        self._login_btn = PrimaryButton(
            btns, colors=c, icon="check", text="Se connecter",
            command=self._do_login,
        )
        self._login_btn.pack(side="right")

        # Focus dans le 1er champ utile
        first = self._url_entry or self._email_entry
        if first:
            first.focus_set()

        # Enter = login
        self.bind("<Return>", lambda _e: self._do_login())
        self.bind("<Escape>", lambda _e: self.destroy())

    def _field(self, parent, label: str, *, placeholder: str = "",
               show: str | None = None) -> ctk.CTkEntry:
        c = self._colors
        ctk.CTkLabel(
            parent, text=label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", pady=(T.SPACE_SM, 2))
        kwargs: dict = {
            "fg_color": c.bg_alt,
            "text_color": c.text_primary,
            "border_color": c.border,
            "border_width": 1,
            "corner_radius": T.RADIUS_SM,
            "height": 34,
            "font": (T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            "placeholder_text": placeholder,
        }
        if show:
            kwargs["show"] = show
        e = ctk.CTkEntry(parent, **kwargs)
        e.pack(fill="x")
        return e

    def _check_needs_config(self) -> bool:
        try:
            from triskell_core.db.client import SupabaseConfig, SupabaseNotConfigured
            try:
                SupabaseConfig.resolve()
                return False
            except SupabaseNotConfigured:
                return True
        except Exception:
            return True

    def _do_login(self) -> None:
        self._error_var.set("")
        email = self._email_entry.get().strip()
        password = self._password_entry.get()
        if not email or not password:
            self._error_var.set("Email et mot de passe requis.")
            return

        # Si l'URL/clé sont saisis → on les écrit dans settings.json avant le login
        if self._needs_config:
            url = (self._url_entry.get() if self._url_entry else "").strip()
            key = (self._key_entry.get() if self._key_entry else "").strip()
            if not url or not key:
                self._error_var.set("Adresse de la base et clé d'accès requises.")
                return
            self._persist_supabase_config(url, key)
            # Reset du client global pour qu'il relise la nouvelle config
            try:
                from triskell_core.db import reset_client
                reset_client()
            except Exception:
                pass

        self._login_btn.configure(state="disabled", text="…")

        def worker():
            try:
                from triskell_core.db import get_client, SupabaseAuthError
                client = get_client()
                client.sign_in(email, password)
            except Exception as exc:
                self.after(0, lambda: self._error_var.set(str(exc)))
                self.after(0, lambda: self._login_btn.configure(
                    state="normal", text="Se connecter"))
                return
            # Succès
            self.after(0, self._on_success)

        threading.Thread(target=worker, daemon=True).start()

    def _on_success(self) -> None:
        if self._on_done:
            try:
                self._on_done()
            except Exception:
                pass
        self.destroy()

    def _persist_supabase_config(self, url: str, anon_key: str) -> None:
        """Écrit la section 'supabase' dans ~/.triskell-command/settings.json."""
        import json
        from pathlib import Path
        cfg_path = Path.home() / ".triskell-command" / "settings.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except Exception:
                data = {}
        data["supabase"] = {"url": url, "anon_key": anon_key}
        tmp = cfg_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(cfg_path)
