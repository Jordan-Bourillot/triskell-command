"""Dialog d'aide — guide rapide d'utilisation de Triskell Command."""

from __future__ import annotations

import customtkinter as ctk

from .. import theme as T
from .components import SecondaryButton
from .window_icon import apply_window_icon


# ---------------------------------------------------------------------------
# Contenu du guide (markdown-like, parsé manuellement)
# ---------------------------------------------------------------------------
SECTIONS = [
    {
        "title": "Le pipeline en 4 étapes",
        "body": (
            "Triskell Command automatise une chaîne complète de prospection. "
            "Tu configures 1 fois, ça tourne en boucle.\n\n"
            "  1. RECHERCHE — Sirene (entreprises FR) ou Maps (commerces) ramène "
            "des prospects matchant ton ICP.\n\n"
            "  2. ENRICHISSEMENT — Visite des sites web, extraction email/tél/adresse, "
            "vérification cross-référence avec Sirene (élimine les faux positifs).\n\n"
            "  3. RÉDACTION IA — Pour chaque prospect, l'IA reçoit son contexte "
            "(nom, ville, secteur, site web) + tes instructions, et génère un mail unique.\n\n"
            "  4. ENVOI — Mode auto : envoi direct.   "
            "Mode validation : déposé dans « À valider », tu approuves d'un clic."
        ),
    },
    {
        "title": "Les 2 modes : auto vs validation",
        "body": (
            "MODE AUTO\n"
            "  • L'IA génère un mail → l'envoie immédiatement\n"
            "  • Tu n'interviens que sur les réponses\n"
            "  • Risque : 1 mail sur 50 peut être bizarre\n"
            "  • Bon une fois la machine calibrée\n\n"
            "MODE VALIDATION (recommandé)\n"
            "  • L'IA génère un mail → le DÉPOSE dans la corbeille « À valider »\n"
            "  • Tu vois la liste des mails préparés chaque matin (~5 min)\n"
            "  • Tu peux ÉDITER le corps avant d'envoyer\n"
            "  • Bouton « Approuver & envoyer » : c'est là que ça part\n"
            "  • Bouton « Rejeter » : poubelle, ne part jamais\n"
            "  • Le mode prudent — utilise-le au début"
        ),
    },
    {
        "title": "Les méga-prompts : c'est quoi ?",
        "body": (
            "Ce sont des règles de comportement que tu donnes à l'IA AVANT chaque "
            "génération. Elles ne disent pas QUOI écrire mais COMMENT.\n\n"
            "Exemple. Sans méga-prompt, tu demandes :\n"
            "    « Rédige un mail de prospection »\n"
            "→ L'IA fait un truc générique correct.\n\n"
            "Avec méga-prompt « [01] Honnêteté brutale » coché :\n"
            "    [9 règles strictes injectées en intro]\n"
            "    « Rédige un mail de prospection »\n"
            "→ L'IA respecte les 9 règles : pas de flatterie, verdict explicite, "
            "critique avant qualité, etc.\n\n"
            "Tu peux EMPILER plusieurs méga-prompts. Pour la prospection, "
            "je recommande la stack :\n"
            "  • [01] Honnêteté brutale  → pas de bullshit\n"
            "  • [06] Anti-slop          → langage marketing creux interdit\n"
            "  • [13] Mode produit       → focus bénéfice client\n"
            "Mets dans le champ « Méga-prompts » : 01,06,13"
        ),
    },
    {
        "title": "À quel moment précis le méga-prompt entre en jeu ?",
        "body": (
            "À CHAQUE génération de mail individuel, pas une seule fois pour la "
            "campagne entière.\n\n"
            "Pour un pipeline qui traite 30 prospects, l'IA reçoit 30 fois ce "
            "type de prompt :\n\n"
            "    [INSTRUCTIONS DES MÉGA-PROMPTS COCHÉS]\n"
            "    [CONTEXTE DU PROSPECT N°X : nom, ville, secteur, site...]\n"
            "    [TON MODÈLE DE CONSIGNE : la consigne que tu écris dans Auto-pilote]\n"
            "    DEMANDE : rédige un mail pour CE prospect.\n\n"
            "Résultat : un mail unique par prospect, mais TOUS suivent les mêmes "
            "règles comportementales que tu as choisies. Cohérence de ton garantie "
            "sur toute ta campagne."
        ),
    },
    {
        "title": "Ton modèle de consigne : à quoi il sert ?",
        "body": (
            "Le « modèle de consigne » dans Auto-pilote, ce n'est PAS un mail figé. "
            "C'est la consigne que tu donnes à l'IA pour qu'elle sache quel TYPE "
            "de mail produire.\n\n"
            "Exemple de modèle de consigne :\n\n"
            "    « Génère un mail de prospection court (10 lignes max) pour proposer "
            "un site web premium à un artisan. Tutoiement chaleureux, pas de jargon. "
            "Format strict : OBJET : <objet>\\n\\n<corps>\\n\\nCordialement,\\n{mon_prenom} »\n\n"
            "L'IA combine : ton modèle de consigne + le contexte du prospect + tes "
            "méga-prompts → génère un mail UNIQUE. Pas de copier-coller mécanique."
        ),
    },
    {
        "title": "Workflow recommandé pour démarrer",
        "body": (
            "1. RÉGLAGES → mets ta clé Gemini (gratuit) dans Providers IA, "
            "Provider par défaut « google », modèle « gemini-2.5-flash ».\n\n"
            "2. RÉGLAGES → SMTP/IMAP Gmail avec mot de passe d'application "
            "(bouton ↗ pour la page Google).\n\n"
            "3. AUTO-PILOTE → mode = « validation » (sécurité), source Sirene avec "
            "ton ICP (NAF + département), méga-prompts = 01,06,13, modèle de consigne "
            "adapté à ton offre.\n\n"
            "4. AUTO-PILOTE → « Lancer maintenant » → tu vois le log live.\n\n"
            "5. À VALIDER → tu vois les mails préparés. Tu valides ou rejettes.\n\n"
            "6. Quand tu es à l'aise (90% des brouillons sont bons) → bascule "
            "en mode « auto » et active la boucle nocturne dans Réglages."
        ),
    },
    {
        "title": "Glossaire rapide",
        "body": (
            "ICP : « Ideal Customer Profile ». Tes critères de prospect idéal.\n\n"
            "Sirene : base officielle des entreprises FR (gratuit, sans clé).\n\n"
            "Cross-ref : on vérifie que le site web trouvé correspond bien au "
            "prospect Sirene (SIREN affiché sur le site, code postal cohérent...).\n\n"
            "site_verified : tag posé sur un prospect dont le site web a été "
            "validé par cross-ref. Seuls les prospects « site_verified » sont "
            "ciblés en mode auto-pilote.\n\n"
            "Dry-run : simulation, rien ne part vraiment. Pour tester.\n\n"
            "Daily cap : plafond d'envois par jour (40 par défaut, safe pour Gmail "
            "gratuit qui permet jusqu'à 500/jour).\n\n"
            "Footprint : technique pour deviner le site web d'une entreprise depuis "
            "son nom + ville (essai de plusieurs domaines candidats)."
        ),
    },
]


class HelpDialog(ctk.CTkToplevel):
    """Modal d'aide avec sections + navigation."""

    def __init__(self, master, *, colors: T.ThemeColors):
        super().__init__(master)
        self._colors = colors
        c = colors
        self.title("Guide Triskell Command")
        self.geometry("840x720")
        self.minsize(720, 600)
        self.configure(fg_color=c.bg)
        self.transient(master.winfo_toplevel())
        apply_window_icon(self)
        self.after(100, lambda: self.lift())

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent", height=80)
        header.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_SM))
        bar = ctk.CTkFrame(header, fg_color=c.accent, width=32, height=3,
                           corner_radius=1)
        bar.pack(anchor="w", pady=(0, T.SPACE_XS))
        ctk.CTkLabel(
            header, text="Guide Triskell Command",
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_DISPLAY, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", anchor="w")
        ctk.CTkLabel(
            header, text="Tout ce qu'il faut comprendre pour utiliser l'app",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_secondary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(T.SPACE_XS, 0))

        # Body : 2 colonnes (sommaire à gauche, contenu à droite)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=T.SPACE_LG, pady=T.SPACE_MD)

        # Sommaire
        toc = ctk.CTkFrame(
            body, fg_color=c.panel,
            corner_radius=T.RADIUS_MD, border_color=c.border, border_width=1,
            width=240,
        )
        toc.pack(side="left", fill="y", padx=(0, T.SPACE_MD))
        toc.pack_propagate(False)

        ctk.CTkLabel(
            toc, text="SOMMAIRE",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted, anchor="w",
        ).pack(fill="x", padx=T.SPACE_MD, pady=(T.SPACE_MD, T.SPACE_XS))

        # Content (scrollable)
        content = ctk.CTkScrollableFrame(
            body, fg_color=c.panel,
            corner_radius=T.RADIUS_MD,
            scrollbar_button_color=c.border_strong,
        )
        content.pack(side="left", fill="both", expand=True)

        # Items du sommaire (cliquables pour scroller à la section)
        self._sections_widgets: dict[int, ctk.CTkFrame] = {}
        for i, section in enumerate(SECTIONS):
            self._make_toc_item(toc, i, section["title"])

        for i, section in enumerate(SECTIONS):
            self._make_section(content, i, section["title"], section["body"])

        # Footer
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=T.SPACE_LG, pady=(0, T.SPACE_LG))
        SecondaryButton(bottom, colors=c, icon="close", text="Fermer",
                        command=self.destroy).pack(side="right")

    def _make_toc_item(self, parent, index: int, title: str) -> None:
        c = self._colors
        item = ctk.CTkButton(
            parent,
            text=f"{index + 1}.  {title}",
            anchor="w",
            fg_color="transparent",
            hover_color=c.panel_hover,
            text_color=c.text_secondary,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL),
            corner_radius=T.RADIUS_SM,
            command=lambda i=index: self._scroll_to(i),
            height=32,
        )
        item.pack(fill="x", padx=T.SPACE_SM, pady=2)

    def _make_section(self, parent, index: int, title: str, body: str) -> None:
        c = self._colors
        wrapper = ctk.CTkFrame(parent, fg_color="transparent")
        wrapper.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_MD))

        # Bandeau or signature
        bar = ctk.CTkFrame(wrapper, fg_color=c.accent, width=32, height=3,
                           corner_radius=1)
        bar.pack(anchor="w", pady=(0, T.SPACE_XS))

        ctk.CTkLabel(
            wrapper, text=f"{index + 1}.  {title}",
            font=(T.FONT_FAMILY_DISPLAY, T.FONT_SIZE_TITLE, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", anchor="w", pady=(0, T.SPACE_SM))

        ctk.CTkLabel(
            wrapper, text=body,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_secondary,
            anchor="w", justify="left", wraplength=520,
        ).pack(fill="x", anchor="w")

        self._sections_widgets[index] = wrapper

    def _scroll_to(self, index: int) -> None:
        widget = self._sections_widgets.get(index)
        if widget is None:
            return
        # Force update + scroll vers la section
        try:
            widget.update_idletasks()
            widget.tk.call(widget._parent_canvas, "yview_moveto",  # noqa: SLF001
                           widget.winfo_y() / max(1, widget.master.winfo_reqheight()))
        except Exception:
            pass
