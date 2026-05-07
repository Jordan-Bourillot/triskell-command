"""Lanceur UI web — alternative pywebview à `run.py` (Tk).

Usage :
    python run_web.py

Cohabite avec `run.py` : tu peux lancer l'un OU l'autre, ils ne se gênent
pas. Quand l'UI web est validée, on coupera Tk.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Permet d'importer triskell_core depuis ../Triskell Core sans pip install
HERE = Path(__file__).parent
CORE = HERE.parent / "Triskell Core"
if CORE.exists() and str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("triskell.command.web")
    logger.info("Démarrage Triskell Command (UI web)")

    try:
        import webview
    except ImportError:
        print("⚠ Module 'pywebview' manquant. Installe :")
        print("    pip install pywebview")
        sys.exit(1)

    from triskell_command.web.api import Api

    api = Api()
    html_path = HERE / "triskell_command" / "web" / "ui" / "index.html"
    if not html_path.exists():
        print(f"⚠ Fichier HTML introuvable : {html_path}")
        sys.exit(1)

    window = webview.create_window(
        title="Triskell Command",
        url=str(html_path),
        js_api=api,
        width=1320,
        height=860,
        min_size=(1140, 740),
        resizable=True,
        background_color="#F8FAFC",   # bg light (par défaut, slate-50)
        text_select=True,
    )

    # Force le boot de l'API à la création de la fenêtre via expose
    # (pywebview appelle pywebviewready côté JS quand prêt)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
