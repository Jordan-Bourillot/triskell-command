"""Status bar haute — état du système et KPIs en un coup d'œil."""

from __future__ import annotations

import logging
import threading
from typing import Callable

import customtkinter as ctk

from .. import theme as T

logger = logging.getLogger(__name__)


class StatusPill(ctk.CTkFrame):
    """Pastille d'état compacte : dot coloré + label + valeur, sur une seule ligne."""

    def __init__(
        self,
        master,
        *,
        label: str,
        ok: bool,
        colors: T.ThemeColors,
        on_click: Callable[[], None] | None = None,
        ok_text: str = "OK",
        ko_text: str = "à configurer",
    ):
        super().__init__(
            master,
            fg_color="transparent",
            corner_radius=0,
        )
        c = colors

        # Dot coloré (filled circle Unicode)
        dot_color = c.success if ok else c.warning
        dot = ctk.CTkLabel(
            self, text="●",
            font=(T.FONT_FAMILY_FALLBACK, 11),
            text_color=dot_color,
        )
        dot.pack(side="left", padx=(0, 6))

        # Label en caps subtle
        ctk.CTkLabel(
            self, text=label.upper(),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_muted,
        ).pack(side="left", padx=(0, 6))

        # Valeur (état) — couleur selon ok/ko
        ctk.CTkLabel(
            self,
            text=ok_text if ok else ko_text,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.text_secondary if ok else c.warning,
        ).pack(side="left")

        if on_click:
            for w in (self, dot):
                w.bind("<Button-1>", lambda _e: on_click())
                try:
                    w.configure(cursor="hand2")
                except Exception:
                    pass
            # Toute la pill devient cliquable
            for child in self.winfo_children():
                child.bind("<Button-1>", lambda _e: on_click())
                try:
                    child.configure(cursor="hand2")
                except Exception:
                    pass


class StatusBar(ctk.CTkFrame):
    """Barre d'état globale en haut de la window principale.

    Affiche en temps réel :
    - 🟢/🟠 Service IA (clé configurée ?)
    - 🟢/🟠 Mail (SMTP configuré ?)
    - 🟢/⚪ Pilote auto (activé ?)
    - 📬 N drafts en attente
    - 📊 N prospects, M envoyés aujourd'hui
    """

    HEIGHT = 36

    def __init__(
        self,
        master,
        *,
        colors: T.ThemeColors,
        app_state,
        on_navigate: Callable[[str], None],
    ):
        super().__init__(
            master,
            fg_color=colors.bg_alt,
            corner_radius=0,
            height=self.HEIGHT,
        )
        self.pack_propagate(False)
        self._colors = colors
        self._app_state = app_state
        self._on_navigate = on_navigate

        # Cache du count prospects : la lecture CRM peut être lente sur grosse
        # base (ex. 5000+ entrées). On affiche la dernière valeur connue et on
        # rafraîchit en arrière-plan.
        self._cached_prospects: int = 0
        self._prospects_fetching: bool = False

        # Container interne (padding horizontal)
        self._inner = ctk.CTkFrame(self, fg_color="transparent")
        self._inner.pack(fill="both", expand=True, padx=T.SPACE_LG, pady=4)

        self.refresh()

    def refresh(self) -> None:
        """Recalcule l'état complet et reconstruit la barre."""
        for w in self._inner.winfo_children():
            w.destroy()

        c = self._colors

        # === État IA ===
        ai_ok = self._has_ai_key()
        StatusPill(
            self._inner, label="IA",
            ok=ai_ok, colors=c,
            on_click=lambda: self._on_navigate("config"),
            ok_text="prête", ko_text="clé manquante",
        ).pack(side="left", padx=(0, T.SPACE_LG))

        # === État Mail ===
        mail_ok = self._has_smtp()
        StatusPill(
            self._inner, label="MAIL",
            ok=mail_ok, colors=c,
            on_click=lambda: self._on_navigate("config"),
            ok_text="prêt", ko_text="à configurer",
        ).pack(side="left", padx=(0, T.SPACE_LG))

        # === Pilote auto ===
        pilot_on = self._is_pilot_enabled()
        StatusPill(
            self._inner, label="PILOTE",
            ok=pilot_on, colors=c,
            on_click=lambda: self._on_navigate("autopilot"),
            ok_text="activé", ko_text="désactivé",
        ).pack(side="left", padx=(0, T.SPACE_LG))

        # Spacer
        spacer = ctk.CTkFrame(self._inner, fg_color="transparent")
        spacer.pack(side="left", fill="x", expand=True)

        # === Brouillons en attente ===
        n_drafts = self._count_pending_drafts()
        if n_drafts > 0:
            self._make_kpi_link(
                self._inner,
                f"{n_drafts} brouillon{'s' if n_drafts > 1 else ''} à valider",
                color=c.accent,
                on_click=lambda: self._on_navigate("drafts"),
            )

        # === Prospects total === (cache + fetch async pour ne pas bloquer UI)
        n_prospects = self._cached_prospects
        self._make_kpi_link(
            self._inner,
            f"{n_prospects} prospect{'s' if n_prospects > 1 else ''}",
            color=c.text_secondary,
            on_click=lambda: self._on_navigate("prospects"),
        )
        self._maybe_fetch_prospects_async()

        # === Envoyés aujourd'hui ===
        n_today = self._count_today()
        if n_today > 0:
            self._make_kpi_link(
                self._inner,
                f"{n_today} envoyé{'s' if n_today > 1 else ''} aujourd'hui",
                color=c.success,
                on_click=lambda: self._on_navigate("dashboard"),
            )

        # === Profil utilisateur (Jordan / Thomas / non connecté) ===
        self._make_profile_chip(self._inner)

    def _make_profile_chip(self, parent) -> None:
        """Affiche le profil connecté à droite de la status bar.

        - Authentifié → dot coloré + nom (Jordan / Thomas) + click → logout
        - Non authentifié → "non connecté" + click → ouvre le dialogue de login
        """
        c = self._colors
        info = self._get_profile_info()
        if info is None:
            # Pas de Supabase configuré du tout → on n'affiche rien (mode legacy
            # 100% local). L'app continue de marcher comme avant la migration.
            return

        if info.get("authenticated"):
            color = info.get("color") or c.accent
            name = info.get("display_name") or "(sans nom)"
            chip = ctk.CTkFrame(
                parent, fg_color=c.panel,
                corner_radius=T.RADIUS_PILL,
                border_color=color, border_width=1,
            )
            chip.pack(side="left", padx=(0, T.SPACE_SM))
            ctk.CTkLabel(
                chip, text="●",
                font=(T.FONT_FAMILY_FALLBACK, 11),
                text_color=color,
            ).pack(side="left", padx=(8, 4), pady=2)
            ctk.CTkLabel(
                chip, text=name,
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                text_color=c.text_primary,
            ).pack(side="left", padx=(0, 8), pady=2)
            for w in (chip, ) + tuple(chip.winfo_children()):
                try:
                    w.configure(cursor="hand2")
                except Exception:
                    pass
                w.bind("<Button-1>", lambda _e: self._on_navigate("config"))
        else:
            # Bouton "Se connecter"
            btn = ctk.CTkLabel(
                parent, text="se connecter",
                font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
                text_color=c.warning,
            )
            btn.pack(side="left", padx=(0, T.SPACE_SM))
            try:
                btn.configure(cursor="hand2")
            except Exception:
                pass
            btn.bind("<Button-1>", lambda _e: self._open_login_dialog())

    def _get_profile_info(self) -> dict | None:
        """None = Supabase pas configuré ; sinon dict avec authenticated."""
        try:
            from triskell_core.db import get_client
            client = get_client()
        except Exception:
            return None
        if client.is_authenticated:
            color = self._app_state.get("profile", "color", default=None)
            return {
                "authenticated": True,
                "user_id": client.user_id,
                "display_name": client.user_display_name or "(sans nom)",
                "color": color or self._colors.accent,
            }
        return {"authenticated": False}

    def _open_login_dialog(self) -> None:
        try:
            from .login_dialog import LoginDialog
            top = self.winfo_toplevel()
            LoginDialog(top, colors=self._colors,
                         on_done=lambda: self.refresh())
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Login dialog échec : %s", exc
            )

    def _make_kpi_link(self, parent, text, *, color, on_click):
        c = self._colors
        lbl = ctk.CTkLabel(
            parent, text=text,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color=color,
        )
        lbl.pack(side="left", padx=(0, T.SPACE_LG))
        if on_click:
            try:
                lbl.configure(cursor="hand2")
            except Exception:
                pass
            lbl.bind("<Button-1>", lambda _e: on_click())

    # ------------------------------------------------------------------
    # Helpers : interroge l'état du système
    # ------------------------------------------------------------------
    def _has_ai_key(self) -> bool:
        keys = self._app_state.get("ai", "api_keys", default={}) or {}
        provider = self._app_state.get("ai", "selected_provider", default="anthropic")
        return bool(keys.get(provider))

    def _has_smtp(self) -> bool:
        outreach = self._app_state.get("outreach", default={}) or {}
        return all(outreach.get(k) for k in
                   ("smtp_host", "smtp_port", "smtp_user", "smtp_password", "from_email"))

    def _is_pilot_enabled(self) -> bool:
        try:
            from triskell_core.prospect.pipeline import PipelineConfig
            return PipelineConfig.load().enabled
        except Exception:
            return False

    def _maybe_fetch_prospects_async(self) -> None:
        """Lance un fetch CRM en thread si pas déjà en cours.

        Le résultat alimente `self._cached_prospects` puis re-trigger un
        `refresh()` UI seulement si la valeur a changé (évite la boucle).
        """
        if self._prospects_fetching:
            return
        self._prospects_fetching = True

        def worker():
            try:
                from triskell_core.prospect.core.crm import CRM
                n = len(CRM().all())
            except Exception as exc:
                logger.debug("count_prospects fetch failed: %s", exc)
                n = self._cached_prospects
            try:
                self.after(0, self._on_prospects_fetched, n)
            except Exception:
                # Widget détruit entre-temps
                self._prospects_fetching = False

        threading.Thread(target=worker, daemon=True).start()

    def _on_prospects_fetched(self, n: int) -> None:
        self._prospects_fetching = False
        if n == self._cached_prospects:
            return
        self._cached_prospects = n
        try:
            self.refresh()
        except Exception:
            pass

    def _count_pending_drafts(self) -> int:
        try:
            from triskell_core.prospect.pipeline import list_pending_drafts
            return len(list_pending_drafts())
        except Exception:
            return 0

    def _count_today(self) -> int:
        try:
            from triskell_core.prospect.outreach.smtp_sender import _load_today_count
            return _load_today_count()
        except Exception:
            return 0
