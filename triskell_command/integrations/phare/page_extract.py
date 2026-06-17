"""Lecture EN DIRECT d'une page pour les corrections qui ont besoin du corps
de la page (pas seulement title/meta/H1 du crawl).

Deux usages, demandés par Jordan le 17/06/2026 (« rends le robot capable de le
faire seul ») :
  - FAQ structurée : recopier MOT POUR MOT les vraies questions-réponses déjà
    visibles sur la page → données structurées FAQPage (Google peut les
    afficher en grand). On n'invente JAMAIS de Q/R (sinon pénalité Google).
  - Précharger / prioriser l'image principale : trouver la vraie grande image
    en haut de page pour dire au navigateur de la charger en priorité.

Tout est best-effort et CONSERVATEUR : si la page n'est pas lisible ou si la
structure n'est pas nette, on ne renvoie rien (le robot dira « à voir
ensemble » plutôt que de fabriquer n'importe quoi).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = "TriskellLePhare-PageExtract/0.1"
_TIMEOUT = 15

# Images qui ne sont PAS le visuel principal (icônes, pixels…)
_NON_HERO = ("favicon", "apple-touch-icon", "apple-icon", "android-chrome",
             "mstile", "sprite", "spacer", "blank.", "1x1", "pixel.gif",
             "logo", "icon")


def fetch_page(url: str) -> Optional[str]:
    """Récupère le HTML d'une page. None si injoignable."""
    try:
        r = requests.get(url, timeout=_TIMEOUT,
                         headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        return r.text
    except requests.RequestException as exc:
        logger.info("page_extract.fetch_page %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# FAQ
# ---------------------------------------------------------------------------
def extract_faq_pairs(html: str) -> list[dict]:
    """Questions-réponses VISIBLES de la page, recopiées telles quelles.

    Cherche d'abord une section FAQ (`id=faq` / `class=faq`), sinon des
    `<details class="faq-item">` / `<details>` n'importe où. Ne garde une paire
    que si la question finit par « ? » et que la réponse est non triviale —
    pour ne jamais fabriquer une fausse FAQ."""
    try:
        soup = BeautifulSoup(html or "", "html.parser")
    except Exception:
        return []
    scope = (soup.find(id=re.compile(r"faq", re.I))
             or soup.find(class_=re.compile(r"faq", re.I))
             or soup)
    items = scope.find_all(class_=re.compile(r"faq-item", re.I))
    if not items:
        items = scope.find_all("details")
    pairs: list[dict] = []
    seen = set()
    for item in items:
        summ = item.find("summary")
        if summ is not None:
            q = summ.get_text(" ", strip=True)
            summ.extract()                 # retire la question du bloc
            a = item.get_text(" ", strip=True)
        else:
            # paire « titre ? » + paragraphe suivant
            head = item.find(re.compile(r"^h[2-5]$"))
            if head is None:
                continue
            q = head.get_text(" ", strip=True)
            sib = head.find_next_sibling()
            a = sib.get_text(" ", strip=True) if sib else ""
        q = re.sub(r"\s+", " ", q).strip()
        a = re.sub(r"\s+", " ", a).strip()
        if not q or not a or "?" not in q or len(a) < 15:
            continue
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        pairs.append({"q": q, "a": a})
    return pairs[:12]


def has_faq_schema(html: str) -> bool:
    """La page a-t-elle DÉJÀ des données structurées FAQ ?"""
    return bool(re.search(r"FAQPage", html or "", re.I))


def build_faqpage_jsonld(pairs: list[dict]) -> str:
    """Construit le bloc FAQPage à partir des paires (recopiées mot pour mot)."""
    data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": p["q"],
             "acceptedAnswer": {"@type": "Answer", "text": p["a"]}}
            for p in pairs
        ],
    }
    return ('<script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False) + "</script>")


# ---------------------------------------------------------------------------
# Image principale (hero) — préchargement / priorité
# ---------------------------------------------------------------------------
def _is_non_hero(src: str) -> bool:
    s = (src or "").lower()
    return (not s) or s.startswith("data:") or any(h in s for h in _NON_HERO)


def find_hero_image(html: str, page_url: str) -> Optional[str]:
    """L'URL de la grande image affichée en premier (best-effort)."""
    try:
        soup = BeautifulSoup(html or "", "html.parser")
    except Exception:
        return None
    # 1) la 1re vraie <img> du corps (hors icônes/logos/pixels)
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not _is_non_hero(src):
            return urljoin(page_url, src)
    # 2) repli : og:image
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        return urljoin(page_url, og["content"])
    return None


def already_preloads(html: str, image_url: str) -> bool:
    """La page précharge-t-elle déjà cette image ?"""
    name = (urlparse(image_url).path or "").split("/")[-1]
    return bool(name and re.search(
        r'rel=["\']preload["\'][^>]*' + re.escape(name), html or "", re.I))


def preload_link(image_url: str) -> str:
    """Balise de préchargement de l'image (chemin relatif au domaine)."""
    rel = urlparse(image_url).path or image_url
    return f'<link rel="preload" as="image" href="{rel}">'
