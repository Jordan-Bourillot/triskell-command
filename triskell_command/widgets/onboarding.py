"""Onboarding — wizard 3 étapes au 1er lancement."""

from __future__ import annotations

import webbrowser
from typing import Callable

import customtkinter as ctk

from .. import theme as T
from .components import PrimaryButton, SecondaryButton
from .window_icon import apply_window_icon


GEMINI_KEY_URL = "https://aistudio.google.com/app/apikey"


# Presets de fournisseurs mail courants → serveurs SMTP/IMAP + URL d'aide
MAIL_PROVIDERS = {
    "Gmail": {
        "smtp_host": "smtp.gmail.com", "smtp_port": 587,
        "imap_host": "imap.gmail.com", "imap_port": 993,
        "password_label": "Mot de passe d'application Gmail (16 caractères)",
        "password_help_url": "https://myaccount.google.com/apppasswords",
        "password_help_text": "Crée un mot de passe d'application Gmail",
    },
    "IONOS": {
        "smtp_host": "smtp.ionos.fr", "smtp_port": 587,
        "imap_host": "imap.ionos.fr", "imap_port": 993,
        "password_label": "Mot de passe de ta boîte mail IONOS",
        "password_help_url": "https://www.ionos.fr/aide/email/configuration-pour-clients-de-messagerie/parametres-imap-smtp-pop3-pour-ionos-mail/",
        "password_help_text": "Aide IONOS — paramètres de boîte mail",
    },
    "OVH": {
        "smtp_host": "ssl0.ovh.net", "smtp_port": 587,
        "imap_host": "ssl0.ovh.net", "imap_port": 993,
        "password_label": "Mot de passe de ta boîte mail OVH",
        "password_help_url": "https://help.ovhcloud.com/csm/fr-mail-emails-pro-imap-smtp",
        "password_help_text": "Aide OVH — paramètres de boîte mail",
    },
    "Office 365 / Outlook": {
        "smtp_host": "smtp.office365.com", "smtp_port": 587,
        "imap_host": "outlook.office365.com", "imap_port": 993,
        "password_label": "Mot de passe Outlook (ou mot de passe d'application)",
        "password_help_url": "https://support.microsoft.com/fr-fr/account-billing/utiliser-des-mots-de-passe-d-application-avec-des-applications-qui-ne-prennent-pas-en-charge-la-v%C3%A9rification-en-deux-%C3%A9tapes-5896ed9b-4263-e681-128a-a6f2979a7944",
        "password_help_text": "Aide Microsoft — mot de passe d'application",
    },
    "Autre fournisseur": {
        "smtp_host": "", "smtp_port": 587,
        "imap_host": "", "imap_port": 993,
        "password_label": "Mot de passe de ta boîte mail",
        "password_help_url": "",
        "password_help_text": "",
    },
}


class OnboardingDialog(ctk.CTkToplevel):
    """Wizard 3 étapes : Bienvenue → Clé IA → Mail. Modal au 1er lancement."""

    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        app_state,
        on_done: Callable[[], None] | None = None,
    ):
        super().__init__(master)
        self._colors = colors
        self._app_state = app_state
        self._on_done = on_done
        self._step = 0

        c = colors
        self.title("Bienvenue dans Triskell Command")
        # Plus grand pour éviter que les boutons soient coupés
        self.geometry("780x780")
        self.minsize(720, 700)
        self.configure(fg_color=c.bg)
        self.transient(master.winfo_toplevel())
        self.grab_set()
        apply_window_icon(self)
        self.after(100, lambda: self.lift())

        # Step indicator (3 dots) — toujours visible en haut
        self._indicator = ctk.CTkFrame(self, fg_color="transparent")
        self._indicator.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_MD))

        # Bottom actions (boutons) — toujours visible en bas, packé AVANT le body
        # pour que le body remplisse la place restante sans cacher les boutons
        self._bottom = ctk.CTkFrame(self, fg_color="transparent")
        self._bottom.pack(side="bottom", fill="x", padx=T.SPACE_LG,
                          pady=(0, T.SPACE_LG))

        # Body container scrollable — si le contenu dépasse, on scroll
        self._body = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        self._body.pack(fill="both", expand=True, padx=T.SPACE_LG)

        self._show_step()

    def _show_step(self) -> None:
        # Reset body + bottom + indicator
        for w in self._indicator.winfo_children():
            w.destroy()
        for w in self._body.winfo_children():
            w.destroy()
        for w in self._bottom.winfo_children():
            w.destroy()

        # Indicator
        c = self._colors
        for i in range(3):
            dot = ctk.CTkFrame(
                self._indicator,
                fg_color=c.accent if i == self._step else c.border_strong,
                width=40 if i == self._step else 20,
                height=4, corner_radius=2,
            )
            dot.pack(side="left", padx=4)
            dot.pack_propagate(False)

        # Step content
        if self._step == 0:
            self._build_welcome()
        elif self._step == 1:
            self._build_ai_step()
        elif self._step == 2:
            self._build_mail_step()
        else:
            self._build_finish()

    # ------------------------------------------------------------------
    def _build_welcome(self) -> None:
        c = self._colors
        ctk.CTkLabel(
            self._body, text="Bienvenue.",
            font=(T.FONT_FAMILY_DISPLAY, 32, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_XL, T.SPACE_MD))

        ctk.CTkLabel(
            self._body,
            text=(
                "Triskell Command, c'est ton tableau de bord pour piloter "
                "tout Triskell.\n\n"
                "Tu décris qui tu veux contacter (secteur, région) UNE fois.\n"
                "L'app cherche, enrichit, rédige et envoie pendant que tu "
                "fais autre chose.\n\n"
                "Ton seul travail : valider chaque matin ce qui est préparé, "
                "et répondre quand un prospect répond.\n\n"
                "Avant de commencer, on te demande 2 choses : ta clé IA et "
                "ton mail. 5 minutes max, on te guide."
            ),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY_LG),
            text_color=c.text_secondary, justify="left", anchor="w",
        ).pack(fill="x", anchor="w", pady=(0, T.SPACE_XL))

        # Bottom : skip + start
        SecondaryButton(self._bottom, colors=c, text="Passer (configurer plus tard)",
                        command=self._skip).pack(side="left")
        PrimaryButton(
            self._bottom, colors=c, icon="arrow_right", text="C'est parti",
            command=self._next,
        ).pack(side="right")

    def _build_ai_step(self) -> None:
        c = self._colors
        ctk.CTkLabel(
            self._body, text="Étape 1 / 2 — Ta clé IA",
            font=(T.FONT_FAMILY_DISPLAY, 24, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_LG, T.SPACE_SM))

        ctk.CTkLabel(
            self._body,
            text=(
                "L'IA rédige tes mails. Tu as besoin d'une clé pour t'y connecter.\n\n"
                "On te recommande Google Gemini : gratuit, généreux, "
                "1500 messages/jour offerts."
            ),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_secondary, justify="left", anchor="w",
        ).pack(fill="x", anchor="w", pady=(0, T.SPACE_MD))

        SecondaryButton(
            self._body, colors=c, icon="external",
            text="Récupérer ma clé Gemini gratuite (ouvre le navigateur)",
            command=lambda: webbrowser.open(GEMINI_KEY_URL, new=2),
        ).pack(fill="x", pady=(0, T.SPACE_LG))

        ctk.CTkLabel(
            self._body, text="Colle ta clé Gemini ici :",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(0, 2))

        self._gemini_entry = ctk.CTkEntry(
            self._body, placeholder_text="AIza...",
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border_strong, border_width=1,
            corner_radius=T.RADIUS_SM, height=36,
            font=(T.FONT_FAMILY_MONO, T.FONT_SIZE_BODY),
            show="•",
        )
        # Pré-remplit si déjà saisie
        existing = self._app_state.get("ai", "api_keys", "google", default="")
        if existing:
            self._gemini_entry.insert(0, existing)
        self._gemini_entry.pack(fill="x", pady=(0, T.SPACE_MD))

        ctk.CTkLabel(
            self._body,
            text=(
                "Tu peux aussi sauter cette étape et ajouter une clé OpenAI / "
                "Anthropic plus tard dans Réglages."
            ),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, justify="left",
        ).pack(fill="x", anchor="w")

        # Bottom
        SecondaryButton(self._bottom, colors=c, icon="arrow_left", text="Retour",
                        command=self._prev).pack(side="left")
        PrimaryButton(
            self._bottom, colors=c, icon="arrow_right", text="Suivant",
            command=self._save_ai_then_next,
        ).pack(side="right")

    def _build_mail_step(self) -> None:
        c = self._colors
        ctk.CTkLabel(
            self._body, text="Étape 2 / 2 — Ton mail",
            font=(T.FONT_FAMILY_DISPLAY, 24, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_LG, T.SPACE_SM))

        ctk.CTkLabel(
            self._body,
            text=(
                "L'app envoie tes mails depuis ton compte mail. "
                "Choisis ton fournisseur ci-dessous, on remplit "
                "automatiquement les serveurs."
            ),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_secondary, justify="left", anchor="w",
            wraplength=620,
        ).pack(fill="x", anchor="w", pady=(0, T.SPACE_MD))

        # Sélecteur fournisseur
        ctk.CTkLabel(
            self._body, text="Fournisseur de ta boîte mail :",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(0, 2))

        # Détecte le provider courant depuis le smtp_host enregistré, sinon Gmail
        current_host = self._app_state.get("outreach", "smtp_host", default="")
        current_provider = "Gmail"
        for name, preset in MAIL_PROVIDERS.items():
            if preset["smtp_host"] and preset["smtp_host"] == current_host:
                current_provider = name
                break

        self._provider_var = ctk.StringVar(value=current_provider)
        ctk.CTkOptionMenu(
            self._body,
            values=list(MAIL_PROVIDERS.keys()),
            variable=self._provider_var,
            fg_color=c.bg_alt, button_color=c.accent,
            button_hover_color=c.accent_hover, text_color=c.text_primary,
            corner_radius=T.RADIUS_SM, height=36,
            command=self._on_provider_change,
        ).pack(fill="x", pady=(0, T.SPACE_MD))

        # Container des champs serveurs SMTP/IMAP (visible si "Autre fournisseur")
        self._mail_advanced = ctk.CTkFrame(self._body, fg_color="transparent")
        self._mail_advanced.pack(fill="x", pady=(0, T.SPACE_MD))

        # Bouton aide récupération mot de passe (peut être absent)
        self._mail_help_btn_container = ctk.CTkFrame(
            self._body, fg_color="transparent")
        self._mail_help_btn_container.pack(fill="x", pady=(0, T.SPACE_LG))

        # Email
        ctk.CTkLabel(
            self._body, text="Ton adresse mail :",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(0, 2))
        self._mail_entry = ctk.CTkEntry(
            self._body, placeholder_text="toi@ton-domaine.fr",
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border_strong, border_width=1,
            corner_radius=T.RADIUS_SM, height=36,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
        )
        existing_mail = self._app_state.get("outreach", "smtp_user", default="")
        if existing_mail:
            self._mail_entry.insert(0, existing_mail)
        self._mail_entry.pack(fill="x", pady=(0, T.SPACE_MD))

        # Password — label dynamique selon provider
        self._pwd_label_var = ctk.StringVar(value="Mot de passe :")
        ctk.CTkLabel(
            self._body, textvariable=self._pwd_label_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(0, 2))
        self._pwd_entry = ctk.CTkEntry(
            self._body,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border_strong, border_width=1,
            corner_radius=T.RADIUS_SM, height=36,
            font=(T.FONT_FAMILY_MONO, T.FONT_SIZE_BODY),
            show="•",
        )
        existing_pwd = self._app_state.get("outreach", "smtp_password", default="")
        if existing_pwd:
            self._pwd_entry.insert(0, existing_pwd)
        self._pwd_entry.pack(fill="x", pady=(0, T.SPACE_MD))

        # Mon prénom
        ctk.CTkLabel(
            self._body, text="Ton prénom (signature des mails) :",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(0, 2))
        self._prenom_entry = ctk.CTkEntry(
            self._body, placeholder_text="ex: Jordan",
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border_strong, border_width=1,
            corner_radius=T.RADIUS_SM, height=36,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
        )
        existing_prenom = self._app_state.get("outreach", "mon_prenom", default="")
        if existing_prenom:
            self._prenom_entry.insert(0, existing_prenom)
        self._prenom_entry.pack(fill="x", pady=(0, T.SPACE_MD))

        # Bottom
        SecondaryButton(self._bottom, colors=c, icon="arrow_left", text="Retour",
                        command=self._prev).pack(side="left")
        PrimaryButton(
            self._bottom, colors=c, icon="check", text="Terminer",
            command=self._save_mail_then_finish,
        ).pack(side="right")

        # Sync label/bouton aide au démarrage
        self._on_provider_change(current_provider)

    def _build_finish(self) -> None:
        c = self._colors
        ctk.CTkLabel(
            self._body, text="Tout est prêt.",
            font=(T.FONT_FAMILY_DISPLAY, 32, "bold"),
            text_color=c.accent, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_XL, T.SPACE_MD))

        ctk.CTkLabel(
            self._body,
            text=(
                "Tu peux maintenant aller dans « Auto-pilote » pour décrire "
                "qui tu veux contacter (secteur d'activité, département…) "
                "et lancer la machine.\n\n"
                "Une visite guidée va s'ouvrir derrière pour te présenter "
                "tout le reste. Tu peux aussi cliquer « Tuto » dans la barre "
                "de gauche à tout moment."
            ),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY_LG),
            text_color=c.text_secondary, justify="left", anchor="w",
        ).pack(fill="x", anchor="w", pady=(0, T.SPACE_XL))

        PrimaryButton(
            self._bottom, colors=c, icon="sparkle", text="Commencer",
            command=self._finish,
        ).pack(side="right")

    # ------------------------------------------------------------------
    def _on_provider_change(self, provider_name: str) -> None:
        """Met à jour le label du mot de passe et le bouton d'aide
        en fonction du fournisseur mail sélectionné. Reconstruit aussi les
        champs avancés (serveurs SMTP/IMAP) pour 'Autre fournisseur'."""
        preset = MAIL_PROVIDERS.get(provider_name, MAIL_PROVIDERS["Autre fournisseur"])

        # Met à jour le label du mot de passe
        if hasattr(self, "_pwd_label_var"):
            self._pwd_label_var.set(preset["password_label"] + " :")

        # Adapte le placeholder du mot de passe (Gmail = format spécial)
        if hasattr(self, "_pwd_entry"):
            try:
                self._pwd_entry.configure(
                    placeholder_text=(
                        "abcd efgh ijkl mnop (espaces tolérés)"
                        if provider_name == "Gmail"
                        else "(mot de passe de ta boîte mail)"
                    )
                )
            except Exception:
                pass

        # Reconstruit le bouton d'aide
        for w in self._mail_help_btn_container.winfo_children():
            w.destroy()
        if preset["password_help_url"]:
            SecondaryButton(
                self._mail_help_btn_container, colors=self._colors,
                icon="external", text=preset["password_help_text"],
                command=lambda url=preset["password_help_url"]:
                    webbrowser.open(url, new=2),
            ).pack(fill="x")

        # Reconstruit les champs serveurs avancés
        for w in self._mail_advanced.winfo_children():
            w.destroy()
        if provider_name == "Autre fournisseur":
            c = self._colors
            ctk.CTkLabel(
                self._mail_advanced,
                text="Serveurs à configurer manuellement :",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
                text_color=c.text_secondary, anchor="w",
            ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, T.SPACE_XS))
            self._smtp_host_entry = ctk.CTkEntry(
                self._mail_advanced,
                placeholder_text="Serveur d'envoi SMTP (ex: mail.tondomaine.fr)",
                fg_color=c.bg_alt, text_color=c.text_primary,
                border_color=c.border, border_width=1,
                corner_radius=T.RADIUS_SM, height=32,
            )
            self._smtp_host_entry.pack(fill="x", pady=(0, T.SPACE_XS))
            self._imap_host_entry = ctk.CTkEntry(
                self._mail_advanced,
                placeholder_text="Serveur de réception IMAP (ex: mail.tondomaine.fr)",
                fg_color=c.bg_alt, text_color=c.text_primary,
                border_color=c.border, border_width=1,
                corner_radius=T.RADIUS_SM, height=32,
            )
            self._imap_host_entry.pack(fill="x", pady=(0, T.SPACE_SM))
            # Pré-remplit avec les valeurs courantes du state si disponibles
            cur_smtp = self._app_state.get("outreach", "smtp_host", default="")
            cur_imap = self._app_state.get("outreach", "imap_host", default="")
            if cur_smtp:
                self._smtp_host_entry.insert(0, cur_smtp)
            if cur_imap:
                self._imap_host_entry.insert(0, cur_imap)

    def _next(self):
        self._step += 1
        self._show_step()

    def _prev(self):
        self._step -= 1
        self._show_step()

    def _save_ai_then_next(self):
        key = self._gemini_entry.get().strip()
        if key:
            self._app_state.set("ai", "api_keys", "google", value=key)
            self._app_state.set("ai", "selected_provider", value="google")
            self._app_state.set("ai", "selected_model", value="gemini-2.5-flash")
            self._app_state.save()
        self._next()

    def _save_mail_then_finish(self):
        mail = self._mail_entry.get().strip()
        pwd = self._pwd_entry.get().strip().replace(" ", "")
        prenom = self._prenom_entry.get().strip()
        provider_name = self._provider_var.get()
        preset = MAIL_PROVIDERS.get(provider_name, MAIL_PROVIDERS["Autre fournisseur"])

        # Si "Autre fournisseur", récupère les serveurs saisis manuellement
        smtp_host = preset["smtp_host"]
        imap_host = preset["imap_host"]
        if provider_name == "Autre fournisseur":
            try:
                smtp_host = self._smtp_host_entry.get().strip()
                imap_host = self._imap_host_entry.get().strip()
            except AttributeError:
                pass

        if mail:
            if smtp_host:
                self._app_state.set("outreach", "smtp_host", value=smtp_host)
            self._app_state.set("outreach", "smtp_port", value=preset["smtp_port"])
            self._app_state.set("outreach", "smtp_user", value=mail)
            self._app_state.set("outreach", "from_email", value=mail)
            if imap_host:
                self._app_state.set("outreach", "imap_host", value=imap_host)
            self._app_state.set("outreach", "imap_port", value=preset["imap_port"])
            self._app_state.set("outreach", "imap_user", value=mail)
            if pwd:
                self._app_state.set("outreach", "smtp_password", value=pwd)
                self._app_state.set("outreach", "imap_password", value=pwd)
            if prenom:
                self._app_state.set("outreach", "mon_prenom", value=prenom)
                self._app_state.set("outreach", "from_name",
                                     value=f"{prenom} — Triskell Studio")
            self._app_state.save()
        self._next()

    def _skip(self):
        self._app_state.set("ui", "onboarding_skipped", value=True)
        self._app_state.save()
        if self._on_done:
            self._on_done()
        self.destroy()

    def _finish(self):
        self._app_state.set("ui", "onboarding_done", value=True)
        self._app_state.save()
        if self._on_done:
            self._on_done()
        self.destroy()


def needs_onboarding(app_state) -> bool:
    """True si l'user n'a pas encore fini l'onboarding ET n'a pas configuré IA + mail."""
    if app_state.get("ui", "onboarding_done", default=False):
        return False
    if app_state.get("ui", "onboarding_skipped", default=False):
        return False
    # On déclenche l'onboarding si AUCUNE clé IA n'est saisie
    keys = app_state.get("ai", "api_keys", default={}) or {}
    has_any_key = any(keys.values())
    return not has_any_key
