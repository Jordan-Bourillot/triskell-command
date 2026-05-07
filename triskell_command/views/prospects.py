"""Vue Prospection — table des prospects + recherche multi-source."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from .. import theme as T
from ..widgets.components import (
    Card,
    PrimaryButton,
    SecondaryButton,
    StatCard,
    StatusPill,
    ViewHeader,
)
from ..widgets.window_icon import apply_window_icon
from .base import BaseView


class ProspectsView(BaseView):
    title = "Trouver tes prospects"
    subtitle = "Toutes tes pistes : créateurs sur 9 plateformes, entreprises FR, commerces locaux."

    def build(self) -> None:
        c = self.colors
        # Header
        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_LG))

        SecondaryButton(header.actions, colors=c, icon="refresh", text="Rafraîchir",
                        command=self._refresh).pack(side="left", padx=(0, T.SPACE_SM))
        SecondaryButton(header.actions, colors=c, icon="trash", text="Vider",
                        command=self._wipe_crm).pack(side="left", padx=(0, T.SPACE_SM))
        SecondaryButton(header.actions, colors=c, icon="download", text="Importer Le Dénicheur",
                        command=self._import_denicheur).pack(side="left", padx=(0, T.SPACE_SM))
        SecondaryButton(header.actions, colors=c, icon="globe", text="Enrichir",
                        command=self._open_enrich_dialog).pack(side="left", padx=(0, T.SPACE_SM))
        SecondaryButton(header.actions, colors=c, icon="plus", text="Nouveau",
                        command=self._new_prospect).pack(side="left", padx=(0, T.SPACE_SM))
        PrimaryButton(header.actions, colors=c, icon="search", text="Nouvelle recherche",
                      command=self._open_search_dialog).pack(side="left")

        # Stats
        self._stats_row = ctk.CTkFrame(self, fg_color="transparent")
        self._stats_row.pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))
        self._stat_cards: dict[str, StatCard] = {}
        for key, label, accent in [
            ("total",     "Total prospects", c.text_primary),
            ("verified",  "Vérifiés",        c.success),
            ("with_email","Avec email",      c.info),
            ("contacted", "Déjà contactés",  c.warning),
        ]:
            card = StatCard(self._stats_row, label=label, value="—",
                            accent=accent, colors=c)
            card.pack(side="left", expand=True, fill="x", padx=T.SPACE_SM)
            self._stat_cards[key] = card

        # Filtre rapide — entry pleine largeur avec icône loupe et placeholder
        filter_row = ctk.CTkFrame(self, fg_color="transparent")
        filter_row.pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_MD))
        # Icône loupe à gauche pour signaler que c'est un filtre
        from ..widgets import icons as _I
        icon_lbl = ctk.CTkLabel(filter_row, text="", width=24)
        icon_lbl.pack(side="left", padx=(0, T.SPACE_SM))
        _search_icon = _I.get_icon("search", c.text_muted, size=16)
        if _search_icon is not None:
            icon_lbl.configure(image=_search_icon)
            icon_lbl._icon_ref = _search_icon
        self._filter_var = ctk.StringVar(value="")
        ctk.CTkEntry(filter_row, textvariable=self._filter_var,
                     placeholder_text="Filtrer par nom, email, ville…",
                     fg_color=c.bg_alt, text_color=c.text_primary,
                     border_color=c.border_strong, border_width=1,
                     corner_radius=T.RADIUS_SM, height=34,
                     font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
                     ).pack(side="left", fill="x", expand=True)
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())

        # Table de prospects
        self._build_table()

        # Status bar
        self._status_var = ctk.StringVar(value="Prêt.")
        ctk.CTkLabel(
            self,
            textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
            anchor="w",
        ).pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

        # Charge initial
        self._all_prospects: list = []

    def on_show(self) -> None:
        self._refresh()

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------
    def _build_table(self) -> None:
        c = self.colors
        body = Card(self, colors=c)
        body.pack(fill="both", expand=True, padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

        # ttk.Treeview customisé pour matcher le thème Triskell
        style = ttk.Style()
        style.theme_use("clam")

        # Tronc principal
        style.configure(
            "Triskell.Treeview",
            background=c.panel,
            foreground=c.text_primary,
            fieldbackground=c.panel,
            bordercolor=c.border,
            borderwidth=0,
            rowheight=36,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
        )
        # En-têtes
        style.configure(
            "Triskell.Treeview.Heading",
            background=c.bg_alt,
            foreground=c.text_muted,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            relief="flat",
            borderwidth=0,
            padding=(T.SPACE_SM, T.SPACE_SM),
        )
        style.map(
            "Triskell.Treeview.Heading",
            background=[("active", c.bg_alt)],
        )
        # Sélection : indigo doux + texte blanc
        style.map(
            "Triskell.Treeview",
            background=[("selected", c.accent)],
            foreground=[("selected", "#FFFFFF")],
        )

        # SCROLLBAR sombre custom (Triskell)
        style.configure(
            "Triskell.Vertical.TScrollbar",
            background=c.bg_alt,
            troughcolor=c.bg,
            bordercolor=c.bg,
            arrowcolor=c.text_muted,
            gripcount=0,
            relief="flat",
        )
        style.map(
            "Triskell.Vertical.TScrollbar",
            background=[("active", c.border_strong),
                        ("pressed", c.accent)],
            arrowcolor=[("active", c.text_secondary)],
        )

        wrapper = tk.Frame(body, bg=c.panel)
        wrapper.pack(fill="both", expand=True, padx=T.SPACE_LG,
                     pady=(T.SPACE_SM, T.SPACE_LG))

        cols = ("name", "email", "phone", "city", "industry", "source", "status")
        self._tree = ttk.Treeview(
            wrapper,
            columns=cols,
            show="headings",
            style="Triskell.Treeview",
            selectmode="extended",
        )
        for col, label, width in [
            ("name",     "Nom",        260),
            ("email",    "Email",      220),
            ("phone",    "Téléphone",  130),
            ("city",     "Ville",      140),
            ("industry", "Secteur",    160),
            ("source",   "Source",     100),
            ("status",   "Statut",     100),
        ]:
            self._tree.heading(col, text=label.upper(), anchor="w")
            self._tree.column(col, width=width, anchor="w")

        # Zébrures : alternance subtle panel / bg_alt
        self._tree.tag_configure("oddrow", background=c.panel)
        self._tree.tag_configure("evenrow", background=c.bg_alt)

        sb = ttk.Scrollbar(
            wrapper, orient="vertical",
            command=self._tree.yview,
            style="Triskell.Vertical.TScrollbar",
        )
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Double-clic = ouvre le dialog d'édition
        self._tree.bind("<Double-1>", self._on_row_double_click)
        # Clic-droit = menu contextuel
        self._tree.bind("<Button-3>", self._on_row_right_click)
        # Map iid Treeview → Prospect
        self._row_to_prospect: dict[str, "Prospect"] = {}

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        try:
            from triskell_core.prospect.core.crm import CRM
        except ImportError as e:
            self._status_var.set(f"⚠ Triskell Core introuvable : {e}")
            return

        crm = CRM()
        self._all_prospects = crm.all()
        self._update_stats()
        self._apply_filter()

    def _update_stats(self) -> None:
        prospects = self._all_prospects
        total = len(prospects)
        verified = sum(1 for p in prospects if "site_verified" in (p.tags or []))
        with_email = sum(1 for p in prospects if p.emails)
        contacted = sum(1 for p in prospects
                        if p.status in ("contacted", "replied", "won"))

        # Met à jour les stats cards (nécessite de reconstruire la valeur)
        for key, value in [("total", total), ("verified", verified),
                           ("with_email", with_email), ("contacted", contacted)]:
            self._update_stat_value(key, value)

    def _update_stat_value(self, key: str, value: int) -> None:
        card = self._stat_cards.get(key)
        if not card:
            return
        # Trouve le label de valeur (la 2e CTkLabel dans la card)
        labels = [w for w in card.winfo_children()
                  if isinstance(w, ctk.CTkLabel)]
        if len(labels) >= 2:
            labels[1].configure(text=str(value))

    def _apply_filter(self) -> None:
        f = (self._filter_var.get() or "").lower().strip()

        # Vide le tree + map
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._row_to_prospect.clear()

        idx = 0
        for p in self._all_prospects:
            if f:
                hay = " ".join([
                    p.name or "", p.legal_name or "",
                    " ".join(p.emails or []),
                    p.city or "", p.industry or "",
                ]).lower()
                if f not in hay:
                    continue
            sources = ",".join(sorted({s.name for s in (p.sources or [])}))
            status = p.status or "new"
            zebra = "evenrow" if (idx % 2 == 0) else "oddrow"
            status_dot = {
                "new":       "○",
                "qualified": "●",
                "contacted": "●",
                "replied":   "●",
                "won":       "✓",
                "lost":      "✗",
                "refused":   "✗",
            }.get(status, "○")
            status_display = f"{status_dot}  {status}"
            iid = self._tree.insert(
                "", "end",
                values=(
                    p.name or p.legal_name or "(sans nom)",
                    (p.emails or [""])[0] or "—",
                    (p.phones or [""])[0] or "—",
                    p.city or "—",
                    p.industry or "—",
                    sources or "—",
                    status_display,
                ),
                tags=(zebra,),
            )
            self._row_to_prospect[iid] = p
            idx += 1
        self._status_var.set(f"{len(self._tree.get_children())} prospect(s) affiché(s)")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _import_denicheur(self) -> None:
        self._status_var.set("Import Le Dénicheur en cours…")
        self.update_idletasks()

        def worker():
            try:
                from triskell_core.prospect.core.crm import CRM
                from triskell_core.prospect.sources import denicheur as src
                if not src.is_available():
                    self._set_status("⚠ Aucun fichier ~/.ledenicheur/prospects.json trouvé.",
                                     kind="warning")
                    return
                crm = CRM()
                stats = crm.upsert_many(src.import_all())
                crm.save()
                self._set_status(
                    f"✓ Le Dénicheur : {stats['created']} créés, "
                    f"{stats['merged']} fusionnés. Total : {stats['total']}.",
                    kind="success",
                )
                self.after(0, self._refresh)
            except Exception as e:
                self._set_status(f"✗ Erreur : {e}", kind="danger")

        threading.Thread(target=worker, daemon=True).start()

    def _open_search_dialog(self) -> None:
        SearchDialog(self, on_done=self._refresh)

    def _open_enrich_dialog(self) -> None:
        EnrichDialog(self, on_done=self._refresh)

    def _new_prospect(self) -> None:
        from ..widgets.prospect_dialog import ProspectDialog
        ProspectDialog(
            self,
            prospect=None,
            colors=self.colors,
            on_saved=lambda _p: self._refresh(),
        )

    def _on_row_double_click(self, _event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        prospect = self._row_to_prospect.get(iid)
        if prospect is None:
            return
        from ..widgets.prospect_dialog import ProspectDialog
        ProspectDialog(
            self,
            prospect=prospect,
            colors=self.colors,
            on_saved=lambda _p: self._refresh(),
            on_deleted=lambda _p: self._refresh(),
        )

    def _on_row_right_click(self, event) -> None:
        # Sélectionne la ligne au clic-droit puis ouvre l'édition
        iid = self._tree.identify_row(event.y)
        if iid:
            self._tree.selection_set(iid)
            self._on_row_double_click()

    def _wipe_crm(self) -> None:
        from ..widgets.prospect_dialog import ConfirmDialog
        n = len(self._all_prospects)
        if n == 0:
            self._status_var.set("La liste est déjà vide.")
            return
        confirm = ConfirmDialog(
            self,
            title="Vider toute la liste ?",
            message=(f"Les {n} prospects vont être supprimés de la base "
                     f"partagée Triskell.\nCette action est irréversible. "
                     f"Les prospects d'Obelisk ne sont PAS touchés."),
            colors=self.colors,
        )
        self.wait_window(confirm)
        if not confirm.confirmed:
            return
        try:
            from triskell_core.prospect.core.crm import PROSPECTS_FILE
            if PROSPECTS_FILE.exists():
                PROSPECTS_FILE.unlink()
            self._refresh()
            self._status_var.set(f"✓ Liste vidée ({n} prospects supprimés).")
        except Exception as e:
            self._status_var.set(f"✗ Échec : {e}")

    def _set_status(self, msg: str, *, kind: str = "info") -> None:
        c = self.colors
        color_map = {
            "info": c.text_muted,
            "success": c.success,
            "warning": c.warning,
            "danger": c.danger,
        }
        def apply():
            self._status_var.set(msg)
        self.after(0, apply)


# ----------------------------------------------------------------------
# Dialog : Nouvelle recherche (Sirene + Maps + à venir)
# ----------------------------------------------------------------------
class SearchDialog(ctk.CTkToplevel):
    """Modal pour lancer une recherche : choix source + paramètres."""

    def __init__(self, master, *, on_done):
        super().__init__(master)
        self._parent = master
        self._on_done = on_done
        self._colors = master.colors

        c = self._colors
        self.title("Nouvelle recherche")
        self.geometry("560x520")
        self.minsize(520, 480)
        self.configure(fg_color=c.bg)
        self.transient(master.winfo_toplevel())
        apply_window_icon(self)
        self.after(100, lambda: self.lift())

        # Header
        ctk.CTkLabel(
            self,
            text="🔎 Nouvelle recherche",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TITLE, "bold"),
            text_color=c.text_primary,
        ).pack(anchor="w", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))

        # Source selector
        ctk.CTkLabel(
            self,
            text="Source",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary,
        ).pack(anchor="w", padx=T.SPACE_LG, pady=(T.SPACE_SM, 2))
        self._source_var = ctk.StringVar(value="sirene")
        ctk.CTkOptionMenu(
            self,
            values=["sirene", "maps"],
            variable=self._source_var,
            fg_color=c.bg_alt,
            button_color=c.accent, button_hover_color=c.accent_hover,
            text_color=c.text_primary,
            command=self._on_source_change,
            corner_radius=T.RADIUS_SM,
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Frame qui contient les params spécifiques (rebuild à chaque change source)
        self._params_frame = ctk.CTkFrame(self, fg_color=c.panel,
                                          corner_radius=T.RADIUS_SM,
                                          border_color=c.border, border_width=1)
        self._params_frame.pack(fill="both", expand=True,
                                padx=T.SPACE_LG, pady=T.SPACE_MD)

        # Bouton
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        SecondaryButton(bottom, colors=c, icon="close", text="Annuler",
                        command=self.destroy).pack(side="right", padx=(T.SPACE_SM, 0))
        self._search_btn = PrimaryButton(bottom, colors=c, icon="play", text="Lancer",
                                         command=self._launch)
        self._search_btn.pack(side="right")

        # Status
        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))

        self._params: dict[str, ctk.CTkEntry] = {}
        self._build_sirene_params()

    # ------------------------------------------------------------------
    def _on_source_change(self, _value=None) -> None:
        for w in self._params_frame.winfo_children():
            w.destroy()
        self._params.clear()
        if self._source_var.get() == "sirene":
            self._build_sirene_params()
        else:
            self._build_maps_params()

    def _build_sirene_params(self) -> None:
        c = self._colors
        self._add_field("Code activité (NAF, ex: 43.21A pour électricien)", "naf", "")
        self._add_field("Département (ex: 35 = Ille-et-Vilaine)", "departement", "")
        self._add_field("Code postal", "code_postal", "")
        self._add_field("Mot-clé dans le nom", "query", "")
        self._add_field("Créées depuis (AAAA-MM-JJ, vide = toutes)", "created_since", "")
        self._add_field("Taille (00=0 salarié, 01=1-2…)", "effectif", "00")
        self._add_field("Nombre max de résultats", "max", "100")

    def _build_maps_params(self) -> None:
        self._add_field("Recherche libre (ex: 'boulangerie Rennes')", "query", "")
        self._add_field("Latitude (optionnel)", "lat", "")
        self._add_field("Longitude (optionnel)", "lng", "")
        self._add_field("Rayon en mètres", "radius", "50000")
        self._add_field("Nombre max de résultats", "max", "60")
        ctk.CTkLabel(
            self._params_frame,
            text="⚠ Google Maps nécessite une clé API. Renseigne-la dans Réglages > Sources.",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=self._colors.warning,
            wraplength=460, justify="left",
        ).pack(anchor="w", padx=T.SPACE_LG, pady=(T.SPACE_SM, 0))

    def _add_field(self, label: str, key: str, default: str = "") -> None:
        c = self._colors
        row = ctk.CTkFrame(self._params_frame, fg_color="transparent")
        row.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_SM, 0))
        ctk.CTkLabel(
            row, text=label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w", width=240,
        ).pack(side="left", padx=(0, T.SPACE_SM))
        entry = ctk.CTkEntry(
            row,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_MONO, T.FONT_SIZE_BODY),
            height=28,
        )
        if default:
            entry.insert(0, default)
        entry.pack(side="left", fill="x", expand=True)
        self._params[key] = entry

    # ------------------------------------------------------------------
    def _launch(self) -> None:
        params = {k: v.get().strip() for k, v in self._params.items()}
        source = self._source_var.get()

        self._search_btn.configure(state="disabled", text="…")
        self._status_var.set(f"Recherche {source} en cours…")
        self.update_idletasks()

        def worker():
            try:
                from triskell_core.prospect.core.crm import CRM
                crm = CRM()

                if source == "sirene":
                    from triskell_core.prospect.sources import sirene
                    iterator = sirene.search(
                        activite_principale=params.get("naf", ""),
                        departement=params.get("departement", ""),
                        code_postal=params.get("code_postal", ""),
                        nom_entreprise=params.get("query", ""),
                        min_date_creation=params.get("created_since", ""),
                        tranche_effectif=params.get("effectif", ""),
                        max_results=int(params.get("max") or "100"),
                    )
                elif source == "maps":
                    from triskell_core.prospect.sources import maps
                    if not maps.is_configured():
                        self._set_status("✗ Clé Google Places manquante — vois Réglages",
                                         color=self._colors.danger)
                        self._reset_btn()
                        return
                    iterator = maps.search(
                        text_query=params.get("query", ""),
                        location_bias_lat=float(params["lat"]) if params.get("lat") else None,
                        location_bias_lng=float(params["lng"]) if params.get("lng") else None,
                        radius_m=int(params.get("radius") or "50000"),
                        max_results=int(params.get("max") or "60"),
                    )
                else:
                    self._set_status(f"Source inconnue : {source}",
                                     color=self._colors.danger)
                    self._reset_btn()
                    return

                stats = crm.upsert_many(iterator)
                crm.save()
                self._set_status(
                    f"✓ {source}: {stats['created']} créés, {stats['merged']} fusionnés.",
                    color=self._colors.success,
                )
                self.after(800, self._close_and_refresh)
            except Exception as e:
                self._set_status(f"✗ {e}", color=self._colors.danger)
                self._reset_btn()

        threading.Thread(target=worker, daemon=True).start()

    def _set_status(self, msg: str, *, color: str = "") -> None:
        def apply():
            self._status_var.set(msg)
        self.after(0, apply)

    def _reset_btn(self) -> None:
        def apply():
            self._search_btn.configure(state="normal", text="Lancer")
        self.after(0, apply)

    def _close_and_refresh(self) -> None:
        self._on_done()
        self.destroy()


# ----------------------------------------------------------------------
# Dialog : enrichissement web (footprint + Web Enricher + cross-ref)
# ----------------------------------------------------------------------
class EnrichDialog(ctk.CTkToplevel):
    """Lance l'enrichissement web sur les prospects du CRM."""

    def __init__(self, master, *, on_done):
        super().__init__(master)
        self._parent = master
        self._on_done = on_done
        self._colors = master.colors
        self._stopped = False

        c = self._colors
        self.title("Enrichissement web")
        self.geometry("560x420")
        self.minsize(520, 380)
        self.configure(fg_color=c.bg)
        self.transient(master.winfo_toplevel())
        apply_window_icon(self)
        self.after(100, lambda: self.lift())

        ctk.CTkLabel(
            self, text="Enrichissement web",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TITLE, "bold"),
            text_color=c.text_primary,
        ).pack(anchor="w", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))

        ctk.CTkLabel(
            self,
            text=("Visite les sites des prospects, extrait emails / téléphones / "
                  "adresses, vérifie les mentions légales, et croise avec les "
                  "données Sirene quand c'est possible. ~5-15 secondes par prospect."),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, justify="left", wraplength=500,
        ).pack(anchor="w", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Options
        opts = ctk.CTkFrame(self, fg_color=c.panel,
                            corner_radius=T.RADIUS_SM,
                            border_color=c.border, border_width=1)
        opts.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Max
        row1 = ctk.CTkFrame(opts, fg_color="transparent")
        row1.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_MD, T.SPACE_SM))
        ctk.CTkLabel(row1, text="Max prospects à traiter",
                     font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                     text_color=c.text_secondary, width=200,
                     ).pack(side="left")
        self._max_var = ctk.StringVar(value="50")
        ctk.CTkEntry(
            row1, textvariable=self._max_var,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM, height=28, width=100,
        ).pack(side="left")

        # Footprint
        self._footprint_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            opts, text="Footprint (deviner le site web pour les prospects sans URL)",
            variable=self._footprint_var,
            fg_color=c.accent, hover_color=c.accent_hover,
            text_color=c.text_primary,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))

        # Sans email seulement
        self._no_emails_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            opts, text="Ne traiter que les prospects sans email",
            variable=self._no_emails_var,
            fg_color=c.accent, hover_color=c.accent_hover,
            text_color=c.text_primary,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Progress
        self._progress_var = ctk.DoubleVar(value=0.0)
        self._progress = ctk.CTkProgressBar(
            self, variable=self._progress_var,
            progress_color=c.accent, fg_color=c.bg_alt,
            corner_radius=T.RADIUS_SM, height=12,
        )
        self._progress.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_SM, T.SPACE_XS))
        self._progress.set(0)

        self._progress_label_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._progress_label_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_SM))

        # Bottom
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        self._cancel_btn = SecondaryButton(
            bottom, colors=c, icon="close", text="Fermer",
            command=self._cancel,
        )
        self._cancel_btn.pack(side="right", padx=(T.SPACE_SM, 0))
        self._launch_btn = PrimaryButton(
            bottom, colors=c, icon="play", text="Lancer",
            command=self._launch,
        )
        self._launch_btn.pack(side="right")

    # ------------------------------------------------------------------
    def _cancel(self) -> None:
        self._stopped = True
        self.destroy()

    def _launch(self) -> None:
        try:
            max_n = int(self._max_var.get() or "50")
        except ValueError:
            self._progress_label_var.set("⚠ Max invalide")
            return

        use_footprint = self._footprint_var.get()
        no_emails_only = self._no_emails_var.get()

        self._launch_btn.configure(state="disabled", text="…")
        self._progress_label_var.set("Préparation…")
        self.update_idletasks()

        threading.Thread(
            target=self._run,
            args=(max_n, use_footprint, no_emails_only),
            daemon=True,
        ).start()

    def _run(self, max_n: int, use_footprint: bool, no_emails_only: bool) -> None:
        """Exécute l'enrichissement (équivalent CLI `enrich --footprint`)."""
        from datetime import datetime
        try:
            from triskell_core.prospect.core.crm import CRM
            from triskell_core.prospect.core.prospect import Source, norm_website
            from triskell_core.prospect.enrichers.web import WebEnricher
            from triskell_core.prospect.enrichers.linktree import (
                LinktreeFollower, is_hub,
            )
            from triskell_core.prospect.enrichers.footprint import FootprintFinder
        except Exception as e:
            self._set_status(f"✗ Import : {e}")
            self._reset_btn()
            return

        crm = CRM()
        web = WebEnricher()
        linktree = LinktreeFollower(web_enricher=web)
        footprint = FootprintFinder() if use_footprint else None

        targets = self._select(crm, max_n, no_emails_only, use_footprint)
        if not targets:
            self._set_status("Aucun prospect à enrichir avec ces filtres.")
            self._reset_btn()
            return

        n = len(targets)
        self._set_status(f"Enrichissement de {n} prospect(s)…")

        counters = {"site": 0, "hub": 0, "fp": 0, "rej": 0,
                    "new_emails": 0, "new_phones": 0}

        for i, prospect in enumerate(targets, 1):
            if self._stopped:
                break

            url = prospect.website or self._first_useful_url(prospect)
            url_was_guessed = False
            if not url and footprint and prospect.name and (prospect.city or prospect.legal_name):
                url = footprint.find_official_site(
                    prospect.name or prospect.legal_name,
                    city=prospect.city,
                    country=prospect.country or "FR",
                )
                if url:
                    counters["fp"] += 1
                    url_was_guessed = True
            if not url:
                self._tick(i, n, prospect.name)
                continue

            try:
                if is_hub(url):
                    data = linktree.enrich_hub(url)
                    counters["hub"] += 1
                    if data.get("primary_url") and not prospect.website:
                        prospect.website = data["primary_url"]
                else:
                    data = web.enrich_url(url)
                    counters["site"] += 1
                    verdict = self._cross_ref(prospect, data, url=url)
                    if verdict == "reject":
                        counters["rej"] += 1
                        prospect.history.append({
                            "ts": datetime.now().isoformat(timespec="seconds"),
                            "kind": "site_rejected", "url": url,
                            "reason": "cross_ref_mismatch",
                        })
                        self._tick(i, n, prospect.name)
                        continue
                    if not prospect.website:
                        if not url_was_guessed or verdict in ("high", "ok"):
                            prospect.website = url
                        else:
                            if url not in prospect.other_urls:
                                prospect.other_urls.append(url)
                    if verdict == "high":
                        prospect.tags = [t for t in prospect.tags
                                         if t != "site_unverified"]
                        if "site_verified" not in prospect.tags:
                            prospect.tags.append("site_verified")
                    elif verdict == "ok":
                        if "site_postal_match" not in prospect.tags:
                            prospect.tags.append("site_postal_match")
                    elif verdict == "low" and "site_unverified" not in prospect.tags:
                        prospect.tags.append("site_unverified")

                gained_emails = [e for e in data["emails"]
                                 if e.lower() not in
                                 {x.lower() for x in prospect.emails}]
                gained_phones = [p for p in data["phones"]
                                 if p not in prospect.phones]
                if gained_emails:
                    prospect.emails = (prospect.emails + gained_emails)[:8]
                    counters["new_emails"] += len(gained_emails)
                if gained_phones:
                    prospect.phones = (prospect.phones + gained_phones)[:5]
                    counters["new_phones"] += len(gained_phones)
                if data["address"] and not prospect.address:
                    prospect.address = data["address"]
                if data["has_legal_mentions"]:
                    prospect.has_legal_mentions = True

                prospect.history.append({
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "kind": "web_enrich", "url": url,
                    "pages": data.get("pages_visited", []),
                    "found_emails": gained_emails,
                    "found_phones": gained_phones,
                })
                prospect.sources.append(Source(
                    name="linktree" if is_hub(url) else "web",
                    source_id=norm_website(url), url=url,
                ))
                prospect.updated_at = datetime.now().isoformat(timespec="seconds")
                crm._dirty = True  # noqa: SLF001
            except Exception as e:
                self._set_status(f"⚠ {prospect.name[:30]} : {e}")

            self._tick(i, n, prospect.name)

        crm._rebuild_index()  # noqa: SLF001
        crm.save()
        msg = (f"✓ Terminé : {counters['site']} site(s), {counters['hub']} hub(s), "
               f"{counters['fp']} site(s) trouvé(s), {counters['rej']} rejeté(s). "
               f"+{counters['new_emails']} email(s), +{counters['new_phones']} tél(s).")
        self._set_status(msg)
        self.after(0, self._on_done)
        self._reset_btn(text="Lancer à nouveau")

    # --- helpers ------------------------------------------------------
    def _select(self, crm, max_n, no_emails_only, use_footprint) -> list:
        candidates = crm.all()
        if no_emails_only:
            candidates = [p for p in candidates if not p.emails]
        if use_footprint:
            candidates = [p for p in candidates
                          if p.website
                          or any(not self._is_pure_social(u) for u in p.other_urls)
                          or (p.name and p.city)]
        else:
            candidates = [p for p in candidates
                          if p.website
                          or any(not self._is_pure_social(u) for u in p.other_urls)]
        return candidates[:max_n]

    @staticmethod
    def _is_pure_social(url: str) -> bool:
        from urllib.parse import urlparse
        try:
            host = urlparse(
                url if url.startswith(("http://", "https://"))
                else "https://" + url
            ).netloc.lower()
        except Exception:
            return False
        pure = ("youtube.com", "youtu.be", "twitch.tv", "reddit.com",
                "x.com", "twitter.com", "facebook.com", "instagram.com",
                "tiktok.com", "linkedin.com")
        return any(host == d or host.endswith("." + d) for d in pure)

    @staticmethod
    def _first_useful_url(prospect) -> str:
        for u in prospect.other_urls:
            if u and not EnrichDialog._is_pure_social(u):
                return u
        return ""

    @staticmethod
    def _cross_ref(prospect, web_data: dict, url: str = "") -> str:
        """Réplique de la fonction _cross_ref du CLI (mêmes règles)."""
        from urllib.parse import urlparse
        import re as _re
        import unicodedata

        site_sirens = set(web_data.get("sirens") or [])
        site_sirets = set(web_data.get("sirets") or [])
        site_postal = set(web_data.get("postal_codes") or [])
        site_emails = web_data.get("emails") or []

        if not prospect.siren and not prospect.postal_code:
            return "low"

        if prospect.siren:
            if prospect.siren in site_sirens:
                return "high"
            if any(s.startswith(prospect.siren) for s in site_sirets):
                return "high"
            if site_sirens and prospect.siren not in site_sirens:
                return "reject"

        # Email-domaine match
        if url and site_emails:
            try:
                host = urlparse(
                    url if url.startswith(("http://", "https://"))
                    else "https://" + url
                ).netloc.lower().lstrip("www.")
            except Exception:
                host = ""
            if host:
                domain_emails = [e for e in site_emails if e.endswith("@" + host)]
                if domain_emails:
                    def _main_slug(s: str) -> str:
                        if not s:
                            return ""
                        base = s.split("(", 1)[0]
                        nfkd = unicodedata.normalize("NFKD", base)
                        no_acc = "".join(ch for ch in nfkd
                                         if not unicodedata.combining(ch))
                        return _re.sub(r"[^a-z0-9]", "", no_acc.lower())
                    name_slug = _main_slug(prospect.name) or _main_slug(prospect.legal_name)
                    host_slug = _main_slug(host.split(".")[0])
                    if name_slug and host_slug:
                        if name_slug == host_slug:
                            return "high"
                        a, b = sorted([len(name_slug), len(host_slug)])
                        ratio = a / b if b else 0
                        if ratio >= 0.7 and (name_slug in host_slug
                                              or host_slug in name_slug):
                            return "high"

        if prospect.postal_code and site_postal:
            if prospect.postal_code in site_postal:
                return "ok"
            dept = prospect.postal_code[:2]
            if any(cp.startswith(dept) for cp in site_postal):
                return "low"
            return "reject"
        return "low"

    def _tick(self, i: int, n: int, name: str) -> None:
        def apply():
            self._progress_var.set(i / n)
            self._progress_label_var.set(f"{i}/{n} — {name[:40]}")
        self.after(0, apply)

    def _set_status(self, msg: str) -> None:
        def apply():
            self._progress_label_var.set(msg)
        self.after(0, apply)

    def _reset_btn(self, *, text: str = "Lancer") -> None:
        def apply():
            self._launch_btn.configure(state="normal", text=text)
            self._cancel_btn.configure(text="Fermer")
        self.after(0, apply)
