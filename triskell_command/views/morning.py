"""Matinale — l'écran qui t'accueille le matin.

Esprit : Apple-clear. Hiérarchie nette, large white space, peu de chiffres
mais bien choisis, ton chaleureux. Une seule priorité mise en avant à la
fois — pas une liste anxiogène.
"""

from __future__ import annotations

import logging
from datetime import datetime

import customtkinter as ctk

from .. import theme as T
from ..integrations import morning_digest
from ..tokens_v2 import ttype
from ..widgets.components import (
    Card,
    EmptyState,
    PrimaryButton,
    SecondaryButton,
    StatCard,
)
from ..widgets.components_pro import KpiHero
from .base import BaseView

logger = logging.getLogger(__name__)


# Salutation contextuelle simple selon l'heure
def _greeting() -> str:
    h = datetime.now().hour
    if h < 6:
        return "Bonne nuit"
    if h < 12:
        return "Bonjour"
    if h < 18:
        return "Bon après-midi"
    return "Bonsoir"


def _date_phrase() -> str:
    months = ["janvier", "février", "mars", "avril", "mai", "juin",
              "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    days = ["lundi", "mardi", "mercredi", "jeudi", "vendredi",
            "samedi", "dimanche"]
    now = datetime.now()
    return f"{days[now.weekday()]} {now.day} {months[now.month - 1]}"


def _transition_phrase(digest: dict | None) -> str:
    """Phrase d'accroche contextuelle au-dessous du greeting.

    Patch M3 (cf. docs/PATCHES.md) : varie selon ce qui attend
    réellement l'utilisateur. Plus vivant qu'une constante.
    """
    if not digest:
        return "Voilà ce qui t'attend aujourd'hui."
    queue = digest.get("queue", {}) or {}
    if queue.get("replies_unhandled_interested", 0) > 0:
        return "Tu as une vraie occasion ce matin."
    if (queue.get("drafts_prospect_pending", 0)
            + queue.get("drafts_convoy_pending", 0)) > 0:
        return "Quelques validations rapides et tu débloques la journée."
    if queue.get("replies_unhandled_total", 0) > 0:
        return "Un peu de tri à faire avant d'attaquer."
    return "Aucune urgence. Le terrain est libre."


class MorningView(BaseView):
    title = "Matinale"
    subtitle = ""  # Le hero personnalisé prend le relais

    def build(self) -> None:
        c = self.colors

        # Container scroll directement (pas de header standard, hero custom)
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=c.border_strong,
        )
        self._scroll.pack(fill="both", expand=True,
                          padx=T.SPACE_2XL, pady=T.SPACE_LG)

        # Status bar discrète tout en bas
        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=(T.FONT_FAMILY, T.FONT_SIZE_TINY, "normal"),
            text_color=c.text_muted,
        ).pack(fill="x", padx=T.SPACE_2XL, pady=(0, T.SPACE_SM))

    def on_show(self) -> None:
        self._refresh()

    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        for w in self._scroll.winfo_children():
            w.destroy()
        c = self.colors

        # Digest d'abord — la phrase d'accroche du hero en dépend.
        digest = morning_digest.compute_digest()

        # --- HERO : salut chaleureux + date + phrase contextuelle ---
        self._hero(c, digest=digest if digest.get("ok") else None)

        if not digest.get("ok"):
            EmptyState(
                self._scroll, colors=c, icon="settings",
                title="Connexion requise",
                message=(
                    "Connecte-toi à la base partagée Triskell depuis les "
                    "Réglages pour que cette page se remplisse."
                ),
                cta_text="Aller dans Réglages",
                cta_command=lambda: self._navigate_to("config"),
            ).pack(fill="both", expand=True, pady=T.SPACE_2XL)
            self._status_var.set("Connexion à la base partagée requise.")
            return

        # --- ZONE 1 : ta priorité du jour (UNE seule, mise en avant) ---
        self._priority_block(digest)

        # --- ZONE 2 : Hier en chiffres (3 KPIs choisis) ---
        self._yesterday_block(digest)

        # --- ZONE 3 : Aujourd'hui (sobre) ---
        self._today_block(digest)

        # --- ZONE 4 : À corriger (uniquement s'il y a quelque chose) ---
        self._issues_block(digest)

        # --- ZONE 5 : Visibilité (Le Phare) — uniquement s'il y a du travail ---
        self._phare_block()

        # Status bar
        sent_y = digest["sent"]["yesterday"]
        replies_y = digest["replies"]["yesterday_total"]
        interested_y = (digest["replies"]["yesterday_breakdown"] or {}).get(
            "interested", 0)
        self._status_var.set(
            f"Hier : {sent_y} envoyés · {replies_y} réponses · "
            f"{interested_y} intéressés"
        )

    # ------------------------------------------------------------------
    def _hero(self, c, *, digest: dict | None = None) -> None:
        wrap = ctk.CTkFrame(self._scroll, fg_color="transparent")
        wrap.pack(fill="x", pady=(T.SPACE_LG, T.SPACE_2XL))

        # Filet accent OR — signature exclusive de la Matinale.
        # Ne réutiliser nulle part ailleurs dans l'app : c'est ce qui
        # marque le moment rituel matinal. Voir docs/PATCHES.md (M2).
        bar = ctk.CTkFrame(wrap, fg_color=c.gold,
                           width=32, height=3, corner_radius=2)
        bar.pack(anchor="w", pady=(0, T.SPACE_SM))
        bar.pack_propagate(False)

        # Petit label date discret
        ctk.CTkLabel(
            wrap, text=_date_phrase().upper(),
            font=ttype.SECTION_CAP,
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w")

        # Salut hero
        name = self.app_state.get("outreach", "from_name", default="") or "Jordan"
        if "—" in name:
            name = name.split("—")[0].strip()
        if " " in name:
            name = name.split(" ")[0]
        ctk.CTkLabel(
            wrap, text=f"{_greeting()} {name}.",
            font=ttype.HERO,
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_XS, 0))

        # Phrase de transition contextuelle (patch M3)
        ctk.CTkLabel(
            wrap, text=_transition_phrase(digest),
            font=ttype.BODY_LG,
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_XS, 0))

        # Action discrète : refresh seulement.
        # « Demander conseil à Claude » est accessible via le FAB flottant
        # (F12) — pas la peine de doubler dans le hero.
        action_row = ctk.CTkFrame(wrap, fg_color="transparent")
        action_row.pack(fill="x", pady=(T.SPACE_MD, 0), anchor="w")
        SecondaryButton(action_row, colors=c, icon="refresh",
                         text="Rafraîchir",
                         command=self._refresh).pack(side="left")

    # ------------------------------------------------------------------
    def _priority_block(self, digest: dict) -> None:
        """Met en avant UNE priorité — la plus importante uniquement.

        Ordre de priorité :
        1. Réponses positives non traitées (forte valeur)
        2. Brouillons en attente (action rapide)
        3. Autres réponses non triées
        4. Si rien : message zen + CTA prospection
        """
        c = self.colors
        queue = digest.get("queue", {}) or {}
        n_int = queue.get("replies_unhandled_interested", 0)
        n_total = queue.get("replies_unhandled_total", 0)
        n_drafts_p = queue.get("drafts_prospect_pending", 0)
        n_drafts_c = queue.get("drafts_convoy_pending", 0)
        n_drafts = n_drafts_p + n_drafts_c

        # Hero card grande, premier élément après le hero
        if n_int > 0:
            self._big_card(
                kicker="PRIORITÉ DU JOUR",
                title=(f"{n_int} prospect intéressé·e à recontacter"
                        if n_int == 1
                        else f"{n_int} prospects intéressés à recontacter"),
                body=("Ils ont répondu positivement à un de tes mails. "
                      "C'est ta meilleure piste pour transformer "
                      "aujourd'hui."),
                cta=("Voir leurs réponses",
                      lambda: self._navigate_to("replies")),
                accent=c.success,
            )
        elif n_drafts > 0:
            label = (f"{n_drafts} brouillon à valider" if n_drafts == 1
                      else f"{n_drafts} brouillons à valider")
            self._big_card(
                kicker="À FAIRE EN PREMIER",
                title=label,
                body=("Des mails préparés par l'app attendent ton OK. "
                      "Tu peux les approuver en lot."),
                cta=("Valider les brouillons",
                      lambda: self._navigate_to("drafts")),
                accent=c.accent,
            )
        elif n_total > 0:
            self._big_card(
                kicker="À TRIER",
                title=(f"{n_total} réponse à examiner" if n_total == 1
                        else f"{n_total} réponses à examiner"),
                body="Pas maintenant, refus, désinscriptions — un coup d'œil "
                     "rapide suffit pour les classer.",
                cta=("Voir les réponses",
                      lambda: self._navigate_to("replies")),
                accent=c.warning,
            )
        else:
            self._big_card(
                kicker="TOUT EST À JOUR",
                title="Rien ne t'attend ce matin.",
                body="Aucune réponse à traiter, aucun brouillon en attente. "
                     "Bon moment pour lancer une nouvelle vague de "
                     "prospection ou prendre un café.",
                cta=("Lancer l'auto-pilote",
                      lambda: self._navigate_to("autopilot")),
                accent=c.accent_secondary,
            )

    # ------------------------------------------------------------------
    def _yesterday_block(self, digest: dict) -> None:
        """3 KPIs pour la veille (patch M1 — KpiHero + sparkline 7 j).

        Pas 4 KPIs (manifeste DESIGN.md), pas de désinscriptions
        affichées par défaut (anxiogène et rare).
        """
        c = self.colors
        self._section_label("Hier en chiffres")

        sent_y = digest["sent"]["yesterday"]
        replies_y = digest["replies"]["yesterday_total"]
        breakdown = digest["replies"]["yesterday_breakdown"] or {}
        interested_y = breakdown.get("interested", 0)
        spark_sent = digest["sent"].get("daily_last_7d") or []
        # Tendance « envois » : J-1 vs J-2 (les 2 derniers points utiles)
        sent_trend = "neutral"
        if len(spark_sent) >= 2:
            prev = spark_sent[-2]
            if sent_y > prev:
                sent_trend = "up"
            elif sent_y < prev:
                sent_trend = "down"

        grid = ctk.CTkFrame(self._scroll, fg_color="transparent")
        grid.pack(fill="x", pady=(0, T.SPACE_2XL))
        for col in range(3):
            grid.grid_columnconfigure(col, weight=1, uniform="kpi")

        KpiHero(
            grid, colors=c,
            label="Mails envoyés", value=str(sent_y),
            delta_value=f"{digest['sent']['last_7d']} en 7 jours",
            delta_kind=sent_trend,
            sparkline=spark_sent if any(spark_sent) else None,
        ).grid(row=0, column=0, padx=(0, T.SPACE_MD), sticky="nsew")

        rate = int(100 * replies_y / max(sent_y, 1)) if replies_y else 0
        KpiHero(
            grid, colors=c,
            label="Réponses reçues", value=str(replies_y),
            delta_value=("—" if replies_y == 0 else f"{rate} % des envoyés"),
            delta_kind="up" if replies_y > 0 else "neutral",
        ).grid(row=0, column=1, padx=T.SPACE_MD, sticky="nsew")

        KpiHero(
            grid, colors=c,
            label="Prospects intéressés", value=str(interested_y),
            delta_value=("—" if interested_y == 0 else "à recontacter"),
            delta_kind="up" if interested_y > 0 else "neutral",
            accent=c.success if interested_y > 0 else "",
        ).grid(row=0, column=2, padx=(T.SPACE_MD, 0), sticky="nsew")

    # ------------------------------------------------------------------
    def _today_block(self, digest: dict) -> None:
        """Aperçu d'aujourd'hui — 2 chiffres seulement."""
        c = self.colors
        self._section_label("Aujourd'hui")

        sent_t = digest["sent"]["today"]
        replies_t = digest["replies"]["today_total"]

        grid = ctk.CTkFrame(self._scroll, fg_color="transparent")
        grid.pack(fill="x", pady=(0, T.SPACE_2XL))
        for col in range(2):
            grid.grid_columnconfigure(col, weight=1, uniform="today")

        StatCard(
            grid, label="Envoyés depuis 00:00", value=str(sent_t),
            delta=("—" if sent_t == 0
                    else "L'auto-pilote tourne" if sent_t > 0 else ""),
            colors=c,
        ).grid(row=0, column=0, padx=(0, T.SPACE_MD), sticky="ew")
        StatCard(
            grid, label="Réponses depuis 00:00", value=str(replies_t),
            delta=("—" if replies_t == 0 else "À examiner"),
            accent=c.success if replies_t > 0 else "",
            colors=c,
        ).grid(row=0, column=1, padx=(T.SPACE_MD, 0), sticky="ew")

    # ------------------------------------------------------------------
    def _issues_block(self, digest: dict) -> None:
        """N'apparaît que s'il y a vraiment quelque chose qui ne va pas.
        Pas de bloc "À corriger" si tout est OK — pas anxiogène par défaut."""
        c = self.colors
        alerts = digest.get("alerts", {}) or {}
        n_failed_y = alerts.get("convoy_failed_yesterday", 0)
        n_failed_t = alerts.get("convoy_failed_today", 0)
        if not (n_failed_y or n_failed_t):
            return

        self._section_label("À corriger")
        n_total = n_failed_y + n_failed_t
        self._mini_card(
            title=(f"{n_total} mail non parti" if n_total == 1
                    else f"{n_total} mails non partis"),
            body="Un problème de configuration mail ou de destinataire. "
                 "Ouvre l'écran d'import pour voir le détail.",
            cta=("Voir le détail", lambda: self._navigate_to("convoy")),
            accent=c.danger,
        )

    def _phare_block(self) -> None:
        """Bloc Visibilité — apparaît uniquement si Le Phare a du travail
        en attente (PR à valider, recommandations critiques)."""
        try:
            from ..integrations.phare import repo as phare_repo
        except Exception as exc:
            logger.debug("phare import: %s", exc)
            return
        try:
            pending_pr = len(phare_repo.list_actions(status="preview", limit=50))
            recos = phare_repo.list_actions(status="draft", limit=10)
        except Exception as exc:
            logger.debug("phare matinale: %s", exc)
            return
        # Critique : >= 1 PR à valider OU >= 5 recos en attente
        if pending_pr == 0 and len(recos) < 5:
            return
        c = self.colors
        self._section_label("Visibilité")
        if pending_pr:
            title = (f"{pending_pr} PR à valider du Phare" if pending_pr == 1
                     else f"{pending_pr} PRs à valider du Phare")
            body = ("L'agence SEO embarquée a poussé des modifs prêtes "
                    "à merger. Un coup d'œil au bac ?")
            self._mini_card(
                title=title, body=body,
                cta=("Ouvrir Le Phare", lambda: self._navigate_to("phare")),
                accent=c.accent,
            )
        elif len(recos) >= 5:
            self._mini_card(
                title=f"{len(recos)} recommandations SEO en attente",
                body="Le Phare a accumulé des recommandations à trier. "
                     "Rien d'urgent, mais une demi-heure suffit pour faire "
                     "le tour.",
                cta=("Ouvrir Le Phare", lambda: self._navigate_to("phare")),
                accent=c.text_secondary,
            )

    # ------------------------------------------------------------------
    # Helpers de rendu
    # ------------------------------------------------------------------
    def _section_label(self, text: str) -> None:
        c = self.colors
        ctk.CTkLabel(
            self._scroll, text=text.upper(),
            font=ttype.SECTION_CAP,
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w", pady=(0, T.SPACE_MD))

    def _big_card(self, *, kicker: str, title: str, body: str,
                    cta: tuple, accent: str = "") -> None:
        """Card hero — celle qui prend la place principale."""
        c = self.colors
        card = ctk.CTkFrame(
            self._scroll, fg_color=c.panel,
            corner_radius=T.RADIUS_LG,
            border_color=c.border, border_width=1,
        )
        card.pack(fill="x", pady=(0, T.SPACE_2XL))

        # Bande accent à gauche (4px)
        accent_color = accent or c.accent
        body_wrap = ctk.CTkFrame(card, fg_color="transparent")
        body_wrap.pack(fill="x", padx=T.SPACE_2XL, pady=T.SPACE_2XL)

        ctk.CTkLabel(
            body_wrap, text=kicker.upper(),
            font=ttype.SECTION_CAP,
            text_color=accent_color, anchor="w",
        ).pack(fill="x", anchor="w")

        ctk.CTkLabel(
            body_wrap, text=title,
            font=ttype.DISPLAY,
            text_color=c.text_primary, anchor="w",
            justify="left", wraplength=860,
        ).pack(fill="x", anchor="w", pady=(T.SPACE_SM, T.SPACE_SM))

        ctk.CTkLabel(
            body_wrap, text=body,
            font=ttype.BODY_LG,
            text_color=c.text_secondary, anchor="w",
            justify="left", wraplength=860,
        ).pack(fill="x", anchor="w", pady=(0, T.SPACE_LG))

        label, cmd = cta
        PrimaryButton(body_wrap, colors=c, text=label, command=cmd).pack(
            anchor="w")

    def _mini_card(self, *, title: str, body: str, cta: tuple,
                    accent: str = "") -> None:
        """Card sobre, taille intermédiaire."""
        c = self.colors
        card = Card(self._scroll, colors=c)
        card.pack(fill="x", pady=(0, T.SPACE_LG))

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=T.SPACE_XL, pady=(T.SPACE_LG, T.SPACE_XS))
        if accent:
            dot = ctk.CTkFrame(head, fg_color=accent, width=8, height=8,
                                corner_radius=4)
            dot.pack(side="left", padx=(0, T.SPACE_SM))
            dot.pack_propagate(False)
        ctk.CTkLabel(
            head, text=title,
            font=ttype.H2,
            text_color=c.text_primary, anchor="w",
        ).pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            card, text=body,
            font=ttype.BODY_SM,
            text_color=c.text_secondary, anchor="w",
            justify="left", wraplength=900,
        ).pack(fill="x", padx=T.SPACE_XL, pady=(0, T.SPACE_SM))

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=T.SPACE_XL, pady=(0, T.SPACE_LG))
        label, cmd = cta
        SecondaryButton(actions, colors=c, text=label, command=cmd).pack(
            side="left")
