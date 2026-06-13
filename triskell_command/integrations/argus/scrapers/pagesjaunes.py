"""
Scraper Pages Jaunes — version boostée.

Améliorations vs v3 :
- Plus de pages de listing visitées (10 au lieu de 5).
- Plus de fiches visitées (200 au lieu de 80).
- Décodage plus tolérant des liens chiffrés `data-pjlb`.
- Extraction depuis d'autres attributs (data-url, data-website, href, etc.).
- Capture des URLs de redirect Pages Jaunes (qui contiennent l'URL réelle).
"""

import asyncio
import base64
import json
import re
import urllib.parse

from playwright.async_api import BrowserContext, Page, async_playwright

from .base import BaseScraper, random_user_agent
from ..state import state


PJ_BASE = "https://www.pagesjaunes.fr"
PJ_BLOCKED_DOMAINS = (
    "pagesjaunes.fr",
    "solocal.com",
    "mappy.com",
    "ooreka.fr",
    "google.",
    "facebook.com",
    "twitter.com",
    "linkedin.com",
    "instagram.com",
    "youtube.com",
    "googletagmanager",
    "doubleclick",
    "gstatic",
    "googleapis",
)

MAX_LISTING_PAGES = 10
MAX_FICHES_TOTAL = 200
PARALLEL_FICHES = 6

# Pages Jaunes utilise parfois ce type de redirect : .../redirect/?url=...
REDIRECT_URL_RE = re.compile(r"[?&]url=([^&]+)", re.IGNORECASE)


def _decode_pjlb(raw: str) -> list[str]:
    """
    Décode un attribut data-pjlb : retourne TOUTES les URLs trouvées.
    Plusieurs formats possibles selon l'âge de la fiche :
    - base64 → JSON {url: base64} → URL
    - base64 → JSON {url: clair}
    - base64 → URL directe
    - JSON direct {url: ...}
    """
    if not raw:
        return []
    urls = []

    candidates = [raw, raw.replace("-", "+").replace("_", "/")]
    seen = set()

    for c in candidates:
        if c in seen:
            continue
        seen.add(c)

        # Tentative 1 : base64 → JSON
        try:
            decoded = base64.b64decode(c + "===").decode("utf-8", errors="ignore")
            try:
                obj = json.loads(decoded)
                # Plusieurs noms de clé possibles.
                for key in ("url", "u", "link", "href", "site"):
                    val = obj.get(key) if isinstance(obj, dict) else None
                    if not val:
                        continue
                    # Si val est base64.
                    try:
                        v2 = base64.b64decode(val + "===").decode("utf-8", errors="ignore")
                        if v2.startswith("http"):
                            urls.append(v2)
                            continue
                    except Exception:
                        pass
                    if val.startswith("http"):
                        urls.append(val)
            except (json.JSONDecodeError, ValueError):
                pass
            # Si le décodé est directement une URL.
            if decoded.startswith("http"):
                urls.append(decoded)
        except Exception:
            pass

        # Tentative 2 : JSON direct (non base64).
        try:
            obj = json.loads(c)
            for key in ("url", "u", "link", "href", "site"):
                val = obj.get(key) if isinstance(obj, dict) else None
                if val and val.startswith("http"):
                    urls.append(val)
        except Exception:
            pass

    return urls


def _extract_from_redirect(url: str) -> str | None:
    """Pages Jaunes utilise des redirects type /redirect/?url=https...
    On extrait l'URL réelle de derrière."""
    m = REDIRECT_URL_RE.search(url)
    if m:
        try:
            return urllib.parse.unquote(m.group(1))
        except Exception:
            return None
    return None


def _looks_external(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    low = url.lower()
    return not any(b in low for b in PJ_BLOCKED_DOMAINS)


class PagesJaunesScraper(BaseScraper):
    name = "pagesjaunes"

    async def run(self) -> None:
        state.init_source(self.name)
        self.log("info", f"Démarrage Pages Jaunes : {self.query!r} / {self.location!r}")

        if not self.query:
            self.log("warn", "Mot-clé vide, scraper ignoré.")
            state.update_source(self.name, status="done", message="Mot-clé manquant")
            return

        sites_collected: set[str] = set()
        fiche_urls: list[str] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=random_user_agent(),
                locale="fr-FR",
                viewport={"width": 1366, "height": 900},
            )

            try:
                await self._collect_fiche_urls(context, fiche_urls)

                if not fiche_urls:
                    self.log("warn", "Aucune fiche trouvée sur Pages Jaunes.")
                else:
                    self.log("info", f"{len(fiche_urls)} fiche(s) à visiter.")
                    await self._visit_fiches_parallel(
                        context, fiche_urls[:MAX_FICHES_TOTAL], sites_collected
                    )
            except Exception as exc:
                self.log("error", f"Crash global : {exc}")
                state.update_source(self.name, status="error", message=str(exc))
            finally:
                try:
                    await context.close()
                except Exception:
                    pass
                try:
                    await browser.close()
                except Exception:
                    pass

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
            f"Pages Jaunes : {len(sites_collected)} site(s) web collecté(s) "
            f"sur {self.pages_visited} page(s) visitée(s).",
        )

    # ------------------------------------------------------------------
    # Étape 1 : pages de listing
    # ------------------------------------------------------------------

    async def _collect_fiche_urls(
        self, context: BrowserContext, fiche_urls: list[str]
    ) -> None:
        page = await context.new_page()
        seen: set[str] = set()

        try:
            for page_num in range(1, MAX_LISTING_PAGES + 1):
                await state.wait_if_paused()
                if state.should_stop:
                    return

                params = {
                    "quoiqui": self.query,
                    "ou": self.location or "France",
                    "page": page_num,
                }
                url = f"{PJ_BASE}/annuaire/chercherlespros?{urllib.parse.urlencode(params)}"
                self.log("info", f"Liste page {page_num}")

                try:
                    await page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass
                    content = await page.content()
                except Exception as exc:
                    self.log("warn", f"Listing échoué : {type(exc).__name__}")
                    break

                self.pages_visited += 1
                state.update_source(
                    self.name,
                    visited_pages=self.pages_visited,
                    message=f"Recherche en cours… {len(seen)} fiche(s)",
                )

                if "datadome" in content.lower() and len(content) < 5000:
                    self.log("error", "Datadome bloque Pages Jaunes.")
                    return

                try:
                    links = await page.evaluate(
                        """() => {
                            const out = new Set();
                            document.querySelectorAll('a[href*="/pros/"]').forEach(a => {
                                const href = a.getAttribute('href') || '';
                                if (href.startsWith('/pros/') || href.startsWith('http')) {
                                    out.add(href);
                                }
                            });
                            return Array.from(out);
                        }"""
                    )
                except Exception:
                    links = []

                new_count = 0
                for link in links or []:
                    full = link if link.startswith("http") else f"{PJ_BASE}{link}"
                    if full not in seen:
                        seen.add(full)
                        fiche_urls.append(full)
                        new_count += 1

                self.log("info", f"  → {new_count} nouvelle(s) fiche(s).")

                if new_count == 0:
                    break

                if len(fiche_urls) >= MAX_FICHES_TOTAL:
                    self.log("info", f"Limite de {MAX_FICHES_TOTAL} fiches atteinte.")
                    break

                await self.polite_sleep(1.5, 3.0)
        finally:
            try:
                await page.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Étape 2 : visite parallèle des fiches
    # ------------------------------------------------------------------

    async def _visit_fiches_parallel(
        self,
        context: BrowserContext,
        fiches: list[str],
        sites: set[str],
    ) -> None:
        sem = asyncio.Semaphore(PARALLEL_FICHES)
        progress_lock = asyncio.Lock()
        done_count = [0]
        total = len(fiches)

        async def worker(url: str) -> None:
            async with sem:
                await state.wait_if_paused()
                if state.should_stop:
                    return
                await self._scrape_fiche(context, url, sites)
                async with progress_lock:
                    done_count[0] += 1
                    self.pages_visited += 1
                    if done_count[0] % 10 == 0 or done_count[0] == total:
                        state.update_source(
                            self.name,
                            visited_pages=self.pages_visited,
                            message=f"{len(sites)} site(s) — {done_count[0]}/{total} fiche(s)",
                        )

        await asyncio.gather(*(worker(u) for u in fiches), return_exceptions=True)

    async def _scrape_fiche(
        self, context: BrowserContext, url: str, sites: set[str]
    ) -> None:
        page = await context.new_page()
        try:
            try:
                await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
            except Exception:
                return

            # Extrait les emails affichés en clair sur la fiche (Pages Jaunes
            # en expose certains). consume_text() valide + ajoute à l'état.
            # Manquait totalement → 0 mail récolté alors que les fiches sont
            # bien visitées (Europages, lui, appelle consume_text). 14/06/2026.
            try:
                html_fiche = await page.content()
                if html_fiche:
                    self.consume_text(html_fiche)
            except Exception:
                pass

            try:
                data = await page.evaluate(
                    """() => {
                        const links = [];
                        document.querySelectorAll('a[href]').forEach(a => {
                            const h = a.href || a.getAttribute('href') || '';
                            if (h) links.push(h);
                        });
                        const pjlb = [];
                        document.querySelectorAll('[data-pjlb]').forEach(el => {
                            const raw = el.getAttribute('data-pjlb');
                            if (raw) pjlb.push(raw);
                        });
                        const dataAttrs = [];
                        // Cherche tous les attributs data-* qui pourraient contenir une URL.
                        document.querySelectorAll('*').forEach(el => {
                            for (const attr of el.attributes) {
                                if (attr.name.startsWith('data-') &&
                                    attr.value &&
                                    (attr.value.includes('http') || attr.value.length > 30)) {
                                    dataAttrs.push(attr.value);
                                }
                            }
                        });
                        return { links, pjlb, dataAttrs };
                    }"""
                )
            except Exception:
                return

            # 1) Liens directs.
            for u in (data.get("links") or []):
                # Lien externe direct → on garde.
                if _looks_external(u):
                    sites.add(self._clean(u))
                # Lien Pages Jaunes type /redirect/?url=... → on extrait l'URL réelle.
                else:
                    real = _extract_from_redirect(u)
                    if real and _looks_external(real):
                        sites.add(self._clean(real))

            # 2) Attributs data-pjlb (URL chiffrée).
            for raw in (data.get("pjlb") or []):
                for decoded in _decode_pjlb(raw):
                    if _looks_external(decoded):
                        sites.add(self._clean(decoded))

            # 3) Autres attributs data-* contenant une URL en clair.
            for val in (data.get("dataAttrs") or []):
                if val.startswith("http") and _looks_external(val):
                    sites.add(self._clean(val))
        finally:
            try:
                await page.close()
            except Exception:
                pass

    def _clean(self, url: str) -> str:
        try:
            parsed = urllib.parse.urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            return url
