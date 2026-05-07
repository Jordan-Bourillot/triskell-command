"""Démo standalone de la WorkerPulse — vitrine isolée du composant.

Ouvre une mini-fenêtre qui n'embarque QUE la WorkerPulse + un cycle
auto qui passe chaque worker en activité à tour de rôle. Permet de
visualiser les 3 états (idle pulsant, active accent, supabase online)
sans dépendre du reste de l'app.

    py -3.14 scripts\demo_worker_pulse.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import customtkinter as ctk

from triskell_command import theme as T
from triskell_command.widgets.worker_pulse import WORKERS, WorkerPulse


CYCLE_MS = 3500


class Demo(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("WorkerPulse — démo")
        self.geometry("1180x240")
        self.configure(fg_color=T.DARK.bg)

        # Bandeau titre
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(fill="x", padx=40, pady=(40, 0))

        bar = ctk.CTkFrame(wrap, fg_color=T.TRISKELL_GOLD,
                           width=32, height=3, corner_radius=2)
        bar.pack(anchor="w", pady=(0, 10))
        bar.pack_propagate(False)

        ctk.CTkLabel(
            wrap, text="Pulsation système",
            font=(T.FONT_FAMILY_DISPLAY, 22, "bold"),
            text_color=T.DARK.text_primary, anchor="w",
        ).pack(fill="x", anchor="w")

        ctk.CTkLabel(
            wrap, text=f"Cycle de démo · chaque worker passe en activité {CYCLE_MS // 1000} s "
                       "puis revient au repos. La pulsation lente = idle, "
                       "l'accent indigo = active.",
            font=(T.FONT_FAMILY, T.FONT_SIZE_BODY),
            text_color=T.DARK.text_secondary, anchor="w",
            justify="left", wraplength=1080,
        ).pack(fill="x", anchor="w", pady=(4, 0))

        # WorkerPulse en bas
        self.pulse = WorkerPulse(self, colors=T.DARK)
        self.pulse.pack(side="bottom", fill="x")
        self.pulse.set_supabase_status(True, label="Supabase")

        self._cycle_index = 0
        self.after(900, self._tick)

    def _tick(self):
        # Worker précédent → idle
        prev = WORKERS[(self._cycle_index - 1) % len(WORKERS)]
        self.pulse.update_worker(prev.key, state="idle",
                                  broadcast_to_event=False)
        # Worker courant → active
        cur = WORKERS[self._cycle_index % len(WORKERS)]
        msgs = {
            "sync":      "48 prospects synchronisés",
            "replies":   "3 nouvelles réponses (1 intéressé)",
            "responder": "2 drafts envoyés (délai 30 min écoulé)",
            "drip":      "12 relances J+7 préparées",
            "postsale":  "Cross-sell J+30 généré pour 3 clients",
            "phare":     "Audit hebdo bobeez.triskell-studio.fr",
        }
        self.pulse.update_worker(
            cur.key, state="active",
            last_activity_text=msgs.get(cur.key, "en activité"),
            relative_time="à l'instant",
        )
        self._cycle_index += 1
        self.after(CYCLE_MS, self._tick)


if __name__ == "__main__":
    Demo().mainloop()
