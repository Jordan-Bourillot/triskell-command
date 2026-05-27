"""
Scraper "Sites web".

Pour chaque URL collectée par les autres scrapers (et/ou fournie par l'utilisateur),
visite la page d'accueil + les pages classiques "Contact", "Mentions légales",
"À propos", etc. et extrait les emails présents littéralement dans le HTML.
"""

import asyncio
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, default_headers
from ..state import state


# Chemins courants où on trouve des emails sur un site pro français.
COMMON_PATHS = [
    "/",
    "/contact",
    "/contact.html",
    "/contact.php",
    "/nous-contacter",
    "/contactez-nous",
    "/mentions-legales",
    "/mentions-legales.html",
    "/mentions-legales.php",
    "/mentions",
    "/legal",
    "/a-propos",
    "/about",
    "/qui-sommes-nous",
    "/equipe",
]


class WebsitesScraper(BaseScraper):
    name = "websites"

    def __init__(
        self,
        query: str,
        location: str,
        max_emails: int,
        include_personal: bool,
        seed_urls: list[str] | None = None,
    ) -> None:
        super().__init__(query, location, max_emails, include_personal)
        self.seed_urls = seed_urls or []

    async def run(self) -> None:
        state.init_source(self.name)
        self.log("info", "Démarrage scraping des sites web.")

        # Combine les seeds fournis par l'utilisateur et ceux découverts pendant
        # les autres scrapings.
        urls = set(self.seed_urls) | set(state.discovered_sites)
        urls = {self._normalize(u) for u in urls if u}
        urls = {u for u in urls if u}

        if not urls:
            self.log("info", "Aucun site à scraper.")
            state.update_source(self.name, status="done", message="Aucun site à scraper")
            return

        self.log("info", f"{len(urls)} site(s) à parcourir.")

        async with httpx.AsyncClient(
            follow_redirects=True,
            headers=default_headers(),
            timeout=15.0,
        ) as client:
            # On limite le parallélisme à 5 pour ne pas saturer le réseau.
            semaphore = asyncio.Semaphore(5)

            async def worker(url: str) -> None:
                async with semaphore:
                    await state.wait_if_paused()
                    if state.should_stop or self.reached_limit():
                        return
                    await self._scrape_site(client, url)

            await asyncio.gather(*(worker(u) for u in urls), return_exceptions=True)

        status = "stopped" if state.should_stop else "done"
        state.update_source(self.name, status=status)
        self.log("success", f"Sites web terminé : {self.found_count} emails.")

    def _normalize(self, url: str) -> str | None:
        """Normalise une URL : http(s)://domaine, sans paramètres ni fragment."""
        if not url:
            return None
        try:
            parsed = urlparse(url if url.startswith("http") else f"http://{url}")
            if not parsed.netloc:
                return None
            # On ignore les domaines de redirection/raccourcissement et trackers.
            blocked = (
                "google.", "facebook.", "twitter.", "instagram.", "linkedin.",
                "youtube.", "pinterest.", "tiktok.", "bit.ly", "tinyurl",
                "googletagmanager", "doubleclick", "gstatic", "googleapis",
                "cloudflare", "jsdelivr", "fontawesome",
            )
            if any(b in parsed.netloc.lower() for b in blocked):
                return None
            return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            return None

    async def _scrape_site(self, client: httpx.AsyncClient, base_url: str) -> None:
        if self.reached_limit():
            return

        # On essaie chaque chemin courant.
        for path in COMMON_PATHS:
            if self.reached_limit() or state.should_stop:
                return
            await state.wait_if_paused()

            url = urljoin(base_url, path)
            html = await self.fetch_html(client, url, timeout=10.0)
            self.pages_visited += 1
            if not html:
                continue

            added = self.consume_text(html)

            # Si la page d'accueil pointe vers une page "contact" différente
            # (lien custom), on suit ce lien aussi.
            if path == "/":
                try:
                    soup = BeautifulSoup(html, "html.parser")
                    for a in soup.find_all("a", href=True):
                        text = (a.get_text() or "").lower()
                        href = a["href"].lower()
                        if "contact" in text or "contact" in href or "mentions" in href:
                            extra = urljoin(base_url, a["href"])
                            if extra.startswith(base_url) and extra != base_url:
                                eh = await self.fetch_html(client, extra, timeout=10.0)
                                self.pages_visited += 1
                                if eh:
                                    self.consume_text(eh)
                                    if self.reached_limit():
                                        return
                except Exception:
                    pass

            self.push_progress()

            # Si on a trouvé un email sur cette page, on peut passer au site suivant
            # (inutile d'aller chercher plus loin pour un même site).
            if added:
                return
