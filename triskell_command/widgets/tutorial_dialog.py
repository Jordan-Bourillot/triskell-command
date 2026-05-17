"""Tutorial Dialog — visite guidée du pipeline d'automatisation v0.3.

S'affiche automatiquement au 1er lancement après installation (flag
`tutorial_v3_done` dans settings.json local par-machine).

Accessible à tout moment via :
- Sidebar SYSTÈME → bouton "Tuto"
- Vue Matinale → bouton "Revoir le tuto" dans le header
- Vue Réglages → carte dédiée (futur)

Format : 11 étapes navigables avec Suivant / Précédent. À chaque étape,
un bouton "Aller voir" ouvre la vue concernée pour démo en contexte.

Note design : on garde la modale en CTkToplevel (pas full-screen) pour
permettre à Jordan de cliquer sur "Aller voir" et voir la vue derrière.
"""

from __future__ import annotations

import logging
from typing import Callable

import customtkinter as ctk

from .. import theme as T
from .components import PrimaryButton, SecondaryButton

logger = logging.getLogger(__name__)


# Stepper du tuto — 12 étapes en français parlant
TUTORIAL_STEPS = [
    {
        "icon": "sparkle",
        "title": "Bienvenue",
        "lead": "Triskell Command : ton tableau de bord pour tout piloter.",
        "body": (
            "Ce tour te montre en quelques minutes comment l'app travaille pour "
            "toi : de la recherche d'un prospect jusqu'au suivi du client après "
            "livraison.\n\n"
            "Tu peux le rouvrir à tout moment depuis la barre de gauche → "
            "bouton « Tuto », ou depuis le bouton « Revoir le tuto » en haut "
            "de la Matinale et des Réglages."
        ),
        "goto": None,
    },
    {
        "icon": "chart",
        "title": "1. La Matinale, ton seul écran du matin",
        "lead": "Tout en 5 minutes par jour.",
        "body": (
            "Tu y vois en un coup d'œil :\n"
            "• Hier en chiffres : mails envoyés, réponses reçues, prospects "
            "intéressés, désinscriptions.\n"
            "• Ce qui t'attend : brouillons à valider, réponses positives à "
            "traiter.\n"
            "• Les soucis éventuels : envois ratés, paramètres incomplets.\n\n"
            "C'est l'écran qui s'ouvre par défaut quand tu lances l'app."
        ),
        "goto": "morning",
    },
    {
        "icon": "search",
        "title": "2. Trois façons de trouver des prospects",
        "lead": "Auto-pilote · Importer un fichier · Obelisk.",
        "body": (
            "• Auto-pilote : cherche tout seul des entreprises locales (base "
            "officielle Sirene + Google Maps).\n"
            "• Importer un fichier : tu glisses un PDF, Excel, Word, image ou "
            "texte avec une liste, l'app extrait les contacts.\n"
            "• Obelisk : ton outil de recherche de créateurs sur 9 plateformes "
            "(YouTube, Twitch, Reddit, Bluesky, Mastodon, podcasts, "
            "Dailymotion, Kick, GitHub).\n\n"
            "Les trois alimentent la même base partagée entre toi et Thomas. "
            "Plus de doublons, plus de listes éparpillées."
        ),
        "goto": "autopilot",
    },
    {
        "icon": "mail",
        "title": "3. Les réponses arrivent ici, pas dans ta boîte mail",
        "lead": "L'app surveille ta boîte mail toutes les 5 minutes.",
        "body": (
            "Quand un prospect répond à un de tes mails, l'app :\n"
            "1. Détecte la réponse et l'associe au bon prospect.\n"
            "2. La trie automatiquement en 5 catégories : intéressé, pas "
            "maintenant, refus, désinscription, à trier.\n"
            "3. Te prépare un brouillon de réponse adapté à la catégorie.\n\n"
            "Tu n'as plus à surveiller ta boîte mail toi-même."
        ),
        "goto": "replies",
    },
    {
        "icon": "settings",
        "title": "4. Réponses : à toi de choisir le niveau d'automatisation",
        "lead": "Validation manuelle / Auto après 30 min / Auto immédiat.",
        "body": (
            "Pour chaque type de réponse, tu décides :\n"
            "• Validation manuelle : rien ne part sans ton clic.\n"
            "• Auto après 30 min : si tu ne touches pas au brouillon dans "
            "ce délai, il part tout seul.\n"
            "• Auto immédiat : ça part dès la détection.\n\n"
            "Conseil pour démarrer : tout en manuel le temps de calibrer les "
            "messages, puis bascule au cas par cas. Par exemple les "
            "désinscriptions peuvent partir en auto immédiat (pas de risque), "
            "les prospects intéressés restent manuels (forte valeur)."
        ),
        "goto": "replies",
    },
    {
        "icon": "check",
        "title": "5. Brouillons à valider, ton sas de contrôle",
        "lead": "Tout ce qui est en attente d'un clic de ta part.",
        "body": (
            "Tous les mails préparés par l'app (premiers contacts, relances, "
            "réponses, suivi après-vente) en mode « validation manuelle » "
            "atterrissent ici.\n\n"
            "Tu peux les lire, les corriger, les approuver un par un ou tout "
            "approuver d'un coup. Ce qui est en mode auto saute cette étape."
        ),
        "goto": "drafts",
    },
    {
        "icon": "send",
        "title": "6. Relances automatiques à 7 et 30 jours",
        "lead": "Plus jamais une relance oubliée.",
        "body": (
            "Quand un prospect ne répond pas à ton premier mail, l'app prépare "
            "automatiquement :\n"
            "• Une première relance polie 7 jours après.\n"
            "• Une dernière relance 30 jours après.\n\n"
            "Avec le même choix que pour les réponses (manuel / auto après "
            "30 min / auto immédiat). Et l'app saute la relance toute seule "
            "si entretemps le prospect a répondu, est devenu client, ou a "
            "déjà été contacté autrement."
        ),
        "goto": "drafts",
    },
    {
        "icon": "doc",
        "title": "7. Clients : tableau pour suivre les livraisons",
        "lead": "Briefing → En cours → Livré → Clôturé.",
        "body": (
            "Quand tu vends un service (Eliks Studio, site agence, dev "
            "custom), une carte client apparaît ici. Tu la fais glisser de "
            "colonne en colonne au fil de l'avancement, avec les flèches "
            "gauche / droite.\n\n"
            "Tout reste dans Triskell, sans aller chercher dans Notion ou "
            "Trello. Tu vois en un coup d'œil tous les projets en cours, "
            "leurs montants, leurs échéances."
        ),
        "goto": "clients",
    },
    {
        "icon": "chart",
        "title": "8. Funnel : tes conversions en un clic",
        "lead": "Prospects → Envoyés → Réponses → Intéressés → Gagnés.",
        "body": (
            "Une vue qui te montre où ça coince et où ça marche. Filtres :\n"
            "• Période : 7 jours, 30 jours, 90 jours, tout.\n"
            "• Segment : créateurs, B2B local, tous.\n\n"
            "Tu vois en direct ton taux de réponse, ton taux d'intérêt, "
            "ton taux de gain. Les ouvertures et clics sur les liens dans "
            "les mails seront ajoutés plus tard (l'infrastructure est "
            "prête, à activer côté envoi quand tu seras prêt à tester)."
        ),
        "goto": "funnel",
    },
    {
        "icon": "sparkle",
        "title": "9. Suivi automatique après livraison",
        "lead": "Garde tes clients chauds sans y penser.",
        "body": (
            "Quand un projet client passe en colonne « Livré », l'app prend "
            "le relais :\n\n"
            "• 30 jours après : un mail propose un produit complémentaire "
            "du catalogue (vente additionnelle).\n"
            "• 90 jours après : un mail demande la satisfaction du client. "
            "Une seule question simple sur une note de 0 à 10, qui te "
            "permet d'identifier tes ambassadeurs (qui te recommanderont) "
            "et les insatisfaits (à rappeler avant qu'ils ne parlent en mal).\n\n"
            "Toujours avec le même choix : manuel / auto 30 min / auto "
            "immédiat."
        ),
        "goto": "clients",
    },
    {
        "icon": "play",
        "title": "10. L'app travaille en arrière-plan pour toi",
        "lead": "Cinq tâches tournent toutes seules dès que tu es connecté.",
        "body": (
            "• Synchronisation entre toi et Thomas (toutes les 15 à 30 "
            "secondes).\n"
            "• Lecture de tes mails entrants (toutes les 5 minutes).\n"
            "• Envoi des réponses automatiques quand le délai est écoulé "
            "(toutes les minutes).\n"
            "• Préparation des relances à 7 et 30 jours (toutes les heures).\n"
            "• Préparation des suivis après livraison (toutes les heures).\n\n"
            "Tu n'as rien à lancer toi-même. Si quelque chose n'est pas "
            "configuré, la tâche concernée se met en pause sans rien casser."
        ),
        "goto": None,
    },
    {
        "icon": "target",
        "title": "11. Pour démarrer, 5 petits réglages",
        "lead": "Compte 5 à 10 minutes une seule fois.",
        "body": (
            "1. Te connecter à la base partagée Triskell (Réglages → "
            "Connexion).\n"
            "2. Renseigner ta boîte mail entrante (Réglages → Mail), sinon "
            "l'app ne pourra pas lire les réponses des prospects.\n"
            "3. Régler les niveaux d'automatisation (Réponses des prospects "
            "→ « Niveau d'automatisation ») et tes boutons d'achat.\n"
            "4. Activer le résumé matinal par mail (optionnel — un script "
            "PowerShell est fourni dans le dossier scripts/).\n"
            "5. Plus tard : activer le suivi des ouvertures et clics dans "
            "les mails (un guide dédié t'accompagne)."
        ),
        "goto": "config",
    },
]


SETTINGS_KEY_TUTORIAL_DONE = ("ui", "tutorial_v3_done")


def needs_tutorial(app_state) -> bool:
    """True si le tuto v0.3 n'a jamais été marqué comme vu."""
    return not bool(app_state.get(*SETTINGS_KEY_TUTORIAL_DONE, default=False))


def mark_tutorial_done(app_state) -> None:
    app_state.set(*SETTINGS_KEY_TUTORIAL_DONE, value=True)
    try:
        app_state.save()
    except Exception:
        pass


def reset_tutorial(app_state) -> None:
    """Pour qu'il se reaffiche au prochain boot — utile pour un reset / test."""
    app_state.set(*SETTINGS_KEY_TUTORIAL_DONE, value=False)
    try:
        app_state.save()
    except Exception:
        pass


class TutorialDialog(ctk.CTkToplevel):
    """Modale stepper du tuto v0.3."""

    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        app_state,
        on_navigate: Callable[[str], None] | None = None,
        start_index: int = 0,
    ):
        super().__init__(master)
        self._colors = colors
        self._app_state = app_state
        self._on_navigate = on_navigate
        self._index = max(0, min(start_index, len(TUTORIAL_STEPS) - 1))

        self.title("Triskell — Visite guidée")
        self.geometry("760x620")
        self.minsize(660, 540)
        self.configure(fg_color=colors.bg)
        try:
            self.grab_set()
            self.transient(master)
        except Exception:
            pass
        # Logo Triskell (3 pétales) dans la barre de titre
        try:
            self._set_window_icon()
        except Exception:
            pass

        c = colors

        # Layout : header (progress bar + step counter) / body / footer
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ---- Header ----
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew",
                     padx=T.SPACE_2XL, pady=(T.SPACE_LG, T.SPACE_SM))

        # Filet accent signature
        bar = ctk.CTkFrame(header, fg_color=c.accent, width=32, height=3,
                            corner_radius=2)
        bar.pack(anchor="w", pady=(0, T.SPACE_XS))
        bar.pack_propagate(False)

        # Compteur d'étapes
        self._counter_var = ctk.StringVar()
        ctk.CTkLabel(
            header, textvariable=self._counter_var,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", anchor="w")

        # Progress bar
        self._progress = ctk.CTkProgressBar(
            header, fg_color=c.panel,
            progress_color=c.accent, height=4, corner_radius=2,
        )
        self._progress.pack(fill="x", pady=(T.SPACE_XS, 0))
        self._progress.set(0)

        # ---- Body (mis à jour à chaque step) ----
        self._body_wrap = ctk.CTkFrame(self, fg_color="transparent")
        self._body_wrap.grid(row=1, column=0, sticky="nsew",
                              padx=T.SPACE_2XL, pady=(T.SPACE_SM, T.SPACE_SM))

        # ---- Footer ----
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew",
                     padx=T.SPACE_2XL, pady=(T.SPACE_SM, T.SPACE_LG))

        self._skip_btn = SecondaryButton(
            footer, colors=c, text="Passer le tuto",
            command=self._skip,
        )
        self._skip_btn.pack(side="left")

        right = ctk.CTkFrame(footer, fg_color="transparent")
        right.pack(side="right")
        self._prev_btn = SecondaryButton(
            right, colors=c, text="◀ Précédent",
            command=self._prev,
        )
        self._prev_btn.pack(side="left", padx=(0, T.SPACE_SM))
        self._next_btn = PrimaryButton(
            right, colors=c, text="Suivant ▶",
            command=self._next,
        )
        self._next_btn.pack(side="left")

        self._render_step()

    # ------------------------------------------------------------------
    def _render_step(self) -> None:
        for w in self._body_wrap.winfo_children():
            w.destroy()
        c = self._colors
        step = TUTORIAL_STEPS[self._index]
        total = len(TUTORIAL_STEPS)

        # Compteur + progress
        self._counter_var.set(f"ÉTAPE {self._index + 1} / {total}")
        self._progress.set((self._index + 1) / total)

        # Icône (ronde indigo)
        icon_wrap = ctk.CTkFrame(
            self._body_wrap, fg_color=c.accent, corner_radius=32,
            width=64, height=64,
        )
        icon_wrap.pack(anchor="w", pady=(T.SPACE_LG, T.SPACE_LG))
        icon_wrap.pack_propagate(False)
        try:
            from . import icons as _icons
            img = _icons.get_icon(step.get("icon", "sparkle"),
                                    c.accent_text, size=32)
            if img is not None:
                ctk.CTkLabel(icon_wrap, image=img, text="").place(
                    relx=0.5, rely=0.5, anchor="center")
        except Exception:
            pass

        # Titre
        ctk.CTkLabel(
            self._body_wrap, text=step.get("title", ""),
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_DISPLAY, "bold"),
            text_color=c.text_primary, anchor="w",
            justify="left", wraplength=680,
        ).pack(fill="x", anchor="w")

        # Lead
        if step.get("lead"):
            ctk.CTkLabel(
                self._body_wrap, text=step["lead"],
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
                text_color=c.accent, anchor="w",
                justify="left", wraplength=680,
            ).pack(fill="x", anchor="w", pady=(T.SPACE_XS, T.SPACE_MD))

        # Body
        ctk.CTkLabel(
            self._body_wrap, text=step.get("body", ""),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_secondary, anchor="w",
            justify="left", wraplength=680,
        ).pack(fill="x", anchor="w")

        # CTA "Aller voir" si la step pointe vers une vue
        goto = step.get("goto")
        if goto:
            cta_row = ctk.CTkFrame(self._body_wrap, fg_color="transparent")
            cta_row.pack(fill="x", anchor="w", pady=(T.SPACE_LG, 0))
            label = self._goto_label(goto)
            SecondaryButton(
                cta_row, colors=c,
                text=f"Aller voir : {label}",
                command=lambda v=goto: self._goto(v),
            ).pack(side="left")

        # MAJ état des boutons nav
        self._prev_btn.configure(state=("normal" if self._index > 0
                                          else "disabled"))
        is_last = (self._index == total - 1)
        self._next_btn.configure(text="Terminer ✓" if is_last else "Suivant ▶")

    def _goto_label(self, view_id: str) -> str:
        labels = {
            "morning":   "la Matinale",
            "autopilot": "l'Auto-pilote",
            "convoy":    "Importer une liste",
            "drafts":    "Brouillons à valider",
            "replies":   "Réponses des prospects",
            "clients":   "Projets clients",
            "funnel":    "Conversions",
            "config":    "Réglages",
        }
        return labels.get(view_id, view_id)

    # ------------------------------------------------------------------
    def _next(self) -> None:
        if self._index >= len(TUTORIAL_STEPS) - 1:
            # Dernière étape → marque comme vu et ferme
            mark_tutorial_done(self._app_state)
            self.destroy()
            return
        self._index += 1
        self._render_step()

    def _prev(self) -> None:
        if self._index <= 0:
            return
        self._index -= 1
        self._render_step()

    def _skip(self) -> None:
        # On marque quand même comme vu, pour ne pas le re-spammer au boot
        mark_tutorial_done(self._app_state)
        self.destroy()

    def _goto(self, view_id: str) -> None:
        if self._on_navigate is None:
            return
        try:
            self._on_navigate(view_id)
        except Exception as exc:
            logger.debug("tutorial goto %s: %s", view_id, exc)

    # ------------------------------------------------------------------
    def _set_window_icon(self) -> None:
        """Pose le logo Triskell aux 3 pétales sur la barre de titre."""
        import sys
        from pathlib import Path
        # Cherche assets/triskell.ico — mode dev OU PyInstaller frozen
        candidates = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "assets" / "triskell.ico")
        here = Path(__file__).resolve()
        for parent in (here.parent.parent.parent,
                        here.parent.parent.parent.parent):
            candidates.append(parent / "assets" / "triskell.ico")
        for p in candidates:
            if p.exists():
                self.iconbitmap(str(p))
                return
        # Fallback PNG via PIL si .ico absent
        for p in candidates:
            png = p.with_suffix(".png")
            if png.exists():
                try:
                    from PIL import Image, ImageTk
                    img = Image.open(png)
                    self._icon_ref = ImageTk.PhotoImage(img)  # garde une ref
                    self.iconphoto(False, self._icon_ref)
                except Exception:
                    pass
                return
