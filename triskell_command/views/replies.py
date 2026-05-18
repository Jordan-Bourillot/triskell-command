"""Vue Réponses — affiche les mails entrants détectés par le poller IMAP,
classés par l'IA en interested / not_now / no / unsubscribe / unknown.

L'utilisateur peut filtrer par catégorie, lire la réponse, marquer traité,
ou ouvrir le thread du prospect dans la vue Prospects.

Le poller tourne en background depuis le boot — cette vue se contente de
lire la table email_history (kind=reply_received). Elle n'a pas à connaître
IMAP.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import customtkinter as ctk

from .. import theme as T
from ..integrations import replies_poller, reply_responder
from ..widgets.components import (
    Card,
    Chip,
    EmptyState,
    PrimaryButton,
    SecondaryButton,
    StatusPill,
    ViewHeader,
)
from .base import BaseView

logger = logging.getLogger(__name__)


CATEGORY_LABELS = {
    "all":          "Toutes",
    "interested":   "Intéressé",
    "not_now":      "Pas maintenant",
    "no":           "Refus",
    "unsubscribe":  "Désinscription",
    "unknown":      "À trier",
}

CATEGORY_COLORS = {
    "interested":   "success",
    "not_now":      "warning",
    "no":           "danger",
    "unsubscribe":  "danger",
    "unknown":      "text_muted",
}


class RepliesView(BaseView):
    title = "Réponses"
    subtitle = (
        "Les prospects qui te répondent atterrissent ici, déjà triés. "
        "Pas besoin d'ouvrir ta boîte mail."
    )

    def build(self) -> None:
        c = self.colors
        header = ViewHeader(self, title=self.title, subtitle=self.subtitle, colors=c)
        header.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_MD))

        SecondaryButton(header.actions, colors=c, icon="settings",
                         text="Automatisation",
                         command=self._open_settings).pack(side="left",
                                                            padx=(0, T.SPACE_SM))
        SecondaryButton(header.actions, colors=c, icon="refresh",
                         text="Rafraîchir",
                         command=self._refresh).pack(side="left",
                                                      padx=(0, T.SPACE_SM))
        PrimaryButton(header.actions, colors=c, icon="convoy",
                       text="Vérifier maintenant",
                       command=self._poll_now).pack(side="left")

        # Filtres par catégorie — précédés d'un petit label pour donner sens
        filters_wrap = ctk.CTkFrame(self, fg_color="transparent")
        filters_wrap.pack(fill="x", padx=T.SPACE_2XL, pady=(T.SPACE_SM, T.SPACE_LG))
        ctk.CTkLabel(
            filters_wrap, text="FILTRER PAR TYPE",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(0, T.SPACE_XS))
        filters_row = ctk.CTkFrame(filters_wrap, fg_color="transparent")
        filters_row.pack(fill="x", anchor="w")
        self._chips: dict[str, Chip] = {}
        self._active_filter = "all"
        for key, label in CATEGORY_LABELS.items():
            chip = Chip(
                filters_row, text=label, colors=c,
                is_active=(key == "all"),
                on_toggle=lambda _v, k=key: self._set_filter(k),
            )
            chip.pack(side="left", padx=(0, T.SPACE_SM))
            self._chips[key] = chip

        # Container scroll
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
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
            text_color=c.text_muted,
        ).pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

    def on_show(self) -> None:
        self._refresh()

    # ------------------------------------------------------------------
    def _set_filter(self, key: str) -> None:
        self._active_filter = key
        # Visuellement, on s'assure qu'un seul chip est actif
        for k, chip in self._chips.items():
            chip.set_active(k == key)
        self._refresh()

    def _refresh(self) -> None:
        # Vide la liste
        for w in self._scroll.winfo_children():
            w.destroy()

        client = self._get_client()
        if client is None:
            EmptyState(
                self._scroll, colors=self.colors, icon="settings",
                title="Connexion à la base partagée requise",
                message=(
                    "Pour détecter automatiquement les réponses des prospects, "
                    "connecte-toi à la base partagée Triskell depuis les "
                    "Réglages. La surveillance des mails démarrera "
                    "immédiatement."
                ),
                cta_text="Aller dans Réglages",
                cta_command=lambda: self._navigate_to("config"),
            ).pack(fill="both", expand=True)
            self._status_var.set("Connexion requise.")
            return

        rows = self._fetch_unhandled(client, self._active_filter)
        prospects_by_id = self._fetch_prospects(client,
                                                  [r.get("prospect_id") for r in rows])

        if not rows:
            poller_status = replies_poller.get_status()
            run_info = ""
            if poller_status.get("last_run_at"):
                res = poller_status.get("last_run_result", {})
                run_info = (
                    f"  ·  Dernière vérification {poller_status['last_run_at']} : "
                    f"{res.get('scanned', 0)} mail(s) examiné(s), "
                    f"{res.get('matched', 0)} associé(s) à un prospect, "
                    f"{res.get('written', 0)} nouveau(x)."
                )
            EmptyState(
                self._scroll, colors=self.colors, icon="check",
                title="Aucune réponse en attente",
                message=(
                    "L'app vérifie ta boîte mail toutes les 5 minutes. "
                    "Tu peux forcer une vérification immédiate avec le "
                    "bouton « Vérifier maintenant » en haut à droite."
                ),
            ).pack(fill="both", expand=True)
            self._status_var.set(f"Aucune réponse à traiter.{run_info}")
            return

        for row in rows:
            self._make_reply_card(row, prospects_by_id.get(row.get("prospect_id"), {}))

        self._status_var.set(
            f"{len(rows)} réponse(s) en attente"
            f" · filtre : {CATEGORY_LABELS.get(self._active_filter, self._active_filter)}"
        )

    def _make_reply_card(self, row: dict, prospect: dict) -> None:
        c = self.colors
        extra = row.get("extra") or {}
        if isinstance(extra, str):
            try:
                import json
                extra = json.loads(extra)
            except Exception:
                extra = {}
        category = (extra.get("classification") or {}).get("category", "unknown")
        confidence = (extra.get("classification") or {}).get("confidence", 0.0)

        card = Card(self._scroll, colors=c)
        card.pack(fill="x", pady=(0, T.SPACE_LG))

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=T.SPACE_XL, pady=(T.SPACE_LG, T.SPACE_SM))

        name = prospect.get("name") or prospect.get("legal_name") or "(prospect inconnu)"
        emails_list = prospect.get("emails") or []
        email_first = emails_list[0] if emails_list else (extra.get("from") or "")

        # Bloc gauche : nom + email + date
        left = ctk.CTkFrame(head, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            left, text=name,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", anchor="w")
        ctk.CTkLabel(
            left, text=f"{email_first}  ·  {row.get('ts','')[:19].replace('T',' ')}",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w")

        # Bloc droite : badge catégorie
        right = ctk.CTkFrame(head, fg_color="transparent")
        right.pack(side="right")
        cat_label = CATEGORY_LABELS.get(category, category)
        cat_color_attr = CATEGORY_COLORS.get(category, "text_muted")
        try:
            cat_text_color = getattr(c, cat_color_attr)
        except AttributeError:
            cat_text_color = c.text_muted
        ctk.CTkLabel(
            right, text=cat_label,
            text_color=cat_text_color,
            fg_color=c.panel,
            corner_radius=T.RADIUS_PILL,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            padx=10, pady=4,
        ).pack(side="right", padx=(T.SPACE_SM, 0))
        if confidence:
            ctk.CTkLabel(
                right, text=f"{int(confidence*100)}%",
                text_color=c.text_muted,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
            ).pack(side="right", padx=(0, T.SPACE_SM))

        # Subject
        subject = row.get("subject") or "(sans objet)"
        ctk.CTkLabel(
            card, text=subject,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY_LG, "bold"),
            text_color=c.text_primary, anchor="w",
            justify="left", wraplength=900,
        ).pack(fill="x", padx=T.SPACE_XL, pady=(0, T.SPACE_XS))

        # Body excerpt
        body = (extra.get("body_excerpt") or "").strip()
        if body:
            ctk.CTkLabel(
                card, text=body[:600] + ("…" if len(body) > 600 else ""),
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
                text_color=c.text_secondary, anchor="w",
                justify="left", wraplength=900,
            ).pack(fill="x", padx=T.SPACE_XL, pady=(0, T.SPACE_MD))

        # Bloc brouillon suggéré (si présent)
        suggested = extra.get("suggested_reply") or {}
        if suggested and suggested.get("status") in ("pending", "sent"):
            self._make_suggested_block(card, row, suggested)

        # Footer card : actions
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=T.SPACE_XL, pady=(T.SPACE_SM, T.SPACE_LG))
        SecondaryButton(
            actions, colors=c, text="Voir prospect",
            command=lambda pid=row.get("prospect_id"): self._goto_prospect(pid),
        ).pack(side="left", padx=(0, T.SPACE_SM))
        if not suggested:
            PrimaryButton(
                actions, colors=c, text="Marquer traité",
                command=lambda rid=row.get("id"): self._mark_handled(rid),
            ).pack(side="left")
        else:
            SecondaryButton(
                actions, colors=c, text="Marquer traité",
                command=lambda rid=row.get("id"): self._mark_handled(rid),
            ).pack(side="left")

    def _make_suggested_block(self, card, row, suggested) -> None:
        """Affiche le draft de réponse + actions Envoyer / Modifier / Annuler."""
        c = self.colors
        rid = row.get("id")
        mode = suggested.get("mode", "manual")
        status = suggested.get("status", "pending")

        wrap = ctk.CTkFrame(
            card, fg_color=c.panel_elevated if hasattr(c, "panel_elevated") else c.panel,
            corner_radius=T.RADIUS_SM,
        )
        wrap.pack(fill="x", padx=T.SPACE_XL, pady=(T.SPACE_SM, 0))

        # Header bloc brouillon
        head = ctk.CTkFrame(wrap, fg_color="transparent")
        head.pack(fill="x", padx=T.SPACE_MD, pady=(T.SPACE_MD, 0))

        bar = ctk.CTkFrame(head, fg_color=c.accent, width=20, height=2,
                            corner_radius=1)
        bar.pack(side="left", padx=(0, T.SPACE_SM))
        bar.pack_propagate(False)

        ctk.CTkLabel(
            head, text="Réponse suggérée",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(side="left", fill="x")

        mode_label, mode_color = self._format_mode_badge(mode, status, suggested)
        ctk.CTkLabel(
            head, text=mode_label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=mode_color, fg_color=c.panel,
            corner_radius=T.RADIUS_PILL, padx=8, pady=2,
        ).pack(side="right")

        # Subject
        ctk.CTkLabel(
            wrap, text=suggested.get("subject", ""),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color=c.text_primary, anchor="w",
            justify="left", wraplength=860,
        ).pack(fill="x", padx=T.SPACE_MD, pady=(T.SPACE_XS, 0))

        # Body
        body_text = (suggested.get("body") or "").strip()
        body_show = body_text[:500] + ("…" if len(body_text) > 500 else "")
        ctk.CTkLabel(
            wrap, text=body_show,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            text_color=c.text_secondary, anchor="w",
            justify="left", wraplength=860,
        ).pack(fill="x", padx=T.SPACE_MD, pady=(0, T.SPACE_SM))

        if status == "sent":
            return  # rien à faire de plus

        # Actions
        act = ctk.CTkFrame(wrap, fg_color="transparent")
        act.pack(fill="x", padx=T.SPACE_MD, pady=(0, T.SPACE_SM))
        SecondaryButton(
            act, colors=c, text="Modifier",
            command=lambda r=row, s=suggested: self._open_edit(r, s),
        ).pack(side="left", padx=(0, T.SPACE_SM))
        SecondaryButton(
            act, colors=c, text="Annuler le brouillon",
            command=lambda i=rid: self._cancel_draft(i),
        ).pack(side="left", padx=(0, T.SPACE_SM))
        PrimaryButton(
            act, colors=c, text="Envoyer maintenant",
            command=lambda i=rid: self._send_now(i),
        ).pack(side="left")

    def _format_mode_badge(self, mode: str, status: str,
                            suggested: dict) -> tuple[str, str]:
        c = self.colors
        if status == "sent":
            return ("envoyé", c.success)
        if mode == "manual":
            return ("validation manuelle", c.text_muted)
        if mode == "instant":
            return ("envoi imminent", c.warning)
        if mode == "delay_30m":
            send_after = suggested.get("send_after", "")
            try:
                from datetime import datetime
                target = datetime.fromisoformat(send_after)
                delta = (target - datetime.now()).total_seconds()
                if delta <= 0:
                    return ("envoi imminent", c.warning)
                mins = int(delta // 60)
                return (f"auto dans {mins} min", c.warning)
            except Exception:
                return ("auto 30 min", c.warning)
        return (mode, c.text_muted)

    # ------------------------------------------------------------------
    # Data fetch
    # ------------------------------------------------------------------
    def _get_client(self):
        try:
            from triskell_core.db import get_client, SupabaseNotConfigured
        except ImportError:
            return None
        try:
            client = get_client()
        except SupabaseNotConfigured:
            return None
        if not client.is_authenticated:
            return None
        return client

    def _fetch_unhandled(self, client, category_filter: str) -> list[dict]:
        try:
            sb = client.raw
            q = (sb.table("email_history").select("*")
                 .eq("kind", "reply_received")
                 .order("ts", desc=True).limit(200))
            res = q.execute()
            rows = res.data or []
            out = []
            # Rows detectees comme mails auto (newsletter / notif / no-reply)
            # qui ne devraient jamais avoir atteri ici. On les marque
            # handled=true en background pour qu'elles disparaissent
            # definitivement.
            auto_to_cleanup: list[str] = []
            try:
                from ..integrations import prospect_status as PS
            except Exception:
                PS = None
            for r in rows:
                extra = r.get("extra") or {}
                if isinstance(extra, str):
                    try:
                        import json
                        extra = json.loads(extra)
                    except Exception:
                        extra = {}
                if extra.get("handled"):
                    continue
                # Detection retroactive des mails automatiques. Pour les
                # anciens rows on n'a pas les headers IMAP stockes — on se
                # rabat sur le from + subject, ce qui suffit pour les
                # newsletters et notifs evidentes (noreply@, security@,
                # domaines connus, sujets type "bulletin", "new login"...).
                from_addr = (extra.get("from") or "").lower()
                subject = r.get("subject") or ""
                if PS is not None and PS.looks_like_automated(
                        headers={}, from_addr=from_addr, subject=subject):
                    rid = r.get("id")
                    if rid:
                        auto_to_cleanup.append(rid)
                    continue
                if category_filter != "all":
                    cat = (extra.get("classification") or {}).get("category", "unknown")
                    if cat != category_filter:
                        continue
                # Reattach extra parsé pour l'affichage
                r["extra"] = extra
                out.append(r)
            # Cleanup background : marque les autos handled=true en DB pour
            # qu'ils ne reapparaissent plus aux prochains refresh.
            if auto_to_cleanup:
                threading.Thread(
                    target=self._cleanup_auto_rows,
                    args=(client, auto_to_cleanup),
                    daemon=True,
                ).start()
            return out
        except Exception as exc:
            logger.warning("fetch_unhandled: %s", exc)
            return []

    def _cleanup_auto_rows(self, client, row_ids: list[str]) -> None:
        """Marque handled=true les rows reply_received qui sont en fait des
        mails automatiques. Appele en background depuis _fetch_unhandled.
        """
        if not row_ids:
            return
        sb = client.raw
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        for rid in row_ids:
            try:
                # On lit l'extra courant pour preserver les autres cles
                res = (sb.table("email_history").select("extra")
                       .eq("id", rid).limit(1).execute())
                row = (res.data or [{}])[0]
                extra = row.get("extra") or {}
                if isinstance(extra, str):
                    try:
                        import json
                        extra = json.loads(extra)
                    except Exception:
                        extra = {}
                extra["handled"] = True
                extra["handled_at"] = now
                extra["auto_cleanup"] = "filtered_as_automated_mail"
                sb.table("email_history").update(
                    {"extra": extra}).eq("id", rid).execute()
            except Exception as exc:
                logger.debug("cleanup auto row %s KO: %s", rid, exc)
        logger.info("Reponses : %s mails auto nettoyes", len(row_ids))

    def _fetch_prospects(self, client, ids: list) -> dict:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        try:
            sb = client.raw
            res = (sb.table("prospects")
                   .select("id,name,legal_name,emails,status")
                   .in_("id", list(set(ids))).execute())
            return {r["id"]: r for r in (res.data or []) if r.get("id")}
        except Exception as exc:
            logger.warning("fetch_prospects: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _mark_handled(self, row_id: str) -> None:
        if not row_id:
            return
        client = self._get_client()
        if client is None:
            return
        # On lit la row, on update extra.handled = true, on push.
        try:
            sb = client.raw
            res = (sb.table("email_history").select("extra")
                   .eq("id", row_id).limit(1).execute())
            row = (res.data or [{}])[0]
            extra = row.get("extra") or {}
            if isinstance(extra, str):
                try:
                    import json
                    extra = json.loads(extra)
                except Exception:
                    extra = {}
            extra["handled"] = True
            from datetime import datetime
            extra["handled_at"] = datetime.now().isoformat(timespec="seconds")
            sb.table("email_history").update({"extra": extra}).eq("id", row_id).execute()
        except Exception as exc:
            logger.warning("mark_handled %s: %s", row_id, exc)
        self._refresh()

    def _goto_prospect(self, prospect_id: str) -> None:
        # On stocke le prospect_id ciblé dans app_state pour que la vue
        # Prospects puisse filtrer dessus (compat futur).
        if prospect_id:
            try:
                self.app_state.set("ui", "focus_prospect_id", value=prospect_id)
            except Exception:
                pass
        self._navigate_to("prospects")

    def _poll_now(self) -> None:
        # Vérification synchrone, dans un thread pour ne pas bloquer l'UI.
        self._status_var.set("Vérification de la boîte mail en cours…")
        def _run():
            res = replies_poller.poll_now(self.app_state)
            try:
                self.after(0, lambda: self._on_poll_done(res))
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def _on_poll_done(self, res: dict) -> None:
        if "error" in res:
            err = res.get("error", "")
            # Traduit les erreurs techniques courantes en français parlant
            if err == "supabase_unavailable":
                msg = "La base partagée n'est pas accessible (connecte-toi)."
            elif err == "imap_not_configured":
                msg = "Renseigne tes identifiants mail dans Réglages."
            else:
                msg = f"Vérification interrompue : {err}"
            self._status_var.set(msg)
        else:
            self._status_var.set(
                f"Vérification terminée : "
                f"{res.get('scanned', 0)} mail(s) examiné(s), "
                f"{res.get('matched', 0)} associé(s) à un prospect, "
                f"{res.get('written', 0)} nouveau(x), "
                f"{res.get('errors', 0)} erreur(s)."
            )
        self._refresh()

    # ------------------------------------------------------------------
    # Suggested reply : actions
    # ------------------------------------------------------------------
    def _send_now(self, history_row_id: str) -> None:
        client = self._get_client()
        if client is None:
            return
        self._status_var.set("Envoi en cours…")
        def _run():
            res = reply_responder.send_now(client, self.app_state, history_row_id)
            self.after(0, lambda r=res: self._on_send_done(r))
        threading.Thread(target=_run, daemon=True).start()

    def _on_send_done(self, res: dict) -> None:
        if res.get("success"):
            self._status_var.set("Réponse envoyée.")
        else:
            self._status_var.set(f"Échec envoi : {res.get('error', 'inconnu')}")
        self._refresh()

    def _cancel_draft(self, history_row_id: str) -> None:
        client = self._get_client()
        if client is None:
            return
        reply_responder.cancel_draft(client, history_row_id)
        self._refresh()

    def _open_edit(self, row: dict, suggested: dict) -> None:
        from ..widgets.reply_edit_dialog import ReplyEditDialog
        client = self._get_client()
        if client is None:
            return

        def on_save(subject: str, body: str) -> None:
            res = reply_responder.update_draft(
                client, row.get("id"), subject=subject, body=body)
            if res.get("success"):
                self._status_var.set("Brouillon mis à jour.")
            else:
                self._status_var.set(f"Échec : {res.get('error')}")
            self._refresh()

        ReplyEditDialog(
            self.winfo_toplevel(), colors=self.colors,
            subject=suggested.get("subject", ""),
            body=suggested.get("body", ""),
            on_save=on_save,
        )

    def _open_settings(self) -> None:
        from ..widgets.reply_settings_dialog import ReplySettingsDialog
        client = self._get_client()
        if client is None:
            self._status_var.set(
                "Connecte-toi à la base partagée Triskell pour régler "
                "le niveau d'automatisation.")
            return
        ReplySettingsDialog(
            self.winfo_toplevel(), colors=self.colors,
            client=client, on_done=self._refresh,
        )
