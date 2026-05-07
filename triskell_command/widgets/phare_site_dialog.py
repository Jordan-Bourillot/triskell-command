"""Dialog d'ajout / édition d'un site dans Le Phare.

Deux modes :
  - **Manuel** : tous les champs sont vides, tu remplis à la main.
  - **Auto-détection** : bouton « Détecter depuis un dossier… » → tu choisis
    le dossier local du site, on lit `.git/config`, `.netlify/state.json` et
    `package.json` pour pré-remplir les champs. Si `netlify_token` est
    configuré, on appelle aussi l'API Netlify pour récupérer le domaine.
"""
from __future__ import annotations

import logging
import re
from tkinter import filedialog, messagebox
from typing import Callable, Optional

import customtkinter as ctk

from .. import theme as T
from ..integrations.phare import repo, site_onboard
from .components import PrimaryButton, SecondaryButton

logger = logging.getLogger(__name__)


STACK_OPTIONS = ("astro", "next", "vite", "html", "autre")


class PhareSiteDialog(ctk.CTkToplevel):
    """Modale d'ajout (ou édition) d'un site surveillé par Le Phare."""

    def __init__(
        self,
        master,
        *,
        colors,
        site: Optional[dict] = None,
        on_done: Optional[Callable[[], None]] = None,
    ):
        super().__init__(master)
        self._colors = colors
        self._site = dict(site or {})
        self._on_done = on_done
        self._is_edit = bool(self._site.get("id"))

        self.title("Site Le Phare")
        self.geometry("680x780")
        self.configure(fg_color=colors.bg)
        try:
            self.grab_set()
            self.transient(master)
        except Exception:
            pass

        c = colors
        outer = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        outer.pack(fill="both", expand=True, padx=T.SPACE_LG, pady=T.SPACE_LG)

        ctk.CTkLabel(
            outer,
            text="Modifier le site" if self._is_edit else "Ajouter un site",
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_TITLE, "bold"),
            text_color=c.text_primary,
        ).pack(anchor="w")
        ctk.CTkLabel(
            outer,
            text=("Le site sera surveillé par les 8 agents (audit, mots-clés, "
                  "maillage, backlinks, etc.). Tu peux remplir à la main ou "
                  "pointer un dossier local pour auto-détecter."),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, wraplength=600, justify="left",
        ).pack(anchor="w", pady=(2, T.SPACE_LG))

        # Bouton auto-détection (uniquement en mode création)
        if not self._is_edit:
            detect_card = ctk.CTkFrame(
                outer, fg_color=c.panel,
                border_color=c.border, border_width=1,
                corner_radius=T.RADIUS_SM,
            )
            detect_card.pack(fill="x", pady=(0, T.SPACE_MD))
            ctk.CTkLabel(
                detect_card, text="AUTO-DÉTECTION",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                text_color=c.text_muted, anchor="w",
            ).pack(fill="x", padx=T.SPACE_MD, pady=(T.SPACE_MD, 0))
            ctk.CTkLabel(
                detect_card,
                text=("Pointe le dossier local du site (le repo cloné) — on "
                      "lit .git/config, .netlify/state.json et package.json."),
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                text_color=c.text_muted, anchor="w", wraplength=560,
                justify="left",
            ).pack(fill="x", padx=T.SPACE_MD, pady=(2, T.SPACE_XS))
            self._detect_status = ctk.CTkLabel(
                detect_card, text="",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
                text_color=c.text_secondary, anchor="w",
                wraplength=560, justify="left",
            )
            self._detect_status.pack(fill="x", padx=T.SPACE_MD,
                                       pady=(0, T.SPACE_XS))
            SecondaryButton(
                detect_card, colors=c,
                text="Détecter depuis un dossier…", icon="search",
                command=self._on_detect_clicked,
            ).pack(anchor="w", padx=T.SPACE_MD, pady=(0, T.SPACE_MD))

        # ---- Champs ----
        self._name = self._field(
            outer, "Nom du site (requis)",
            placeholder="ex: Cabinet Dupont",
            value=self._site.get("name") or "",
        )
        self._domain = self._field(
            outer, "Domaine (requis, ex: cabinet-dupont.fr)",
            placeholder="cabinet-dupont.fr",
            value=self._site.get("domain") or "",
        )
        self._repo_github = self._field(
            outer, "Repo GitHub (owner/repo)",
            placeholder="ex: Jordan-Bourillot/cabinet-dupont",
            value=self._site.get("repo_github") or "",
        )
        self._repo_branch = self._field(
            outer, "Branche de prod",
            placeholder="main",
            value=self._site.get("repo_branch_main") or "main",
        )
        self._netlify_id = self._field(
            outer, "Netlify site ID",
            placeholder="(uuid Netlify)",
            value=self._site.get("netlify_site_id") or "",
        )

        # Stack (dropdown)
        ctk.CTkLabel(
            outer, text="STACK",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, T.SPACE_XS))
        cur_stack = (self._site.get("stack") or "html").lower()
        if cur_stack not in STACK_OPTIONS:
            cur_stack = "autre"
        self._stack_var = ctk.StringVar(value=cur_stack)
        ctk.CTkOptionMenu(
            outer, variable=self._stack_var,
            values=list(STACK_OPTIONS),
            fg_color=c.panel, button_color=c.panel,
            button_hover_color=c.panel_hover, dropdown_fg_color=c.panel,
            text_color=c.text_primary,
        ).pack(fill="x")

        # Priority
        self._priority = self._field(
            outer, "Priorité (0-100, plus haut = plus prioritaire)",
            placeholder="50",
            value=str(self._site.get("priority") or 50),
        )

        # Key paths (textarea)
        ctk.CTkLabel(
            outer, text="PAGES CLÉS À SURVEILLER (1 par ligne, max 10)",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, T.SPACE_XS))
        self._key_paths = ctk.CTkTextbox(
            outer, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=80, wrap="none",
        )
        self._key_paths.pack(fill="x", pady=(2, T.SPACE_XS))
        existing_paths = self._site.get("key_paths") or ["/"]
        self._key_paths.insert("1.0", "\n".join(existing_paths))
        ctk.CTkLabel(
            outer, text="Ex: / puis /a-propos puis /produit",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(0, T.SPACE_SM))

        # Client externe (checkbox)
        self._is_external_var = ctk.BooleanVar(
            value=bool(self._site.get("is_external_client", False))
        )
        ctk.CTkCheckBox(
            outer, variable=self._is_external_var,
            text="Site d'un client externe (active la fiche client + envoi rapport)",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_primary,
            fg_color=c.accent, hover_color=c.accent,
            border_color=c.border,
        ).pack(fill="x", anchor="w", pady=(T.SPACE_MD, T.SPACE_XS))

        # Notes
        ctk.CTkLabel(
            outer, text="NOTES INTERNES",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, T.SPACE_XS))
        self._notes = ctk.CTkTextbox(
            outer, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=80, wrap="word",
        )
        self._notes.pack(fill="x", pady=(2, T.SPACE_MD))
        if self._site.get("notes"):
            self._notes.insert("1.0", self._site["notes"])

        # ---- Actions ----
        actions = ctk.CTkFrame(outer, fg_color="transparent")
        actions.pack(fill="x", pady=(T.SPACE_LG, 0))
        SecondaryButton(actions, colors=c, text="Annuler",
                         command=self.destroy).pack(side="left")
        PrimaryButton(actions, colors=c, text="Enregistrer",
                       command=self._save).pack(side="right")

    # ------------------------------------------------------------------
    # Helpers UI
    # ------------------------------------------------------------------
    def _field(self, master, label: str, *,
                placeholder: str = "", value: str = "") -> ctk.CTkEntry:
        c = self._colors
        ctk.CTkLabel(
            master, text=label.upper(),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, T.SPACE_XS))
        entry = ctk.CTkEntry(
            master, fg_color=c.panel, border_color=c.border, border_width=1,
            text_color=c.text_primary, height=36,
            placeholder_text=placeholder,
        )
        entry.pack(fill="x")
        if value:
            entry.insert(0, value)
        return entry

    def _set_entry(self, entry: ctk.CTkEntry, value: str) -> None:
        entry.delete(0, "end")
        if value:
            entry.insert(0, value)

    # ------------------------------------------------------------------
    # Auto-détection
    # ------------------------------------------------------------------
    def _on_detect_clicked(self) -> None:
        folder = filedialog.askdirectory(
            title="Choisis le dossier local du site (repo cloné)",
            mustexist=True,
        )
        if not folder:
            return

        cfg = repo.get_config() or {}
        netlify_token = cfg.get("netlify_token") or ""

        try:
            result = site_onboard.detect_from_folder(
                folder, netlify_token=netlify_token or None,
            )
        except Exception as exc:
            logger.warning("phare site_onboard failed: %s", exc)
            messagebox.showerror(
                "Auto-détection",
                f"Impossible d'analyser le dossier :\n{exc}",
            )
            return

        status = result.get("_status", {})
        if status.get("folder") == "not_a_directory":
            messagebox.showerror("Auto-détection",
                                  "Ce chemin n'est pas un dossier.")
            return

        # Pré-remplit uniquement les champs vides (n'écrase pas une saisie
        # manuelle déjà faite).
        if result.get("name") and not self._name.get().strip():
            self._set_entry(self._name, result["name"])
        if result.get("domain") and not self._domain.get().strip():
            self._set_entry(self._domain, result["domain"])
        if result.get("repo_github"):
            self._set_entry(self._repo_github, result["repo_github"])
        if result.get("repo_branch_main"):
            self._set_entry(self._repo_branch, result["repo_branch_main"])
        if result.get("netlify_site_id"):
            self._set_entry(self._netlify_id, result["netlify_site_id"])
        if result.get("stack"):
            stack = result["stack"]
            self._stack_var.set(stack if stack in STACK_OPTIONS else "autre")

        # Affiche un récap de ce qui a été détecté / manqué
        lines = []
        for key, label in (
            ("repo_github", "Repo GitHub"),
            ("repo_branch_main", "Branche"),
            ("netlify_site_id", "Netlify site ID"),
            ("stack", "Stack"),
            ("domain", "Domaine"),
        ):
            s = status.get(key)
            if s == "detected" or s == "detected_via_netlify":
                lines.append(f"✓ {label}")
            else:
                lines.append(f"✗ {label} (à remplir)")
        self._detect_status.configure(text="   ·   ".join(lines))

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def _save(self) -> None:
        name = self._name.get().strip()
        domain = self._domain.get().strip().lower()

        if not name:
            messagebox.showerror("Champs requis", "Le nom du site est requis.")
            return
        if not domain:
            messagebox.showerror("Champs requis", "Le domaine est requis.")
            return
        # Validation basique du domaine
        if not re.match(r'^[a-z0-9.\-]+\.[a-z]{2,}$', domain):
            messagebox.showerror(
                "Domaine invalide",
                "Le domaine doit ressembler à `cabinet-dupont.fr` "
                "(pas de http://, pas de slash).",
            )
            return

        # Priority parsing
        try:
            priority = int(self._priority.get().strip() or "50")
        except ValueError:
            priority = 50
        priority = max(0, min(100, priority))

        # Key paths : 1 par ligne, on garde max 10
        raw_paths = self._key_paths.get("1.0", "end").strip().splitlines()
        key_paths = [p.strip() for p in raw_paths if p.strip()][:10]
        if not key_paths:
            key_paths = ["/"]

        payload = {
            "name": name,
            "domain": domain,
            "repo_github": self._repo_github.get().strip(),
            "repo_branch_main": self._repo_branch.get().strip() or "main",
            "netlify_site_id": self._netlify_id.get().strip(),
            "stack": self._stack_var.get(),
            "priority": priority,
            "key_paths": key_paths,
            "is_external_client": bool(self._is_external_var.get()),
            "notes": self._notes.get("1.0", "end").rstrip(),
        }
        if self._is_edit and self._site.get("id"):
            payload["id"] = self._site["id"]

        result = repo.upsert_site(payload)
        if not result:
            messagebox.showerror(
                "Erreur",
                "Impossible d'enregistrer le site. "
                "Vérifie la connexion à Supabase et regarde les logs.",
            )
            return

        if self._on_done:
            try:
                self._on_done()
            except Exception as exc:
                logger.debug("phare site dialog on_done: %s", exc)
        self.destroy()
