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
from .views.convoy import ConvoyView
from .views.dashboard import DashboardView
from .views.autopilot import AutopilotView
from .views.clients import ClientsView
from .views.drafts import DraftsView
from .views.funnel import FunnelView
from .views.la_forge import LaForgeView
from .views.morning import MorningView
from .views.phare import PhareView
from .views.prospects import ProspectsView
from .views.publish import PublishView
from .views.replies import RepliesView
from .views.templates import TemplatesView
from .widgets.sidebar import Sidebar
from .widgets.splash import SplashScreen
from .widgets.status_bar import StatusBar
from .widgets.worker_pulse import WorkerPulse


logger = logging.getLogger("triskell.command")


# Ordre = ordre dans la sidebar
VIEW_REGISTRY: dict[str, type[BaseView]] = {
    "morning":    MorningView,
    "autopilot":  AutopilotView,
    "convoy":     ConvoyView,
    "drafts":     DraftsView,
    "replies":    RepliesView,
    "prospects":  ProspectsView,
    "compose":    ComposeView,
    "templates":  TemplatesView,
    "campaigns":  CampaignsView,
    "publish":    PublishView,
    "clients":    ClientsView,
    "funnel":     FunnelView,
    "dashboard":  DashboardView,
    "phare":      PhareView,
    "la_forge":   LaForgeView,
    "config":     ConfigView,
}


class TriskellCommandApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.app_state = AppState()

        # Apparence — 3 modes : light / mid / dark. CustomTkinter gère
        # 2 modes ('light' et 'dark') ; on map 'mid' → 'dark' pour les
        # composants natifs CTk, et on applique nos propres couleurs.
        appearance = T.normalize_mode(
            self.app_state.get("appearance_mode", default="mid")
        )
        ctk.set_appearance_mode("light" if appearance == "light" else "dark")
        self.colors = T.get_theme(appearance)
        self.appearance_mode = appearance

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

        # Layout : status bar haute + sidebar gauche + content + worker pulse bas
        # - col 0 : sidebar (ns sur 3 rows)
        # - col 1 : status bar (row 0), content (row 1), worker pulse (row 2)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=0)  # status bar
        self.grid_rowconfigure(1, weight=1)  # content
        self.grid_rowconfigure(2, weight=0)  # worker pulse

        # Sidebar (s'étend sur les 3 rows)
        self.sidebar = Sidebar(
            self,
            colors=self.colors,
            on_navigate=self.show_view,
            active_view=self.app_state.get("active_view", default="autopilot"),
        )
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="ns")

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

        # Worker pulse (col 1, row 2) — pulsation des 6 workers background
        self.worker_pulse = WorkerPulse(self, colors=self.colors)
        self.worker_pulse.grid(row=2, column=1, sticky="sew")
        self.worker_pulse.set_last_event("Cockpit prêt. 6 engrenages au repos.")

        # Branche le bus de pulsation : chaque worker publie via
        # `pulse_bus.report(...)` ; on relaye sur le mainloop Tk pour
        # toucher l'UI proprement (les workers tournent en background).
        from .integrations import pulse_bus

        def _on_pulse_event(evt: dict) -> None:
            try:
                self.after(0, lambda: self.worker_pulse.update_worker(
                    evt["key"], state=evt["state"],
                    last_activity_text=evt.get("text", ""),
                    relative_time=evt.get("relative_time", ""),
                    error_message=evt.get("error", ""),
                ))
            except Exception:
                pass

        pulse_bus.subscribe(_on_pulse_event)

        # Vues — instanciation lazy (pas tout d'un coup, gain perfs)
        self._views: dict[str, BaseView] = {}
        self._current_view: BaseView | None = None

        # Bouton flottant Claude — toujours visible, par-dessus tout.
        # Placé sur self (la window) avec place(), donc indépendant des vues.
        try:
            from .widgets.claude_fab import ClaudeFAB
            self.claude_fab = ClaudeFAB(
                self, colors=self.colors,
                on_click=lambda: self.show_view("claude"),
            )
            # Position : en bas à droite, marges généreuses
            self.claude_fab.place(relx=1.0, rely=1.0, x=-32, y=-32, anchor="se")
            # Lift par-dessus tout
            self.claude_fab.lift()
        except Exception as exc:
            logger.debug("Claude FAB non créé : %s", exc)
            self.claude_fab = None

        # Bouton flottant Chat Thomas — juste au-dessus du FAB Claude.
        # Même style, vert pour distinguer, badge avec compteur de non-lus.
        try:
            from .widgets.thomas_fab import ThomasFAB, SIZE as _THOMAS_SIZE
            self.thomas_fab = ThomasFAB(
                self, colors=self.colors,
                on_click=lambda: self.show_view("thomas"),
            )
            # Position : 12 px de gap au-dessus du Claude FAB (lui à y=-32)
            self.thomas_fab.place(relx=1.0, rely=1.0,
                                    x=-32, y=-32 - _THOMAS_SIZE - 12,
                                    anchor="se")
            self.thomas_fab.lift()
        except Exception as exc:
            logger.debug("Thomas FAB non créé : %s", exc)
            self.thomas_fab = None
        # Le dialog est ouvert pour mark_read → on n'a pas besoin de garder
        # une ref ; mais on suit son ouverture pour ne pas en empiler 2.
        self._thomas_dialog = None

        # Affiche la dernière vue active (ou la Matinale par défaut)
        initial = self.app_state.get("active_view", default="morning")
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

        # Initialisation Supabase (passive : si configuré, restaure la session ;
        # sinon on continue en mode local sans broncher).
        self.after(800, self._init_supabase_session)

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
                "active_view", default="morning"))
            return
        # Cas spécial : "tutorial" ouvre la visite guidée v0.3
        if view_id == "tutorial":
            from .widgets.tutorial_dialog import TutorialDialog
            TutorialDialog(
                self, colors=self.colors, app_state=self.app_state,
                on_navigate=self.show_view,
            )
            self.sidebar.set_active(self.app_state.get(
                "active_view", default="morning"))
            return
        # Cas spécial : "thomas" ouvre la modale de chat 1-à-1
        if view_id == "thomas":
            # Évite d'empiler 2 dialogs si l'utilisateur reclique
            existing = getattr(self, "_thomas_dialog", None)
            if existing is not None:
                try:
                    if existing.winfo_exists():
                        existing.lift()
                        existing.focus_force()
                        return
                except Exception:
                    pass
            from .widgets.thomas_dialog import ThomasDialog

            def _on_closed():
                self._thomas_dialog = None
                # Refresh du compteur de non-lus après fermeture
                self._refresh_unread_badge()

            self._thomas_dialog = ThomasDialog(
                self, colors=self.colors, app_state=self.app_state,
                on_closed=_on_closed,
            )
            # Le dialog marque les reçus comme lus à l'ouverture → on
            # éteint le badge tout de suite côté UI.
            try:
                if getattr(self, "thomas_fab", None) is not None:
                    self.thomas_fab.set_unread(0)
            except Exception:
                pass
            self.sidebar.set_active(self.app_state.get(
                "active_view", default="morning"))
            return
        # Cas spécial : "claude" ouvre la modale Allô Claude
        if view_id == "claude":
            from .widgets.claude_dialog import ClaudeDialog
            # Récupère un éventuel conseil pré-calculé par la veille auto
            prefilled = None
            try:
                from .integrations import claude_proactive
                prefilled = claude_proactive.consume_pending_advice()
            except Exception:
                pass
            ClaudeDialog(
                self, colors=self.colors, app_state=self.app_state,
                on_navigate=self.show_view,
                prefilled_advice=prefilled,
            )
            self.sidebar.set_active(self.app_state.get(
                "active_view", default="morning"))
            # Réinitialise le badge "Claude veut te parler"
            try:
                self.sidebar.set_attention("claude", False)
            except Exception:
                pass
            try:
                if getattr(self, "claude_fab", None) is not None:
                    self.claude_fab.set_attention(False)
            except Exception:
                pass
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
        """Raccourcis clavier globaux.

        Ordre choisi pour mettre en avant les actions quotidiennes
        (cf. docs/ux/01_NAVIGATION §3.4) :
            1 Aujourd'hui · 2 Brouillons · 3 Réponses · 4 Prospects
            5 Auto-pilote · 6 Convoy · 7 Compose · 8 Phare · 9 Tableau
            0 Tunnel
        """
        ordered_views = [
            "morning",     # 1
            "drafts",      # 2 — porte d'entrée quotidienne
            "replies",     # 3 — réponses entrantes
            "prospects",   # 4 — recherche manuelle
            "autopilot",   # 5
            "convoy",      # 6
            "compose",     # 7
            "phare",       # 8 — promu vs ancien ordre (était hors raccourci)
            "dashboard",   # 9
        ]
        for i, view_id in enumerate(ordered_views, 1):
            self.bind(
                f"<Control-Key-{i}>",
                lambda _e, v=view_id: self.show_view(v),
            )
        # Ctrl+0 → Tunnel de conversion (10e vue)
        self.bind("<Control-Key-0>", lambda _e: self.show_view("funnel"))
        # Ctrl+, → Réglages (convention macOS/Windows)
        self.bind("<Control-comma>", lambda _e: self.show_view("config"))
        # F1 ou Ctrl+? → Aide
        self.bind("<F1>", lambda _e: self.show_view("help"))
        self.bind("<Control-question>", lambda _e: self.show_view("help"))
        # Ctrl+R → rafraîchir vue courante + status bar
        self.bind("<Control-r>", lambda _e: self._refresh_current())
        # Ctrl+T → cycle de thème (light → mid → dark → light)
        self.bind("<Control-t>", lambda _e: self.cycle_theme())
        # F12 → Allô Claude
        self.bind("<F12>", lambda _e: self.show_view("claude"))
        # F11 → Chat avec l'équipier (Thomas / Jordan)
        self.bind("<F11>", lambda _e: self.show_view("thomas"))

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
    def cycle_theme(self) -> None:
        """Bascule le thème : light → mid → dark → light."""
        self.apply_theme(T.cycle_mode(self.appearance_mode))

    def apply_theme(self, mode: str) -> None:
        """Applique un thème (light / mid / dark) à chaud.

        Note : le re-rendu propre des vues déjà construites n'est pas
        instantané dans CTk (les widgets gardent leur fg_color). On force
        une reconstruction des vues à la prochaine activation. La fenêtre
        principale et la sidebar sont rebuilt immédiatement.
        """
        mode = T.normalize_mode(mode)
        if mode == self.appearance_mode:
            return
        self.appearance_mode = mode
        self.app_state.set("appearance_mode", value=mode)
        self.app_state.save()
        ctk.set_appearance_mode("light" if mode == "light" else "dark")
        self.colors = T.get_theme(mode)
        self.configure(fg_color=self.colors.bg)
        try:
            self.content.configure(fg_color=self.colors.bg)
        except Exception:
            pass
        # Force la reconstruction des vues au prochain affichage
        # (les widgets CTk ne rééchantillonnent pas leurs fg_color seuls).
        try:
            cur = self._current_view
            self._views.clear()
            self._current_view = None
            # Rebuild la sidebar avec les nouvelles couleurs
            self._rebuild_sidebar()
            self._rebuild_status_bar()
            self._rebuild_claude_fab()
            # Réaffiche la vue active
            active = self.app_state.get("active_view", default="morning")
            self.show_view(active)
        except Exception as exc:
            logger.warning("apply_theme rebuild: %s", exc)

    def _rebuild_sidebar(self) -> None:
        try:
            self.sidebar.destroy()
        except Exception:
            pass
        self.sidebar = Sidebar(
            self,
            colors=self.colors,
            on_navigate=self.show_view,
            active_view=self.app_state.get("active_view", default="morning"),
        )
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="ns")

    def _rebuild_status_bar(self) -> None:
        try:
            self.status_bar.destroy()
        except Exception:
            pass
        self.status_bar = StatusBar(
            self,
            colors=self.colors,
            app_state=self.app_state,
            on_navigate=self.show_view,
        )

    def _rebuild_claude_fab(self) -> None:
        """Recrée les FABs Claude + Thomas avec la nouvelle palette."""
        had_attention = False
        try:
            if getattr(self, "claude_fab", None) is not None:
                had_attention = bool(getattr(self.claude_fab,
                                              "_has_attention", False))
                self.claude_fab.destroy()
        except Exception:
            pass
        try:
            from .widgets.claude_fab import ClaudeFAB
            self.claude_fab = ClaudeFAB(
                self, colors=self.colors,
                on_click=lambda: self.show_view("claude"),
            )
            self.claude_fab.place(relx=1.0, rely=1.0,
                                    x=-32, y=-32, anchor="se")
            self.claude_fab.lift()
            if had_attention:
                self.claude_fab.set_attention(True)
        except Exception as exc:
            logger.debug("rebuild claude_fab: %s", exc)
            self.claude_fab = None
        # FAB Thomas (rebuild miroir)
        prev_unread = 0
        try:
            if getattr(self, "thomas_fab", None) is not None:
                prev_unread = int(getattr(self.thomas_fab, "_unread", 0))
                self.thomas_fab.destroy()
        except Exception:
            pass
        try:
            from .widgets.thomas_fab import ThomasFAB, SIZE as _THOMAS_SIZE
            self.thomas_fab = ThomasFAB(
                self, colors=self.colors,
                on_click=lambda: self.show_view("thomas"),
            )
            self.thomas_fab.place(relx=1.0, rely=1.0,
                                    x=-32, y=-32 - _THOMAS_SIZE - 12,
                                    anchor="se")
            self.thomas_fab.lift()
            if prev_unread > 0:
                self.thomas_fab.set_unread(prev_unread)
        except Exception as exc:
            logger.debug("rebuild thomas_fab: %s", exc)
            self.thomas_fab = None
        self.status_bar.grid(row=0, column=1, sticky="new")

    # -----------------------------------------------------------------
    def _refresh_forge_badge(self) -> None:
        """MAJ la pastille « briefs en attente » sur l'item sidebar La Forge.

        Appelé au login Supabase, et à chaque notification SyncPoller sur
        forge_pending_briefs / forge_projects. Tourne en thread pour ne
        pas bloquer le mainloop sur l'appel réseau Supabase."""
        import threading
        from .integrations.forge import repo as forge_repo

        def worker():
            try:
                n = forge_repo.count_briefs(status="new")
            except Exception:
                n = 0
            try:
                self.after(0, lambda v=n:
                           self.sidebar.set_attention("la_forge", v > 0))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True,
                         name="ForgeBadgeRefresh").start()

    # -----------------------------------------------------------------
    def _refresh_unread_badge(self) -> None:
        """Recalcule (async) le compteur de non-lus + l'aperçu du dernier
        message, MAJ le FAB. Notifie aussi côté système si un nouveau
        message reçu est arrivé pendant que l'app n'avait pas le focus.

        Appelé au login Supabase, à la fermeture du chat et à chaque
        notification 'messages' du SyncPoller."""
        if getattr(self, "thomas_fab", None) is None:
            return
        import threading
        from .integrations import messages as _M

        def worker():
            try:
                n = _M.count_unread()
            except Exception:
                n = 0
            try:
                preview = _M.last_message_preview()
            except Exception:
                preview = None
            try:
                self.after(0, lambda v=n, p=preview:
                           self._apply_unread_update(v, p))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True,
                         name="ChatUnreadCount").start()

    def _apply_unread_update(self, n: int, preview: dict | None) -> None:
        """Sur le mainloop : applique le compteur + l'aperçu, et déclenche
        la notif système si on est passé de N à N+ avec un message reçu."""
        if self.thomas_fab is None:
            return
        prev = int(getattr(self, "_last_unread_count", 0) or 0)
        # Met à jour le FAB
        try:
            self.thomas_fab.set_unread(n)
        except Exception:
            pass
        # Met à jour l'aperçu du tooltip
        try:
            if preview is not None:
                self.thomas_fab.set_last_preview(
                    preview.get("body"),
                    is_from_me=bool(preview.get("is_from_me")),
                )
            else:
                self.thomas_fab.set_last_preview(None)
        except Exception:
            pass
        # Notif système : on a un nouveau message reçu
        if n > prev and preview is not None and not preview.get("is_from_me"):
            try:
                self._notify_new_message(preview)
            except Exception as exc:
                logger.debug("notify_new_message: %s", exc)
        self._last_unread_count = n

    def _has_focus(self) -> bool:
        """True si la fenêtre Tk a actuellement le focus système."""
        try:
            return self.focus_displayof() is not None
        except Exception:
            return True   # par défaut, on suppose focus pour ne pas spammer

    def _notify_new_message(self, preview: dict) -> None:
        """Beep système + flash taskbar (si pas focus) + toast in-app si
        le dialog n'est pas déjà ouvert."""
        focused = self._has_focus()
        dialog_open = (getattr(self, "_thomas_dialog", None) is not None
                       and self._thomas_dialog.winfo_exists())
        # Pas de bruit si l'utilisateur est déjà dans le chat
        if dialog_open:
            return
        # Beep + flash uniquement quand l'app n'a pas le focus
        if not focused:
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                try:
                    self.bell()
                except Exception:
                    pass
            try:
                self._flash_taskbar()
            except Exception:
                pass
        # Toast in-app : visible si la window est affichée mais le dialog non
        try:
            self._show_chat_toast(preview)
        except Exception as exc:
            logger.debug("chat toast: %s", exc)

    def _flash_taskbar(self) -> None:
        """Fait clignoter le bouton de la barre des tâches (Windows uniquement)."""
        import sys
        if not sys.platform.startswith("win"):
            return
        import ctypes
        from ctypes import wintypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize",    wintypes.UINT),
                ("hwnd",      wintypes.HWND),
                ("dwFlags",   wintypes.DWORD),
                ("uCount",    wintypes.UINT),
                ("dwTimeout", wintypes.DWORD),
            ]

        FLASHW_TRAY = 0x00000002
        FLASHW_TIMERNOFG = 0x0000000C   # flash jusqu'à ce que la window ait le focus
        try:
            hwnd = self.winfo_id()
        except Exception:
            return
        info = FLASHWINFO(
            cbSize=ctypes.sizeof(FLASHWINFO),
            hwnd=hwnd,
            dwFlags=FLASHW_TRAY | FLASHW_TIMERNOFG,
            uCount=5,
            dwTimeout=0,
        )
        try:
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except Exception:
            pass

    def _show_chat_toast(self, preview: dict) -> None:
        """Toast in-app cliquable en bas-droite, juste au-dessus des FABs."""
        c = self.colors
        peer = "Ton équipier"
        try:
            from .integrations import messages as _M
            other = _M.other_user()
            if other:
                peer = other.get("display_name") or peer
        except Exception:
            pass
        body = (preview.get("body") or "").strip()
        if len(body) > 110:
            body = body[:107] + "…"

        toast = ctk.CTkFrame(self, fg_color=c.success, corner_radius=12)
        ctk.CTkLabel(
            toast, text=f"💬  {peer}",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color="#FFFFFF",
        ).pack(anchor="w", padx=14, pady=(10, 0))
        ctk.CTkLabel(
            toast, text=body or "(message vide)",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color="#FFFFFF",
            wraplength=320, justify="left",
        ).pack(anchor="w", padx=14, pady=(2, 4))
        ctk.CTkLabel(
            toast, text="Cliquer pour répondre →",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
            text_color="#FFFFFF",
        ).pack(anchor="w", padx=14, pady=(0, 10))
        # Au-dessus des deux FABs (Thomas est à -32 - 60 - 12 = -104,
        # le toast lui-même fait ~80 px, on le place ~200 au-dessus du bas)
        toast.place(relx=1.0, rely=1.0, x=-24, y=-200, anchor="se")

        def _open(_evt=None):
            try:
                toast.destroy()
            except Exception:
                pass
            self.show_view("thomas")

        for w in (toast, *toast.winfo_children()):
            w.bind("<Button-1>", _open)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

        # Auto-destroy après 8 s
        self.after(8_000,
                   lambda: toast.destroy() if toast.winfo_exists() else None)

    # -----------------------------------------------------------------
    def _init_supabase_session(self) -> None:
        """Tente de restaurer une session Supabase au démarrage.

        - Si pas configuré : silencieux, l'app continue en mode local.
        - Si configuré + token persisté valide : login transparent, refresh
          de la status bar.
        - Si configuré mais pas de session : ouvre le dialogue de login.
        """
        try:
            from triskell_core.db import get_client, SupabaseNotConfigured
            try:
                client = get_client()
            except SupabaseNotConfigured:
                logger.info("Supabase non configuré → mode local.")
                return
            if client.is_authenticated:
                name = client.user_display_name or client.user_id
                logger.info("Supabase : session restaurée pour %s", name)
                try:
                    self.status_bar.refresh()
                except Exception:
                    pass
                # Pulse worker : signale la connexion + bascule l'indicateur
                # de la worker_pulse de "Local" à "Supabase".
                try:
                    self.worker_pulse.set_supabase_status(True, label="Supabase")
                    from .integrations import pulse_bus
                    pulse_bus.report(
                        "sync", "active",
                        text=f"Connecté en tant que {name}",
                        relative_time="à l'instant",
                    )
                except Exception:
                    pass
                self._start_sync_poller()
                return
            # Pas de session → demande login
            try:
                from .widgets.login_dialog import LoginDialog

                def _on_login_done():
                    try:
                        self.status_bar.refresh()
                    except Exception:
                        pass
                    try:
                        self.worker_pulse.set_supabase_status(True, label="Supabase")
                        from .integrations import pulse_bus
                        pulse_bus.report(
                            "sync", "active",
                            text="Connecté à Supabase",
                            relative_time="à l'instant",
                        )
                    except Exception:
                        pass
                    self._start_sync_poller()

                LoginDialog(self, colors=self.colors, on_done=_on_login_done)
            except Exception as exc:
                logger.warning("Login dialog échec : %s", exc)
        except ImportError:
            logger.debug("SDK Supabase absent → mode local.")
        except Exception as exc:
            logger.warning("Init Supabase échouée : %s", exc)

    # -----------------------------------------------------------------
    def _start_sync_poller(self) -> None:
        """Démarre les pollers Supabase + IMAP au login (idempotent)."""
        if getattr(self, "_sync_poller", None) is None:
            try:
                from .integrations.sync_poll import SyncPoller

                def on_table_change(table: str) -> None:
                    # Le callback tourne dans un thread → on schedule sur la UI
                    logger.info("Sync : table '%s' a changé, refresh UI.", table)
                    self.after(0, self._on_remote_change, table)

                poller = SyncPoller(on_change=on_table_change)
                ok = poller.start()
                if ok:
                    self._sync_poller = poller
                    logger.info("SyncPoller actif (polling Supabase).")
            except Exception as exc:
                logger.debug("SyncPoller non démarré : %s", exc)
        # Poller IMAP des réponses prospects (best-effort, no-op si IMAP pas
        # configuré dans shared_settings ou settings.json local).
        try:
            from .integrations import replies_poller
            replies_poller.start_poller(self.app_state)
            logger.info("RepliesPoller actif (IMAP toutes les 5 min).")
        except Exception as exc:
            logger.debug("RepliesPoller non démarré : %s", exc)
        # Worker des réponses auto (envoie les drafts pending dont le délai
        # configuré est expiré, mode delay_30m / instant).
        try:
            from .integrations import reply_responder
            reply_responder.start_worker(self.app_state)
            logger.info("ReplyResponder actif (worker auto-envoi 60 s).")
        except Exception as exc:
            logger.debug("ReplyResponder non démarré : %s", exc)
        # Drip runner — relances J+7 / J+30 sur les envois sans réponse.
        try:
            from .integrations import drip_runner
            drip_runner.start_worker(self.app_state)
            logger.info("DripRunner actif (cycle 1 h).")
        except Exception as exc:
            logger.debug("DripRunner non démarré : %s", exc)
        # Post-sale — cross-sell J+30 + NPS J+90 sur les clients livrés.
        try:
            from .integrations import post_sale_runner
            post_sale_runner.start_worker(self.app_state)
            logger.info("PostSaleRunner actif (cycle 1 h).")
        except Exception as exc:
            logger.debug("PostSaleRunner non démarré : %s", exc)
        # Veille Claude — toutes les heures, signale les urgences.
        try:
            from .integrations import claude_proactive
            claude_proactive.set_notify_callback(self._on_claude_calls)
            claude_proactive.start_worker(self.app_state)
            logger.info("Veille Claude active (cycle 1 h).")
        except Exception as exc:
            logger.debug("Veille Claude non démarrée : %s", exc)
        # Chat Thomas : compteur de non-lus initial
        try:
            self._refresh_unread_badge()
        except Exception:
            pass
        # Bridge Teddy → La Forge du Web : poller IMAP filtré qui détecte
        # les mails "Demande de création de site" et dépose les briefs
        # dans forge_pending_briefs.
        try:
            from .integrations import teddy_to_forge
            teddy_to_forge.start_poller(self.app_state)
            logger.info("TeddyToForge bridge actif (cycle 5 min).")
        except Exception as exc:
            logger.debug("TeddyToForge non démarré : %s", exc)
        # Badge sidebar La Forge : compte des briefs en attente d'import
        try:
            self._refresh_forge_badge()
        except Exception:
            pass

    def _on_remote_change(self, table: str) -> None:
        """Appelée sur le mainloop Tk quand Supabase signale un changement."""
        # Chat : nouveau message → MAJ badge FAB + refresh dialog si ouvert
        if table == "messages":
            self._refresh_unread_badge()
            dlg = getattr(self, "_thomas_dialog", None)
            if dlg is not None:
                try:
                    if dlg.winfo_exists():
                        dlg._reload_async()
                except Exception:
                    pass
            return
        # Forge : nouveau brief / projet → MAJ badge sidebar
        if table in ("forge_pending_briefs", "forge_projects"):
            self._refresh_forge_badge()
        # Status bar : toujours utile
        try:
            self.status_bar.refresh()
        except Exception:
            pass
        # Vue courante : on rafraîchit si elle dépend de la table changée
        relevant_views = {
            "prospects": ("prospects", "drafts", "replies", "dashboard",
                           "morning", "funnel"),
            "prospect_drafts": ("drafts", "dashboard", "morning"),
            "convoy_drafts": ("convoy", "morning"),
            "convoy_campaigns": ("convoy",),
            "email_history": ("replies", "dashboard", "morning", "funnel"),
            "shared_settings": ("config",),
            "forge_pending_briefs": ("la_forge",),
            "forge_projects":       ("la_forge",),
        }
        targets = relevant_views.get(table, ())
        if self._current_view is not None and targets:
            for view_id, view in self._views.items():
                if view_id in targets and view is self._current_view:
                    try:
                        view.on_show()
                    except Exception:
                        pass

    # -----------------------------------------------------------------
    def _on_claude_calls(self, advice: dict) -> None:
        """Callback invoqué (depuis un thread) quand la veille Claude détecte
        une urgence. On schedule sur le mainloop Tk pour toucher l'UI.
        """
        try:
            self.after(0, self._handle_claude_call, advice)
        except Exception:
            pass

    def _handle_claude_call(self, advice: dict) -> None:
        # Pastille sur le bouton sidebar (si encore présent)
        try:
            self.sidebar.set_attention("claude", True)
        except Exception:
            pass
        # FAB Claude : passe en mode attention (pulse rapide + dot rouge)
        try:
            if getattr(self, "claude_fab", None) is not None:
                self.claude_fab.set_attention(True)
        except Exception:
            pass
        # Toast cliquable en bas à droite — discret, disparaît seul
        try:
            self._show_claude_toast(advice)
        except Exception as exc:
            logger.debug("toast claude: %s", exc)

    def _show_claude_toast(self, advice: dict) -> None:
        c = self.colors
        urgency = advice.get("urgency", "medium")
        head = advice.get("headline", "").strip() or "Claude veut te parler"
        label = head if len(head) <= 90 else head[:87] + "…"
        bg = c.danger if urgency == "high" else c.warning

        toast = ctk.CTkFrame(self, fg_color=bg, corner_radius=12)
        ctk.CTkLabel(
            toast, text=f"📞  Allô Claude",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color="#FFFFFF",
        ).pack(anchor="w", padx=14, pady=(10, 0))
        ctk.CTkLabel(
            toast, text=label,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_SMALL, "bold"),
            text_color="#FFFFFF",
            wraplength=320, justify="left",
        ).pack(anchor="w", padx=14, pady=(2, 4))
        ctk.CTkLabel(
            toast, text="Cliquer pour ouvrir →",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY),
            text_color="#FFFFFF",
        ).pack(anchor="w", padx=14, pady=(0, 10))

        # Place en bas à droite, marge 24px
        toast.place(relx=1.0, rely=1.0, x=-24, y=-24, anchor="se")

        def open_dialog(_evt=None):
            try:
                toast.destroy()
            except Exception:
                pass
            self.show_view("claude")

        for w in (toast, *toast.winfo_children()):
            w.bind("<Button-1>", open_dialog)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

        # Auto-destroy après 12s
        self.after(12_000, lambda: toast.destroy() if toast.winfo_exists() else None)

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
    logger.info("Démarrage Triskell Command %s", T.APP_VERSION_LABEL)
    # Splash bref pendant que l'app se charge
    app = TriskellCommandApp()
    app.withdraw()  # cache la window principale pendant le splash
    try:
        splash = SplashScreen(app, duration_ms=1400)
        app.update_idletasks()
        # 1.4s plus tard : on affiche la window principale + onboarding si nécessaire
        def _post_splash():
            app.deiconify()
            tutorial_pending = False
            try:
                from .widgets.onboarding import OnboardingDialog, needs_onboarding
                if needs_onboarding(app.app_state):
                    def _refresh_status():
                        try:
                            app.status_bar.refresh()
                        except Exception:
                            pass
                        # Onboarding fini : on enchaîne sur le tuto v0.3
                        _maybe_show_tutorial(app)
                    OnboardingDialog(
                        app, colors=app.colors,
                        app_state=app.app_state,
                        on_done=_refresh_status,
                    )
                else:
                    tutorial_pending = True
            except Exception as exc:
                logger.debug("Onboarding skipped : %s", exc)
                tutorial_pending = True
            if tutorial_pending:
                _maybe_show_tutorial(app)
        app.after(1400, _post_splash)
    except Exception as exc:
        logger.debug("Splash skipped : %s", exc)
        app.deiconify()
    app.mainloop()


def _maybe_show_tutorial(app) -> None:
    """Affiche le tuto v0.3 au 1er boot (flag persisté). Idempotent."""
    try:
        from .widgets.tutorial_dialog import TutorialDialog, needs_tutorial
        if not needs_tutorial(app.app_state):
            return
        TutorialDialog(
            app, colors=app.colors, app_state=app.app_state,
            on_navigate=app.show_view,
        )
    except Exception as exc:
        logger.debug("Tutorial skipped : %s", exc)
