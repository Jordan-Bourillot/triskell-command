"""Dialog d'édition / création d'un prospect."""

from __future__ import annotations

import customtkinter as ctk

from .. import theme as T
from .components import PrimaryButton, SecondaryButton
from .window_icon import apply_window_icon


STATUS_VALUES = [
    "new", "qualified", "contacted", "replied",
    "won", "lost", "refused",
]


class ProspectDialog(ctk.CTkToplevel):
    """Modal pour voir / éditer / supprimer / créer un prospect."""

    def __init__(
        self,
        master,
        *,
        prospect=None,           # None = mode création
        colors: T.ThemeColors,
        on_saved=None,           # callback(prospect) après save
        on_deleted=None,         # callback(prospect) après delete
    ):
        super().__init__(master)
        self._colors = colors
        self._on_saved = on_saved
        self._on_deleted = on_deleted
        self._is_new = prospect is None

        if self._is_new:
            from triskell_core.prospect.core.prospect import Prospect, Source
            self._prospect = Prospect(
                sources=[Source(name="manual", source_id="")],
            )
        else:
            self._prospect = prospect

        c = self._colors
        self.title("Nouveau prospect" if self._is_new else "Éditer le prospect")
        self.geometry("680x720")
        self.minsize(620, 600)
        self.configure(fg_color=c.bg)
        self.transient(master.winfo_toplevel())
        apply_window_icon(self)
        self.after(100, lambda: self.lift())

        # Header
        ctk.CTkLabel(
            self,
            text=("Nouveau prospect" if self._is_new
                  else self._prospect.name or "(sans nom)"),
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_TITLE, "bold"),
            text_color=c.text_primary,
        ).pack(anchor="w", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_XS))

        # Sous-info
        if not self._is_new:
            sources = ", ".join(sorted({s.name for s in self._prospect.sources}))
            ctk.CTkLabel(
                self,
                text=f"Sources : {sources or '—'} · "
                     f"créé : {self._prospect.created_at[:10] or '—'}",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
                text_color=c.text_muted,
            ).pack(anchor="w", padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        # Conteneur scrollable
        scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        scroll.pack(fill="both", expand=True, padx=T.SPACE_LG, pady=(0, T.SPACE_MD))

        self._fields: dict[str, ctk.CTkEntry | ctk.StringVar | ctk.CTkTextbox] = {}

        # Identité
        self._make_section_label(scroll, "IDENTITÉ")
        self._make_input(scroll, "Nom", "name", self._prospect.name)
        self._make_input(scroll, "Raison sociale (legal_name)", "legal_name",
                         self._prospect.legal_name)
        self._make_input(scroll, "SIREN", "siren", self._prospect.siren)
        self._make_input(scroll, "Handle", "handle", self._prospect.handle)

        # Contact
        self._make_section_label(scroll, "CONTACT")
        self._make_input(
            scroll, "Email principal", "_email_main",
            (self._prospect.emails or [""])[0],
        )
        self._make_input(
            scroll, "Téléphone principal", "_phone_main",
            (self._prospect.phones or [""])[0],
        )
        self._make_input(scroll, "Site web", "website",
                         self._prospect.website)
        self._make_input(scroll, "Adresse", "address", self._prospect.address)
        self._make_input(scroll, "Ville", "city", self._prospect.city)
        self._make_input(scroll, "Code postal", "postal_code",
                         self._prospect.postal_code)
        self._make_input(scroll, "Pays", "country",
                         self._prospect.country or "FR")

        # Activité
        self._make_section_label(scroll, "ACTIVITÉ")
        self._make_input(scroll, "Secteur", "industry", self._prospect.industry)
        self._make_input(scroll, "Code NAF", "naf_code", self._prospect.naf_code)
        self._make_textarea(scroll, "Description", "description",
                            self._prospect.description, height=70)

        # CRM
        self._make_section_label(scroll, "CRM")
        self._make_select(scroll, "Statut", "status",
                          self._prospect.status or "new", STATUS_VALUES)
        self._make_input(scroll, "Tags (séparés par virgules)", "_tags_csv",
                         ",".join(self._prospect.tags))
        self._make_textarea(scroll, "Notes", "notes",
                            self._prospect.notes, height=80)

        # Footer actions
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        SecondaryButton(bottom, colors=c, icon="close", text="Annuler",
                        command=self.destroy
                        ).pack(side="right", padx=(T.SPACE_SM, 0))
        PrimaryButton(bottom, colors=c, icon="save", text="Enregistrer",
                      command=self._save).pack(side="right")

        if not self._is_new:
            SecondaryButton(bottom, colors=c, icon="trash", text="Supprimer",
                            command=self._delete).pack(side="left")

        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            bottom, textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
        ).pack(side="left", fill="x", expand=True, padx=T.SPACE_MD)

    # ------------------------------------------------------------------
    def _make_section_label(self, parent, text):
        ctk.CTkLabel(
            parent, text=text,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=self._colors.text_muted, anchor="w",
        ).pack(fill="x", pady=(T.SPACE_MD, T.SPACE_SM))

    def _make_input(self, parent, label, key, value):
        c = self._colors
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, T.SPACE_SM))
        ctk.CTkLabel(
            row, text=label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w", width=200,
        ).pack(side="left", padx=(0, T.SPACE_MD))
        entry = ctk.CTkEntry(
            row,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM, height=30,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
        )
        if value:
            entry.insert(0, str(value))
        entry.pack(side="left", fill="x", expand=True)
        self._fields[key] = entry

    def _make_textarea(self, parent, label, key, value, *, height=80):
        c = self._colors
        ctk.CTkLabel(
            parent, text=label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", pady=(T.SPACE_SM, 2))
        tb = ctk.CTkTextbox(
            parent, height=height,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            wrap="word",
        )
        if value:
            tb.insert("1.0", str(value))
        tb.pack(fill="x", pady=(0, T.SPACE_SM))
        self._fields[key] = tb

    def _make_select(self, parent, label, key, value, values):
        c = self._colors
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, T.SPACE_SM))
        ctk.CTkLabel(
            row, text=label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w", width=200,
        ).pack(side="left", padx=(0, T.SPACE_MD))
        var = ctk.StringVar(value=value)
        ctk.CTkOptionMenu(
            row, values=values, variable=var,
            fg_color=c.bg_alt, button_color=c.accent,
            button_hover_color=c.accent_hover, text_color=c.text_primary,
            corner_radius=T.RADIUS_SM, height=30,
        ).pack(side="left", fill="x", expand=True)
        self._fields[key] = var

    # ------------------------------------------------------------------
    def _read_field(self, key) -> str:
        widget = self._fields.get(key)
        if widget is None:
            return ""
        if isinstance(widget, ctk.CTkEntry):
            return widget.get().strip()
        if isinstance(widget, ctk.CTkTextbox):
            return widget.get("1.0", "end").rstrip()
        if isinstance(widget, ctk.StringVar):
            return widget.get().strip()
        return ""

    def _save(self) -> None:
        from datetime import datetime
        from triskell_core.prospect.core.crm import CRM
        from triskell_core.prospect.core.prospect import norm_email, norm_phone

        # Lecture des champs
        p = self._prospect
        p.name = self._read_field("name")
        p.legal_name = self._read_field("legal_name")
        p.siren = self._read_field("siren")
        p.handle = self._read_field("handle")
        p.website = self._read_field("website")
        p.address = self._read_field("address")
        p.city = self._read_field("city")
        p.postal_code = self._read_field("postal_code")
        p.country = self._read_field("country")
        p.industry = self._read_field("industry")
        p.naf_code = self._read_field("naf_code")
        p.description = self._read_field("description")
        p.status = self._read_field("status") or "new"
        p.notes = self._read_field("notes")
        p.tags = [t.strip() for t in self._read_field("_tags_csv").split(",")
                  if t.strip()]

        email_main = self._read_field("_email_main")
        if email_main and norm_email(email_main):
            if not p.emails:
                p.emails = [email_main]
            else:
                p.emails[0] = email_main
        elif not email_main and p.emails:
            p.emails = p.emails[1:]  # Vide → on retire le 1er

        phone_main = self._read_field("_phone_main")
        if phone_main and norm_phone(phone_main):
            if not p.phones:
                p.phones = [phone_main]
            else:
                p.phones[0] = phone_main
        elif not phone_main and p.phones:
            p.phones = p.phones[1:]

        if not p.name and not p.legal_name:
            self._status_var.set("⚠ Le nom est obligatoire.")
            return

        p.updated_at = datetime.now().isoformat(timespec="seconds")

        crm = CRM()
        crm.upsert(p)
        crm.save()
        self._status_var.set("✓ Enregistré.")

        if self._on_saved:
            try:
                self._on_saved(p)
            except Exception:
                pass
        self.after(500, self.destroy)

    def _delete(self) -> None:
        from triskell_core.prospect.core.crm import CRM
        # Confirmation
        confirm = ConfirmDialog(
            self,
            title="Supprimer ce prospect ?",
            message=f"« {self._prospect.name} » sera retiré du CRM.\n"
                    f"Cette action est irréversible.",
            colors=self._colors,
        )
        self.wait_window(confirm)
        if not confirm.confirmed:
            return

        crm = CRM()
        # On charge tous, on enlève celui qui matche, on save
        all_p = crm.all()
        keys = set(self._prospect.match_keys)
        new_list = [
            p for p in all_p
            if not (set(p.match_keys) & keys)
        ]
        crm._prospects = new_list  # noqa: SLF001
        crm._rebuild_index()        # noqa: SLF001
        crm._dirty = True           # noqa: SLF001
        crm.save()
        self._status_var.set("✓ Supprimé.")
        if self._on_deleted:
            try:
                self._on_deleted(self._prospect)
            except Exception:
                pass
        self.after(500, self.destroy)


class ConfirmDialog(ctk.CTkToplevel):
    """Modale de confirmation Oui / Non. Set self.confirmed."""

    def __init__(self, master, *, title: str, message: str,
                 colors: T.ThemeColors, danger: bool = True):
        super().__init__(master)
        self.confirmed = False
        c = colors
        self.title(title)
        self.geometry("440x220")
        self.configure(fg_color=c.bg)
        self.transient(master.winfo_toplevel())
        self.grab_set()
        apply_window_icon(self)
        self.after(100, lambda: self.lift())

        ctk.CTkLabel(
            self, text=title,
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary,
        ).pack(anchor="w", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))
        ctk.CTkLabel(
            self, text=message,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_secondary, justify="left", wraplength=400,
        ).pack(anchor="w", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        SecondaryButton(bottom, colors=c, text="Annuler",
                        command=self._cancel).pack(side="right",
                                                    padx=(T.SPACE_SM, 0))
        # Bouton confirmation : danger=rouge, sinon primary
        ok_btn = ctk.CTkButton(
            bottom,
            text="Confirmer",
            fg_color=c.danger if danger else c.accent,
            hover_color="#FF6B6B" if danger else c.accent_hover,
            text_color="#FFFFFF",
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            height=38, border_spacing=10,
            command=self._ok,
        )
        ok_btn.pack(side="right")

    def _cancel(self):
        self.confirmed = False
        self.destroy()

    def _ok(self):
        self.confirmed = True
        self.destroy()
