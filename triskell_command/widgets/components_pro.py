"""Composants pro complémentaires.

Coexiste avec `widgets/components.py` (qui contient déjà ViewHeader,
Card, PrimaryButton, SecondaryButton, GoldButton, StatusPill, Chip,
StatCard, EmptyState, Toast). Ce fichier ajoute seulement ce qui
manquait pour les vues data-heavy et les rituels :

- `KpiHero`     — KPI XL pour la Matinale (chiffre géant, delta colorisé,
                   sparkline optionnelle)
- `LogRow`      — ligne de log timestampée, alignée pour activity feeds
- `DrawerRight` — panneau coulissant droite, pour outils avancés
                   (Phare → missions ponctuelles)
- `Disclosure`  — section repliable inline pour densité maîtrisée

Aucun de ces composants ne duplique l'existant — chacun a un rôle
distinct documenté dans `docs/DESIGN.md` (axe E).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterable, Literal, Optional

import customtkinter as ctk

from .. import theme as T
from ..tokens_v2 import borders, heights, motion, ttype, widths


# ---------------------------------------------------------------------------
# KpiHero — KPI XL pour la Matinale (chiffre géant + delta + sparkline)
# ---------------------------------------------------------------------------
class KpiHero(ctk.CTkFrame):
    """KPI taille XL pour les vues rituelles.

    Différences avec StatCard :
    - chiffre encore plus grand (44 px vs 36 px)
    - hauteur réservée pour sparkline (canvas 32 px)
    - delta avec icône directionnelle (▲ / ▼ / ●)
    - tabular nums pour alignement vertical multi-cards

    Usage typique :
        KpiHero(parent,
                colors=c,
                label="Prospects synchros",
                value="1 248",
                delta_value="+47",
                delta_kind="up",     # up | down | neutral
                sparkline=[3, 5, 4, 6, 8, 7, 9, 11])
    """

    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        label: str,
        value: str,
        delta_value: str = "",
        delta_kind: Literal["up", "down", "neutral"] = "neutral",
        sparkline: Optional[Iterable[float]] = None,
        accent: str = "",
        height: int = heights.KPI_CARD_HERO,
    ):
        super().__init__(
            master,
            fg_color=colors.panel,
            corner_radius=T.RADIUS_MD,
            border_color=colors.border,
            border_width=borders.HAIRLINE,
            height=height,
        )
        self.pack_propagate(False)
        self._colors = colors

        # Label en caps
        ctk.CTkLabel(
            self, text=label.upper(),
            font=ttype.SECTION_CAP, text_color=colors.text_muted,
            anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_LG, T.SPACE_XS))

        # Valeur géante
        ctk.CTkLabel(
            self, text=value,
            font=ttype.KPI_HERO,
            text_color=accent or colors.text_primary,
            anchor="w",
        ).pack(fill="x", padx=T.SPACE_LG)

        # Delta (optionnel)
        if delta_value:
            arrow = {"up": "▲", "down": "▼", "neutral": "●"}[delta_kind]
            color = {
                "up": colors.success,
                "down": colors.danger,
                "neutral": colors.text_secondary,
            }[delta_kind]
            ctk.CTkLabel(
                self, text=f"{arrow} {delta_value}",
                font=ttype.KPI_DELTA, text_color=color,
                anchor="w",
            ).pack(fill="x", padx=T.SPACE_LG, pady=(2, 0))

        # Sparkline (optionnelle)
        if sparkline is not None:
            sl = _Sparkline(
                self, colors=colors, values=list(sparkline),
                height=32, accent=accent or colors.accent,
            )
            sl.pack(fill="x", padx=T.SPACE_LG, pady=(T.SPACE_SM, T.SPACE_LG))
        else:
            # Spacer pour homogénéiser la hauteur entre KPIs avec/sans sparkline
            ctk.CTkFrame(self, fg_color="transparent", height=T.SPACE_LG).pack()


class _Sparkline(ctk.CTkCanvas):
    """Sparkline minimaliste (8-12 points) en Canvas Tk."""

    def __init__(self, master, *, colors: T.ThemeColors, values: list[float],
                 height: int = 32, accent: str = ""):
        super().__init__(
            master, height=height, highlightthickness=0,
            bg=colors.panel,
        )
        self._values = values or [0]
        self._accent = accent or colors.accent
        self._colors = colors
        self.bind("<Configure>", self._redraw)

    def _redraw(self, _event=None):
        self.delete("all")
        w = max(1, int(self.winfo_width()))
        h = max(1, int(self.winfo_height()))
        if not self._values or len(self._values) < 2:
            return
        vmin, vmax = min(self._values), max(self._values)
        span = (vmax - vmin) or 1
        step = w / (len(self._values) - 1)
        pts: list[float] = []
        for i, v in enumerate(self._values):
            x = i * step
            y = h - 4 - ((v - vmin) / span) * (h - 8)
            pts.extend([x, y])
        self.create_line(*pts, fill=self._accent, width=1.5, smooth=True)


# ---------------------------------------------------------------------------
# LogRow — ligne de log timestampée pour activity feeds
# ---------------------------------------------------------------------------
class LogRow(ctk.CTkFrame):
    """Ligne de log compacte : timestamp · niveau · message.

    Alignement vertical garanti entre lignes adjacentes (largeurs fixes
    pour timestamp et niveau), pour que le texte se lise comme une
    colonne propre.

    Niveaux : "info" (gris), "ok" (vert), "warn" (orange), "err" (rouge),
    "muted" (très discret pour les événements de fond).
    """

    LevelKind = Literal["info", "ok", "warn", "err", "muted"]

    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        timestamp: datetime | str,
        level: LevelKind = "info",
        message: str,
        source: str = "",       # ex "phare", "drip" — affiché en mono compact
    ):
        super().__init__(
            master,
            fg_color="transparent",
            height=heights.LOG_ROW,
        )
        self.pack_propagate(False)

        # Timestamp colonne fixe (mono)
        ts_text = (
            timestamp.strftime("%H:%M:%S")
            if isinstance(timestamp, datetime) else str(timestamp)
        )
        ctk.CTkLabel(
            self, text=ts_text,
            font=ttype.TIMESTAMP, text_color=colors.text_muted,
            width=widths.LOG_TIMESTAMP, anchor="w",
        ).pack(side="left", padx=(T.SPACE_SM, T.SPACE_SM))

        # Niveau colonne fixe (caps colorisé)
        level_color = {
            "info":  colors.info,
            "ok":    colors.success,
            "warn":  colors.warning,
            "err":   colors.danger,
            "muted": colors.text_muted,
        }[level]
        level_label = {
            "info":  "INFO",
            "ok":    "OK",
            "warn":  "WARN",
            "err":   "ERR",
            "muted": "·",
        }[level]
        ctk.CTkLabel(
            self, text=level_label,
            font=ttype.LABEL_TINY, text_color=level_color,
            width=widths.LOG_LEVEL, anchor="w",
        ).pack(side="left", padx=(0, T.SPACE_SM))

        # Source compacte (optionnelle)
        if source:
            ctk.CTkLabel(
                self, text=source,
                font=ttype.MONO_SM, text_color=colors.text_secondary,
                anchor="w",
            ).pack(side="left", padx=(0, T.SPACE_SM))

        # Message (prend la place restante)
        ctk.CTkLabel(
            self, text=message,
            font=ttype.BODY_SM, text_color=colors.text_primary,
            anchor="w", justify="left",
        ).pack(side="left", fill="x", expand=True)


# ---------------------------------------------------------------------------
# DrawerRight — panneau coulissant droite
# ---------------------------------------------------------------------------
class DrawerRight(ctk.CTkFrame):
    """Panneau qui se déploie sur le côté droit de son parent.

    Pas de vraie animation interpolée (Tk n'a pas d'API), mais un slide
    en N frames de 16 ms via .after() pour une transition perceptiblement
    fluide.

    Usage :
        drawer = DrawerRight(parent_frame, colors=c, width=380)
        drawer.add_title("Outils avancés du Phare")
        drawer.add_content_widget(my_panel)
        drawer.toggle()        # ouvre/ferme

    Le parent doit être un widget qui supporte .place(), idéalement un
    CTkFrame ou la fenêtre principale. Le drawer occupe toute la
    hauteur du parent et glisse depuis le bord droit.
    """

    SLIDE_FRAMES = 12        # nombre d'étapes pour la transition

    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        width: int = widths.DRAWER_RIGHT,
        on_close: Optional[Callable[[], None]] = None,
    ):
        super().__init__(
            master,
            fg_color=colors.panel_elevated,
            corner_radius=0,
            border_color=colors.border_strong,
            border_width=borders.HAIRLINE,
        )
        self._colors = colors
        self._target_width = width
        self._is_open = False
        self._on_close = on_close

        # Header avec titre + bouton fermer
        self._header = ctk.CTkFrame(self, fg_color="transparent", height=56)
        self._header.pack(fill="x", side="top")
        self._header.pack_propagate(False)

        self._title_label = ctk.CTkLabel(
            self._header, text="",
            font=ttype.H2, text_color=colors.text_primary,
            anchor="w",
        )
        self._title_label.pack(side="left", padx=(T.SPACE_LG, 0))

        close_btn = ctk.CTkButton(
            self._header, text="×", width=32, height=32,
            fg_color="transparent",
            hover_color=colors.panel_hover,
            text_color=colors.text_secondary,
            font=(T.FONT_FAMILY, 22, "bold"),
            corner_radius=T.RADIUS_SM,
            command=self.close,
        )
        close_btn.pack(side="right", padx=(0, T.SPACE_SM))

        # Filet sous le header
        ctk.CTkFrame(
            self, fg_color=colors.border, height=1, corner_radius=0,
        ).pack(fill="x", side="top")

        # Zone de contenu scrollable
        self._content = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=colors.border_strong,
            scrollbar_button_hover_color=colors.text_muted,
        )
        self._content.pack(fill="both", expand=True, padx=T.SPACE_LG,
                           pady=T.SPACE_LG)

    # ------------------------------------------------------------------ API
    def add_title(self, text: str) -> None:
        self._title_label.configure(text=text)

    def add_content_widget(self, widget: ctk.CTkBaseClass) -> None:
        widget.master = self._content
        widget.pack(in_=self._content, fill="x", pady=(0, T.SPACE_MD))

    @property
    def content(self) -> ctk.CTkScrollableFrame:
        """Conteneur sur lequel poser des widgets ad hoc."""
        return self._content

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> None:
        if self._is_open:
            return
        self._is_open = True
        self._slide(direction="open")

    def close(self) -> None:
        if not self._is_open:
            return
        self._is_open = False
        self._slide(direction="close")

    def toggle(self) -> None:
        if self._is_open:
            self.close()
        else:
            self.open()

    # --------------------------------------------------------------- slide
    def _slide(self, *, direction: Literal["open", "close"]):
        """Anime le drawer en place() sur N frames."""
        master = self.master
        master.update_idletasks()
        parent_w = master.winfo_width()
        parent_h = master.winfo_height()

        # Place le drawer si pas encore placé
        try:
            self.place_info()
        except Exception:
            self.place(x=parent_w, y=0, height=parent_h, width=self._target_width)

        # Trajectoire : de off-screen (x=parent_w) à visible (x=parent_w - width)
        start_x = parent_w if direction == "open" else parent_w - self._target_width
        end_x = parent_w - self._target_width if direction == "open" else parent_w

        frame_ms = max(8, motion.STANDARD // self.SLIDE_FRAMES)

        def step(i: int):
            t = i / self.SLIDE_FRAMES
            # easing : cubic-out pour un slide qui ralentit en fin de course
            eased = 1 - (1 - t) ** 3
            x = int(start_x + (end_x - start_x) * eased)
            try:
                self.place_configure(x=x, y=0, height=parent_h,
                                     width=self._target_width)
            except Exception:
                return
            if i < self.SLIDE_FRAMES:
                self.after(frame_ms, lambda: step(i + 1))
            else:
                if direction == "close":
                    self.place_forget()
                    if self._on_close:
                        try:
                            self._on_close()
                        except Exception:
                            pass

        step(0)


# ---------------------------------------------------------------------------
# Disclosure — section repliable inline
# ---------------------------------------------------------------------------
class Disclosure(ctk.CTkFrame):
    """Section repliable avec en-tête cliquable.

    Pattern : un titre cliquable affiche/cache un bloc de contenu.
    Utile pour densité maîtrisée — détails techniques masqués par
    défaut, accessibles d'un clic.

    Usage :
        d = Disclosure(parent, colors=c, title="Détails techniques")
        d.add_widget(my_widget)         # ajout dans le contenu
        d.pack(fill="x")
    """

    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        title: str,
        opened: bool = False,
        on_toggle: Optional[Callable[[bool], None]] = None,
    ):
        super().__init__(master, fg_color="transparent")
        self._colors = colors
        self._opened = opened
        self._on_toggle = on_toggle

        # En-tête cliquable
        self._header = ctk.CTkFrame(
            self, fg_color="transparent", cursor="hand2",
        )
        self._header.pack(fill="x")

        self._chevron = ctk.CTkLabel(
            self._header, text="▸" if not opened else "▾",
            font=ttype.LABEL, text_color=colors.text_secondary,
            width=16,
        )
        self._chevron.pack(side="left", padx=(0, T.SPACE_SM))

        self._title_label = ctk.CTkLabel(
            self._header, text=title,
            font=ttype.H3, text_color=colors.text_primary,
            anchor="w",
        )
        self._title_label.pack(side="left")

        for w in (self._header, self._chevron, self._title_label):
            w.bind("<Button-1>", lambda _e: self.toggle())

        # Conteneur de contenu (visible uniquement si opened)
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        if opened:
            self._content.pack(fill="x", pady=(T.SPACE_SM, 0),
                               padx=(24, 0))

    # ------------------------------------------------------------------ API
    def add_widget(self, widget: ctk.CTkBaseClass) -> None:
        widget.master = self._content
        widget.pack(in_=self._content, fill="x", pady=(0, T.SPACE_XS))

    @property
    def content(self) -> ctk.CTkFrame:
        return self._content

    @property
    def is_open(self) -> bool:
        return self._opened

    def toggle(self) -> None:
        self._opened = not self._opened
        self._chevron.configure(text="▾" if self._opened else "▸")
        if self._opened:
            self._content.pack(fill="x", pady=(T.SPACE_SM, 0), padx=(24, 0))
        else:
            self._content.pack_forget()
        if self._on_toggle:
            self._on_toggle(self._opened)


# ---------------------------------------------------------------------------
# HeroQuestion — question narrative en haut de vue data-heavy
# ---------------------------------------------------------------------------
class HeroQuestion(ctk.CTkLabel):
    """Question narrative en haut d'une vue data-heavy.

    Pose en français parlé ce que la vue est censée répondre. Donne un
    fil narratif au cockpit et transforme une grille de chiffres en
    récit. Toujours en Cinzel thin pour signaler le moment de
    cadrage avant la densité.

    Usage :
        HeroQuestion(parent, colors=c,
            text="Comment se portent les sites de l'écosystème ?"
        ).pack(fill="x", pady=(T.SPACE_LG, T.SPACE_MD))
    """

    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        text: str,
    ):
        super().__init__(
            master,
            text=text,
            font=(T.FONT_FAMILY_DISPLAY, 22, "normal"),
            text_color=colors.text_secondary,
            anchor="w",
            justify="left",
        )


__all__ = ["KpiHero", "LogRow", "DrawerRight", "Disclosure", "HeroQuestion"]
