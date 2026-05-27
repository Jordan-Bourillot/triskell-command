"""
Scraper Europages — robustifié.

Le test précédent a crashé avec :
"Page.content: Unable to retrieve content because the page is navigating
and changing the content."
→ ça veut dire qu'on appelait page.content() pendant une navigation.

Corrections :
- wait_for_load_state("networkidle") après chaque goto, avec timeout court.
- try/except autour de chaque page individuellement.
- retry rapide si page.content() échoue.
"""

import asyncio
import urllib.parse

from playwright.async_api import Page, async_playwright

from .base import BaseScraper, random_user_agent
from ..state import state


EP_BASE = "https://www.europages.fr"


class EuropagesScraper(BaseScraper):
    name = "europages"

    async def run(self) -> None:
        state.init_source(self.name)
        self.log("info", f"Démarrage Europages : {self.query!r}")

        if not self.query:
            self.log("warn", "Mot-clé vide, scraper ignoré.")
            state.update_source(self.name, status="done", message="Mot-clé manquant")
            return

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=random_user_agent(),
                locale="fr-FR",
                viewport={"width": 1366, "height": 900},
            )
            page = await context.new_page()

            try:
                await self._scrape(page)
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

        status = "stopped" if state.should_stop else "done"
        state.update_source(self.name, status=status)
        self.log("success", f"Europages terminé : {self.found_count} emails.")

    async def _scrape(self, page: Page) -> None:
        page_num = 1
        seen_fiche_urls: set[str] = set()
        empty_streak = 0

        while not self.reached_limit() and page_num <= 30:
            await state.wait_if_paused()
            if state.should_stop:
                return

            slug = urllib.parse.quote(self.query.lower().replace(" ", "-"))
            url = f"{EP_BASE}/entreprises/{slug}.html?page={page_num}"
            self.log("info", f"Liste page {page_num}")

            try:
                html = await self._safe_load(page, url)
            except Exception as exc:
                self.log("warn", f"Page {page_num} échouée : {type(exc).__name__}")
                empty_streak += 1
                if empty_streak >= 3:
                    break
                page_num += 1
                continue

            self.pages_visited += 1
            self.push_progress()

            if not html or len(html) < 2000:
                self.log("info", "Plus de résultats Europages.")
                break

            before = self.found_count
            self.consume_text(html)

            # On collecte tous les sites externes pour le scraper Sites web.
            try:
                sites = await page.evaluate(
                    """() => {
                        const out = [];
                        document.querySelectorAll('a[href^="http"]').forEach(a => {
                            const href = a.href;
                            if (!href.includes('europages.')) out.push(href);
                        });
                        return out;
                    }"""
                )
                for s in sites:
                    state.add_site(s)
            except Exception:
                pass

            # On parcourt les fiches détaillées pour des emails plus directs.
            try:
                fiche_links = await page.evaluate(
                    """() => {
                        const out = [];
                        document.querySelectorAll('a[href]').forEach(a => {
                            const href = a.getAttribute('href') || '';
                            if (href.includes('/entreprise/') || href.includes('/societe/')) {
                                out.push(href);
                            }
                        });
                        return out;
                    }"""
                )
            except Exception:
                fiche_links = []

            for link in fiche_links:
                if self.reached_limit():
                    break
                full = link if link.startswith("http") else f"{EP_BASE}{link}"
                if full in seen_fiche_urls:
                    continue
                seen_fiche_urls.add(full)
                await self._scrape_fiche(page, full)
                await self.polite_sleep(1.0, 2.5)

            # Si rien collecté sur cette page : streak.
            if self.found_count == before:
                empty_streak += 1
                if empty_streak >= 3:
                    self.log("info", "3 pages sans email, on s'arrête.")
                    break
            else:
                empty_streak = 0

            page_num += 1
            await self.polite_sleep(1.5, 3.0)

    async def _safe_load(self, page: Page, url: str) -> str:
        """Goto + attente que la page se stabilise, avec retry sur content()."""
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")

        # Attendre que les XHR finissent, max 5s.
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        # Tentative de récupération du HTML avec retry si la page navigue encore.
        for attempt in range(3):
            try:
                return await page.content()
            except Exception:
                await asyncio.sleep(0.8)
        return ""

    async def _scrape_fiche(self, page: Page, url: str) -> None:
        await state.wait_if_paused()
        if state.should_stop:
            return

        try:
            html = await self._safe_load(page, url)
        except Exception as exc:
            self.log("warn", f"Fiche inaccessible : {type(exc).__name__}")
            return

        self.pages_visited += 1
        if not html:
            return

        try:
            sites = await page.evaluate(
                """() => {
                    const out = [];
                    document.querySelectorAll('a[href^="http"]').forEach(a => {
                        const href = a.href;
                        if (!href.includes('europages.')) out.push(href);
                    });
                    return out;
                }"""
            )
            for s in sites:
                state.add_site(s)
        except Exception:
            pass

        self.consume_text(html)
        self.push_progress()
