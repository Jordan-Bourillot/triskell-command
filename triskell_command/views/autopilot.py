"""Vue Auto-pilote — config + lancement du pipeline complet en 1 clic."""

from __future__ import annotations

import threading

import customtkinter as ctk

from .. import theme as T
from ..widgets.components import Card, PrimaryButton, SecondaryButton, ViewHeader
from .base import BaseView


class AutopilotView(BaseView):
    title = "Auto-pilote"
    subtitle = (
        "Définis ta cible 1 fois. La machine cherche, enrichit, rédige, "
        "envoie (ou prépare des drafts) — pendant que tu fais autre chose."
    )

    def build(self) -> None:
        c = self.colors
        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_LG))

        SecondaryButton(header.actions, colors=c, icon="save", text="Enregistrer",
                        command=self._save_only).pack(side="left", padx=(0, T.SPACE_SM))
        self._launch_btn = PrimaryButton(
            header.actions, colors=c, icon="play",
            text="Lancer maintenant", command=self._launch_now,
        )
        self._launch_btn.pack(side="left")

        # Container principal scrollable
        scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        scroll.pack(fill="both", expand=True, padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))

        self._fields: dict[str, ctk.CTkEntry | ctk.StringVar | ctk.CTkTextbox |
                            ctk.BooleanVar] = {}

        # Charge config
        from triskell_core.prospect.pipeline import PipelineConfig
        self._cfg = PipelineConfig.load()

        self._build_general(scroll)
        self._build_search(scroll)
        self._build_enrich(scroll)
        self._build_ai(scroll)
        self._build_log(scroll)

    def on_show(self) -> None:
        # Recharger config en cas de modif externe
        from triskell_core.prospect.pipeline import PipelineConfig
        self._cfg = PipelineConfig.load()

    # ------------------------------------------------------------------
    def _make_section(self, parent, title: str, subtitle: str = "") -> Card:
        c = self.colors
        card = Card(parent, colors=c)
        card.pack(fill="x", pady=(0, T.SPACE_LG))
        ctk.CTkLabel(
            card, text=title,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, 2))
        if subtitle:
            ctk.CTkLabel(
                card, text=subtitle,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_muted, anchor="w", justify="left",
                wraplength=900,
            ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))
        return card

    def _input(self, parent, label, key, value: str = "", placeholder: str = ""):
        c = self.colors
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))
        ctk.CTkLabel(
            row, text=label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w", width=240,
        ).pack(side="left", padx=(0, T.SPACE_MD))
        entry = ctk.CTkEntry(
            row, placeholder_text=placeholder,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM, height=30,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
        )
        if value:
            entry.insert(0, str(value))
        entry.pack(side="left", fill="x", expand=True)
        self._fields[key] = entry

    def _select(self, parent, label, key, value: str, values: list[str]):
        c = self.colors
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))
        ctk.CTkLabel(
            row, text=label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w", width=240,
        ).pack(side="left", padx=(0, T.SPACE_MD))
        var = ctk.StringVar(value=value)
        ctk.CTkOptionMenu(
            row, values=values, variable=var,
            fg_color=c.bg_alt, button_color=c.accent,
            button_hover_color=c.accent_hover, text_color=c.text_primary,
            corner_radius=T.RADIUS_SM, height=30,
        ).pack(side="left", fill="x", expand=True)
        self._fields[key] = var

    def _checkbox(self, parent, label, key, value: bool):
        c = self.colors
        var = ctk.BooleanVar(value=value)
        ctk.CTkCheckBox(
            parent, text=label, variable=var,
            fg_color=c.accent, hover_color=c.accent_hover,
            text_color=c.text_primary,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM), anchor="w")
        self._fields[key] = var

    def _textarea(self, parent, label, key, value: str, height: int = 100):
        c = self.colors
        ctk.CTkLabel(
            parent, text=label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_SM, 2))
        tb = ctk.CTkTextbox(
            parent, height=height,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            wrap="word",
        )
        if value:
            tb.insert("1.0", value)
        tb.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))
        self._fields[key] = tb

    # ------------------------------------------------------------------
    def _build_general(self, parent):
        cfg = self._cfg
        section = self._make_section(
            parent,
            "Mode d'envoi",
            "AUTO : l'IA envoie chaque mail sans demander.   "
            "VALIDATION : l'IA prépare un brouillon, tu valides en 1 clic "
            "chaque matin (vue « À valider »).",
        )
        # Migration douce : ancien "sas" devient "validation"
        current_mode = "validation" if cfg.mode in ("sas", "validation") else "auto"
        self._select(section, "Mode d'envoi", "mode", current_mode,
                     ["validation", "auto"])
        self._checkbox(
            section,
            "Pipeline activé (la boucle nocturne lance ce pipeline si activé)",
            "enabled", cfg.enabled,
        )

    def _build_search(self, parent):
        cfg = self._cfg
        section = self._make_section(
            parent,
            "Où trouver les prospects ?",
            "La nuit, l'app cherche de nouveaux prospects qui correspondent à "
            "tes critères. Choisis la base de données :  "
            "« Sirene » = entreprises françaises (gratuit), "
            "« Google Maps » = commerces locaux (clé Google requise), "
            "« aucune » = pas de recherche auto.",
        )
        self._select(section, "Base de données", "source", cfg.source,
                     ["sirene", "maps", "none"])
        # Sirene
        self._input(section, "Sirene — Code activité (NAF)", "sirene_naf",
                    cfg.sirene_naf, "ex: 43.21A pour électricien")
        self._input(section, "Sirene — Département", "sirene_departement",
                    cfg.sirene_departement, "ex: 35 pour Ille-et-Vilaine")
        self._input(section, "Sirene — Code postal", "sirene_code_postal",
                    cfg.sirene_code_postal)
        self._input(section, "Sirene — Mot-clé dans le nom", "sirene_query",
                    cfg.sirene_query)
        self._input(section, "Sirene — Taille de l'entreprise", "sirene_effectif",
                    cfg.sirene_effectif, "00 = sans salarié, 01 = 1-2 salariés…")
        self._input(section, "Sirene — Créées depuis (AAAA-MM-JJ)",
                    "sirene_min_date_creation", cfg.sirene_min_date_creation,
                    "vide = toutes ; ex: 2024-01-01 = uniquement les entreprises créées récemment")
        # Maps
        self._input(section, "Google Maps — Recherche libre", "maps_query",
                    cfg.maps_query, "ex: 'boulangerie Rennes'")
        self._input(section, "Google Maps — Latitude", "maps_lat",
                    str(cfg.maps_lat or ""))
        self._input(section, "Google Maps — Longitude", "maps_lng",
                    str(cfg.maps_lng or ""))
        self._input(section, "Google Maps — Rayon (m)", "maps_radius_m",
                    str(cfg.maps_radius_m))
        # Common
        self._input(section, "Nombre max de prospects par recherche",
                    "search_max_results", str(cfg.search_max_results))

    def _build_enrich(self, parent):
        cfg = self._cfg
        section = self._make_section(
            parent,
            "Recherche d'emails et téléphones",
            "L'app visite le site web de chaque prospect, en extrait email + "
            "téléphone + adresse, et vérifie automatiquement que le site "
            "correspond bien à l'entreprise (anti-faux-positifs).",
        )
        self._checkbox(
            section,
            "Détecter automatiquement le site web quand il est inconnu "
            "(essaie nom-entreprise.fr, .com, etc.)",
            "enrich_with_footprint", cfg.enrich_with_footprint,
        )
        self._checkbox(section, "Ne traiter que les prospects sans email connu",
                       "enrich_no_emails_only", cfg.enrich_no_emails_only)
        self._input(section, "Nombre max de prospects à enrichir par run",
                    "enrich_max", str(cfg.enrich_max))

    def _build_ai(self, parent):
        cfg = self._cfg
        section = self._make_section(
            parent,
            "Rédaction des mails par l'IA",
            "Pour chaque prospect, l'IA reçoit son contexte (nom, ville, secteur, "
            "site web) + tes instructions, et rédige un mail unique. "
            "Pas de copier-coller mécanique — chaque mail est personnalisé.",
        )
        self._select(section, "Service IA", "ai_provider", cfg.ai_provider,
                     ["google", "anthropic", "openai", "mistral", "xai"])
        self._input(section, "Modèle IA", "ai_model", cfg.ai_model,
                    "ex: gemini-2.5-flash (gratuit) ou claude-sonnet-4-5")
        self._input(
            section,
            "Règles d'écriture (numéros séparés par virgules)",
            "ai_mega_prompts_csv",
            ",".join(cfg.ai_mega_prompts),
            "ex: 01,06,13 — clique « Aide » pour voir la liste des règles"
        )
        self._textarea(
            section, "Mes instructions à l'IA",
            "ai_template_brief", cfg.ai_template_brief, height=160,
        )
        self._input(section, "Mon prénom (signature)", "sender_mon_prenom",
                    cfg.sender_mon_prenom)
        self._input(section, "Plafond d'envois par jour", "daily_cap",
                    str(cfg.daily_cap))
        self._input(section, "Délai avant relance (en jours)", "follow_up_days",
                    str(cfg.follow_up_days))

    def _build_log(self, parent):
        c = self.colors
        section = self._make_section(
            parent,
            "Journal du run en cours",
            "S'affiche en direct quand tu cliques « Lancer maintenant ».",
        )
        self._log_text = ctk.CTkTextbox(
            section, height=180,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_MONO, T.FONT_SIZE_SMALL),
            wrap="word",
        )
        self._log_text.pack(fill="both", expand=True,
                            padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        self._log_text.insert("1.0", "(en attente d'un run…)")

    # ------------------------------------------------------------------
    def _read(self, key: str) -> str:
        w = self._fields.get(key)
        if w is None:
            return ""
        if isinstance(w, ctk.CTkEntry):
            return w.get().strip()
        if isinstance(w, ctk.CTkTextbox):
            return w.get("1.0", "end").rstrip()
        if isinstance(w, ctk.StringVar):
            return w.get().strip()
        if isinstance(w, ctk.BooleanVar):
            return "1" if w.get() else "0"
        return ""

    def _read_bool(self, key: str) -> bool:
        w = self._fields.get(key)
        return bool(w.get()) if isinstance(w, ctk.BooleanVar) else False

    def _read_int(self, key: str, default: int) -> int:
        try:
            return int(self._read(key) or default)
        except ValueError:
            return default

    def _read_float(self, key: str) -> float | None:
        v = self._read(key)
        if not v or v.lower() == "none":
            return None
        try:
            return float(v)
        except ValueError:
            return None

    def _gather_config(self):
        from triskell_core.prospect.pipeline import PipelineConfig
        cfg = PipelineConfig(
            enabled=self._read_bool("enabled"),
            mode=self._read("mode") or "validation",
            source=self._read("source") or "sirene",
            sirene_naf=self._read("sirene_naf"),
            sirene_departement=self._read("sirene_departement"),
            sirene_code_postal=self._read("sirene_code_postal"),
            sirene_query=self._read("sirene_query"),
            sirene_effectif=self._read("sirene_effectif") or "00",
            sirene_min_date_creation=self._read("sirene_min_date_creation"),
            maps_query=self._read("maps_query"),
            maps_lat=self._read_float("maps_lat"),
            maps_lng=self._read_float("maps_lng"),
            maps_radius_m=self._read_int("maps_radius_m", 50000),
            search_max_results=self._read_int("search_max_results", 50),
            enrich_with_footprint=self._read_bool("enrich_with_footprint"),
            enrich_no_emails_only=self._read_bool("enrich_no_emails_only"),
            enrich_max=self._read_int("enrich_max", 100),
            ai_provider=self._read("ai_provider") or "google",
            ai_model=self._read("ai_model") or "gemini-2.5-flash",
            ai_mega_prompts=[s.strip() for s in self._read("ai_mega_prompts_csv").split(",") if s.strip()],
            ai_template_brief=self._read("ai_template_brief"),
            sender_mon_prenom=self._read("sender_mon_prenom"),
            daily_cap=self._read_int("daily_cap", 40),
            follow_up_days=self._read_int("follow_up_days", 5),
        )
        return cfg

    def _save_only(self):
        cfg = self._gather_config()
        cfg.save()
        self._append_log(f"\n[{_now()}] Config enregistrée.")

    def _launch_now(self):
        cfg = self._gather_config()
        cfg.save()

        # Sync les clés API IA et SMTP du state Triskell Command vers le config Core
        self._sync_keys_to_core()

        self._launch_btn.configure(state="disabled", text="…")
        self._log_text.delete("1.0", "end")
        self._append_log(f"[{_now()}] Lancement du pipeline (mode {cfg.mode})…")

        def worker():
            try:
                from triskell_core.prospect.pipeline import run_full_pipeline
                stats = run_full_pipeline(
                    cfg,
                    progress=self._append_log,
                )
                summary = (
                    f"\n[{_now()}] === Fin === "
                    f"{stats.searched} trouvés, "
                    f"{stats.enriched} enrichis, "
                    f"{stats.drafts_sent} envoyés, "
                    f"{stats.drafts_pending} drafts en attente, "
                    f"{stats.replies_detected} réponses, "
                    f"{len(stats.errors)} erreurs."
                )
                self._append_log(summary)
            except Exception as e:
                self._append_log(f"\n✗ Pipeline a échoué : {e}")
            finally:
                self.after(0, lambda: self._launch_btn.configure(
                    state="normal", text="Lancer maintenant"))

        threading.Thread(target=worker, daemon=True).start()

    def _sync_keys_to_core(self) -> None:
        """Recopie les clés API et credentials SMTP/IMAP du state vers config.json Core."""
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
            # SMTP/IMAP
            outreach = self.app_state.get("outreach", default={}) or {}
            for k in ("smtp_host", "smtp_port", "smtp_user", "smtp_password",
                      "from_email", "from_name", "imap_host", "imap_port",
                      "imap_user", "imap_password"):
                v = outreach.get(k)
                if v not in (None, ""):
                    current[k] = v
            # Maps
            sources = self.app_state.get("sources", default={}) or {}
            if sources.get("google_places_api_key"):
                current["google_places_api_key"] = sources["google_places_api_key"]
            CONFIG_FILE.write_text(
                json.dumps(current, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _append_log(self, msg: str) -> None:
        def apply():
            self._log_text.insert("end", msg + "\n")
            self._log_text.see("end")
        try:
            self.after(0, apply)
        except Exception:
            pass


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")
