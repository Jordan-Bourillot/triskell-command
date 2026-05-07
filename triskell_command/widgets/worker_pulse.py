"""WorkerPulse — pulsation système permanente en bas de l'app.

Visualise les 6 workers background (SyncPoller, RepliesPoller,
ReplyResponder, DripRunner, PostSaleRunner, PhareScheduler) sous forme
de LED qui respirent.

Complémentaire à `widgets/status_bar.py` (qui occupe le haut et montre
la configuration IA/MAIL/PILOTE + KPIs cliquables). Cette barre-ci
occupe le bas et montre la **vie des workers** : si les engrenages
tournent, ce qu'ils ont fait, et si quelque chose a planté.

Layout (de gauche à droite) :

    ●SYNC ●MAIL ●RESP ●DRIP ●POST ●PHAR  │ Le Phare → bulletin · à l'instant  │ ●Supabase  12:34

Effet recherché : l'opérateur sait en permanence que les engrenages
tournent. Si une LED passe au rouge, ça se voit sans interrompre le
travail en cours.

Usage :

    from .widgets.worker_pulse import WorkerPulse
    bar = WorkerPulse(root, colors=current_colors)
    bar.pack(side="bottom", fill="x")
    bar.update_worker("sync", state="active",
                      last_activity_text="48 prospects synchros",
                      relative_time="à l'instant")

Pas de threading interne : l'app appelle `update_worker()` depuis ses
callbacks. Les pulsations LED en mode `idle` sont gérées via `.after()`
sur le thread Tk, à 80 ms de cadence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

import customtkinter as ctk

from .. import theme as T
from ..tokens_v2 import heights, motion, ttype


WorkerState = Literal["idle", "active", "error", "off"]


@dataclass
class WorkerSpec:
    """Spécification statique d'un worker."""
    key: str
    short_label: str            # 4 chars, affichage compact
    full_name: str              # nom complet, pour tooltip
    cycle_label: str            # description du cycle


# Ordre canonique d'affichage (gauche → droite).
# Doit matcher les workers démarrés au login Supabase
# (cf. PROJECT_STATE.md § "Workers background").
WORKERS: list[WorkerSpec] = [
    WorkerSpec("sync",       "SYNC", "Synchronisation Supabase",     "toutes les 15-30 s"),
    WorkerSpec("replies",    "MAIL", "Réponses entrantes (IMAP)",    "toutes les 5 min"),
    WorkerSpec("responder",  "RESP", "Envoi des drafts validés",     "toutes les minutes"),
    WorkerSpec("drip",       "DRIP", "Relances J+7 / J+30",          "toutes les heures"),
    WorkerSpec("postsale",   "POST", "Cross-sell + NPS post-vente",  "toutes les heures"),
    WorkerSpec("phare",      "PHAR", "Le Phare (SEO autonome)",      "selon planning hebdo"),
]


@dataclass
class _LedState:
    state: WorkerState = "idle"
    last_activity_text: str = ""
    relative_time: str = ""
    pulse_phase: float = 0.0
    error_message: str = ""
    active_token: int = 0          # incrémenté à chaque passage "active" — anti-race


# ---------------------------------------------------------------------------
# Tooltip minimaliste — CustomTkinter n'en a pas, on construit le nôtre
# ---------------------------------------------------------------------------
class _Tooltip:
    """Tooltip flottant attaché à un widget. Apparaît après un court hover."""

    DELAY_MS = 350

    def __init__(self, widget, *, get_text, colors: T.ThemeColors):
        self._widget = widget
        self._get_text = get_text
        self._colors = colors
        self._after_id: Optional[str] = None
        self._top: Optional[ctk.CTkToplevel] = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self._widget.after(self.DELAY_MS, self._show)

    def _cancel(self):
        if self._after_id is not None:
            try:
                self._widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._top is not None:
            return
        text = self._get_text()
        if not text:
            return
        x = self._widget.winfo_rootx() + 12
        y = self._widget.winfo_rooty() - 8
        top = ctk.CTkToplevel(self._widget)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(fg_color=self._colors.panel_elevated)
        frame = ctk.CTkFrame(
            top, fg_color=self._colors.panel_elevated,
            border_color=self._colors.border_strong, border_width=1,
            corner_radius=8,
        )
        frame.pack(padx=0, pady=0)
        ctk.CTkLabel(
            frame, text=text,
            font=ttype.BODY_SM,
            text_color=self._colors.text_primary,
            justify="left", wraplength=320,
        ).pack(padx=10, pady=6)
        top.update_idletasks()
        h = top.winfo_height()
        top.geometry(f"+{x}+{y - h}")
        self._top = top

    def _hide(self, _event=None):
        self._cancel()
        if self._top is not None:
            try:
                self._top.destroy()
            except Exception:
                pass
            self._top = None


# ---------------------------------------------------------------------------
# WorkerPulse
# ---------------------------------------------------------------------------
class WorkerPulse(ctk.CTkFrame):
    """Barre de pulsation système en bas de l'app.

    Hauteur fixe : `tokens_v2.heights.STATUS_BAR` (28 px).
    """

    LED_RADIUS = 4

    def __init__(self, master, *, colors: T.ThemeColors, **kwargs):
        super().__init__(
            master,
            fg_color=colors.bg_alt,
            corner_radius=0,
            height=heights.STATUS_BAR,
            **kwargs,
        )
        self.pack_propagate(False)
        self._colors = colors
        self._led_states: dict[str, _LedState] = {w.key: _LedState() for w in WORKERS}
        self._led_canvas: dict[str, ctk.CTkCanvas] = {}
        self._supabase_online = False
        self._last_event_text = "Cockpit prêt."
        self._build()
        self._start_pulse_loop()
        self._start_clock_loop()

    # ------------------------------------------------------------------ build
    def _build(self):
        # Filet horizontal au-dessus de la barre (signature)
        top_rule = ctk.CTkFrame(
            self, fg_color=self._colors.border, height=1, corner_radius=0,
        )
        top_rule.pack(side="top", fill="x")

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(side="top", fill="both", expand=True, padx=14, pady=0)

        # --- Bloc gauche : 6 LED workers
        leds_frame = ctk.CTkFrame(inner, fg_color="transparent")
        leds_frame.pack(side="left", padx=(0, 14))
        for spec in WORKERS:
            led = self._make_led(leds_frame, spec)
            led.pack(side="left", padx=(0, 6))

        # Séparateur fin entre LED et message
        sep = ctk.CTkFrame(
            inner, fg_color=self._colors.border, width=1,
        )
        sep.pack(side="left", fill="y", padx=(2, 10), pady=4)

        # --- Bloc centre : dernière activité (vit à gauche, en italique discret)
        self._last_event_label = ctk.CTkLabel(
            inner, text=self._last_event_text,
            font=ttype.LOG, text_color=self._colors.text_muted,
            anchor="w",
        )
        self._last_event_label.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # --- Bloc droite : Supabase + horloge
        right = ctk.CTkFrame(inner, fg_color="transparent")
        right.pack(side="right")

        self._supabase_dot = ctk.CTkCanvas(
            right, width=10, height=10, highlightthickness=0,
            bg=self._colors.bg_alt,
        )
        self._supabase_dot.pack(side="left", padx=(0, 6))
        self._draw_dot(self._supabase_dot, color=self._colors.text_muted, radius=3)

        self._supabase_label = ctk.CTkLabel(
            right, text="Local",
            font=ttype.TIMESTAMP, text_color=self._colors.text_muted,
        )
        self._supabase_label.pack(side="left", padx=(0, 14))

        self._clock_label = ctk.CTkLabel(
            right, text="--:--",
            font=ttype.TIMESTAMP, text_color=self._colors.text_secondary,
        )
        self._clock_label.pack(side="left")

    def _make_led(self, parent, spec: WorkerSpec) -> ctk.CTkFrame:
        wrap = ctk.CTkFrame(parent, fg_color="transparent")

        canvas = ctk.CTkCanvas(
            wrap, width=10, height=10, highlightthickness=0,
            bg=self._colors.bg_alt,
        )
        canvas.pack(side="left", padx=(0, 4))
        self._led_canvas[spec.key] = canvas

        label = ctk.CTkLabel(
            wrap, text=spec.short_label,
            font=ttype.LABEL_TINY, text_color=self._colors.text_muted,
        )
        label.pack(side="left")

        def _tooltip_text() -> str:
            st = self._led_states[spec.key]
            lines = [spec.full_name]
            lines.append(f"  · cycle : {spec.cycle_label}")
            lines.append(f"  · état  : {self._state_label(st.state)}")
            if st.last_activity_text:
                lines.append(f"  · dernière : {st.last_activity_text}")
            if st.relative_time:
                lines.append(f"  · {st.relative_time}")
            if st.error_message:
                lines.append("")
                lines.append(f"  ⚠ {st.error_message}")
            return "\n".join(lines)

        _Tooltip(canvas, get_text=_tooltip_text, colors=self._colors)
        _Tooltip(label, get_text=_tooltip_text, colors=self._colors)

        self._render_led(spec.key)
        return wrap

    @staticmethod
    def _state_label(state: WorkerState) -> str:
        return {
            "idle": "au repos",
            "active": "en activité",
            "error": "erreur",
            "off": "désactivé",
        }.get(state, state)

    # ----------------------------------------------------------------- update
    AUTO_IDLE_MS = 4000        # durée d'affichage de l'état "active" avant retour idle

    def update_worker(
        self, key: str, *,
        state: WorkerState,
        last_activity_text: str = "",
        relative_time: str = "",
        error_message: str = "",
        broadcast_to_event: bool = True,
    ):
        """Met à jour l'état d'un worker. Appelé depuis les callbacks.

        Sémantique d'auto-decay : un état "active" repasse automatiquement
        à "idle" après `AUTO_IDLE_MS` (sauf si une nouvelle update arrive
        entre-temps, qui réinitialise le compteur). Les workers n'ont
        donc qu'un seul `report("active", ...)` à émettre par tick — ils
        n'ont pas à envoyer un "idle" ensuite.
        """
        if key not in self._led_states:
            return
        st = self._led_states[key]
        st.state = state
        if last_activity_text:
            st.last_activity_text = last_activity_text
        if relative_time:
            st.relative_time = relative_time
        st.error_message = error_message if state == "error" else ""
        self._render_led(key)
        if broadcast_to_event and state in ("active", "error") and last_activity_text:
            spec = next((w for w in WORKERS if w.key == key), None)
            prefix = spec.full_name.split(" (")[0] if spec else key
            arrow = "⚠" if state == "error" else "→"
            time_part = f" · {relative_time}" if relative_time else ""
            self._set_last_event(f"{prefix} {arrow} {last_activity_text}{time_part}")
        # Auto-decay : "active" → "idle" après AUTO_IDLE_MS si rien d'autre
        # n'arrive entre-temps. Un cookie incrémental évite la race condition
        # (mises à jour multiples se succédant rapidement).
        if state == "active":
            st.active_token += 1
            token = st.active_token
            try:
                self.after(self.AUTO_IDLE_MS,
                           lambda: self._auto_idle(key, token))
            except Exception:
                pass

    def _auto_idle(self, key: str, token: int) -> None:
        """Repasse un worker en idle si son token n'a pas été invalidé."""
        st = self._led_states.get(key)
        if st is None or st.active_token != token:
            return
        if st.state == "active":
            st.state = "idle"
            self._render_led(key)

    def set_supabase_status(self, online: bool, *, label: str = ""):
        """Met à jour l'indicateur Supabase (online / local)."""
        self._supabase_online = online
        color = self._colors.success if online else self._colors.text_muted
        self._draw_dot(self._supabase_dot, color=color, radius=3)
        try:
            self._supabase_label.configure(text=label or ("Supabase" if online else "Local"))
        except Exception:
            pass

    def set_last_event(self, text: str):
        """API publique pour pousser un événement dans la zone centrale."""
        self._set_last_event(text)

    # ------------------------------------------------------- render & helpers
    def _render_led(self, key: str):
        canvas = self._led_canvas.get(key)
        if canvas is None:
            return
        st = self._led_states[key]
        color = self._color_for_state(st.state, st.pulse_phase)
        self._draw_dot(canvas, color=color, radius=self.LED_RADIUS)

    def _color_for_state(self, state: WorkerState, phase: float) -> str:
        if state == "error":
            return self._colors.danger
        if state == "off":
            return self._colors.text_muted
        if state == "active":
            return self._colors.accent
        # idle : interpolation entre 2 nuances proches (respiration discrète)
        return self._lerp_hex(self._colors.text_muted,
                              self._colors.text_secondary,
                              phase)

    @staticmethod
    def _lerp_hex(c1: str, c2: str, t: float) -> str:
        t = max(0.0, min(1.0, t))

        def _hex_to_rgb(h):
            h = h.lstrip("#")
            return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))

        r1, g1, b1 = _hex_to_rgb(c1)
        r2, g2, b2 = _hex_to_rgb(c2)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def _draw_dot(canvas: ctk.CTkCanvas, *, color: str, radius: int):
        canvas.delete("all")
        w = int(canvas.winfo_reqwidth())
        h = int(canvas.winfo_reqheight())
        cx, cy = w // 2, h // 2
        canvas.create_oval(
            cx - radius, cy - radius, cx + radius, cy + radius,
            fill=color, outline="",
        )

    def _set_last_event(self, text: str):
        self._last_event_text = text
        try:
            self._last_event_label.configure(text=text)
        except Exception:
            pass

    # ------------------------------------------------------------- pulse loop
    def _start_pulse_loop(self):
        self._pulse_step = 0
        self._tick_pulse()

    def _tick_pulse(self):
        FRAME_MS = 80
        frames_per_cycle = max(1, motion.PULSE_IDLE // FRAME_MS)
        self._pulse_step = (self._pulse_step + 1) % frames_per_cycle

        # Triangle wave : 0 → 1 → 0
        half = frames_per_cycle / 2
        if self._pulse_step <= half:
            phase = self._pulse_step / half
        else:
            phase = (frames_per_cycle - self._pulse_step) / half

        for key, st in self._led_states.items():
            if st.state == "idle":
                st.pulse_phase = phase
                self._render_led(key)

        try:
            self.after(FRAME_MS, self._tick_pulse)
        except Exception:
            pass

    # ------------------------------------------------------------- clock loop
    def _start_clock_loop(self):
        self._tick_clock()

    def _tick_clock(self):
        try:
            self._clock_label.configure(text=datetime.now().strftime("%H:%M"))
            self.after(20_000, self._tick_clock)
        except Exception:
            pass


__all__ = ["WorkerPulse", "WorkerSpec", "WORKERS"]
