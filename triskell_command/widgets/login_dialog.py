"""Dialogue de connexion simplifié — tape juste ton prénom.

Comportement :
- 1er lancement (aucun prénom enregistré sur ce poste) : on demande prénom +
  email + password Supabase. Une fois connecté, les identifiants sont
  enregistrés dans `~/.triskell-command/users.json`.
- Tous les lancements suivants : on demande juste le prénom. Connexion
  automatique invisible avec les identifiants enregistrés.
- Si le prénom tapé n'est pas connu (par ex. Thomas se connecte pour la 1re
  fois sur le poste de Jordan), on affiche les champs email/password en
  plus, le temps d'enregistrer ses identifiants. Une seule fois.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import customtkinter as ctk

from .. import theme as T
from ..local_users import get_credentials, known_names, save_credentials
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
        self.configure(fg_color=colors.bg)
        self.resizable(False, False)
        try:
            self.grab_set()
            self.transient(master)
        except Exception:
            pass

        c = colors
        self._wrap = ctk.CTkFrame(self, fg_color="transparent")
        self._wrap.pack(fill="both", expand=True, padx=T.SPACE_2XL, pady=T.SPACE_2XL)

        # ---- Titre + sous-titre dynamique ----
        ctk.CTkLabel(
            self._wrap, text="Connexion",
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_DISPLAY, "bold"),
            text_color=c.text_primary,
        ).pack(anchor="w")

        existing = known_names()
        if existing:
            sub = ("Tape ton prénom : " + " ou ".join(existing) + ".")
        else:
            sub = ("Première connexion sur ce poste : tape ton prénom, "
                   "ton email et ton mot de passe Supabase. "
                   "Le mot de passe ne sera demandé qu'une seule fois.")
        ctk.CTkLabel(
            self._wrap, text=sub,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, wraplength=380, justify="left",
        ).pack(anchor="w", pady=(2, T.SPACE_LG))

        # ---- Si Supabase pas configuré, demander URL + clé ----
        self._needs_config = self._check_needs_config()
        if self._needs_config:
            self._url_entry = self._field(self._wrap, "Adresse de la base partagée",
                                          placeholder="https://xxxxx.supabase.co")
            self._key_entry = self._field(self._wrap, "Clé d'accès publique",
                                          placeholder="eyJhbGciOi...")
        else:
            self._url_entry = None
            self._key_entry = None

        # ---- Champ Prénom (toujours visible) ----
        self._name_entry = self._field(
            self._wrap, "Prénom",
            placeholder=("Jordan" if not existing else " ou ".join(existing)),
        )

        # ---- Conteneur Email / Mot de passe (visible seulement si nécessaire) ----
        self._extra_frame = ctk.CTkFrame(self._wrap, fg_color="transparent")
        self._extra_msg = ctk.CTkLabel(
            self._extra_frame,
            text=("Première fois pour ce prénom — entre tes identifiants Supabase. "
                  "Ils seront mémorisés sur ce poste."),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.warning, wraplength=380, justify="left",
        )
        self._email_entry = self._field(
            self._extra_frame, "Email",
            placeholder="ex: jordan@triskell-studio.fr",
        )
        self._password_entry = self._field(
            self._extra_frame, "Mot de passe",
            placeholder="********", show="•",
        )

        # Affiche le bloc email/password si aucun prénom enregistré
        self._extras_shown = False
        if not existing:
            self._show_extras(announce=False)

        # ---- Erreur ----
        self._error_var = ctk.StringVar(value="")
        self._error_label = ctk.CTkLabel(
            self._wrap, textvariable=self._error_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.danger, wraplength=380, justify="left",
        )
        self._error_label.pack(anchor="w", pady=(T.SPACE_SM, 0))

        # ---- Boutons ----
        btns = ctk.CTkFrame(self._wrap, fg_color="transparent")
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

        # Taille auto selon le contenu
        self.update_idletasks()
        w = max(440, self.winfo_reqwidth())
        h = self.winfo_reqheight() + T.SPACE_2XL
        self.geometry(f"{w}x{h}")

        # Focus dans le 1er champ utile
        first = self._url_entry or self._name_entry
        if first:
            first.focus_set()

        # Enter = login
        self.bind("<Return>", lambda _e: self._do_login())
        self.bind("<Escape>", lambda _e: self.destroy())

    # ------------------------------------------------------------------
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

    def _show_extras(self, *, announce: bool = True) -> None:
        if self._extras_shown:
            return
        self._extras_shown = True
        # Si appelé après l'initialisation, on insère le bloc juste
        # avant le label d'erreur (sinon le pack par défaut le mettrait
        # tout en bas, après les boutons).
        try:
            self._extra_frame.pack(fill="x", pady=(T.SPACE_SM, 0),
                                    before=self._error_label)
        except Exception:
            self._extra_frame.pack(fill="x", pady=(T.SPACE_SM, 0))
        self._extra_msg.pack(fill="x", pady=(0, T.SPACE_SM))
        # Réajuste la taille de la fenêtre
        self.update_idletasks()
        w = max(440, self.winfo_reqwidth())
        h = self.winfo_reqheight() + T.SPACE_2XL
        self.geometry(f"{w}x{h}")
        if announce:
            self._error_var.set("")

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

    # ------------------------------------------------------------------
    def _do_login(self) -> None:
        self._error_var.set("")
        name = self._name_entry.get().strip()
        if not name:
            self._error_var.set("Indique ton prénom.")
            return

        # Si l'URL/clé sont à saisir → on les écrit avant tout
        if self._needs_config:
            url = (self._url_entry.get() if self._url_entry else "").strip()
            key = (self._key_entry.get() if self._key_entry else "").strip()
            if not url or not key:
                self._error_var.set("Adresse de la base et clé d'accès requises.")
                return
            self._persist_supabase_config(url, key)
            try:
                from triskell_core.db import reset_client
                reset_client()
            except Exception:
                pass
            self._needs_config = False

        # 1. On essaie de retrouver les identifiants connus pour ce prénom
        creds = get_credentials(name)
        if creds:
            email, password = creds
            self._launch_signin(name, email, password, remember=False)
            return

        # 2. Prénom inconnu → on demande email + password (1 seule fois)
        if not self._extras_shown:
            self._show_extras()
            self._error_var.set(
                f"« {name} » n'est pas encore enregistré sur ce poste. "
                "Entre tes identifiants ci-dessous (1 seule fois)."
            )
            self._email_entry.focus_set()
            return

        email = self._email_entry.get().strip()
        password = self._password_entry.get()
        if not email or not password:
            self._error_var.set("Email et mot de passe requis pour ce premier login.")
            return
        self._launch_signin(name, email, password, remember=True)

    def _launch_signin(self, name: str, email: str, password: str,
                        *, remember: bool) -> None:
        self._login_btn.configure(state="disabled", text="…")

        def worker():
            try:
                from triskell_core.db import get_client
                client = get_client()
                client.sign_in(email, password)
            except Exception as exc:
                msg = str(exc) or type(exc).__name__
                # Si on avait des creds sauvés et qu'ils ne marchent plus
                # (changement de password côté Supabase), on demande de
                # re-saisir. La sauvegarde sera mise à jour à la prochaine
                # tentative réussie.
                if not remember:
                    msg += (" — Le mot de passe enregistré pour ce prénom "
                            "ne fonctionne plus. Re-tape-le ci-dessous.")
                    self.after(0, self._show_extras)
                    self.after(0, lambda: self._email_entry.delete(0, "end"))
                    self.after(0, lambda v=email: self._email_entry.insert(0, v))
                self.after(0, lambda m=msg: self._error_var.set(m))
                self.after(0, lambda: self._login_btn.configure(
                    state="normal", text="Se connecter"))
                return
            # Succès
            if remember:
                try:
                    save_credentials(name, email, password)
                except Exception as exc:
                    logger.warning("save_credentials failed: %s", exc)
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
