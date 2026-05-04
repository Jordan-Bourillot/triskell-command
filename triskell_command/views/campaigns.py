"""Vue Campagnes — envois SMTP + relances + détection IMAP."""

from __future__ import annotations

import threading

import customtkinter as ctk

from .. import theme as T
from ..widgets.components import (
    Card,
    PrimaryButton,
    SecondaryButton,
    StatCard,
    ViewHeader,
)
from .base import BaseView


class CampaignsView(BaseView):
    title = "Envoyer & suivre"
    subtitle = "Tes vagues d'emails, relances J+5, détection automatique des réponses."

    def build(self) -> None:
        c = self.colors
        # Header
        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_LG))

        SecondaryButton(header.actions, colors=c, icon="refresh",
                        text="Vérifier réponses",
                        command=self._poll_replies).pack(side="left", padx=(0, T.SPACE_SM))

        # Stats : envoyés aujourd'hui, réponses, taux
        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))
        self._stat_cards: dict[str, StatCard] = {}
        for key, label, accent in [
            ("today",     "Envoyés aujourd'hui", c.text_primary),
            ("contacted", "Total contactés",     c.warning),
            ("replied",   "Réponses",            c.success),
            ("rate",      "Taux de réponse",     c.gold),
        ]:
            card = StatCard(stats, label=label, value="—", accent=accent, colors=c)
            card.pack(side="left", expand=True, fill="x", padx=T.SPACE_SM)
            self._stat_cards[key] = card

        # Body : 2 cards côte à côte (campagne + dernières actions)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))

        # Carte gauche : lancer une campagne
        camp_card = Card(body, colors=c)
        camp_card.pack(side="left", fill="both", expand=True, padx=(0, T.SPACE_MD))

        ctk.CTkLabel(
            camp_card, text="Lancer une vague",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))

        ctk.CTkLabel(
            camp_card,
            text=("Cible : prospects qualifiés avec email + site web vérifié.\n"
                  "L'app attend un délai aléatoire 30-120 s entre chaque envoi "
                  "(évite d'avoir l'air d'un robot pour Gmail).\n"
                  "Le plafond quotidien est défini dans les Réglages."),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, justify="left", wraplength=420,
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Sélecteur template
        ctk.CTkLabel(
            camp_card, text="Template",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, 2))
        self._template_var = ctk.StringVar(value="tpe_intro")
        try:
            from triskell_core.prospect.outreach import templates as tpls
            available = list(tpls.load_all().keys()) or ["tpe_intro", "tpe_relance_j5"]
        except Exception:
            available = ["tpe_intro", "tpe_relance_j5"]
        ctk.CTkOptionMenu(
            camp_card, values=available, variable=self._template_var,
            fg_color=c.bg_alt, button_color=c.accent,
            button_hover_color=c.accent_hover, text_color=c.text_primary,
            corner_radius=T.RADIUS_SM, height=32,
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Mode : 1er contact ou relance
        self._mode_var = ctk.StringVar(value="first")
        mode_frame = ctk.CTkFrame(camp_card, fg_color="transparent")
        mode_frame.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))
        ctk.CTkRadioButton(
            mode_frame, text="1er contact",
            variable=self._mode_var, value="first",
            fg_color=c.accent, hover_color=c.accent_hover,
            text_color=c.text_primary,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
        ).pack(side="left", padx=(0, T.SPACE_LG))
        ctk.CTkRadioButton(
            mode_frame, text="Relance",
            variable=self._mode_var, value="followup",
            fg_color=c.accent, hover_color=c.accent_hover,
            text_color=c.text_primary,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
        ).pack(side="left")

        # Dry-run toggle
        self._dry_run_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            camp_card, text="Mode test (rien n'est envoyé pour de vrai — simulation)",
            variable=self._dry_run_var,
            fg_color=c.accent, hover_color=c.accent_hover,
            text_color=c.text_primary,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Plafond cette session
        max_row = ctk.CTkFrame(camp_card, fg_color="transparent")
        max_row.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        ctk.CTkLabel(
            max_row, text="Max cette session",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, width=140,
        ).pack(side="left")
        self._max_var = ctk.StringVar(value="10")
        ctk.CTkEntry(
            max_row, textvariable=self._max_var,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM, height=28, width=80,
        ).pack(side="left")

        self._launch_btn = PrimaryButton(
            camp_card, colors=c, icon="send", text="Envoyer",
            command=self._launch_campaign,
        )
        self._launch_btn.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        # Carte droite : log d'activité récente
        log_card = Card(body, colors=c)
        log_card.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(
            log_card, text="📜 Activité récente",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))

        self._log_text = ctk.CTkTextbox(
            log_card,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_MONO, T.FONT_SIZE_SMALL),
            wrap="word",
        )
        self._log_text.pack(fill="both", expand=True,
                            padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        # Status bar
        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
        ).pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

    def on_show(self) -> None:
        self._refresh_stats()
        self._refresh_log()

    # ------------------------------------------------------------------
    def _refresh_stats(self) -> None:
        try:
            from triskell_core.prospect.core.crm import CRM
            crm = CRM()
            prospects = crm.all()
        except Exception:
            return

        contacted = sum(1 for p in prospects
                        if p.status in ("contacted", "replied", "won"))
        replied = sum(1 for p in prospects if p.status in ("replied", "won"))
        rate = f"{(replied / contacted * 100):.0f}%" if contacted else "—"

        # send_log : envoyés aujourd'hui
        try:
            from triskell_core.prospect.outreach.smtp_sender import _load_today_count
            today = _load_today_count()
        except Exception:
            today = 0

        for key, value in [("today", today), ("contacted", contacted),
                           ("replied", replied), ("rate", rate)]:
            self._set_stat(key, str(value))

    def _set_stat(self, key: str, value: str) -> None:
        card = self._stat_cards.get(key)
        if not card:
            return
        labels = [w for w in card.winfo_children() if isinstance(w, ctk.CTkLabel)]
        if len(labels) >= 2:
            labels[1].configure(text=value)

    def _refresh_log(self) -> None:
        """Affiche les 30 derniers événements `email_sent` / `reply_detected` / `email_failed`."""
        try:
            from triskell_core.prospect.core.crm import CRM
            crm = CRM()
        except Exception:
            return
        events = []
        for p in crm.all():
            for h in (p.history or []):
                kind = h.get("kind", "")
                if kind in ("email_sent", "email_failed", "reply_detected"):
                    events.append((h.get("ts", ""), kind, p.name or "(?)", h))
        events.sort(reverse=True)
        events = events[:30]

        self._log_text.delete("1.0", "end")
        if not events:
            self._log_text.insert("1.0", "Aucune activité d'envoi/réponse pour l'instant.")
            return

        for ts, kind, name, h in events:
            icon = {"email_sent": "✉", "email_failed": "✗", "reply_detected": "↩"}.get(kind, "·")
            line = f"{icon} {ts[:19]}  {name[:35]:35s}  {kind}"
            if kind == "email_sent":
                line += f"  → {h.get('to', '')}"
            elif kind == "reply_detected":
                line += f"  ← {h.get('from', '')}"
            elif kind == "email_failed":
                line += f"  : {h.get('error', '')[:60]}"
            self._log_text.insert("end", line + "\n")

    # ------------------------------------------------------------------
    def _launch_campaign(self) -> None:
        # Charge config SMTP depuis state et écrit dans le format attendu par smtp_sender
        cfg_keys = ("smtp_host", "smtp_port", "smtp_user", "smtp_password",
                    "from_email", "from_name", "imap_host", "imap_port",
                    "imap_user", "imap_password")
        cfg = {k: self.app_state.get("outreach", k, default="") for k in cfg_keys}

        missing = [k for k in ("smtp_host", "smtp_port", "smtp_user",
                               "smtp_password", "from_email") if not cfg.get(k)]
        if missing and not self._dry_run_var.get():
            self._status_var.set(
                f"⚠ Config SMTP incomplète : manque {', '.join(missing)}. "
                f"Voir Réglages."
            )
            return

        # Synchronise le fichier config Triskell Core (~/.triskell-prospect/config.json)
        # avec ce que Triskell Command a en state — sinon smtp_sender ne trouvera rien.
        self._sync_core_config()

        sender_vars = {
            "mon_prenom": self.app_state.get("outreach", "mon_prenom", default=""),
            "signature": self.app_state.get("outreach", "signature", default=""),
        }
        template = self._template_var.get()
        mode = self._mode_var.get()
        dry = self._dry_run_var.get()
        try:
            limit = int(self._max_var.get() or "0")
        except ValueError:
            limit = 0
        daily_cap = self.app_state.get("outreach", "daily_cap", default=40) or 40
        follow_up_days = self.app_state.get("outreach", "follow_up_days", default=5) or 5

        self._launch_btn.configure(state="disabled", text="…")
        self._status_var.set(
            f"{'Dry-run' if dry else 'Envoi'} {mode} avec template {template}…"
        )

        def worker():
            try:
                from triskell_core.prospect.outreach import smtp_sender
                stats = smtp_sender.run_campaign(
                    template_key=template,
                    sender_vars=sender_vars,
                    daily_cap=int(daily_cap),
                    follow_up=(mode == "followup"),
                    follow_up_days=int(follow_up_days),
                    dry_run=dry,
                    limit=limit,
                )
                def apply():
                    self._status_var.set(
                        f"{'✓' if stats.get('sent', 0) >= 0 else '✗'} "
                        f"{stats.get('sent', 0)} envoi(s) "
                        f"({stats.get('errors', 0)} erreur(s)) "
                        f"sur {stats.get('candidates', 0)} candidat(s)."
                    )
                    self._launch_btn.configure(state="normal", text="Envoyer")
                    self._refresh_stats()
                    self._refresh_log()
                self.after(0, apply)
            except Exception as e:
                err = str(e)
                def apply():
                    self._status_var.set(f"✗ {err[:200]}")
                    self._launch_btn.configure(state="normal", text="Envoyer")
                self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _poll_replies(self) -> None:
        self._sync_core_config()
        self._status_var.set("Connexion IMAP…")

        def worker():
            try:
                from triskell_core.prospect.outreach import imap_listener
                stats = imap_listener.poll_replies(verbose=False)
                def apply():
                    self._status_var.set(
                        f"✓ IMAP : {stats['scanned']} mail(s) scanné(s), "
                        f"{stats['matched']} réponse(s) détectée(s)."
                    )
                    self._refresh_stats()
                    self._refresh_log()
                self.after(0, apply)
            except Exception as e:
                err = str(e)
                def apply():
                    self._status_var.set(f"✗ IMAP : {err[:200]}")
                self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _sync_core_config(self) -> None:
        """Recopie les réglages SMTP/IMAP/Maps de Triskell Command vers le fichier
        config attendu par Triskell Core (~/.triskell-prospect/config.json)."""
        try:
            import json
            from triskell_core.prospect.core.crm import CONFIG_FILE, ensure_dirs
            ensure_dirs()

            current = {}
            if CONFIG_FILE.exists():
                try:
                    current = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                except Exception:
                    current = {}

            outreach = self.app_state.get("outreach", default={}) or {}
            for k in ("smtp_host", "smtp_port", "smtp_user", "smtp_password",
                      "from_email", "from_name", "imap_host", "imap_port",
                      "imap_user", "imap_password"):
                v = outreach.get(k)
                if v not in (None, ""):
                    current[k] = v
            sources = self.app_state.get("sources", default={}) or {}
            if sources.get("google_places_api_key"):
                current["google_places_api_key"] = sources["google_places_api_key"]
            CONFIG_FILE.write_text(
                json.dumps(current, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass
