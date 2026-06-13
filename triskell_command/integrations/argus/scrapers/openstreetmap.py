"""
Scraper OpenStreetMap (via l'API publique Overpass).

OSM contient des millions d'entreprises avec leur site web. On l'interroge
directement par bounding box.

Robustifié :
- Rotation sur plusieurs miroirs Overpass (l'API principale est souvent saturée).
- Requête simplifiée (search par tag "name").
- Logs détaillés pour comprendre les échecs.
"""

import asyncio
from typing import Optional

import httpx

from ..email_utils import is_valid_email
from .base import BaseScraper
from ..state import state


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Plusieurs miroirs Overpass : on essaye dans l'ordre, on garde le premier qui répond.
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

OSM_HEADERS = {
    # User-Agent explicite avec contact : la politique d'usage Nominatim/
    # Overpass exige un UA identifiable. « EmailsScraper » se faisait bloquer
    # (HTTP 403 sur overpass.openstreetmap.fr). Vérifié le 13/06/2026 :
    # avec cet en-tête, les miroirs répondent 200.
    "User-Agent": "TriskellProspect/1.0 (+https://triskell-studio.fr; contact@triskell-studio.fr)",
    # Sans Accept explicite, overpass-api.de renvoie HTTP 406 (Not Acceptable).
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9",
}


class OpenStreetMapScraper(BaseScraper):
    name = "openstreetmap"

    async def run(self) -> None:
        state.init_source(self.name)
        self.log("info", f"Démarrage OpenStreetMap : {self.query!r} / {self.location!r}")

        if not self.query:
            self.log("warn", "Mot-clé vide, scraper ignoré.")
            state.update_source(self.name, status="done", message="Mot-clé manquant")
            return

        sites_collected: set[str] = set()
        emails_direct = 0

        async with httpx.AsyncClient(
            follow_redirects=True,
            headers=OSM_HEADERS,
            timeout=60.0,
        ) as client:
            try:
                # 1) Géocoder la ville pour obtenir la bbox.
                self.log("info", "Géocodage de la zone…")
                bbox = await self._geocode(client)
                if not bbox:
                    self.log("warn", f"Impossible de localiser {self.location!r}.")
                    state.update_source(self.name, status="done",
                                        message="Zone géo introuvable")
                    return

                self.pages_visited += 1
                state.update_source(
                    self.name,
                    visited_pages=self.pages_visited,
                    message=f"Zone localisée, interrogation OSM…",
                )

                # 2) Requête Overpass avec rotation sur les miroirs.
                elements = await self._query_with_fallback(client, bbox)

                if elements is None:
                    self.log("error", "Tous les miroirs Overpass ont échoué.")
                    state.update_source(self.name, status="error",
                                        message="Tous les serveurs Overpass injoignables")
                    return

                self.log("info", f"{len(elements)} entité(s) avec site web trouvée(s).")

                # 3) Extraction sites + emails.
                for el in elements:
                    if state.should_stop:
                        break
                    tags = el.get("tags", {}) or {}

                    for key in ("website", "contact:website", "url"):
                        ws = tags.get(key)
                        if ws:
                            cleaned = self._clean_url(ws)
                            if cleaned:
                                sites_collected.add(cleaned)
                            break

                    for key in ("email", "contact:email"):
                        em = tags.get(key)
                        if em:
                            em = em.strip().lower()
                            if is_valid_email(em, self.include_personal):
                                if state.add_email(em, self.name):
                                    emails_direct += 1
                                    self.found_count += 1
                            break

                self.push_progress()

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
            message=f"{emails_direct} email(s) direct(s), "
                    f"{len(sites_collected)} site(s) pour la suite",
        )
        self.log(
            "success",
            f"OpenStreetMap : {emails_direct} email(s) direct(s), "
            f"{len(sites_collected)} site(s) collecté(s).",
        )

    # ------------------------------------------------------------------

    async def _geocode(self, client: httpx.AsyncClient) -> Optional[tuple]:
        if not self.location:
            # Pas de ville → on prend la France entière (approximative).
            return (41.0, -5.5, 51.5, 9.8)
        params = {
            "q": self.location,
            "format": "json",
            "limit": 1,
            "countrycodes": "fr",
        }
        try:
            r = await client.get(NOMINATIM_URL, params=params, timeout=15.0)
            if r.status_code != 200:
                self.log("warn", f"Nominatim HTTP {r.status_code}")
                return None
            data = r.json()
            if not data:
                return None
            bb = data[0].get("boundingbox")
            if bb and len(bb) == 4:
                # boundingbox = [south, north, west, east]
                s, n, w, e = float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])
                return (s, w, n, e)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            self.log("warn", f"Géocodage échoué : {type(exc).__name__}")
        return None

    async def _query_with_fallback(
        self, client: httpx.AsyncClient, bbox: tuple
    ) -> Optional[list]:
        """Essaye chaque miroir Overpass dans l'ordre."""
        s, w, n, e = bbox
        safe_query = self.query.replace('"', "").replace("\\", "").replace("\n", "")

        # Requête simple et rapide : on cherche les entités qui ont un site web
        # et dont le nom contient le mot-clé. Timeout court pour ne pas bloquer.
        overpass_ql = f"""
[out:json][timeout:25];
(
  nwr["website"]["name"~"{safe_query}",i]({s},{w},{n},{e});
  nwr["contact:website"]["name"~"{safe_query}",i]({s},{w},{n},{e});
);
out tags;
""".strip()

        for mirror in OVERPASS_MIRRORS:
            if state.should_stop:
                return None
            self.log("info", f"Tentative : {mirror}")
            try:
                r = await client.post(
                    mirror,
                    data={"data": overpass_ql},
                    timeout=60.0,
                )
                if r.status_code == 200:
                    try:
                        data = r.json()
                        return data.get("elements", [])
                    except ValueError:
                        self.log("warn", f"  → réponse non-JSON depuis {mirror}")
                        continue
                else:
                    self.log("warn", f"  → HTTP {r.status_code}")
            except httpx.TimeoutException:
                self.log("warn", f"  → timeout")
            except httpx.HTTPError as exc:
                self.log("warn", f"  → {type(exc).__name__}")

            # Petite pause avant d'essayer le miroir suivant.
            await asyncio.sleep(1.0)

        return None

    def _clean_url(self, url: str) -> Optional[str]:
        url = (url or "").strip()
        if not url:
            return None
        if not url.startswith("http"):
            url = "https://" + url.lstrip("/")
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if not parsed.netloc:
                return None
            return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            return None
