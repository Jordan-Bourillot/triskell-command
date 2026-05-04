"""Application Triskell Command — fenêtre principale + routing entre les vues."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Permet d'importer triskell_core même quand on lance depuis n'importe où
HERE = Path(__file__).parent.parent
CORE = HERE.parent / "Triskell Core"
if CORE.exists() and str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import customtkinter as ctk

from . import theme as T
from .state import AppState
from .views.base import BaseView
from .views.campaigns import CampaignsView
from .views.compose import ComposeView
from .views.config import ConfigView
from .views.dashboard import DashboardView
from .views.autopilot import AutopilotView
from .views.drafts import DraftsView
from .views.prospects import ProspectsView
from .views.publish import PublishView
from .views.templates import TemplatesView
from .widgets.sidebar import Sidebar
from .widgets.splash import SplashScreen
from .widgets.status_bar import StatusBar


logger = logging.getLogger("triskell.command")


# Ordre = ordre dans la sidebar
VIEW_REGISTRY: dict[str, type[BaseView]] = {
    "autopilot":  AutopilotView,
    "drafts":     DraftsView,
    "prospects":  ProspectsView,
    "compose":    ComposeView,
    "templates":  TemplatesView,
    "campaigns":  CampaignsView,
    "publish":    PublishView,
    "dashboard":  DashboardView,
    "config":     ConfigView,
}


class TriskellCommandApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.app_state = AppState()

        # Apparence
        appearance = self.app_state.get("appearance_mode", default="dark")
        ctk.set_appearance_mode(appearance)
        self.colors = T.DARK if appearance == "dark" else T.LIGHT

        # Window
        self.title(f"{T.BRAND_NAME} {T.BRAND_PRODUCT} — {T.APP_VERSION_LABEL}")
        self.geometry(f"{T.WINDOW_WIDTH}x{T.WINDOW_HEIGHT}")
        self.minsize(T.WINDOW_MIN_WIDTH, T.WINDOW_MIN_HEIGHT)
        self.configure(fg_color=self.colors.bg)

        # Icône (si trouvée — gère mode dev et mode PyInstaller frozen)
        try:
            icon_path = self._resolve_icon_path()
            if icon_path and icon_path.exists():
                self.iconbitmap(str(icon_path))
        except Exception as exc:
            logger.debug("Échec de chargement de l'icône : %s", exc)

        # Layout : status bar haute + sidebar gauche + content
        # - col 0 : sidebar (ns sur 2 rows)
        # - col 1 : status bar (row 0) puis content (row 1)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=0)  # status bar
        self.grid_rowconfigure(1, weight=1)  # content

        # Sidebar (s'étend sur les 2 rows)
        self.sidebar = Sidebar(
            self,
            colors=self.colors,
            on_navigate=self.show_view,
            active_view=self.app_state.get("active_view", default="autopilot"),
        )
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="ns")

        # Status bar haute (col 1, row 0)
        self.status_bar = StatusBar(
            self,
            colors=self.colors,
            app_state=self.app_state,
            on_navigate=self.show_view,
        )
        self.status_bar.grid(row=0, column=1, sticky="new")

        # Content (col 1, row 1)
        self.content = ctk.CTkFrame(self, fg_color=self.colors.bg, corner_radius=0)
        self.content.grid(row=1, column=1, sticky="nsew")

        # Vues — instanciation lazy (pas tout d'un coup, gain perfs)
        self._views: dict[str, BaseView] = {}
        self._current_view: BaseView | None = None

        # Affiche la dernière vue active (ou prospects par défaut)
        initial = self.app_state.get("active_view", default="prospects")
        self.show_view(initial)

        # Hooks fermeture
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Raccourcis clavier — Ctrl+1..8 pour switcher de vue, Ctrl+, Réglages,
        # Ctrl+? Aide, Ctrl+R Rafraîchir status bar
        self._bind_shortcuts()

        # Vérification de mise à jour (passive, en arrière-plan)
        try:
            from .updater import updater
            self.after(2000, lambda: updater.check_for_updates(async_=True))
        except Exception as exc:
            logger.debug("Updater non lancé : %s", exc)

    # -----------------------------------------------------------------
    def _get_view(self, view_id: str) -> BaseView:
        if view_id in self._views:
            return self._views[view_id]
        view_cls = VIEW_REGISTRY.get(view_id)
        if view_cls is None:
            raise ValueError(f"Vue inconnue : {view_id}")
        view = view_cls(self.content, app_state=self.app_state, colors=self.colors)
        self._views[view_id] = view
        return view

    def show_view(self, view_id: str) -> None:
        # Cas spécial : "help" ouvre la modale d'aide sans changer de vue
        if view_id == "help":
            from .widgets.help_dialog import HelpDialog
            HelpDialog(self, colors=self.colors)
            # Re-sélectionne la vue active dans la sidebar
            self.sidebar.set_active(self.app_state.get(
                "active_view", default="autopilot"))
            return

        if view_id not in VIEW_REGISTRY:
            logger.warning("Vue inconnue : %s", view_id)
            return

        view = self._get_view(view_id)

        # Cache la vue précédente
        if self._current_view is not None and self._current_view is not view:
            self._current_view.pack_forget()

        view.pack(fill="both", expand=True)
        view.show()
        self._current_view = view

        # Sync sidebar + state + status bar
        self.sidebar.set_active(view_id)
        self.app_state.set("active_view", value=view_id)
        try:
            self.status_bar.refresh()
        except Exception:
            pass

    # -----------------------------------------------------------------
    def _bind_shortcuts(self) -> None:
        """Raccourcis clavier globaux."""
        # Ctrl+1..8 → vues, en suivant l'ordre de la sidebar
        ordered_views = [
            "autopilot", "drafts",
            "prospects", "compose", "templates",
            "campaigns", "publish", "dashboard",
        ]
        for i, view_id in enumerate(ordered_views, 1):
            self.bind(
                f"<Control-Key-{i}>",
                lambda _e, v=view_id: self.show_view(v),
            )
        # Ctrl+, → Réglages (convention macOS/Windows)
        self.bind("<Control-comma>", lambda _e: self.show_view("config"))
        # F1 ou Ctrl+? → Aide
        self.bind("<F1>", lambda _e: self.show_view("help"))
        self.bind("<Control-question>", lambda _e: self.show_view("help"))
        # Ctrl+R → rafraîchir vue courante + status bar
        self.bind("<Control-r>", lambda _e: self._refresh_current())

    def _refresh_current(self) -> None:
        if self._current_view is not None:
            try:
                self._current_view.on_show()
            except Exception:
                pass
        try:
            self.status_bar.refresh()
        except Exception:
            pass

    # -----------------------------------------------------------------
    def _resolve_icon_path(self) -> Path | None:
        """Cherche assets/triskell.ico en mode dev ou PyInstaller frozen."""
        # Mode frozen (PyInstaller bundle)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            p = Path(meipass) / "assets" / "triskell.ico"
            if p.exists():
                return p
        # Mode dev : depuis le dossier du package, on remonte au projet
        for root in (
            Path(__file__).parent.parent,         # Triskell Command/
            Path(__file__).parent.parent.parent,  # Triskell Studio/Triskell Command/
        ):
            p = root / "assets" / "triskell.ico"
            if p.exists():
                return p
        return None

    # -----------------------------------------------------------------
    def _on_close(self) -> None:
        try:
            # Sauvegarde dimensions fenêtre
            self.app_state.set("ui", "last_window_width", value=self.winfo_width())
            self.app_state.set("ui", "last_window_height", value=self.winfo_height())
            self.app_state.save()
        except Exception as exc:
            logger.warning("Échec sauvegarde state : %s", exc)
        self.destroy()


def run() -> None:
    # Force stdout/stderr en UTF-8 — évite les UnicodeEncodeError sur Windows bundlé
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info("Démarrage Triskell Command v0.1.0")
    # Splash bref pendant que l'app se charge
    app = TriskellCommandApp()
    app.withdraw()  # cache la window principale pendant le splash
    try:
        splash = SplashScreen(app, duration_ms=1400)
        app.update_idletasks()
        # 1.4s plus tard : on affiche la window principale + onboarding si nécessaire
        def _post_splash():
            app.deiconify()
            try:
                from .widgets.onboarding import OnboardingDialog, needs_onboarding
                if needs_onboarding(app.app_state):
                    def _refresh_status():
                        try:
                            app.status_bar.refresh()
                        except Exception:
                            pass
                    OnboardingDialog(
                        app, colors=app.colors,
                        app_state=app.app_state,
                        on_done=_refresh_status,
                    )
            except Exception as exc:
                logger.debug("Onboarding skipped : %s", exc)
        app.after(1400, _post_splash)
    except Exception as exc:
        logger.debug("Splash skipped : %s", exc)
        app.deiconify()
    app.mainloop()
