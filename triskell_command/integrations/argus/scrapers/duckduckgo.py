"""
Scraper DuckDuckGo HTML Search — version robustifiée.

Le test précédent a retourné 0 site sur 2 requêtes. Causes possibles :
- DuckDuckGo a changé sa structure HTML.
- Mes filtres d'exclusion sont trop stricts.
- Mes sélecteurs CSS ne matchent plus.

Corrections :
- Sélecteurs CSS élargis (a.result__a, a.result__url, mais aussi h2 a, etc.).
- Regex de secours sur le HTML brut (recherche directe d'URLs).
- Filtres d'exclusion plus permissifs : on garde tout sauf les réseaux sociaux
  et les concurrents directs (annuaires déjà scrapés).
- Logging détaillé pour comprendre les futurs problèmes.
"""

import re
import urllib.parse

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, default_headers
from ..state import state


DDG_URL = "https://html.duckduckgo.com/html/"
DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"

# Filtres minimaux : on garde tout sauf les pages "non pertinentes" évidentes.
EXCLUDED_DOMAINS = (
    # Annuaires déjà scrapés (éviter le doublon de requêtes).
    "pagesjaunes.fr",
    "europages.",
    # Réseaux sociaux.
    "facebook.com",
    "twitter.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "pinterest.",
    "tiktok.com",
    # Moteurs de recherche eux-mêmes.
    "google.",
    "bing.com",
    "yahoo.",
    "duckduckgo.",
    # Marketplaces / sites grand public.
    "amazon.",
    "ebay.",
    "wikipedia.org",
    "wikidata.",
)

URL_RE = re.compile(r"https?://[\w.\-]+(?:/[\w.\-/%?=&#~+]*)?", re.IGNORECASE)


class DuckDuckGoScraper(BaseScraper):
    name = "duckduckgo"

    async def run(self) -> None:
        state.init_source(self.name)
        self.log("info", f"Démarrage DuckDuckGo : {self.query!r} / {self.location!r}")

        if not self.query:
            self.log("warn", "Mot-clé vide, scraper ignoré.")
            state.update_source(self.name, status="done", message="Mot-clé manquant")
            return

        sites_collected: set[str] = set()

        async with httpx.AsyncClient(
            follow_redirects=True,
            headers=default_headers(),
            timeout=25.0,
        ) as client:
            try:
                await self._collect(client, sites_collected)
            except Exception as exc:
                self.log("error", f"Crash inattendu : {type(exc).__name__} : {exc}")
                state.update_source(self.name, status="error", message=str(exc))
                return

        for url in sites_collected:
            state.add_site(url)

        status = "stopped" if state.should_stop else "done"
        state.update_source(
            self.name,
            status=status,
            message=f"{len(sites_collected)} site(s) collecté(s) pour la suite",
        )
        self.log(
            "success",
            f"DuckDuckGo : {len(sites_collected)} site(s) web collecté(s).",
        )

    # ------------------------------------------------------------------

    async def _collect(
        self, client: httpx.AsyncClient, sites: set[str]
    ) -> None:
        base = f"{self.query} {self.location}".strip()

        # Plusieurs variantes pour maximiser la couverture.
        variants = [
            base,
            f"{base} contact",
            f"{base} entreprise",
            f"{base} email",
            f"{self.query} {self.location} France" if self.location else f"{self.query} France",
        ]

        empty_streak = 0
        for variant in variants:
            if state.should_stop:
                return
            await state.wait_if_paused()

            new = await self._search(client, variant, sites)
            self.log("info", f"Requête {variant!r} : +{new} (total : {len(sites)})")

            if new == 0:
                empty_streak += 1
                if empty_streak >= 2:
                    self.log("info", "Plusieurs requêtes sans nouveaux résultats, on arrête.")
                    break
            else:
                empty_streak = 0

            await self.polite_sleep(2.0, 4.0)

    async def _search(
        self,
        client: httpx.AsyncClient,
        query: str,
        sites: set[str],
    ) -> int:
        """
        Tente la recherche via plusieurs endpoints DuckDuckGo.
        Retourne le nombre de NOUVEAUX sites trouvés.
        """
        before = len(sites)
        html = None

        # 1) HTML version.
        html = await self._try_endpoint(client, DDG_URL, query)

        # 2) Si rien, essayer la version Lite.
        if not html or len(html) < 1000:
            self.log("info", "  → bascule sur DuckDuckGo Lite")
            html = await self._try_endpoint(client, DDG_LITE_URL, query)

        if not html:
            return 0

        self.pages_visited += 1
        state.update_source(
            self.name,
            visited_pages=self.pages_visited,
            message=f"{len(sites)} site(s) collecté(s)",
        )

        # Extraction via BeautifulSoup avec sélecteurs élargis.
        urls_found: set[str] = set()

        soup = BeautifulSoup(html, "html.parser")

        # Sélecteurs : classes connues + tous les <a> avec href.
        for a in soup.find_all("a", href=True):
            href = a["href"]
            url = self._resolve_url(href)
            if url:
                urls_found.add(url)

        # Filet de sécurité : regex sur le HTML brut pour repêcher
        # d'éventuelles URLs encodées différemment.
        for m in URL_RE.findall(html):
            urls_found.add(m)

        # Filtrage et ajout.
        for url in urls_found:
            if self._is_useful(url):
                sites.add(self._clean(url))

        return len(sites) - before

    async def _try_endpoint(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        query: str,
    ) -> str:
        """Tente une requête vers un endpoint DDG, retourne le HTML ou ''."""
        try:
            r = await client.post(
                endpoint,
                data={"q": query, "kl": "fr-fr", "kp": "-2"},
                timeout=20.0,
            )
            if r.status_code == 200:
                return r.text
            self.log("warn", f"  → HTTP {r.status_code} sur {endpoint}")
        except httpx.TimeoutException:
            self.log("warn", f"  → timeout sur {endpoint}")
        except httpx.HTTPError as exc:
            self.log("warn", f"  → {type(exc).__name__} sur {endpoint}")
        return ""

    def _resolve_url(self, href: str) -> str:
        """
        DuckDuckGo encode parfois les URLs réelles dans un paramètre `uddg`.
        On démêle ça si nécessaire.
        """
        if not href:
            return ""
        if href.startswith("//"):
            href = "https:" + href
        # Lien indirect type /l/?uddg=...
        if "uddg=" in href:
            try:
                qs = href.split("?", 1)[1]
                params = urllib.parse.parse_qs(qs)
                target = params.get("uddg", [None])[0]
                if target:
                    return urllib.parse.unquote(target)
            except Exception:
                pass
        # Lien direct http(s).
        if href.startswith("http"):
            return href
        return ""

    def _is_useful(self, url: str) -> bool:
        if not url or not url.startswith("http"):
            return False
        low = url.lower()
        return not any(d in low for d in EXCLUDED_DOMAINS)

    def _clean(self, url: str) -> str:
        try:
            parsed = urllib.parse.urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            return url
