"""Lanceur racine — pratique pour double-clic / raccourci."""

import sys
from pathlib import Path

# Permet d'importer triskell_core depuis ../Triskell Core sans pip install
HERE = Path(__file__).parent
CORE = HERE.parent / "Triskell Core"
if CORE.exists() and str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from triskell_command.main import run

if __name__ == "__main__":
    run()
