"""Vue Le Convoi — importer une liste de prospects (PDF/Word/Excel/Image/Texte),
extraire les champs, générer des messages personnalisés, envoyer en mode
auto ou validation.

Flux UI à étapes (stack vertical scrollable, chaque étape activée
quand la précédente est OK) :

    1. Import   : drop zone + bouton parcourir + aperçu fichier
    2. Extract  : bouton "Extraire" → tableau éditable des prospects
    3. Compose  : catalogue d'offres + brief IA + bouton "Générer les mails"
    4. Send     : mode auto/validation + cap + délai + bouton "Lancer le convoi"
    5. Results  : compteurs + journal + liste drafts en attente

Toute la persistance passe par convoy_runner.ConvoyCampaign (un fichier JSON
par campagne dans ~/.triskell-command/convoy/campaigns/).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

# tkinterdnd2 est optionnel — si absent, on bascule en "Parcourir…" only.
try:
    from tkinterdnd2 import DND_FILES as _DND_FILES  # type: ignore
    _HAS_DND = True
except Exception:
    _DND_FILES = None
    _HAS_DND = False

from .. import theme as T
from ..integrations import catalog_repo, convoy_ai, convoy_parser, convoy_runner
from ..widgets.components import (
    Card,
    EmptyState,
    PrimaryButton,
    SecondaryButton,
    StatCard,
    StatusPill,
    Toast,
    ViewHeader,
)
from .base import BaseView

logger = logging.getLogger(__name__)


# NOTE : les valeurs par défaut du catalogue vivent maintenant dans
# `integrations.catalog_repo.DEFAULTS`. La vue n'embarque plus de copie
# locale — chaque nouvelle campagne lit le catalogue CENTRAL via
# `catalog_repo.get_catalog()` au moment de sa création.


class ConvoyView(BaseView):
    title = "Importer une liste"
    subtitle = (
        "Glisse un PDF, Word, Excel ou image avec ta liste de prospects. "
        "L'app extrait les contacts, adapte ton catalogue à chacun, "
        "et prépare les mails — en auto ou en validation."
    )

    def build(self) -> None:
        c = self.colors

        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_MD))

        SecondaryButton(
            header.actions, colors=c, icon="refresh", text="Recharger",
            command=self._refresh_campaign_list,
        ).pack(side="left", padx=(0, T.SPACE_SM))
        PrimaryButton(
            header.actions, colors=c, icon="plus", text="Nouvelle campagne",
            command=self._new_campaign,
        ).pack(side="left")

        # 2 colonnes : liste campagnes (gauche) + détail (droite)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))

        # ---- Col gauche : campagnes existantes ----
        left = Card(body, colors=c)
        left.pack(side="left", fill="y", padx=(0, T.SPACE_MD))
        left.configure(width=270)
        left.pack_propagate(False)

        ctk.CTkLabel(
            left, text="Campagnes",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_XS))
        ctk.CTkLabel(
            left, text="Une campagne = 1 fichier importé.",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, anchor="w", wraplength=230, justify="left",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))

        self._list_scroll = ctk.CTkScrollableFrame(
            left, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        self._list_scroll.pack(fill="both", expand=True,
                               padx=T.SPACE_SM, pady=(0, T.SPACE_LG))

        # ---- Col droite : détail / éditeur de campagne courante ----
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        self._detail_scroll = ctk.CTkScrollableFrame(
            right, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        self._detail_scroll.pack(fill="both", expand=True)

        # État courant
        self._campaign: convoy_runner.ConvoyCampaign | None = None
        self._raw_text: str = ""
        self._stop_send: callable | None = None

        # Status bar bas de vue
        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
        ).pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

    def on_show(self) -> None:
        self._refresh_campaign_list()
        if self._campaign is None:
            self._show_empty_detail()

    # ==================================================================
    #   Liste des campagnes (col gauche)
    # ==================================================================
    def _refresh_campaign_list(self) -> None:
        for w in self._list_scroll.winfo_children():
            w.destroy()
        c = self.colors

        campaigns = convoy_runner.list_campaigns()
        if not campaigns:
            ctk.CTkLabel(
                self._list_scroll,
                text="Aucune campagne pour le moment. "
                     "Clique « + Nouvelle campagne » pour commencer.",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_muted, wraplength=230, justify="left",
            ).pack(fill="x", padx=T.SPACE_SM, pady=T.SPACE_MD)
            return

        for camp in campaigns:
            self._make_list_item(camp)

    def _make_list_item(self, camp: convoy_runner.ConvoyCampaign) -> None:
        c = self.colors
        is_active = self._campaign is not None and self._campaign.id == camp.id
        item = ctk.CTkFrame(
            self._list_scroll,
            fg_color=c.panel_hover if is_active else "transparent",
            corner_radius=T.RADIUS_SM,
        )
        item.pack(fill="x", pady=2)

        row = ctk.CTkFrame(item, fg_color="transparent")
        row.pack(fill="x", padx=T.SPACE_SM, pady=T.SPACE_SM)

        # Titre
        title_text = camp.name or "(sans nom)"
        title = ctk.CTkLabel(
            row, text=title_text,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            text_color=c.text_primary, anchor="w",
        )
        title.pack(fill="x", anchor="w")

        # Sous-info : date + counts
        counts = camp.counts()
        sub = (f"{counts['total']} prospect(s) · "
               f"{counts['sent']} envoyé(s) · "
               f"{counts['pending']} en attente")
        sub_lbl = ctk.CTkLabel(
            row, text=sub,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
            text_color=c.text_muted, anchor="w",
        )
        sub_lbl.pack(fill="x", anchor="w", pady=(2, 0))

        for w in (item, row, title, sub_lbl):
            w.bind("<Button-1>", lambda _e, cid=camp.id: self._open_campaign(cid))

    def _open_campaign(self, campaign_id: str) -> None:
        camp = convoy_runner.load_campaign(campaign_id)
        if camp is None:
            self._toast(f"Campagne introuvable : {campaign_id}", kind="warning")
            return
        self._campaign = camp
        self._raw_text = ""
        self._render_detail()
        self._refresh_campaign_list()

    # ==================================================================
    #   Nouvelle campagne
    # ==================================================================
    def _new_campaign(self) -> None:
        from datetime import datetime
        import uuid

        name_default = f"Convoi du {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        camp = convoy_runner.ConvoyCampaign(
            id=uuid.uuid4().hex,
            name=name_default,
            created_at=datetime.now().isoformat(timespec="seconds"),
            source_file="",
            mode="validation",
            user_brief="",
            # Snapshot du catalogue CENTRAL au moment de la création.
            # À chaque génération de mail, on rechargera le catalogue central
            # pour utiliser la version la plus à jour.
            catalog=catalog_repo.get_catalog(),
            drafts=[],
            daily_cap=int(self.app_state.get("outreach", "daily_cap", default=40) or 40),
            delay_seconds=60,
        )
        camp.save()
        self._campaign = camp
        self._raw_text = ""
        self._render_detail()
        self._refresh_campaign_list()

    # ==================================================================
    #   Vide (aucune campagne sélectionnée)
    # ==================================================================
    def _show_empty_detail(self) -> None:
        for w in self._detail_scroll.winfo_children():
            w.destroy()
        EmptyState(
            self._detail_scroll,
            colors=self.colors,
            icon="download",
            title="Charge ta première liste",
            message=(
                "Le Convoi importe ta liste de prospects (chantiers, contacts, "
                "leads), détecte automatiquement leur secteur d'activité, "
                "adapte ton catalogue d'offres à chacun, et envoie des mails "
                "personnalisés — en mode auto ou avec validation un-par-un."
            ),
            cta_text="Nouvelle campagne",
            cta_command=self._new_campaign,
        ).pack(fill="both", expand=True)

    # ==================================================================
    #   Détail d'une campagne (col droite, à étapes)
    # ==================================================================
    def _render_detail(self) -> None:
        for w in self._detail_scroll.winfo_children():
            w.destroy()
        if self._campaign is None:
            self._show_empty_detail()
            return

        # Carte : nom + actions globales
        self._build_header_card()

        # Étape 1 : Import du fichier
        self._build_step_import()

        # Étape 2 : Tableau des prospects extraits
        if self._campaign.drafts or self._raw_text:
            self._build_step_table()

        # Étape 3 : Catalogue + brief + génération
        if self._campaign.drafts or self._raw_text:
            self._build_step_compose()

        # Étape 4 : Mode d'envoi + lancement
        if self._campaign.drafts:
            self._build_step_send()

        # Étape 5 : Résultats / drafts
        if self._campaign.drafts:
            self._build_step_results()

    # ---------- Header ----------
    def _build_header_card(self) -> None:
        c = self.colors
        camp = self._campaign
        card = Card(self._detail_scroll, colors=c)
        card.pack(fill="x", pady=(0, T.SPACE_LG))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=T.SPACE_LG, pady=T.SPACE_LG)

        # Nom de la campagne (éditable inline)
        name_var = ctk.StringVar(value=camp.name)
        name_entry = ctk.CTkEntry(
            row, textvariable=name_var,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM, height=32,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
        )
        name_entry.pack(side="left", fill="x", expand=True)

        def save_name(_e=None):
            camp.name = name_var.get().strip() or camp.name
            camp.save()
            self._refresh_campaign_list()
        name_entry.bind("<FocusOut>", save_name)
        name_entry.bind("<Return>", save_name)

        SecondaryButton(
            row, colors=c, icon="trash", text="Supprimer",
            command=self._delete_current_campaign,
        ).pack(side="right", padx=(T.SPACE_SM, 0))

    def _delete_current_campaign(self) -> None:
        if self._campaign is None:
            return
        ok = convoy_runner.delete_campaign(self._campaign)
        if ok:
            self._toast("Campagne supprimée.", kind="success")
            self._campaign = None
            self._raw_text = ""
            self._render_detail()
            self._refresh_campaign_list()

    # ---------- Étape 1 : Import ----------
    def _build_step_import(self) -> None:
        c = self.colors
        camp = self._campaign

        section = self._make_section(
            "1. Importer la liste",
            "Glisse un fichier PDF, Word, Excel, CSV, image (OCR) ou texte brut. "
            "Triskell détectera le format et extraira le texte.",
        )

        # Drop zone visuelle
        drop = ctk.CTkFrame(
            section, fg_color=c.bg_alt,
            border_color=c.border_strong, border_width=2,
            corner_radius=T.RADIUS_MD, height=140,
        )
        drop.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))
        drop.pack_propagate(False)

        msg = (f"📂 {Path(camp.source_file).name}"
               if camp.source_file
               else "Glisse un fichier ici, ou clique « Parcourir »")
        ctk.CTkLabel(
            drop, text=msg,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_secondary,
        ).pack(expand=True)

        # Drag & drop si tkinterdnd2 dispo (sinon : juste le bouton)
        if _HAS_DND:
            try:
                drop.drop_target_register(_DND_FILES)  # type: ignore
                drop.dnd_bind("<<Drop>>",  # type: ignore
                              lambda e: self._handle_drop(e.data))
            except Exception as exc:
                logger.debug("DnD non activé : %s", exc)

        btns = ctk.CTkFrame(section, fg_color="transparent")
        btns.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        SecondaryButton(
            btns, colors=c, icon="search", text="Parcourir…",
            command=self._pick_file,
        ).pack(side="left")
        if camp.source_file:
            PrimaryButton(
                btns, colors=c, icon="play", text="Extraire les prospects",
                command=self._launch_extraction,
            ).pack(side="left", padx=(T.SPACE_SM, 0))

        # Aperçu texte brut (si chargé)
        if self._raw_text:
            ctk.CTkLabel(
                section, text="Aperçu du texte extrait :",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
                text_color=c.text_secondary, anchor="w",
            ).pack(fill="x", padx=T.SPACE_LG, pady=(0, 2))
            preview = ctk.CTkTextbox(
                section, height=120,
                fg_color=c.bg_alt, text_color=c.text_primary,
                border_color=c.border, border_width=1,
                corner_radius=T.RADIUS_SM,
                font=(T.FONT_FAMILY_MONO, T.FONT_SIZE_SMALL),
                wrap="word",
            )
            preview.insert("1.0", self._raw_text[:4000]
                           + ("\n\n[…texte tronqué pour l'aperçu…]"
                              if len(self._raw_text) > 4000 else ""))
            preview.configure(state="disabled")
            preview.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

    def _pick_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Choisir un fichier de prospects",
            filetypes=[
                ("Tous formats supportés",
                 "*.pdf *.docx *.xlsx *.xlsm *.csv *.tsv *.txt *.md "
                 "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
                ("PDF", "*.pdf"),
                ("Word", "*.docx"),
                ("Excel", "*.xlsx *.xlsm"),
                ("CSV / TSV", "*.csv *.tsv"),
                ("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
                ("Texte", "*.txt *.md"),
            ],
        )
        if path:
            self._set_source_file(path)

    def _handle_drop(self, raw: str) -> None:
        # tkinterdnd2 renvoie {chemin avec espaces} parfois — on nettoie
        path = raw.strip().strip("{}")
        if path:
            self._set_source_file(path)

    def _set_source_file(self, path: str) -> None:
        if self._campaign is None:
            return
        self._campaign.source_file = path
        self._campaign.save()
        self._raw_text = ""
        self._render_detail()

    def _launch_extraction(self) -> None:
        if self._campaign is None or not self._campaign.source_file:
            return
        camp = self._campaign

        self._set_status("Lecture du fichier…")

        def worker():
            try:
                parsed = convoy_parser.parse_file(camp.source_file)
            except convoy_parser.ParserError as exc:
                self._set_status(f"✗ {exc}", kind="danger")
                self._toast(str(exc), kind="danger")
                return
            except Exception as exc:
                self._set_status(f"✗ Erreur lecture : {exc}", kind="danger")
                return

            text = parsed.get("text", "")
            rows = parsed.get("rows", []) or []
            warnings = parsed.get("warnings", [])
            self._raw_text = text
            for w in warnings:
                logger.info("Convoy warning: %s", w)

            # Fast path : si le fichier est déjà tabulaire (csv/xlsx) avec
            # une colonne email reconnaissable, on mappe directement sans IA.
            prospects = convoy_parser.rows_to_prospects(rows) if rows else []
            if prospects:
                self._set_status(
                    f"Mapping direct : {len(prospects)} prospect(s) détecté(s)…"
                )
            else:
                # Fallback IA pour les formats non tabulaires (PDF/Word/image/texte)
                # ou xlsx sans colonne email exploitable.
                basics = convoy_parser.harvest_basics(text)
                self._set_status("Extraction des prospects par IA…")

                ai_cfg = self._ai_config()
                if not ai_cfg:
                    self._set_status(
                        "✗ Configure une clé IA dans Réglages avant d'extraire.",
                        kind="danger",
                    )
                    self.after(0, self._render_detail)
                    return

                try:
                    prospects = convoy_ai.extract_prospects(
                        text,
                        emails_hint=basics.get("emails", []),
                        phones_hint=basics.get("phones", []),
                        urls_hint=basics.get("urls", []),
                        provider=ai_cfg["provider"],
                        model=ai_cfg["model"],
                        api_keys=ai_cfg["api_keys"],
                    )
                except Exception as exc:
                    self._set_status(f"✗ IA : {exc}", kind="danger")
                    self.after(0, self._render_detail)
                    return

            # Crée un draft "vide" par prospect (corps généré à l'étape 3)
            import uuid
            new_drafts = []
            for p in prospects:
                new_drafts.append(convoy_runner.ConvoyDraft(
                    id=uuid.uuid4().hex,
                    prospect=p,
                ))
            camp.drafts = new_drafts
            camp.save()
            self._set_status(
                f"✓ {len(prospects)} prospect(s) extrait(s).",
                kind="success",
            )
            self.after(0, self._render_detail)
            self.after(0, self._refresh_campaign_list)

        threading.Thread(target=worker, daemon=True).start()

    # ---------- Étape 2 : Tableau éditable ----------
    def _build_step_table(self) -> None:
        c = self.colors
        camp = self._campaign
        if not camp.drafts:
            return

        section = self._make_section(
            "2. Vérifier les prospects extraits",
            "Édite ce qui doit l'être. Les lignes en rouge n'ont pas d'email "
            "et seront ignorées. Les lignes en jaune sont incomplètes mais "
            "envoyables.",
        )

        # Compteurs
        ok = warn = err = 0
        for d in camp.drafts:
            v = convoy_ai.validate_prospect(d.prospect)
            if v["severity"] == "ok":
                ok += 1
            elif v["severity"] == "warning":
                warn += 1
            else:
                err += 1

        stats = ctk.CTkFrame(section, fg_color="transparent")
        stats.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))
        for label, value, color in [
            ("Complets", str(ok), c.success),
            ("Incomplets", str(warn), c.warning),
            ("Sans email", str(err), c.danger),
        ]:
            sc = StatCard(
                stats, label=label, value=value, accent=color, colors=c,
            )
            sc.pack(side="left", expand=True, fill="x", padx=(0, T.SPACE_SM))

        # Tableau
        cols = ["raison_sociale", "prenom", "email", "telephone",
                "ville", "secteur"]
        col_widths = [180, 90, 200, 110, 110, 140]
        col_labels = ["Entreprise", "Prénom", "Email", "Téléphone",
                      "Ville", "Secteur"]

        # Header
        head = ctk.CTkFrame(section, fg_color=c.bg_alt, corner_radius=T.RADIUS_SM)
        head.pack(fill="x", padx=T.SPACE_LG, pady=(0, 2))
        for i, lab in enumerate(col_labels):
            ctk.CTkLabel(
                head, text=lab,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                text_color=c.text_muted, anchor="w", width=col_widths[i],
            ).pack(side="left", padx=4, pady=6)

        rows_frame = ctk.CTkFrame(section, fg_color="transparent")
        rows_frame.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        PREVIEW_LIMIT = 15
        for d in camp.drafts[:PREVIEW_LIMIT]:
            self._make_table_row(rows_frame, d, cols, col_widths)

        remaining = len(camp.drafts) - PREVIEW_LIMIT
        if remaining > 0:
            ctk.CTkLabel(
                rows_frame,
                text=f"+ {remaining} autre(s) prospect(s) — la liste complète est visible et éditable plus bas (étape 5).",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "italic"),
                text_color=c.text_muted, anchor="w",
            ).pack(fill="x", padx=4, pady=(T.SPACE_SM, 0))

    def _make_table_row(self, parent, draft, cols, col_widths) -> None:
        c = self.colors
        v = convoy_ai.validate_prospect(draft.prospect)
        bg = c.panel
        if v["severity"] == "warning":
            bg = "#3a3422"  # ambre profond, lisible en dark
        elif v["severity"] == "error":
            bg = "#3a2222"  # rouge profond

        row = ctk.CTkFrame(parent, fg_color=bg, corner_radius=T.RADIUS_SM)
        row.pack(fill="x", pady=1)

        for i, key in enumerate(cols):
            entry = ctk.CTkEntry(
                row,
                fg_color="transparent",
                text_color=c.text_primary,
                border_width=0,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                width=col_widths[i],
                height=28,
            )
            entry.insert(0, draft.prospect.get(key, ""))
            entry.pack(side="left", padx=4, pady=2)

            def on_change(_e, k=key, e=entry, dr=draft):
                dr.prospect[k] = e.get().strip()
                if self._campaign:
                    self._campaign.save()
            entry.bind("<FocusOut>", on_change)

    # ---------- Étape 3 : Catalogue + brief + génération ----------
    def _build_step_compose(self) -> None:
        c = self.colors
        camp = self._campaign

        section = self._make_section(
            "3. Catalogue d'offres + instructions à l'IA",
            "Catalogue CENTRAL — modifié ici, il s'applique à toutes tes "
            "campagnes (présentes et futures). Le Convoi pioche dans ce "
            "catalogue l'offre dont les mots-clés matchent le secteur de "
            "chaque prospect. Format : « Nom | Pitch | mots-clés (virgules) | URL ».",
        )

        # Catalogue (éditeur multi-ligne, parsé en CSV à la sauvegarde).
        # On lit TOUJOURS le central, pas le snapshot de la campagne.
        ctk.CTkLabel(
            section, text="Catalogue d'offres (central, partagé)",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, 2))

        central_catalog = catalog_repo.get_catalog()
        catalog_text = "\n".join(
            f"{o.get('name','')} | {o.get('pitch','')} | "
            f"{o.get('keywords','')} | {o.get('url','')}"
            for o in central_catalog
        )
        cat_box = ctk.CTkTextbox(
            section, height=110,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_MONO, T.FONT_SIZE_SMALL),
            wrap="word",
        )
        cat_box.insert("1.0", catalog_text)
        cat_box.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))

        # Brief utilisateur
        ctk.CTkLabel(
            section, text="Tes instructions à l'IA (ton, contexte, contraintes)",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_SM, 2))
        brief_box = ctk.CTkTextbox(
            section, height=110,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            wrap="word",
        )
        brief_box.insert("1.0", camp.user_brief)
        brief_box.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))

        # Boutons : sauver le brief, générer les mails
        btns = ctk.CTkFrame(section, fg_color="transparent")
        btns.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_SM, T.SPACE_LG))

        def save_compose():
            camp.user_brief = brief_box.get("1.0", "end").rstrip()
            new_catalog = _parse_catalog(cat_box.get("1.0", "end"))
            # 1. Sauvegarde dans le catalogue CENTRAL (toutes campagnes)
            catalog_repo.set_catalog(new_catalog)
            # 2. Snapshot dans la campagne courante (pour traçabilité historique)
            camp.catalog = new_catalog
            camp.save()
            self._toast(
                "Catalogue central mis à jour + brief enregistré.",
                kind="success",
            )

        SecondaryButton(
            btns, colors=c, icon="save", text="Enregistrer",
            command=save_compose,
        ).pack(side="left")
        SecondaryButton(
            btns, colors=c, icon="sparkle", text="Tester (5)",
            command=lambda: self._generate_all_messages(brief_box, cat_box, limit=5),
        ).pack(side="left", padx=(T.SPACE_SM, 0))
        PrimaryButton(
            btns, colors=c, icon="sparkle", text="Générer tous les mails",
            command=lambda: self._generate_all_messages(brief_box, cat_box),
        ).pack(side="left", padx=(T.SPACE_SM, 0))

    def _generate_all_messages(self, brief_box, cat_box, *, limit: int | None = None) -> None:
        camp = self._campaign
        if camp is None:
            return
        camp.user_brief = brief_box.get("1.0", "end").rstrip()
        # On relit le contenu de la zone de texte (= source de vérité UI),
        # on le pousse dans le catalogue CENTRAL, et on snapshot dans la
        # campagne pour garder trace de la version utilisée.
        new_catalog = _parse_catalog(cat_box.get("1.0", "end"))
        catalog_repo.set_catalog(new_catalog)
        camp.catalog = new_catalog
        camp.save()

        ai_cfg = self._ai_config()
        if not ai_cfg:
            self._set_status(
                "✗ Configure une clé IA dans Réglages.", kind="danger",
            )
            return

        sender = (self.app_state.get("outreach", "from_name", default="")
                  or self.app_state.get("outreach", "mon_prenom", default="")
                  or "Jordan")

        # Filtre uniquement les drafts qui ont un email valide
        targets = [d for d in camp.drafts
                   if convoy_ai.validate_prospect(d.prospect)["ok"]]
        if not targets:
            self._toast("Aucun prospect avec email exploitable.", kind="warning")
            return
        if limit is not None and limit > 0:
            targets = targets[:limit]

        self._set_status(f"Génération de {len(targets)} mails…")

        def worker():
            for i, draft in enumerate(targets, 1):
                try:
                    msg = convoy_ai.generate_message(
                        draft.prospect,
                        catalog=camp.catalog,
                        sender_name=sender,
                        user_brief=camp.user_brief,
                        provider=ai_cfg["provider"],
                        model=ai_cfg["model"],
                        api_keys=ai_cfg["api_keys"],
                    )
                    draft.subject = msg.get("subject", "")
                    draft.body = msg.get("body", "")
                    draft.body_html = msg.get("body_html", "")
                    draft.offer_name = msg.get("offer_name", "")
                    self._set_status(
                        f"  ({i}/{len(targets)}) {draft.prospect.get('email','')} OK"
                    )
                except Exception as exc:
                    draft.error = f"génération échouée : {exc}"
                    self._set_status(
                        f"  ({i}/{len(targets)}) ✗ {exc}", kind="danger",
                    )
                camp.save()

            self._set_status("✓ Génération terminée.", kind="success")
            self.after(0, self._render_detail)

        threading.Thread(target=worker, daemon=True).start()

    # ---------- Étape 4 : Mode + envoi ----------
    def _build_step_send(self) -> None:
        c = self.colors
        camp = self._campaign

        section = self._make_section(
            "4. Mode d'envoi",
            "AUTO : envoie tout après confirmation. "
            "VALIDATION : tu valides chaque mail un par un avant qu'il parte.",
        )

        row1 = ctk.CTkFrame(section, fg_color="transparent")
        row1.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))
        ctk.CTkLabel(
            row1, text="Mode",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, width=160, anchor="w",
        ).pack(side="left")
        mode_var = ctk.StringVar(value=camp.mode)
        mode_menu = ctk.CTkOptionMenu(
            row1, values=["validation", "auto"], variable=mode_var,
            fg_color=c.bg_alt, button_color=c.accent,
            button_hover_color=c.accent_hover, text_color=c.text_primary,
            corner_radius=T.RADIUS_SM, height=30,
        )
        mode_menu.pack(side="left", fill="x", expand=True)

        row2 = ctk.CTkFrame(section, fg_color="transparent")
        row2.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))
        ctk.CTkLabel(
            row2, text="Cap quotidien (mails / jour)",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, width=160, anchor="w",
        ).pack(side="left")
        cap_entry = ctk.CTkEntry(
            row2, fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM, height=30,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
        )
        cap_entry.insert(0, str(camp.daily_cap))
        cap_entry.pack(side="left", fill="x", expand=True)

        row3 = ctk.CTkFrame(section, fg_color="transparent")
        row3.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))
        ctk.CTkLabel(
            row3, text="Délai entre 2 envois (secondes)",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, width=160, anchor="w",
        ).pack(side="left")
        delay_entry = ctk.CTkEntry(
            row3, fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM, height=30,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
        )
        delay_entry.insert(0, str(camp.delay_seconds))
        delay_entry.pack(side="left", fill="x", expand=True)

        row4 = ctk.CTkFrame(section, fg_color="transparent")
        row4.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        ctk.CTkLabel(
            row4, text="Démarrer à (laisser vide = maintenant)",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, width=160, anchor="w",
        ).pack(side="left")
        sched_entry = ctk.CTkEntry(
            row4, fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM, height=30,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            placeholder_text="ex: 2026-05-06 08:00",
        )
        if camp.schedule_at:
            sched_entry.insert(0, camp.schedule_at)
        sched_entry.pack(side="left", fill="x", expand=True)

        # Boutons
        btns = ctk.CTkFrame(section, fg_color="transparent")
        btns.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        def save_send_settings():
            camp.mode = mode_var.get()
            try:
                camp.daily_cap = max(1, int(cap_entry.get() or 40))
            except ValueError:
                camp.daily_cap = 40
            try:
                camp.delay_seconds = max(5, int(delay_entry.get() or 60))
            except ValueError:
                camp.delay_seconds = 60
            camp.schedule_at = sched_entry.get().strip()
            camp.save()
            self._toast("Réglages d'envoi enregistrés.", kind="success")

        SecondaryButton(
            btns, colors=c, icon="save", text="Enregistrer",
            command=save_send_settings,
        ).pack(side="left")

        if any(d.status == "approved" for d in camp.drafts) or camp.mode == "auto":
            launch_label = "Lancer le convoi"
        else:
            launch_label = "Préparer & valider"

        PrimaryButton(
            btns, colors=c, icon="play", text=launch_label,
            command=lambda: self._start_convoy(save_send_settings),
        ).pack(side="left", padx=(T.SPACE_SM, 0))

    def _start_convoy(self, save_first) -> None:
        camp = self._campaign
        if camp is None:
            return
        save_first()

        smtp_cfg = self._smtp_config()
        if not smtp_cfg:
            self._set_status(
                "✗ Configure ton compte mail (envoi) dans Réglages.",
                kind="danger",
            )
            return

        # En mode auto, on approuve tout. En validation, l'utilisateur clique
        # individuellement sur chaque draft puis revient lancer.
        if camp.mode == "auto":
            n = convoy_runner.approve_all_pending(camp)
            self._set_status(f"{n} brouillon(s) approuvé(s) automatiquement.")

        approved = [d for d in camp.drafts if d.status == "approved"]
        if not approved:
            self._toast(
                "Aucun brouillon approuvé. Valide-les un par un en mode "
                "validation, ou bascule sur Mode = auto puis relance.",
                kind="warning",
            )
            return

        self._set_status(f"Envoi de {len(approved)} mail(s)…")

        def progress(line: str):
            self._set_status(line)

        thread, stop_fn = convoy_runner.start_send_thread(
            camp, smtp_cfg=smtp_cfg, progress=progress,
        )
        self._stop_send = stop_fn

        def watch():
            thread.join()
            self._stop_send = None
            self.after(0, self._render_detail)
            self.after(0, self._refresh_campaign_list)

        threading.Thread(target=watch, daemon=True).start()

    # ---------- Étape 5 : Résultats / drafts ----------
    def _build_step_results(self) -> None:
        c = self.colors
        camp = self._campaign

        section = self._make_section(
            "5. Brouillons & résultats",
            "Mails préparés. En mode validation, valide ou rejette ici. "
            "Les envoyés sont marqués ✓.",
        )

        counts = camp.counts()
        bar = ctk.CTkFrame(section, fg_color="transparent")
        bar.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))
        for lab, val, col in [
            ("Total", counts["total"], c.text_primary),
            ("En attente", counts["pending"], c.warning),
            ("Approuvés", counts["approved"], c.info),
            ("Envoyés", counts["sent"], c.success),
            ("Échecs", counts["failed"], c.danger),
            ("Rejetés", counts["rejected"], c.text_muted),
        ]:
            sc = StatCard(bar, label=lab, value=str(val), accent=col, colors=c)
            sc.pack(side="left", expand=True, fill="x", padx=(0, T.SPACE_SM))

        # Liste des drafts
        for d in camp.drafts:
            self._make_draft_card(section, d)

    def _make_draft_card(self, parent, draft) -> None:
        c = self.colors
        camp = self._campaign

        card = ctk.CTkFrame(
            parent, fg_color=c.bg_alt,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
        )
        card.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))

        # En-tête : destinataire + statut
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=T.SPACE_MD, pady=(T.SPACE_SM, T.SPACE_XS))

        recipient = (draft.prospect.get("raison_sociale", "")
                     or draft.prospect.get("prenom", "")
                     or draft.prospect.get("email", "(sans destinataire)"))
        ctk.CTkLabel(
            head,
            text=f"{recipient}  ·  {draft.prospect.get('email', '')}",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(side="left", fill="x", expand=True)

        StatusPill(
            head, status=_status_to_pill(draft.status), colors=c,
        ).pack(side="right")

        # Si pas de body : section vide
        if not draft.body and not draft.subject:
            ctk.CTkLabel(
                card, text="(aucun message généré — clique « Générer tous les mails » à l'étape 3)",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_muted,
            ).pack(fill="x", padx=T.SPACE_MD, pady=(0, T.SPACE_SM))
            return

        # Sujet (éditable)
        subj_var = ctk.StringVar(value=draft.subject)
        subj_entry = ctk.CTkEntry(
            card, textvariable=subj_var,
            fg_color=c.panel, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM, height=30,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
        )
        subj_entry.pack(fill="x", padx=T.SPACE_MD, pady=(0, 4))

        # Offre détectée
        if draft.offer_name:
            ctk.CTkLabel(
                card,
                text=f"Offre proposée : {draft.offer_name}",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                text_color=c.accent, anchor="w",
            ).pack(fill="x", padx=T.SPACE_MD, pady=(0, 4))

        # Corps (éditable)
        body_box = ctk.CTkTextbox(
            card, height=120,
            fg_color=c.panel, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            wrap="word",
        )
        body_box.insert("1.0", draft.body)
        body_box.pack(fill="x", padx=T.SPACE_MD, pady=(0, T.SPACE_SM))
        if draft.status in ("sent", "failed", "rejected"):
            subj_entry.configure(state="disabled")
            body_box.configure(state="disabled")

        # Erreur (le cas échéant)
        if draft.error:
            ctk.CTkLabel(
                card, text=f"⚠ {draft.error}",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                text_color=c.danger, anchor="w", wraplength=600, justify="left",
            ).pack(fill="x", padx=T.SPACE_MD, pady=(0, 4))

        # Actions selon statut
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=T.SPACE_MD, pady=(0, T.SPACE_MD))

        if draft.status in ("pending", "approved"):
            def save_edits():
                convoy_runner.update_draft(
                    camp, draft.id,
                    subject=subj_var.get(),
                    body=body_box.get("1.0", "end").rstrip(),
                )

            SecondaryButton(
                actions, colors=c, icon="trash", text="Rejeter",
                command=lambda dr=draft: self._reject_draft(dr.id),
            ).pack(side="right", padx=(T.SPACE_SM, 0))

            if draft.status == "pending":
                PrimaryButton(
                    actions, colors=c, icon="check", text="Approuver",
                    command=lambda dr=draft: (save_edits(),
                                              self._approve_draft(dr.id)),
                ).pack(side="right")
            else:
                ctk.CTkLabel(
                    actions, text="✓ approuvé — partira au prochain lancement",
                    font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                    text_color=c.info,
                ).pack(side="right")

            SecondaryButton(
                actions, colors=c, icon="save", text="Enregistrer édits",
                command=save_edits,
            ).pack(side="right", padx=(T.SPACE_SM, 0))

    def _approve_draft(self, draft_id: str) -> None:
        if self._campaign:
            convoy_runner.approve_draft(self._campaign, draft_id)
            self._render_detail()

    def _reject_draft(self, draft_id: str) -> None:
        if self._campaign:
            convoy_runner.reject_draft(self._campaign, draft_id)
            self._render_detail()

    # ==================================================================
    #   Helpers communs
    # ==================================================================
    def _make_section(self, title: str, subtitle: str = "") -> Card:
        c = self.colors
        card = Card(self._detail_scroll, colors=c)
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

    def _ai_config(self) -> dict | None:
        prov = self.app_state.get("ai", "selected_provider", default="anthropic")
        model = self.app_state.get("ai", "selected_model", default="claude-sonnet-4-5")
        keys = self.app_state.get("ai", "api_keys", default={}) or {}
        if not keys.get(prov):
            return None
        return {"provider": prov, "model": model, "api_keys": keys}

    def _smtp_config(self) -> dict | None:
        o = self.app_state.get("outreach", default={}) or {}
        required = ("smtp_host", "smtp_port", "smtp_user", "smtp_password",
                    "from_email")
        if any(not o.get(k) for k in required):
            return None
        return {
            "smtp_host": o.get("smtp_host"),
            "smtp_port": int(o.get("smtp_port", 587)),
            "smtp_user": o.get("smtp_user"),
            "smtp_password": o.get("smtp_password"),
            "from_email": o.get("from_email"),
            "from_name": o.get("from_name", ""),
        }

    def _set_status(self, msg: str, *, kind: str = "info") -> None:
        def apply():
            self._status_var.set(msg)
        try:
            self.after(0, apply)
        except Exception:
            self._status_var.set(msg)

    def _toast(self, msg: str, *, kind: str = "info") -> None:
        try:
            top = self.winfo_toplevel()
            t = Toast(top, text=msg, kind=kind, colors=self.colors)
            t.place(relx=0.5, rely=0.05, anchor="n")
        except Exception:
            self._set_status(msg, kind=kind)


# ---------------------------------------------------------------------------
# Helpers libres
# ---------------------------------------------------------------------------
def _status_to_pill(status: str) -> str:
    """Mappe un statut Convoi vers une classe StatusPill connue."""
    return {
        "pending": "new",
        "approved": "qualified",
        "sent": "won",
        "failed": "lost",
        "rejected": "refused",
    }.get(status, "new")


def _parse_catalog(text: str) -> list[dict[str, str]]:
    """Parse le textarea catalogue : 1 offre par ligne, '|' comme séparateur."""
    out: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        # Au moins le nom
        name = parts[0] if parts else ""
        if not name:
            continue
        out.append({
            "name": name,
            "pitch": parts[1] if len(parts) > 1 else "",
            "keywords": parts[2] if len(parts) > 2 else "",
            "url": parts[3] if len(parts) > 3 else "",
        })
    return out
