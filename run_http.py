"""Lanceur serveur HTTP — Triskell Command web accessible dans n'importe
quel navigateur (PC, mobile, tablette).

Usage :
    python run_http.py            # localhost:8765
    python run_http.py --port 80  # autre port
    python run_http.py --host 0.0.0.0  # accessible sur le réseau local

Cohabite avec run.py (Tk) et run_web.py (pywebview). Aucun n'interfère.
Quand l'UI HTTP est validée + déployée publiquement, run.py et run_web.py
deviendront inutiles et pourront être supprimés.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

HERE = Path(__file__).parent
CORE = HERE.parent / "Triskell Core"
if CORE.exists() and str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

# Charge .env (SESSION_SECRET, JORDAN_PASSWORD_HASH, THOMAS_PASSWORD_HASH, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
except ImportError:
    pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Serveur HTTP Triskell Command")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Hôte (127.0.0.1 = local seulement, 0.0.0.0 = réseau)")
    parser.add_argument("--port", type=int, default=8765, help="Port (défaut 8765)")
    parser.add_argument("--reload", action="store_true",
                        help="Hot reload (dev) — recharge à chaque modif Python")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("triskell.command.http")
    logger.info("Démarrage serveur HTTP sur http://%s:%d", args.host, args.port)
    if args.host == "127.0.0.1":
        logger.info("→ Ouvre http://localhost:%d/ dans ton navigateur", args.port)
    else:
        logger.info("→ Accessible sur ton réseau local (autres appareils peuvent y accéder)")

    try:
        import uvicorn
    except ImportError:
        print("⚠ Module 'uvicorn' manquant. Installe :")
        print("    pip install uvicorn fastapi")
        sys.exit(1)

    uvicorn.run(
        "triskell_command.web.http_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
