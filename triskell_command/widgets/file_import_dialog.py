"""Dialog d'import de prospects depuis un fichier CSV/XLSX utilisateur."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog, ttk
import tkinter as tk

import customtkinter as ctk

from .. import theme as T
from .components import PrimaryButton, SecondaryButton
from .window_icon import apply_window_icon


_NONE_LABEL = "— (ne pas importer)"


class FileImportDialog(ctk.CTkToplevel):
    """Modal : choisir un fichier, mapper les colonnes, importer."""

    def __init__(self, master, *, on_done):
        super().__init__(master)
        self._parent = master
        self._on_done = on_done
        self._colors = master.colors

        self._file_path: Path | None = None
        self._headers: list[str] = []
        self._rows_total: int = 0
        self._sample: list[dict[str, str]] = []
        self._mapping_vars: dict[str, ctk.StringVar] = {}
        self._importable_fields: list[tuple[str, str]] = []

        c = self._colors
        self.title("Importer un fichier de prospects")
        self.geometry("820x680")
        self.minsize(720, 560)
        self.configure(fg_color=c.bg)
        self.transient(master.winfo_toplevel())
        apply_window_icon(self)
        self.after(100, lambda: self.lift())

        # Header
        ctk.CTkLabel(
            self,
            text="Importer un fichier",
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_TITLE, "bold"),
            text_color=c.text_primary,
        ).pack(anchor="w", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_XS))
        ctk.CTkLabel(
            self,
            text=("Choisis un fichier Excel (.xlsx) ou CSV. "
                  "Les colonnes sont reconnues automatiquement — "
                  "tu peux corriger le mapping avant d'importer."),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
            justify="left", wraplength=760,
        ).pack(anchor="w", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Ligne fichier
        file_row = ctk.CTkFrame(self, fg_color=c.panel,
                                corner_radius=T.RADIUS_SM,
                                border_color=c.border, border_width=1)
        file_row.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))
        inner = ctk.CTkFrame(file_row, fg_color="transparent")
        inner.pack(fill="x", padx=T.SPACE_LG, pady=T.SPACE_MD)

        self._file_var = ctk.StringVar(value="Aucun fichier sélectionné")
        ctk.CTkLabel(
            inner, textvariable=self._file_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_secondary, anchor="w",
        ).pack(side="left", fill="x", expand=True)
        SecondaryButton(
            inner, colors=c, icon="doc", text="Parcourir…",
            command=self._pick_file,
        ).pack(side="right")

        # Conteneur split : mapping (gauche) + aperçu (droite)
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True,
                           padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Placeholder tant qu'aucun fichier
        self._placeholder = ctk.CTkLabel(
            self._content,
            text="Sélectionne un fichier pour voir les colonnes…",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_muted,
        )
        self._placeholder.pack(expand=True)

        # Status
        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_XS))

        # Bottom
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        SecondaryButton(
            bottom, colors=c, icon="close", text="Annuler",
            command=self.destroy,
        ).pack(side="right", padx=(T.SPACE_SM, 0))
        self._import_btn = PrimaryButton(
            bottom, colors=c, icon="download", text="Importer",
            command=self._launch_import,
        )
        self._import_btn.pack(side="right")
        self._import_btn.configure(state="disabled")

    # ------------------------------------------------------------------
    def _pick_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Choisir un fichier de prospects",
            filetypes=[
                ("Tous formats supportés", "*.xlsx *.xlsm *.xls *.csv *.tsv *.txt"),
                ("Excel", "*.xlsx *.xlsm *.xls"),
                ("CSV / TSV", "*.csv *.tsv *.txt"),
                ("Tous fichiers", "*.*"),
            ],
        )
        if not path:
            return
        self._file_path = Path(path)
        self._file_var.set(self._file_path.name)
        self._status_var.set("Lecture du fichier…")
        self.update_idletasks()
        threading.Thread(target=self._load_preview, daemon=True).start()

    def _load_preview(self) -> None:
        try:
            from triskell_core.prospect.sources import file_import as fi
            data = fi.preview(self._file_path)
        except Exception as e:
            self.after(0, lambda: self._status_var.set(f"✗ Erreur lecture : {e}"))
            return

        def apply():
            self._headers = data["headers"]
            self._rows_total = data["rows_total"]
            self._sample = data["sample"]
            self._importable_fields = fi.IMPORTABLE_FIELDS
            self._render_mapping_and_preview(data["suggested_mapping"])
            self._status_var.set(
                f"{self._rows_total} ligne(s) trouvée(s). "
                f"Vérifie le mapping puis clique Importer."
            )
            self._import_btn.configure(state="normal")

        self.after(0, apply)

    # ------------------------------------------------------------------
    def _render_mapping_and_preview(self, suggested: dict[str, str]) -> None:
        c = self._colors
        # Vide le content
        for w in self._content.winfo_children():
            w.destroy()
        self._mapping_vars.clear()

        # Layout : 2 colonnes
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_columnconfigure(1, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        # -- Gauche : mapping
        left = ctk.CTkFrame(
            self._content, fg_color=c.panel,
            corner_radius=T.RADIUS_SM,
            border_color=c.border, border_width=1,
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(0, T.SPACE_SM))

        ctk.CTkLabel(
            left, text="Mapping des colonnes",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_MD, T.SPACE_SM))

        map_scroll = ctk.CTkScrollableFrame(
            left, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        map_scroll.pack(fill="both", expand=True,
                        padx=T.SPACE_SM, pady=(0, T.SPACE_MD))

        options = [_NONE_LABEL] + list(self._headers)
        for field, label in self._importable_fields:
            row = ctk.CTkFrame(map_scroll, fg_color="transparent")
            row.pack(fill="x", padx=T.SPACE_SM, pady=2)
            ctk.CTkLabel(
                row, text=label,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_secondary, anchor="w", width=130,
            ).pack(side="left", padx=(0, T.SPACE_SM))
            var = ctk.StringVar(value=suggested.get(field, _NONE_LABEL))
            ctk.CTkOptionMenu(
                row, values=options, variable=var,
                fg_color=c.bg_alt,
                button_color=c.accent, button_hover_color=c.accent_hover,
                text_color=c.text_primary,
                corner_radius=T.RADIUS_SM,
                dropdown_fg_color=c.panel,
                dropdown_text_color=c.text_primary,
                dropdown_hover_color=c.bg_alt,
                width=200,
            ).pack(side="left", fill="x", expand=True)
            self._mapping_vars[field] = var

        # -- Droite : aperçu
        right = ctk.CTkFrame(
            self._content, fg_color=c.panel,
            corner_radius=T.RADIUS_SM,
            border_color=c.border, border_width=1,
        )
        right.grid(row=0, column=1, sticky="nsew", padx=(T.SPACE_SM, 0))

        ctk.CTkLabel(
            right,
            text=f"Aperçu (5 premières lignes sur {self._rows_total})",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_MD, T.SPACE_SM))

        preview_wrap = tk.Frame(right, bg=c.panel)
        preview_wrap.pack(fill="both", expand=True,
                          padx=T.SPACE_SM, pady=(0, T.SPACE_MD))

        # Treeview pour aperçu
        style = ttk.Style()
        cols = list(self._headers)
        tree = ttk.Treeview(
            preview_wrap, columns=cols, show="headings",
            style="Triskell.Treeview", height=6,
        )
        for col in cols:
            tree.heading(col, text=col, anchor="w")
            tree.column(col, width=120, anchor="w", stretch=False)
        for row in self._sample:
            tree.insert("", "end",
                        values=[row.get(c_, "") for c_ in cols])

        xsb = ttk.Scrollbar(preview_wrap, orient="horizontal",
                            command=tree.xview)
        ysb = ttk.Scrollbar(preview_wrap, orient="vertical",
                            command=tree.yview,
                            style="Triskell.Vertical.TScrollbar")
        tree.configure(xscrollcommand=xsb.set, yscrollcommand=ysb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        preview_wrap.grid_rowconfigure(0, weight=1)
        preview_wrap.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------------
    def _launch_import(self) -> None:
        if not self._file_path:
            return
        mapping = {
            field: var.get()
            for field, var in self._mapping_vars.items()
            if var.get() and var.get() != _NONE_LABEL
        }
        if not mapping:
            self._status_var.set(
                "⚠ Aucune colonne mappée — choisis au moins Nom ou Email."
            )
            return
        # Garde-fou : il faut au moins un champ d'identité
        if not any(k in mapping for k in ("name", "legal_name", "emails",
                                          "phones", "website", "siren")):
            self._status_var.set(
                "⚠ Il faut au moins mapper Nom, Email, Téléphone, "
                "Site web, Raison sociale ou SIREN."
            )
            return

        self._import_btn.configure(state="disabled", text="…")
        self._status_var.set("Import en cours…")
        threading.Thread(
            target=self._run_import,
            args=(mapping,),
            daemon=True,
        ).start()

    def _run_import(self, mapping: dict[str, str]) -> None:
        try:
            from triskell_core.prospect.core.crm import CRM
            from triskell_core.prospect.sources import file_import as fi
            crm = CRM()
            stats = crm.upsert_many(fi.import_with_mapping(self._file_path, mapping))
            crm.save()
            msg = (f"✓ Import terminé : {stats['created']} nouveaux, "
                   f"{stats['merged']} fusionnés. Total CRM : {stats['total']}.")
            self.after(0, lambda: self._status_var.set(msg))
            self.after(0, self._on_done)
            self.after(1500, self.destroy)
        except Exception as e:
            err = str(e)
            self.after(0, lambda: self._status_var.set(f"✗ Erreur : {err}"))
            self.after(0, lambda: self._import_btn.configure(
                state="normal", text="Importer"))
