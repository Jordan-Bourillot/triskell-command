"""Argus — runner d'une session de scraping.

Une session = un run de scraping (toutes sources, un mot-clé, une zone).
Le scraping tourne dans un thread daemon avec son propre event loop asyncio.

API publique du module :
- start_session(payload)   : démarre un nouveau run
- pause_session()
- resume_session()
- stop_session()
- get_status()              : snapshot pour l'UI
- export_xlsx()             : génère le fichier Excel et le renvoie en base64
- set_reference_emails(...) : configure les emails à exclure du run
- is_running()              : raccourci booléen
"""

from __future__ import annotations

import asyncio
import base64
import threading
import time
from pathlib import Path
from typing import Iterable

from .exporter import build_filename, export_to_excel
from .scrapers.duckduckgo import DuckDuckGoScraper
from .scrapers.europages import EuropagesScraper
from .scrapers.openstreetmap import OpenStreetMapScraper
from .scrapers.pagesjaunes import PagesJaunesScraper
from .scrapers.websites import WebsitesScraper
from .state import EXPORTS_DIR, state


# Mapping source → classe scraper. Les noms doivent matcher ceux envoyés
# depuis l'UI (côté navigateur).
SCRAPER_CLASSES = {
    "pagesjaunes": PagesJaunesScraper,
    "europages": EuropagesScraper,
    "openstreetmap": OpenStreetMapScraper,
    "duckduckgo": DuckDuckGoScraper,
}

# Lock global pour éviter qu'on démarre deux sessions en parallèle.
_session_lock = threading.Lock()
_current_thread: threading.Thread | None = None


# ----------------------------------------------------------------------
# API publique
# ----------------------------------------------------------------------

def start_session(payload: dict) -> dict:
    """Démarre une session de scraping en arrière-plan."""
    global _current_thread

    with _session_lock:
        if state.is_running:
            return {"ok": False, "error": "Un scraping est déjà en cours."}

        # Validation rapide.
        sources = payload.get("sources") or []
        if isinstance(sources, str):
            # Tolère une liste passée en string CSV.
            sources = [s.strip() for s in sources.split(",") if s.strip()]
        if not sources:
            return {"ok": False, "error": "Au moins une source doit être sélectionnée."}

        query = (payload.get("query") or "").strip()
        location = (payload.get("location") or "").strip()
        try:
            max_emails = int(payload.get("max_emails") or 200)
        except (TypeError, ValueError):
            max_emails = 200
        include_personal = bool(payload.get("include_personal"))
        test_mode = bool(payload.get("test_mode"))

        seed_urls_raw = payload.get("seed_urls") or ""
        if isinstance(seed_urls_raw, list):
            seed_urls = [str(u).strip() for u in seed_urls_raw if str(u).strip()]
        else:
            seed_urls = [
                line.strip() for line in str(seed_urls_raw).splitlines()
                if line.strip()
            ]

        # Reset complet pour ce nouveau run.
        state.reset()
        state.is_running = True
        state.started_at = time.time()
        state.params = {
            "sources": list(sources),
            "query": query,
            "location": location,
            "max_emails": max_emails,
            "include_personal": include_personal,
            "test_mode": test_mode,
            "seed_urls_count": len(seed_urls),
        }

        _current_thread = threading.Thread(
            target=_run_in_thread,
            args=(sources, query, location, max_emails, include_personal,
                  seed_urls, test_mode),
            name="argus-session",
            daemon=True,
        )
        _current_thread.start()

    return {"ok": True}


def pause_session() -> dict:
    if not state.is_running:
        return {"ok": False, "error": "Aucun scraping en cours."}
    state.pause()
    return {"ok": True}


def resume_session() -> dict:
    if not state.is_running:
        return {"ok": False, "error": "Aucun scraping en cours."}
    state.resume()
    return {"ok": True}


def stop_session() -> dict:
    if not state.is_running:
        return {"ok": True, "info": "Aucun scraping en cours."}
    state.stop()
    return {"ok": True}


def get_status(log_tail: int = 200) -> dict:
    return {"ok": True, **state.snapshot(log_tail=log_tail)}


def is_running() -> bool:
    return state.is_running


def set_reference_emails(emails: Iterable[str]) -> dict:
    cleaned = {str(e).strip().lower() for e in (emails or []) if str(e).strip()}
    state.reference_emails = cleaned
    state.log("info", "system", f"{len(cleaned)} email(s) de référence chargés.")
    return {"ok": True, "count": len(cleaned)}


def export_xlsx() -> dict:
    """Génère un fichier Excel et le renvoie en base64 pour téléchargement."""
    if not state.emails:
        return {"ok": False, "error": "Aucun email à exporter."}
    try:
        out = EXPORTS_DIR / build_filename()
        export_to_excel(state.emails, out)
        data = out.read_bytes()
        return {
            "ok": True,
            "filename": out.name,
            "content_b64": base64.b64encode(data).decode("ascii"),
            "rows": len(state.emails),
        }
    except Exception as exc:
        return {"ok": False, "error": f"Export échoué : {exc}"}


# ----------------------------------------------------------------------
# Exécution dans le thread daemon
# ----------------------------------------------------------------------

def _run_in_thread(
    sources: list[str],
    query: str,
    location: str,
    max_emails: int,
    include_personal: bool,
    seed_urls: list[str],
    test_mode: bool,
) -> None:
    """Crée un event loop asyncio dans ce thread et lance la session."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    state.attach_loop_event(loop)

    try:
        loop.run_until_complete(_run_session_async(
            sources=sources,
            query=query,
            location=location,
            max_emails=max_emails,
            include_personal=include_personal,
            seed_urls=seed_urls,
            test_mode=test_mode,
        ))
    except Exception as exc:
        state.log("error", "system", f"Crash global du run : {exc}")
    finally:
        try:
            loop.close()
        except Exception:
            pass
        state.is_running = False
        state.finished_at = time.time()
        # Sauvegarde finale.
        state.save_to_disk()


async def _run_session_async(
    sources: list[str],
    query: str,
    location: str,
    max_emails: int,
    include_personal: bool,
    seed_urls: list[str],
    test_mode: bool,
) -> None:
    if test_mode:
        max_emails = min(10, max_emails)

    state.log(
        "info", "system",
        f"Démarrage : sources={sources}, requête={query!r}, "
        f"localité={location!r}, max/source={max_emails}, mode test={test_mode}",
    )

    # 1) Sources principales (séquentiel pour respecter les sites).
    for source in sources:
        if state.should_stop:
            break
        if source == "websites":
            # Traité séparément à la fin.
            continue
        cls = SCRAPER_CLASSES.get(source)
        if cls is None:
            state.log("warn", "system", f"Source inconnue : {source}")
            continue
        scraper = cls(
            query=query,
            location=location,
            max_emails=max_emails,
            include_personal=include_personal,
        )
        try:
            await scraper.run()
        except Exception as exc:
            state.log("error", source, f"Crash : {exc}")
            state.update_source(source, status="error", message=str(exc))
        # Sauvegarde progressive.
        state.save_to_disk()

    # 2) Sites web (toujours en dernier, alimenté par les précédents).
    if not state.should_stop:
        if "websites" in sources or seed_urls:
            ws = WebsitesScraper(
                query=query,
                location=location,
                max_emails=max_emails * 2,
                include_personal=include_personal,
                seed_urls=seed_urls,
            )
            try:
                await ws.run()
            except Exception as exc:
                state.log("error", "websites", f"Crash : {exc}")
                state.update_source("websites", status="error", message=str(exc))

    final_msg = (
        f"Session terminée. {len(state.emails)} email(s) au total."
        if not state.should_stop else
        f"Session arrêtée. {len(state.emails)} email(s) collectés."
    )
    state.log("success" if not state.should_stop else "warn", "system", final_msg)
