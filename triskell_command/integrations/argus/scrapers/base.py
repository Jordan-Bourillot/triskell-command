"""
Classe de base pour tous les scrapers.

Chaque scraper concret hérite de BaseScraper et implémente la méthode `run`.
"""

import asyncio
import random
from typing import List

import httpx

from ..email_utils import extract_emails_from_text, is_valid_email
from ..state import state


# User-Agents récents et réalistes pour la rotation.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
]


def random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def default_headers() -> dict:
    return {
        "User-Agent": random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


class BaseScraper:
    """Squelette commun aux scrapers."""

    name: str = "base"

    def __init__(
        self,
        query: str,
        location: str,
        max_emails: int,
        include_personal: bool,
    ) -> None:
        self.query = (query or "").strip()
        self.location = (location or "").strip()
        self.max_emails = max(1, int(max_emails or 0) or 100)
        self.include_personal = include_personal
        self.found_count = 0
        self.pages_visited = 0

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """À implémenter dans chaque scraper concret."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helpers communs
    # ------------------------------------------------------------------

    async def polite_sleep(self, mini: float = 2.0, maxi: float = 5.0) -> None:
        """Pause aléatoire entre requêtes, en respectant la pause utilisateur."""
        await state.wait_if_paused()
        if state.should_stop:
            return
        await asyncio.sleep(random.uniform(mini, maxi))

    def log(self, level: str, message: str) -> None:
        state.log(level, self.name, message)

    def push_progress(self) -> None:
        state.update_source(
            self.name,
            found=self.found_count,
            visited_pages=self.pages_visited,
        )

    def consume_text(self, text: str) -> List[str]:
        """
        Extrait, valide et ajoute à l'état global tous les emails trouvés
        dans un bloc de texte/HTML. Retourne la liste des emails ajoutés.
        """
        added: List[str] = []
        for raw in extract_emails_from_text(text):
            if not is_valid_email(raw, self.include_personal):
                continue
            if state.add_email(raw, self.name):
                added.append(raw)
                self.found_count += 1
        if added:
            self.push_progress()
        return added

    def reached_limit(self) -> bool:
        return self.found_count >= self.max_emails or state.should_stop

    async def fetch_html(
        self,
        client: httpx.AsyncClient,
        url: str,
        timeout: float = 15.0,
    ) -> str | None:
        """Récupère le HTML d'une URL en HTTP simple. Retourne None si échec."""
        try:
            r = await client.get(url, timeout=timeout, headers=default_headers())
            if r.status_code >= 400:
                self.log("warn", f"HTTP {r.status_code} sur {url}")
                return None
            return r.text
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            self.log("warn", f"Erreur réseau {type(exc).__name__} sur {url}")
            return None
        except Exception as exc:
            self.log("warn", f"Erreur inattendue sur {url}: {exc}")
            return None
