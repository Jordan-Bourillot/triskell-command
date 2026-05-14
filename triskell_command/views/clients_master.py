"""Vue Fiche Client 360° — liste + détail d'un client unifié.

Affiche la table master `clients` (créée par 09_clients_master.sql).
Permet de :
  - Rechercher un client par email/nom/société
  - Voir une fiche détaillée (coordonnées, timeline, compteurs)
  - Modifier le statut, les tags, les notes

Pattern aligné sur views/wow_intakes.py.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Optional

import customtkinter as ctk

from .. import theme as T
from ..integrations import clients_master_repo as cm
from ..widgets.components import (
    Card, EmptyState, PrimaryButton, SecondaryButton, ViewHeader,
)
from .base import BaseView

logger = logging.getLogger(__name__)


STATUS_LABELS = {
    "lead": "Lead (premier contact)",
    "prospect": "Prospect (engagé)",
    "client": "Client (a payé)",
    "inactive": "Inactif",
    "churned": "Churn (a quitté)",
}

EVENT_ICONS = {
    "Demande Lagriffe": "🟢",
    "Demande RankUs": "🟣",
    "Demande Studio WoW": "⚫",
    "Facture": "📄",
    "Email envoyé": "✉️",
    "Projet livraison": "📦",
}


def _fmt_dt(iso: str) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m/%y %Hh%M")
    except Exception:
        return iso[:16]


class ClientsMasterView(BaseView):
    title = "Fiches clients"
    subtitle = "Tous les clients Triskell — agrégés depuis prospection, formulaires sites, paiements et emails."

    def __init__(self, master, *, app_state, colors):
        super().__init__(master, app_state=app_state, colors=colors)
        self._clients: list[dict] = []
        self._selected_id: Optional[str] = None
        self._search: str = ""
        self._status_filter: str = ""

    def on_show(self):
        self._refresh()

    def build(self):
        ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=self.colors).pack(
            fill="x", padx=24, pady=(16, 8)
        )

        # ─── Barre filtres + recherche ───
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24, pady=(0, 12))
        ctk.CTkLabel(bar, text="🔍",
                     text_color=self.colors.text_muted,
                     font=ctk.CTkFont(size=14)).pack(side="left", padx=(0, 6))
        self._search_var = ctk.StringVar()
        self._search_entry = ctk.CTkEntry(
            bar, textvariable=self._search_var,
            placeholder_text="Rechercher par email / nom / société…",
            width=320,
        )
        self._search_entry.pack(side="left")
        self._search_entry.bind("<Return>", lambda _e: self._on_search())

        ctk.CTkLabel(bar, text="  Statut :",
                     text_color=self.colors.text_muted).pack(side="left", padx=(16, 6))
        self._status_var = ctk.StringVar(value="(tous)")
        self._status_menu = ctk.CTkOptionMenu(
            bar,
            variable=self._status_var,
            values=["(tous)"] + list(STATUS_LABELS.keys()),
            command=self._on_filter_change,
            width=160,
        )
        self._status_menu.pack(side="left")

        SecondaryButton(bar, text="Rafraîchir", command=self._refresh).pack(side="right")
        PrimaryButton(bar, text="📥 Importer (CSV / Excel / PDF)",
                      command=self._import_file).pack(side="right", padx=(0, 8))

        # ─── Layout 2 colonnes : liste à gauche, détail à droite ───
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=24, pady=(0, 16))
        content.grid_columnconfigure(0, weight=1, minsize=320)
        content.grid_columnconfigure(1, weight=2, minsize=480)
        content.grid_rowconfigure(0, weight=1)

        # ── Colonne gauche : liste des clients ──
        self._list_card = Card(content, title="Clients")
        self._list_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._list_body = ctk.CTkScrollableFrame(
            self._list_card.body, fg_color="transparent",
        )
        self._list_body.pack(fill="both", expand=True)

        # ── Colonne droite : détail ──
        self._detail_card = Card(content, title="Fiche client")
        self._detail_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._detail_body = ctk.CTkScrollableFrame(
            self._detail_card.body, fg_color="transparent",
        )
        self._detail_body.pack(fill="both", expand=True)
        self._render_empty_detail()

        # ── Statut en bas ──
        self._status_lbl = ctk.CTkLabel(self, text="",
                                         text_color=self.colors.text_muted)
        self._status_lbl.pack(fill="x", padx=24, pady=(0, 8))

    # -----------------------------------------------------------------
    def _on_search(self):
        self._search = self._search_var.get().strip()
        self._refresh()

    def _on_filter_change(self, choice: str):
        self._status_filter = "" if choice == "(tous)" else choice
        self._refresh()

    def _set_status(self, msg: str, *, error: bool = False):
        self._status_lbl.configure(
            text=msg,
            text_color=self.colors.danger if error else self.colors.text_muted,
        )

    # -----------------------------------------------------------------
    def _refresh(self):
        try:
            self._clients = cm.list_clients(
                status=self._status_filter or None,
                search=self._search,
                limit=200,
            )
        except Exception as exc:
            logger.warning("list_clients: %s", exc)
            self._clients = []
            self._set_status(f"Erreur : {exc}", error=True)
            return
        self._set_status(f"{len(self._clients)} client(s) chargé(s).")

        for child in self._list_body.winfo_children():
            child.destroy()

        if not self._clients:
            EmptyState(
                self._list_body,
                text="Aucun client. Quand un prospect remplit un formulaire ou paye une facture, il apparaîtra ici.",
            ).pack(fill="both", expand=True, pady=24)
            return

        for c in self._clients:
            self._render_list_row(c)

    def _render_list_row(self, client: dict):
        row = ctk.CTkFrame(self._list_body, fg_color=self.colors.panel,
                            corner_radius=8)
        row.pack(fill="x", padx=4, pady=3)

        # Ligne 1 : nom / société + statut
        head = ctk.CTkFrame(row, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(8, 2))

        full_name = (client.get("full_name") or "").strip()
        if not full_name:
            full_name = "(nom non fourni)"
        company = client.get("company_name") or ""

        primary_text = full_name + (f"  ·  {company}" if company else "")
        ctk.CTkLabel(
            head, text=primary_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).pack(side="left")

        status = client.get("status") or "lead"
        ctk.CTkLabel(
            head, text=STATUS_LABELS.get(status, status),
            text_color=self.colors.accent,
            font=ctk.CTkFont(size=9, weight="bold"),
        ).pack(side="right")

        # Ligne 2 : email + dernier contact
        meta = ctk.CTkFrame(row, fg_color="transparent")
        meta.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(
            meta, text=f"📧 {client.get('email', '—')}",
            text_color=self.colors.text_muted,
            font=ctk.CTkFont(size=10), anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            meta, text=_fmt_dt(client.get("last_contact_at") or client.get("created_at", "")),
            text_color=self.colors.text_muted,
            font=ctk.CTkFont(size=9),
        ).pack(side="right")

        # Ligne 3 : compteurs (sites, factures, mails)
        counters_parts = []
        lag = client.get("lagriffe_count") or 0
        rk = client.get("rankus_count") or 0
        wow = client.get("wow_count") or 0
        inv = client.get("invoices_count") or 0
        em = client.get("emails_sent_count") or 0
        if lag: counters_parts.append(f"Lagriffe ×{lag}")
        if rk: counters_parts.append(f"RankUs ×{rk}")
        if wow: counters_parts.append(f"WoW ×{wow}")
        if inv: counters_parts.append(f"Factures ×{inv}")
        if em: counters_parts.append(f"Emails ×{em}")
        if counters_parts:
            ctk.CTkLabel(
                row, text=" · ".join(counters_parts),
                text_color=self.colors.text_muted,
                font=ctk.CTkFont(size=9), anchor="w",
            ).pack(fill="x", padx=12, pady=(0, 8))
        else:
            ctk.CTkFrame(row, height=4, fg_color="transparent").pack()

        # Click → sélectionne
        def _select(_=None, _id=client["id"]):
            self._selected_id = _id
            self._render_detail(_id)
        row.bind("<Button-1>", _select)
        for child in row.winfo_children():
            child.bind("<Button-1>", _select)
            for sub in child.winfo_children():
                sub.bind("<Button-1>", _select)

    # -----------------------------------------------------------------
    # Détail (panneau droit)
    # -----------------------------------------------------------------
    def _render_empty_detail(self):
        for child in self._detail_body.winfo_children():
            child.destroy()
        EmptyState(
            self._detail_body,
            text="Sélectionne un client dans la liste à gauche pour voir sa fiche complète.",
        ).pack(fill="both", expand=True, pady=24)

    def _render_detail(self, client_id: str):
        for child in self._detail_body.winfo_children():
            child.destroy()

        def _run():
            c = cm.get_client_360(client_id)
            timeline = cm.get_client_timeline(client_id, limit=30)
            self.after(0, lambda: self._render_detail_ui(c, timeline))

        ctk.CTkLabel(self._detail_body, text="Chargement…",
                     text_color=self.colors.text_muted).pack(pady=24)
        threading.Thread(target=_run, daemon=True).start()

    def _render_detail_ui(self, c: Optional[dict], timeline: list[dict]):
        for child in self._detail_body.winfo_children():
            child.destroy()

        if not c:
            ctk.CTkLabel(self._detail_body, text="Client introuvable.",
                         text_color=self.colors.danger).pack(pady=24)
            return

        # ── Header : nom + statut + email ──
        full_name = (c.get("full_name") or "").strip() or "(nom non fourni)"
        ctk.CTkLabel(
            self._detail_body, text=full_name,
            font=ctk.CTkFont(size=18, weight="bold"), anchor="w",
        ).pack(fill="x", padx=12, pady=(12, 0))

        company = c.get("company_name") or ""
        if company:
            ctk.CTkLabel(
                self._detail_body, text=company,
                text_color=self.colors.text_muted,
                font=ctk.CTkFont(size=11), anchor="w",
            ).pack(fill="x", padx=12)

        ctk.CTkLabel(
            self._detail_body,
            text=f"📧  {c.get('email', '—')}    ·    📱  {c.get('phone') or '—'}",
            text_color=self.colors.text_muted,
            font=ctk.CTkFont(size=10), anchor="w",
        ).pack(fill="x", padx=12, pady=(6, 12))

        # ── Compteurs ──
        counters_frame = ctk.CTkFrame(self._detail_body, fg_color=self.colors.panel, corner_radius=8)
        counters_frame.pack(fill="x", padx=12, pady=(0, 12))
        lag = c.get("lagriffe_count") or 0
        rk = c.get("rankus_count") or 0
        wow = c.get("wow_count") or 0
        inv = c.get("invoices_count") or 0
        em = c.get("emails_sent_count") or 0
        proj = c.get("projects_count") or 0
        line = f"  🟢 Lagriffe : {lag}   🟣 RankUs : {rk}   ⚫ WoW : {wow}   📄 Factures : {inv}   ✉️ Emails : {em}   📦 Projets : {proj}"
        ctk.CTkLabel(counters_frame, text=line,
                     font=ctk.CTkFont(size=10),
                     anchor="w", justify="left").pack(fill="x", padx=8, pady=8)

        # ── Identité ──
        id_card = Card(self._detail_body, title="Identité")
        id_card.pack(fill="x", padx=12, pady=(0, 10))
        identity_lines = [
            f"Statut : {STATUS_LABELS.get(c.get('status', 'lead'), c.get('status', 'lead'))}",
            f"Type : {'Professionnel' if c.get('is_pro') else 'Particulier'}",
            f"SIRET : {c.get('siret') or '—'}",
            f"Adresse : {(c.get('address_line1') or '—')}, {(c.get('address_zip') or '')} {(c.get('address_city') or '')}",
            f"Sources : {', '.join(c.get('sources') or []) or '—'}",
            f"Tags : {', '.join(c.get('tags') or []) or '—'}",
            f"Premier contact : {_fmt_dt(c.get('first_contact_at', ''))}",
            f"Dernier contact : {_fmt_dt(c.get('last_contact_at', ''))}",
            f"Stripe customer : {c.get('stripe_customer_id') or '—'}",
        ]
        for txt in identity_lines:
            ctk.CTkLabel(
                id_card.body, text=txt,
                font=ctk.CTkFont(size=10), anchor="w",
                text_color=self.colors.text_secondary,
            ).pack(fill="x", padx=12, pady=2)

        # ── Timeline ──
        tl_card = Card(self._detail_body, title=f"Historique ({len(timeline)} événements)")
        tl_card.pack(fill="x", padx=12, pady=(0, 10))

        if not timeline:
            ctk.CTkLabel(
                tl_card.body, text="Aucun événement encore.",
                text_color=self.colors.text_muted, anchor="w",
            ).pack(fill="x", padx=12, pady=8)
        else:
            for ev in timeline:
                row = ctk.CTkFrame(tl_card.body, fg_color="transparent")
                row.pack(fill="x", padx=12, pady=4)
                icon = EVENT_ICONS.get(ev.get("type"), "•")
                line = f"{icon}  {_fmt_dt(ev.get('created_at', ''))}    {ev.get('type', '')} — {ev.get('label', '')}"
                if ev.get("status"):
                    line += f"   ({ev.get('status')})"
                ctk.CTkLabel(
                    row, text=line,
                    font=ctk.CTkFont(size=10), anchor="w", justify="left",
                ).pack(fill="x")

        # ── Notes ──
        notes_card = Card(self._detail_body, title="Notes internes")
        notes_card.pack(fill="x", padx=12, pady=(0, 16))
        self._notes_txt = ctk.CTkTextbox(notes_card.body, height=80)
        self._notes_txt.pack(fill="x", padx=8, pady=8)
        self._notes_txt.insert("1.0", c.get("notes") or "")

        # Boutons
        btns = ctk.CTkFrame(notes_card.body, fg_color="transparent")
        btns.pack(fill="x", padx=8, pady=(0, 8))
        PrimaryButton(btns, text="Enregistrer les notes",
                      command=self._save_notes).pack(side="left", padx=4)
        SecondaryButton(btns, text="Changer le statut",
                        command=self._change_status).pack(side="left", padx=4)

    # -----------------------------------------------------------------
    def _save_notes(self):
        if not self._selected_id:
            return
        notes = self._notes_txt.get("1.0", "end").strip()
        ok = cm.update_client(self._selected_id, notes=notes)
        self._set_status("Notes enregistrées." if ok else "Échec enregistrement.", error=not ok)

    def _change_status(self):
        if not self._selected_id:
            return
        from tkinter import simpledialog
        new = simpledialog.askstring(
            "Changer le statut",
            "Nouveau statut (lead / prospect / client / inactive / churned) :",
        )
        if not new:
            return
        if new not in STATUS_LABELS:
            self._set_status(f"Statut invalide : {new}", error=True)
            return
        ok = cm.update_client(self._selected_id, status=new)
        if ok:
            self._set_status(f"Statut → {STATUS_LABELS[new]}")
            self._render_detail(self._selected_id)
            self._refresh()
        else:
            self._set_status("Échec changement statut.", error=True)

    # -----------------------------------------------------------------
    # Import CSV / Excel
    # -----------------------------------------------------------------
    def _import_file(self):
        """Ouvre un dialogue de sélection de fichier, parse et importe les
        clients via ensure_client (idempotent)."""
        from tkinter import filedialog, messagebox
        path = filedialog.askopenfilename(
            title="Importer une liste de clients",
            filetypes=[
                ("Tous formats", "*.csv *.xlsx *.xls *.pdf"),
                ("CSV", "*.csv"),
                ("Excel", "*.xlsx *.xls"),
                ("PDF (extraction IA)", "*.pdf"),
                ("Tous", "*.*"),
            ],
        )
        if not path:
            return

        self._set_status(f"Lecture du fichier {path}…")

        def _run():
            try:
                rows = self._parse_file(path)
            except Exception as exc:
                self.after(0, lambda: self._set_status(
                    f"Échec lecture fichier : {exc}", error=True))
                return

            if not rows:
                self.after(0, lambda: self._set_status(
                    "Aucune ligne lisible dans ce fichier.", error=True))
                return

            created = 0
            updated = 0
            errors = 0
            for r in rows:
                email = (r.get("email") or "").strip().lower()
                if not email or "@" not in email:
                    errors += 1
                    continue
                # Vérifie si déjà existant pour différencier created/updated
                existing = cm.get_client_by_email(email)
                cid = cm.ensure_client(
                    email=email,
                    first_name=(r.get("first_name") or r.get("prenom") or "").strip(),
                    last_name=(r.get("last_name") or r.get("nom") or "").strip(),
                    phone=(r.get("phone") or r.get("telephone") or "").strip(),
                    company_name=(r.get("company_name") or r.get("societe") or r.get("company") or "").strip(),
                    siret=(r.get("siret") or "").strip(),
                    source="import_file",
                )
                if cid is None:
                    errors += 1
                elif existing:
                    updated += 1
                else:
                    created += 1

            total = len(rows)
            msg = f"Import terminé : {created} nouveau(x), {updated} déjà connu(s), {errors} erreur(s) (sur {total} lignes)."
            self.after(0, lambda: (
                messagebox.showinfo("Import terminé", msg),
                self._set_status(msg),
                self._refresh(),
            ))

        import threading
        threading.Thread(target=_run, daemon=True).start()

    def _parse_file(self, path: str) -> list[dict]:
        """Lit un fichier .csv ou .xlsx et renvoie une liste de dicts
        (clés en lowercase, snake_case)."""
        import os
        ext = os.path.splitext(path)[1].lower()
        rows: list[dict] = []

        if ext == ".csv":
            import csv
            # Détection automatique de l'encoding et du délimiteur
            for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
                try:
                    with open(path, "r", encoding=encoding, newline="") as f:
                        sample = f.read(4096)
                        f.seek(0)
                        try:
                            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                        except Exception:
                            dialect = csv.excel
                        reader = csv.DictReader(f, dialect=dialect)
                        for r in reader:
                            rows.append({
                                (k or "").strip().lower().replace(" ", "_"): (v or "").strip()
                                for k, v in r.items()
                            })
                    break
                except UnicodeDecodeError:
                    continue
        elif ext in (".xlsx", ".xls"):
            try:
                import openpyxl
            except ImportError:
                raise RuntimeError("openpyxl non installé. Lance : pip install openpyxl")
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            headers = None
            for raw_row in ws.iter_rows(values_only=True):
                if headers is None:
                    headers = [
                        str(h).strip().lower().replace(" ", "_") if h else ""
                        for h in raw_row
                    ]
                    continue
                if all(c is None or str(c).strip() == "" for c in raw_row):
                    continue
                row_dict = {}
                for i, val in enumerate(raw_row):
                    if i < len(headers) and headers[i]:
                        row_dict[headers[i]] = str(val).strip() if val is not None else ""
                if row_dict:
                    rows.append(row_dict)
        elif ext == ".pdf":
            rows = self._parse_pdf_via_claude(path)
        else:
            raise RuntimeError(f"Format non supporté : {ext}")

        return rows

    # -----------------------------------------------------------------
    # Extraction PDF via Claude API
    # -----------------------------------------------------------------
    def _parse_pdf_via_claude(self, path: str) -> list[dict]:
        """Extrait le texte du PDF puis demande à Claude de retourner
        une liste structurée de clients sous forme JSON.

        Renvoie une liste de dicts (email, first_name, last_name, phone,
        company_name, siret) prête pour ensure_client.
        """
        # 1. Extraction texte
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError("pypdf non installé. Lance : pip install pypdf")

        reader = PdfReader(path)
        pages = []
        for i, page in enumerate(reader.pages):
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pages.append("")
        text = "\n\n--- PAGE ---\n\n".join(pages).strip()
        if not text:
            raise RuntimeError("PDF illisible (aucun texte extractible). Probablement un PDF scanné → OCR requis.")

        # Limiter à ~80k chars pour rester dans le contexte (~25 pages)
        if len(text) > 80000:
            text = text[:80000] + "\n\n[...PDF tronqué...]"

        # 2. Récupère la clé Anthropic depuis app_state
        ai = self.app_state.get("ai", default={}) or {}
        keys = ai.get("api_keys") or {}
        api_key = keys.get("anthropic") or ""
        if not api_key:
            raise RuntimeError(
                "Clé Anthropic absente. Va dans Réglages → IA → API keys → Anthropic."
            )

        # 3. Appel Claude API
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("anthropic non installé. Lance : pip install anthropic")

        client = anthropic.Anthropic(api_key=api_key)

        prompt = (
            "Tu es un assistant d'extraction de données structurées. "
            "Voici le contenu d'un fichier PDF qui contient une liste de "
            "clients ou de prospects (potentiellement formatée en tableau, "
            "annuaire, liste de cartes de visite, export d'un autre outil…). "
            "\n\n"
            "Extrais TOUS les contacts trouvés dans ce document et retourne-les "
            "sous forme d'un tableau JSON STRICT (sans aucun texte autour, "
            "uniquement le tableau JSON valide). "
            "\n\n"
            "Schéma de chaque entrée (tous les champs sont des STRINGS, "
            "mettre une chaîne vide si l'info n'est pas présente) :\n"
            "  - email\n"
            "  - first_name\n"
            "  - last_name\n"
            "  - phone\n"
            "  - company_name\n"
            "  - siret\n"
            "\n"
            "Règle : tu ne renvoies une entrée QUE si tu as au moins un email valide. "
            "Pas d'invention : si une info n'est pas dans le PDF, mets une chaîne vide. "
            "Réponse = uniquement le JSON, rien d'autre. Exemple : "
            '[{"email":"jean@x.fr","first_name":"Jean","last_name":"Dupont","phone":"0612345678","company_name":"Boulangerie","siret":""}]'
            "\n\n"
            "--- CONTENU DU PDF ---\n\n"
            + text
        )

        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )

        # 4. Parse la réponse JSON
        import json, re
        raw = "".join(
            block.text for block in message.content
            if getattr(block, "type", "") == "text"
        ).strip()

        # Cherche le 1er tableau JSON dans la réponse (au cas où Claude
        # ajoute du texte autour malgré l'instruction)
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not match:
            raise RuntimeError(f"Réponse Claude non parsable : {raw[:200]}")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"JSON invalide dans la réponse Claude : {e}")

        if not isinstance(data, list):
            raise RuntimeError("La réponse Claude n'est pas un tableau.")

        # Normalise chaque entrée
        rows = []
        for r in data:
            if not isinstance(r, dict):
                continue
            rows.append({
                "email": (r.get("email") or "").strip().lower(),
                "first_name": (r.get("first_name") or "").strip(),
                "last_name": (r.get("last_name") or "").strip(),
                "phone": (r.get("phone") or "").strip(),
                "company_name": (r.get("company_name") or "").strip(),
                "siret": (r.get("siret") or "").strip(),
            })
        return rows
