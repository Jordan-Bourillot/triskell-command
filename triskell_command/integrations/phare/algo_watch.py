"""Algo watch — veille quotidienne des évolutions de l'algo Google.

Sources scrappées (toutes publiques, RSS pour la plupart) :
- Search Engine Land /news/google-algorithm-updates → RSS officiel
- Search Engine Roundtable → RSS
- Google Search Liaison (Twitter) → fragile, on lit le compte via Nitter ou
  un mirror RSS comme rsshub.app si dispo
- Mozcast (volatilité SERP) → endpoint JSON
- Semrush Sensor → RSS public

Pour chaque source, on parse les nouveautés du jour et on fait résumer par
Claude Haiku (modèle léger, suffit pour synthèse 2 lignes).

Affiché dans la Matinale s'il y a un événement "warning" ou "critical".
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

from . import agents, repo

logger = logging.getLogger(__name__)


SOURCES = {
    "search_engine_land": "https://searchengineland.com/feed",
    "search_engine_roundtable": "https://www.seroundtable.com/feed/index.rdf",
    "mozcast": "https://moz.com/mozcast/feed",
    "semrush_sensor": "https://www.semrush.com/sensor/score.json",
    "google_search_liaison": "https://nitter.net/searchliaison/rss",
}


# ---------------------------------------------------------------------------
def _fetch_rss(url: str, *, max_items: int = 10) -> list[dict]:
    try:
        r = requests.get(url, timeout=15,
                         headers={"User-Agent": "TriskellLePhare/0.1"})
        if r.status_code >= 400:
            return []
        soup = BeautifulSoup(r.content, "xml")
    except Exception as exc:
        logger.debug("rss %s: %s", url, exc)
        return []
    items = soup.find_all(["item", "entry"])[:max_items]
    out = []
    for it in items:
        title = (it.find("title").get_text(strip=True) if it.find("title") else "")
        link = ""
        link_tag = it.find("link")
        if link_tag:
            link = link_tag.get("href") or link_tag.get_text(strip=True)
        pub = ""
        for tag_name in ("pubDate", "published", "updated", "dc:date"):
            tag = it.find(tag_name)
            if tag:
                pub = tag.get_text(strip=True)
                break
        desc = ""
        for tag_name in ("description", "summary", "content"):
            tag = it.find(tag_name)
            if tag:
                desc = tag.get_text(" ", strip=True)[:500]
                break
        out.append({"title": title, "link": link, "published": pub,
                     "summary": desc})
    return out


def _fetch_mozcast() -> Optional[float]:
    """Renvoie le score Mozcast (volatilité SERP, 0-100)."""
    try:
        r = requests.get(SOURCES["mozcast"], timeout=10)
        # En réalité Mozcast publie un RSS et non du JSON pur. On parse
        # le titre du dernier item qui contient la valeur.
        items = _fetch_rss(SOURCES["mozcast"], max_items=1)
        if not items:
            return None
        m = re.search(r"(\d+(?:\.\d+)?)", items[0].get("title", ""))
        return float(m.group(1)) if m else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
class AlgoSummarizer(agents.Agent):
    name = "algo_summarizer"
    role = """Tu es l'AlgoSummarizer de Le Phare.

Mission : à partir des nouveautés brutes des sources de veille SEO du jour,
écrire UN résumé en français, 2-4 phrases max, qui dit :
- s'il y a un mouvement algo Google notable aujourd'hui
- si oui, quoi, et qui est impacté
- si non, juste "RAS"

Évalue la sévérité :
- info : RAS, mouvements faibles, anecdotes du secteur
- warning : update ou volatilité notable, à surveiller
- critical : core update officiel ou rollback Google massif

Voix Triskell (préambule). Pas de panique, pas de hype.

Format JSON strict : {"severity": "info"|"warning"|"critical",
                      "headline": str, "summary_md": str}"""

    model = "claude-haiku-4-5"  # léger pour ce job

    def run(self, *, items_by_source: dict, mozcast_score: Optional[float],
            app_state=None) -> dict:
        prompt = f"""SOURCES DU JOUR :

{items_by_source}

Mozcast (volatilité SERP, 0-100) : {mozcast_score if mozcast_score is not None else 'inconnu'}

Produis le résumé au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------------------
def run_algo_watch(*, app_state=None) -> dict:
    cfg = repo.get_config()
    sources_enabled = cfg.get("algo_watch_sources",
                                ["search_engine_land",
                                 "google_search_liaison",
                                 "mozcast"])
    today = date.today()
    items_by_source: dict[str, list[dict]] = {}
    for src in sources_enabled:
        url = SOURCES.get(src)
        if not url:
            continue
        items_by_source[src] = _fetch_rss(url, max_items=5)
    mozcast = _fetch_mozcast() if "mozcast" in sources_enabled else None

    if not any(items_by_source.values()) and mozcast is None:
        return {"ok": True, "events_inserted": 0,
                "message": "aucune source disponible"}

    try:
        summary = AlgoSummarizer().run(
            items_by_source=items_by_source,
            mozcast_score=mozcast,
            app_state=app_state,
        )
    except Exception as exc:
        logger.warning("AlgoSummarizer LLM: %s", exc)
        summary = {}

    sb = repo._sb()
    if sb is None:
        return {"ok": False, "error": "Supabase indispo"}

    headline = (summary.get("headline") or
                  f"Veille algo {today.isoformat()}")
    severity = summary.get("severity", "info")
    summary_md = summary.get("summary_md", "")

    # Existe déjà aujourd'hui ?
    existing = (sb.table("phare_algo_events").select("id")
                .eq("event_date", today.isoformat())
                .eq("source", "+".join(sources_enabled[:3]))
                .limit(1).execute().data)
    if existing:
        return {"ok": True, "events_inserted": 0,
                "message": "déjà fait aujourd'hui"}

    try:
        sb.table("phare_algo_events").insert({
            "source": "+".join(sources_enabled[:3]),
            "event_date": today.isoformat(),
            "headline": headline[:300],
            "summary_md": summary_md,
            "severity": severity,
            "source_url": "",
        }).execute()
    except Exception as exc:
        logger.warning("algo_event insert: %s", exc)

    return {"ok": True, "severity": severity, "headline": headline,
            "events_inserted": 1, "mozcast": mozcast}


def latest_unack(*, days: int = 7) -> list[dict]:
    """Renvoie les événements algo non acquittés des N derniers jours
    (utilisé par la Matinale)."""
    sb = repo._sb()
    if sb is None:
        return []
    since = (date.today() - timedelta(days=days)).isoformat()
    try:
        return (sb.table("phare_algo_events").select("*")
                .gte("event_date", since)
                .eq("acknowledged", False)
                .order("event_date", desc=True).execute().data) or []
    except Exception as exc:
        logger.warning("algo latest: %s", exc)
        return []


def acknowledge(event_id: str) -> bool:
    sb = repo._sb()
    if sb is None:
        return False
    try:
        sb.table("phare_algo_events").update(
            {"acknowledged": True}).eq("id", event_id).execute()
        return True
    except Exception:
        return False
