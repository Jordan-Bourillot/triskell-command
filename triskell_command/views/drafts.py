"""Vue Brouillons à valider — l'utilisateur valide ou rejette les mails
préparés par l'app (mode validation)."""

from __future__ import annotations

import threading

import customtkinter as ctk

from .. import theme as T
from ..widgets.components import (
    Card,
    EmptyState,
    PrimaryButton,
    SecondaryButton,
    ViewHeader,
)
from .base import BaseView


class DraftsView(BaseView):
    title = "Brouillons à valider"
    subtitle = (
        "Les mails préparés par l'app t'attendent ici. "
        "Tu valides en 1 clic, tu corriges, ou tu rejettes."
    )

    def build(self) -> None:
        c = self.colors
        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_MD))

        SecondaryButton(header.actions, colors=c, icon="refresh", text="Rafraîchir",
                        command=self._refresh).pack(side="left")

        # Container principal scrollable (liste de cartes-brouillons)
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        self._scroll.pack(fill="both", expand=True,
                         padx=T.SPACE_2XL, pady=(0, T.SPACE_LG))

        # Status bar
        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
        ).pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

    def on_show(self) -> None:
        self._refresh()

    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        # Vide la liste
        for w in self._scroll.winfo_children():
            w.destroy()

        try:
            from triskell_core.prospect.pipeline import list_pending_drafts
            pairs = list_pending_drafts()
        except Exception as e:
            self._status_var.set(f"⚠ {e}")
            return

        if not pairs:
            EmptyState(
                self._scroll,
                colors=self.colors,
                icon="check",
                title="Tu es à jour.",
                message=(
                    "Aucun mail en attente. Quand l'auto-pilote ou les "
                    "relances en prépareront en mode validation, ils "
                    "atterriront ici."
                ),
                cta_text="Lancer une recherche",
                cta_command=lambda: self._navigate_to("autopilot"),
            ).pack(fill="both", expand=True)
            self._status_var.set("Aucun mail en attente.")
            return

        for prospect, item in pairs:
            self._make_card(prospect, item)

        n_total = sum(len(p.pending_drafts) for p, _d in pairs)
        n_unique = len({id(p) for p, _d in pairs})
        self._status_var.set(
            f"{n_total} brouillon(s) en attente sur {n_unique} prospect(s)."
        )

    def _make_card(self, prospect, item) -> None:
        c = self.colors
        card = Card(self._scroll, colors=c)
        card.pack(fill="x", pady=(0, T.SPACE_LG))

        # Header de la carte : nom + email + auteur du brouillon
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=T.SPACE_XL, pady=(T.SPACE_LG, T.SPACE_SM))

        name = prospect.name or prospect.legal_name or "(sans nom)"
        ctk.CTkLabel(
            head, text=name,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_HEADING, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(side="left", fill="x", expand=True)

        meta = (f"{prospect.emails[0] if prospect.emails else '—'}  ·  "
                f"{prospect.city or '—'}  ·  "
                f"généré {item.get('ts', '?')[:16]} par "
                f"{item.get('provider', '?')}/{item.get('model', '?')}")
        ctk.CTkLabel(
            head, text=meta,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted,
        ).pack(side="left", padx=(T.SPACE_LG, 0))

        # Objet
        ctk.CTkLabel(
            card, text=f"OBJET : {item.get('subject', '')}",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color=c.accent, anchor="w",
        ).pack(fill="x", padx=T.SPACE_XL, pady=(T.SPACE_SM, T.SPACE_XS))

        # Corps (textbox éditable)
        tb = ctk.CTkTextbox(
            card, height=180,
            fg_color=c.bg_alt, text_color=c.text_primary,
            border_color=c.border, border_width=1,
            corner_radius=T.RADIUS_SM,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            wrap="word",
        )
        tb.insert("1.0", item.get("body", ""))
        tb.pack(fill="x", padx=T.SPACE_XL, pady=(0, T.SPACE_MD))

        # Boutons : Approuver, Rejeter
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=T.SPACE_XL, pady=(0, T.SPACE_LG))

        SecondaryButton(
            btns, colors=c, icon="trash", text="Rejeter",
            command=lambda p=prospect: self._reject(p),
        ).pack(side="right", padx=(T.SPACE_SM, 0))

        PrimaryButton(
            btns, colors=c, icon="send", text="Approuver & envoyer",
            command=lambda p=prospect, t=tb: self._approve(p, t),
        ).pack(side="right")

    def _approve(self, prospect, body_textbox) -> None:
        # Récupère la version éventuellement éditée
        edited_body = body_textbox.get("1.0", "end").rstrip()
        # Met à jour le 1er brouillon avant d'envoyer
        if prospect.pending_drafts:
            prospect.pending_drafts[0]["body"] = edited_body

        self._status_var.set(f"Envoi à {prospect.emails[0]}…")

        def worker():
            try:
                # On sauvegarde d'abord (pour propager l'édition du body)
                from triskell_core.prospect.core.crm import CRM
                crm = CRM()
                crm._dirty = True  # noqa: SLF001
                crm.save()
                # Approuve le brouillon (envoie SMTP réel)
                from triskell_core.prospect.pipeline import approve_draft
                key = prospect.match_keys[0] if prospect.match_keys else ""
                r = approve_draft(key, draft_index=0)
                if r.get("ok"):
                    self._set_status(
                        f"✓ Envoyé à {prospect.emails[0]}",
                        kind="success",
                    )
                else:
                    self._set_status(
                        f"✗ {r.get('reason', 'échec')}",
                        kind="danger",
                    )
                self.after(0, self._refresh)
            except Exception as e:
                self._set_status(f"✗ {e}", kind="danger")

        threading.Thread(target=worker, daemon=True).start()

    def _reject(self, prospect) -> None:
        from triskell_core.prospect.pipeline import reject_draft
        key = prospect.match_keys[0] if prospect.match_keys else ""
        r = reject_draft(key, draft_index=0)
        if r.get("ok"):
            self._status_var.set(f"Brouillon rejeté pour {prospect.name}.")
        else:
            self._status_var.set(f"⚠ {r.get('reason', 'échec')}")
        self._refresh()

    def _set_status(self, msg: str, *, kind: str = "info") -> None:
        c = self.colors
        color_map = {
            "info": c.text_muted,
            "success": c.success,
            "danger": c.danger,
        }
        def apply():
            self._status_var.set(msg)
        self.after(0, apply)
