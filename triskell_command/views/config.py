"""Vue Réglages — clés API, SMTP/IMAP, sources, apparence."""

from __future__ import annotations

import subprocess
import sys
import webbrowser

import customtkinter as ctk

from .. import theme as T
from ..widgets import icons as I
from ..widgets.components import Card, PrimaryButton, SecondaryButton, ViewHeader
from .base import BaseView


SCHEDULED_TASK_NAME = "Triskell Prospect Nightly"


# URLs où obtenir chaque clé API (pages officielles, vérifiées 2026)
API_KEY_URLS = {
    # Providers IA
    "anthropic":   "https://console.anthropic.com/settings/keys",
    "openai":      "https://platform.openai.com/api-keys",
    "google":      "https://aistudio.google.com/app/apikey",
    "mistral":     "https://console.mistral.ai/api-keys/",
    "xai":         "https://console.x.ai/",
    # Sources
    "youtube":     "https://console.cloud.google.com/apis/credentials",
    "twitch":      "https://dev.twitch.tv/console/apps",
    "google_maps": "https://console.cloud.google.com/apis/credentials",
    # Email
    "gmail_app":   "https://myaccount.google.com/apppasswords",
}


class ConfigView(BaseView):
    title = "Réglages"
    subtitle = "Tes clés, tes connexions, ton apparence."

    def build(self) -> None:
        c = self.colors
        # Header
        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_LG))

        self._save_button = PrimaryButton(
            header.actions, colors=c, icon="save", text="Enregistrer",
            command=self._save_all,
        )
        self._save_button.pack(side="left")

        # Container scrollable (beaucoup de champs)
        self._scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=c.border_strong,
            scrollbar_button_hover_color=c.text_secondary,
        )
        self._scroll.pack(fill="both", expand=True, padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))

        # Pour collecter les widgets et leur sauvegarde plus tard
        self._fields: list[tuple[tuple[str, ...], ctk.CTkEntry]] = []

        # Status bar bas (dernier message)
        self._status_var = ctk.StringVar(value="")
        self._status_label = ctk.CTkLabel(
            self,
            textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
        )
        self._status_label.pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

        # Sections
        self._build_section_ai()
        self._build_section_outreach()
        self._build_section_sources()
        self._build_section_social()
        self._build_section_nightly()
        self._build_section_appearance()
        self._build_section_updates()

    # ------------------------------------------------------------------
    # Builders de sections
    # ------------------------------------------------------------------
    def _build_section_ai(self) -> None:
        c = self.colors
        section = self._make_section("Services IA",
                                     "Tes clés API (Anthropic, OpenAI, Google, Mistral, xAI). "
                                     "Jamais envoyées hors de l'app, stockées localement.")

        for key, label in [
            ("anthropic", "Anthropic (Claude)"),
            ("openai",    "OpenAI (GPT)"),
            ("google",    "Google (Gemini)"),
            ("mistral",   "Mistral"),
            ("xai",       "xAI (Grok)"),
        ]:
            self._make_password_field(
                section, label,
                path=("ai", "api_keys", key),
                helper_url=API_KEY_URLS.get(key, ""),
            )

        # Provider par défaut
        self._make_combobox_field(
            section, "Service IA utilisé par défaut",
            path=("ai", "selected_provider"),
            values=["anthropic", "openai", "google", "mistral", "xai"],
        )
        self._make_text_field(
            section, "Modèle IA utilisé par défaut",
            path=("ai", "selected_model"),
            placeholder="ex: gemini-2.5-flash, claude-sonnet-4-5",
        )

    def _build_section_outreach(self) -> None:
        c = self.colors
        section = self._make_section(
            "Mail (envoi + réception)",
            "Choisis ton fournisseur dans la liste : les serveurs se "
            "remplissent automatiquement.   "
            "Gmail = mot de passe d'application (16 caractères).   "
            "IONOS / OVH = ton mot de passe normal.",
        )

        # --- Dropdown fournisseur (pré-remplit les champs) ---
        from ..widgets.onboarding import MAIL_PROVIDERS as _MP
        row_p = ctk.CTkFrame(section, fg_color="transparent")
        row_p.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))
        ctk.CTkLabel(
            row_p, text="Fournisseur",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w", width=240,
        ).pack(side="left", padx=(0, T.SPACE_MD))
        # Détecte le provider courant via smtp_host
        cur_host = self.app_state.get("outreach", "smtp_host", default="")
        cur_provider = "Gmail"
        for name, p in _MP.items():
            if p["smtp_host"] and p["smtp_host"] == cur_host:
                cur_provider = name
                break
        self._mail_provider_var = ctk.StringVar(value=cur_provider)
        ctk.CTkOptionMenu(
            row_p, values=list(_MP.keys()),
            variable=self._mail_provider_var,
            fg_color=c.bg_alt, button_color=c.accent,
            button_hover_color=c.accent_hover, text_color=c.text_primary,
            corner_radius=T.RADIUS_SM, height=32,
            command=self._on_mail_provider_change,
        ).pack(side="left", fill="x", expand=True)
        self._make_text_field(section, "Serveur d'envoi (SMTP)",
                              path=("outreach", "smtp_host"),
                              placeholder="smtp.gmail.com")
        self._make_text_field(section, "Port d'envoi",
                              path=("outreach", "smtp_port"),
                              placeholder="587")
        self._make_text_field(section, "Mon adresse mail",
                              path=("outreach", "smtp_user"),
                              placeholder="toi@gmail.com")
        self._make_password_field(section, "Mot de passe d'application",
                                  path=("outreach", "smtp_password"),
                                  helper_url=API_KEY_URLS["gmail_app"])
        self._make_text_field(section, "Mail expéditeur (visible par le destinataire)",
                              path=("outreach", "from_email"))
        self._make_text_field(section, "Nom expéditeur",
                              path=("outreach", "from_name"),
                              placeholder="ex: Jordan — Triskell Studio")
        self._make_text_field(section, "Serveur de réception (IMAP)",
                              path=("outreach", "imap_host"),
                              placeholder="imap.gmail.com")
        self._make_text_field(section, "Mon adresse mail (réception)",
                              path=("outreach", "imap_user"))
        self._make_password_field(section, "Mot de passe d'application (réception)",
                                  path=("outreach", "imap_password"),
                                  helper_url=API_KEY_URLS["gmail_app"])
        self._make_text_field(section, "Plafond d'envois par jour",
                              path=("outreach", "daily_cap"),
                              placeholder="ex: 40")
        self._make_text_field(section, "Délai avant relance (jours)",
                              path=("outreach", "follow_up_days"),
                              placeholder="ex: 5")
        self._make_text_field(section, "Mon prénom (signature des mails)",
                              path=("outreach", "mon_prenom"))

    def _on_mail_provider_change(self, provider_name: str) -> None:
        """Pré-remplit les champs SMTP/IMAP host+port à partir du fournisseur choisi.
        Pour 'Autre fournisseur' : on n'écrase rien, l'user garde la main."""
        from ..widgets.onboarding import MAIL_PROVIDERS as _MP
        preset = _MP.get(provider_name)
        if not preset:
            return
        if provider_name == "Autre fournisseur":
            return  # on laisse l'user saisir manuellement

        # Trouve les widgets Entry correspondants dans self._fields
        # (path tuples) et met à jour leur contenu
        def _set(field_path: tuple, value):
            for path, widget in self._fields:
                if path == field_path and isinstance(widget, ctk.CTkEntry):
                    widget.delete(0, "end")
                    if value not in (None, ""):
                        widget.insert(0, str(value))
                    return

        _set(("outreach", "smtp_host"), preset["smtp_host"])
        _set(("outreach", "smtp_port"), preset["smtp_port"])
        _set(("outreach", "imap_host"), preset["imap_host"])
        _set(("outreach", "imap_port"), preset["imap_port"])

    def _build_section_sources(self) -> None:
        section = self._make_section(
            "Sources",
            "Clés API pour les sources qui en demandent",
        )
        self._make_password_field(section, "YouTube Data API key",
                                  path=("sources", "youtube_api_key"),
                                  helper_url=API_KEY_URLS["youtube"])
        self._make_text_field(section, "Twitch Client ID",
                              path=("sources", "twitch_client_id"),
                              helper_url=API_KEY_URLS["twitch"])
        self._make_password_field(section, "Twitch Client Secret",
                                  path=("sources", "twitch_client_secret"),
                                  helper_url=API_KEY_URLS["twitch"])
        self._make_password_field(section, "Google Maps Places API key",
                                  path=("sources", "google_places_api_key"),
                                  helper_url=API_KEY_URLS["google_maps"])

    def _build_section_social(self) -> None:
        section = self._make_section(
            "Service Réseaux",
            "URL de ton service Réseaux quand il tourne en local",
        )
        self._make_text_field(section, "URL du service",
                              path=("social", "reseaux_api_url"),
                              placeholder="http://localhost:3001")
        self._make_password_field(section, "JWT (si Clerk activé)",
                                  path=("social", "reseaux_jwt"))

    def _build_section_nightly(self) -> None:
        c = self.colors
        section = self._make_section(
            "Pilote automatique pendant la nuit",
            "L'app se lance toute seule chaque nuit à 03:00 et fait : "
            "vérifier les réponses, envoyer les premiers contacts, relancer "
            "ceux qui n'ont pas répondu. Tu n'as rien à faire.",
        )

        # Status texte
        self._nightly_status_var = ctk.StringVar(value="Vérification…")
        ctk.CTkLabel(
            section, textvariable=self._nightly_status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))

        # Boutons
        btn_row = ctk.CTkFrame(section, fg_color="transparent")
        btn_row.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        PrimaryButton(
            btn_row, colors=c, icon="check", text="Activer",
            command=self._enable_nightly,
        ).pack(side="left", padx=(0, T.SPACE_SM))
        SecondaryButton(
            btn_row, colors=c, icon="close", text="Désactiver",
            command=self._disable_nightly,
        ).pack(side="left", padx=(0, T.SPACE_SM))
        SecondaryButton(
            btn_row, colors=c, icon="play", text="Lancer maintenant",
            command=self._run_nightly_now,
        ).pack(side="left")

        # Refresh status au chargement de la vue
        self.after(100, self._refresh_nightly_status)

    def _refresh_nightly_status(self) -> None:
        if sys.platform != "win32":
            self._nightly_status_var.set("Indisponible (Windows uniquement).")
            return
        try:
            r = subprocess.run(
                ["schtasks", "/Query", "/TN", SCHEDULED_TASK_NAME],
                capture_output=True, text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if r.returncode == 0:
                self._nightly_status_var.set(
                    "✓ Boucle nocturne activée — exécution prévue chaque jour à 03:00."
                )
            else:
                self._nightly_status_var.set(
                    "Boucle nocturne désactivée. Clique « Activer » pour la planifier."
                )
        except Exception as exc:
            self._nightly_status_var.set(f"⚠ Vérification impossible : {exc}")

    def _enable_nightly(self) -> None:
        if sys.platform != "win32":
            self._nightly_status_var.set("Indisponible (Windows uniquement).")
            return
        # Détermine le binaire à lancer (mode dev vs frozen)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            # Frozen : le binaire en cours est l'app — on lance plutôt python -m
            # Le PyInstaller bundle ne sait pas exécuter -m triskell_core ; on
            # utilise donc python.exe global s'il est dispo.
            python_exe = self._find_python()
            if not python_exe:
                self._nightly_status_var.set(
                    "⚠ Python introuvable sur la machine — installe Python 3.10+ "
                    "puis réessaie, ou utilise l'installateur de la boucle "
                    "fourni dans l'app."
                )
                return
            target = python_exe
            args = "-m triskell_core.prospect.nightly --mon-prenom Jordan"
        else:
            python_exe = sys.executable
            target = python_exe
            args = "-m triskell_core.prospect.nightly --mon-prenom Jordan"

        try:
            r = subprocess.run(
                [
                    "schtasks", "/Create", "/F",
                    "/TN", SCHEDULED_TASK_NAME,
                    "/TR", f'"{target}" {args}',
                    "/SC", "DAILY",
                    "/ST", "03:00",
                    "/RL", "LIMITED",
                ],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if r.returncode == 0:
                self._nightly_status_var.set(
                    "✓ Boucle activée — démarre chaque jour à 03:00."
                )
            else:
                self._nightly_status_var.set(
                    f"⚠ Échec : {(r.stderr or r.stdout)[:200]}"
                )
        except Exception as exc:
            self._nightly_status_var.set(f"⚠ Erreur : {exc}")
        self.after(500, self._refresh_nightly_status)

    def _disable_nightly(self) -> None:
        if sys.platform != "win32":
            return
        try:
            r = subprocess.run(
                ["schtasks", "/Delete", "/F", "/TN", SCHEDULED_TASK_NAME],
                capture_output=True, text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if r.returncode == 0:
                self._nightly_status_var.set("✓ Boucle désactivée.")
            else:
                self._nightly_status_var.set(
                    "Aucune tâche active à désactiver."
                )
        except Exception as exc:
            self._nightly_status_var.set(f"⚠ Erreur : {exc}")
        self.after(500, self._refresh_nightly_status)

    def _run_nightly_now(self) -> None:
        if sys.platform != "win32":
            return
        try:
            subprocess.run(
                ["schtasks", "/Run", "/TN", SCHEDULED_TASK_NAME],
                capture_output=True, text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._nightly_status_var.set(
                "✓ Boucle lancée maintenant en arrière-plan. "
                "Vois ~/.triskell-prospect/nightly.log pour le détail."
            )
        except Exception as exc:
            self._nightly_status_var.set(f"⚠ Erreur : {exc}")

    @staticmethod
    def _find_python() -> str:
        """Cherche un python.exe utilisable pour le scheduled task."""
        import shutil
        candidates = [
            shutil.which("python"),
            shutil.which("py"),
            r"C:\Users\jorda\AppData\Local\Programs\Python\Python312\python.exe",
            r"C:\Users\jorda\AppData\Local\Programs\Python\Python311\python.exe",
            r"C:\Program Files\Python312\python.exe",
            r"C:\Program Files\Python311\python.exe",
        ]
        from pathlib import Path
        for c in candidates:
            if c and Path(c).exists():
                return c
        return ""

    def _build_section_appearance(self) -> None:
        section = self._make_section(
            "Apparence",
            "Mode clair/sombre",
        )
        self._make_combobox_field(
            section, "Mode",
            path=("appearance_mode",),
            values=["dark", "light"],
        )

    def _build_section_updates(self) -> None:
        c = self.colors
        from ..updater import APP_VERSION, GITHUB_OWNER, GITHUB_REPO, updater
        section = self._make_section(
            "Mises à jour",
            f"Repo source : github.com/{GITHUB_OWNER}/{GITHUB_REPO}",
        )

        # Version actuelle
        info_row = ctk.CTkFrame(section, fg_color="transparent")
        info_row.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))
        ctk.CTkLabel(
            info_row, text=f"Version installée : {APP_VERSION}",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary,
        ).pack(side="left")

        # Statut
        self._update_status_var = ctk.StringVar(value="Statut : prêt")
        ctk.CTkLabel(
            section, textvariable=self._update_status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary,
            anchor="w", justify="left", wraplength=600,
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))

        # Boutons
        btn_row = ctk.CTkFrame(section, fg_color="transparent")
        btn_row.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        SecondaryButton(
            btn_row, colors=c, icon="refresh", text="Vérifier maintenant",
            command=lambda: updater.check_for_updates(async_=True),
        ).pack(side="left", padx=(0, T.SPACE_SM))
        self._install_btn = PrimaryButton(
            btn_row, colors=c, icon="download", text="Installer la mise à jour",
            command=lambda: updater.install(),
        )
        self._install_btn.pack(side="left")
        self._install_btn.configure(state="disabled")

        # S'abonne aux changements de l'updater
        updater.add_listener(self._on_update_status)
        # Affiche le statut courant
        self._on_update_status(updater.status)

    def _on_update_status(self, status) -> None:
        """Callback du updater. Tk-thread-safe via after(0)."""
        def apply():
            phase = status.phase
            text = ""
            if phase == "idle":
                text = "Statut : prêt"
            elif phase == "checking":
                text = "Vérification en cours…"
            elif phase == "not-available":
                text = f"✓ Tu es à jour (version {status.current_version})."
            elif phase == "available":
                text = (f"📦 Nouvelle version {status.next_version} disponible. "
                        f"Téléchargement…")
            elif phase == "downloading":
                size_mb = status.download_size / (1024*1024) if status.download_size else 0
                bps_kb = status.bytes_per_second / 1024 if status.bytes_per_second else 0
                text = (f"Téléchargement {status.percent}% "
                        f"({size_mb:.1f} MB, {bps_kb:.0f} KB/s)")
            elif phase == "ready":
                text = (f"✅ Version {status.next_version} prête à installer. "
                        f"Clique « Installer » — l'app va redémarrer.")
            elif phase == "error":
                text = f"⚠ {status.message}"
            self._update_status_var.set(text)
            # Active le bouton Installer uniquement quand phase=ready
            try:
                if phase == "ready":
                    self._install_btn.configure(state="normal")
                else:
                    self._install_btn.configure(state="disabled")
            except Exception:
                pass

        try:
            self.after(0, apply)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Builders d'éléments
    # ------------------------------------------------------------------
    def _make_section(self, title: str, subtitle: str = "") -> Card:
        c = self.colors
        card = Card(self._scroll, colors=c)
        card.pack(fill="x", pady=(0, T.SPACE_LG))

        ctk.CTkLabel(
            card,
            text=title,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary,
            anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, 2))

        if subtitle:
            ctk.CTkLabel(
                card,
                text=subtitle,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_muted,
                anchor="w",
            ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        return card

    def _make_text_field(
        self, parent: Card, label: str, *,
        path: tuple[str, ...], placeholder: str = "",
        helper_url: str = "",
    ) -> ctk.CTkEntry:
        return self._make_entry(parent, label, path=path,
                                placeholder=placeholder, show=None,
                                helper_url=helper_url)

    def _make_password_field(
        self, parent: Card, label: str, *,
        path: tuple[str, ...], helper_url: str = "",
    ) -> ctk.CTkEntry:
        return self._make_entry(parent, label, path=path,
                                placeholder="•••• (saisie masquée)",
                                show="•", helper_url=helper_url)

    def _make_entry(
        self, parent: Card, label: str, *,
        path: tuple[str, ...], placeholder: str = "",
        show: str | None = None,
        helper_url: str = "",
    ) -> ctk.CTkEntry:
        c = self.colors
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))

        ctk.CTkLabel(
            row,
            text=label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary,
            anchor="w",
            width=240,
        ).pack(side="left", padx=(0, T.SPACE_MD))

        entry = ctk.CTkEntry(
            row,
            placeholder_text=placeholder,
            show=show,
            fg_color=c.bg_alt,
            text_color=c.text_primary,
            border_color=c.border,
            border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_MONO, T.FONT_SIZE_BODY),
            height=32,
        )
        entry.pack(side="left", fill="x", expand=True)

        # Bouton helper "↗ Obtenir la clé" si URL fournie
        if helper_url:
            self._make_helper_button(row, helper_url, label)

        # Pré-remplissage depuis state
        current = self.app_state.get(*path, default="")
        if current:
            entry.insert(0, str(current))

        self._fields.append((path, entry))
        return entry

    def _make_helper_button(self, parent, url: str, label: str) -> None:
        """Petit bouton icône ↗ qui ouvre `url` dans le navigateur."""
        c = self.colors
        icon = I.get_icon("external", c.text_muted, size=14)
        btn = ctk.CTkButton(
            parent,
            text="",
            image=icon,
            width=28, height=32,
            corner_radius=T.RADIUS_SM,
            fg_color="transparent",
            hover_color=c.panel_hover,
            border_width=1,
            border_color=c.border,
            command=lambda: self._open_helper_url(url, label),
        )
        btn.pack(side="left", padx=(T.SPACE_SM, 0))
        # Re-skin l'icône au hover (or au survol — signature Triskell)
        btn._icon_default = icon  # type: ignore
        btn._icon_hover = I.get_icon("external", c.gold, size=14)  # type: ignore
        btn.bind("<Enter>", lambda _e, b=btn: b.configure(image=b._icon_hover))
        btn.bind("<Leave>", lambda _e, b=btn: b.configure(image=b._icon_default))

    def _open_helper_url(self, url: str, label: str) -> None:
        try:
            webbrowser.open(url, new=2)
            self._status_var.set(f"↗ Page ouverte dans ton navigateur : {label}")
            self._status_label.configure(text_color=self.colors.success)
            self.after(4000, lambda: (
                self._status_var.set(""),
                self._status_label.configure(text_color=self.colors.text_muted),
            ))
        except Exception as exc:
            self._status_var.set(f"⚠ Impossible d'ouvrir {url} : {exc}")
            self._status_label.configure(text_color=self.colors.danger)

    def _make_combobox_field(
        self, parent: Card, label: str, *,
        path: tuple[str, ...], values: list[str],
    ) -> ctk.CTkOptionMenu:
        c = self.colors
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))

        ctk.CTkLabel(
            row, text=label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w", width=240,
        ).pack(side="left", padx=(0, T.SPACE_MD))

        var = ctk.StringVar(value=str(self.app_state.get(*path, default=values[0])))
        option = ctk.CTkOptionMenu(
            row,
            values=values,
            variable=var,
            fg_color=c.bg_alt,
            button_color=c.accent,
            button_hover_color=c.accent_hover,
            text_color=c.text_primary,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            corner_radius=T.RADIUS_SM,
            height=32,
        )
        option.pack(side="left", fill="x", expand=True)
        # On stocke le combobox sous une fausse Entry-like via la variable
        self._fields.append((path, _StringVarAdapter(var)))
        return option

    # ------------------------------------------------------------------
    def _save_all(self) -> None:
        for path, entry in self._fields:
            value = entry.get()
            # Cast int si la dernière clé sent le numérique
            last = path[-1]
            if last in ("smtp_port", "imap_port", "daily_cap", "follow_up_days"):
                try:
                    value = int(value) if value else 0
                except ValueError:
                    self._status_var.set(f"⚠ {last} doit être un entier — ignoré")
                    continue
            self.app_state.set(*path, value=value)
        self.app_state.save()
        self._status_var.set("✓ Réglages enregistrés.")
        self._status_label.configure(text_color=self.colors.success)
        # Reset couleur après 4 s
        self.after(4000, lambda: (
            self._status_var.set(""),
            self._status_label.configure(text_color=self.colors.text_muted),
        ))


class _StringVarAdapter:
    """Adapter pour que les CTkOptionMenu (StringVar) ressemblent aux Entry."""
    def __init__(self, var: ctk.StringVar):
        self._var = var

    def get(self) -> str:
        return self._var.get()
