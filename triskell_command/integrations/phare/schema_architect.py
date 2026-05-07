"""Schema-architecte — génère du JSON-LD actif par type de page.

Détecte le type de page (Product / Article / FAQ / BreadcrumbList /
Organization / LocalBusiness) à partir du contenu crawlé, puis génère un
bloc JSON-LD prêt à insérer dans le `<head>` via le patcher.

Pas un agent LLM : la génération est déterministe et fiable. L'agent
intervient uniquement pour deviner le type quand l'auto-détection est
ambiguë.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Voix Triskell — phone/email
TRISKELL_PHONE = "+33 2 96 00 00 00"   # à confirmer avec Jordan
TRISKELL_EMAIL = "contact@triskell-studio.fr"
TRISKELL_REGION = "Bretagne"
TRISKELL_LOCALITY = "Saint-Brieuc"
TRISKELL_COUNTRY = "FR"


# ---------------------------------------------------------------------------
def detect_type(page: dict, site: dict) -> str:
    """Devine le type de page à partir des indices :
    - URL contient /produit, /pack → Product
    - URL contient /blog, /article, /guide → Article
    - URL contient /faq, /aide, /questions → FAQPage
    - URL = / → Organization (home) + LocalBusiness si site local
    - sinon Article par défaut
    """
    path = (page.get("path") or "/").lower()
    title = (page.get("title") or "").lower()
    h1 = (page.get("h1") or "").lower()

    if path == "/" or path == "":
        return "Organization"
    if any(seg in path for seg in ("/produit", "/pack", "/offre", "/abonnement")):
        return "Product"
    if any(seg in path for seg in ("/faq", "/aide", "/questions", "/help")):
        return "FAQPage"
    if any(seg in path for seg in ("/blog", "/article", "/guide", "/tuto")):
        return "Article"
    if "?" in title or "?" in h1:
        return "FAQPage"
    return "Article"


# ---------------------------------------------------------------------------
def build_organization(site: dict) -> dict:
    domain = site.get("domain", "")
    name = site.get("name") or domain.split(".")[0].title()
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": name,
        "url": f"https://{domain}/",
        "logo": f"https://{domain}/assets/logo.svg",
        "sameAs": [
            "https://triskell-studio.fr/",
            "https://github.com/Jordan-Bourillot",
        ],
        "contactPoint": [{
            "@type": "ContactPoint",
            "contactType": "customer support",
            "email": TRISKELL_EMAIL,
            "areaServed": TRISKELL_COUNTRY,
            "availableLanguage": ["French"],
        }],
    }


def build_local_business(site: dict) -> dict:
    org = build_organization(site)
    org["@type"] = "LocalBusiness"
    org["address"] = {
        "@type": "PostalAddress",
        "addressLocality": TRISKELL_LOCALITY,
        "addressRegion": TRISKELL_REGION,
        "addressCountry": TRISKELL_COUNTRY,
    }
    org["telephone"] = TRISKELL_PHONE
    return org


def build_breadcrumb(page: dict, site: dict) -> dict:
    domain = site.get("domain", "")
    path = page.get("path") or "/"
    parts = [p for p in path.split("/") if p]
    items = [{
        "@type": "ListItem", "position": 1,
        "name": "Accueil", "item": f"https://{domain}/",
    }]
    cum = ""
    for i, p in enumerate(parts, start=2):
        cum += "/" + p
        items.append({
            "@type": "ListItem", "position": i,
            "name": p.replace("-", " ").replace(".html", "").title(),
            "item": f"https://{domain}{cum}",
        })
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items,
    }


def build_article(page: dict, site: dict) -> dict:
    domain = site.get("domain", "")
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": page.get("title") or page.get("h1") or "",
        "description": page.get("meta_description") or "",
        "url": page.get("url") or f"https://{domain}{page.get('path', '/')}",
        "author": {"@type": "Organization", "name": "Triskell Studio"},
        "publisher": {
            "@type": "Organization",
            "name": "Triskell Studio",
            "logo": {"@type": "ImageObject",
                     "url": f"https://{domain}/assets/logo.svg"},
        },
        "inLanguage": "fr-FR",
    }


def build_product(page: dict, site: dict, *,
                  price: Optional[float] = None,
                  currency: str = "EUR",
                  availability: str = "https://schema.org/InStock") -> dict:
    domain = site.get("domain", "")
    return {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": page.get("title") or page.get("h1") or "",
        "description": page.get("meta_description") or "",
        "url": page.get("url") or f"https://{domain}{page.get('path', '/')}",
        "brand": {"@type": "Brand", "name": "Triskell Studio"},
        "offers": {
            "@type": "Offer",
            "url": page.get("url") or f"https://{domain}{page.get('path', '/')}",
            "priceCurrency": currency,
            "price": str(price) if price is not None else "",
            "availability": availability,
        },
    }


_QA_RE = re.compile(r"^(.+?\?)\s*\n+(.+?)(?=\n[A-Z0-9].+?\?|\Z)",
                     re.DOTALL | re.MULTILINE)


def build_faq(page: dict, site: dict, raw_text: str = "") -> dict:
    """Détecte les couples Q/R dans le texte brut et génère FAQPage.
    Heuristique : ligne se finissant par ?, suivie d'au moins un paragraphe."""
    text = raw_text or ""
    pairs = []
    for m in _QA_RE.finditer(text)[:20] if hasattr(_QA_RE.finditer(text), "__getitem__") else list(_QA_RE.finditer(text))[:20]:
        q = m.group(1).strip()
        a = m.group(2).strip()[:600]
        if 5 <= len(q) <= 200 and len(a) >= 20:
            pairs.append({"q": q, "a": a})
    # Fallback : utilise l'outline Hn pour les questions
    if not pairs:
        for h in page.get("h_outline", []):
            t = h.get("text", "")
            if t.endswith("?") and 5 <= len(t) <= 200:
                pairs.append({"q": t, "a": "Voir le détail dans l'article."})
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [{
            "@type": "Question",
            "name": p["q"],
            "acceptedAnswer": {"@type": "Answer", "text": p["a"]},
        } for p in pairs[:10]],
    }


# ---------------------------------------------------------------------------
def generate_schemas(page: dict, site: dict, *,
                     extras: Optional[dict] = None) -> dict:
    """Renvoie les schémas pertinents pour une page.

    `extras` peut contenir : price, currency, availability, raw_text, is_local.
    Ne génère que les types pertinents — ne renvoie pas n'importe quoi.

    Renvoie :
        {
          "type_detected": str,
          "schemas": [dict, ...],
          "minified_jsonld": str (concaténation prête à coller),
        }
    """
    extras = extras or {}
    page_type = detect_type(page, site)
    out: list[dict] = []

    if page_type == "Organization":
        if extras.get("is_local"):
            out.append(build_local_business(site))
        else:
            out.append(build_organization(site))
    elif page_type == "Product":
        out.append(build_product(
            page, site,
            price=extras.get("price"),
            currency=extras.get("currency", "EUR"),
            availability=extras.get("availability", "https://schema.org/InStock"),
        ))
        out.append(build_breadcrumb(page, site))
    elif page_type == "FAQPage":
        faq = build_faq(page, site, raw_text=extras.get("raw_text", ""))
        if faq.get("mainEntity"):
            out.append(faq)
        out.append(build_breadcrumb(page, site))
    else:
        out.append(build_article(page, site))
        out.append(build_breadcrumb(page, site))

    minified = "\n".join(
        f'<script type="application/ld+json">{json.dumps(s, ensure_ascii=False, separators=(",", ":"))}</script>'
        for s in out
    )
    return {
        "type_detected": page_type,
        "schemas": out,
        "minified_jsonld": minified,
    }


def patches_for_page(page: dict, site: dict, *,
                     extras: Optional[dict] = None) -> list[dict]:
    """Renvoie une liste de patches (format compatible patcher.py) qui
    remplacent (ou insèrent) le bloc JSON-LD dans le `<head>`."""
    out = generate_schemas(page, site, extras=extras)
    if not out["schemas"]:
        return []
    # On insère AVANT </head> : patcher.py gère le cas field='jsonld'
    return [{
        "field": "jsonld",
        "old": "",
        "new": out["minified_jsonld"],
        "rationale": (f"Génération auto de {len(out['schemas'])} schéma(s) "
                      f"de type {out['type_detected']}."),
    }]
