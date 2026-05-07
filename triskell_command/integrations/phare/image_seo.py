"""Image SEO — audit et optimisation des images d'un site.

Pour chaque page crawlée :
1. Liste les <img> : src, alt, dimensions estimées, format
2. Détecte les problèmes : alt manquant, format pas WebP/AVIF, taille >200ko,
   pas de loading="lazy", pas de srcset
3. Pour les alts manquants, génère un alt SEO via LLM (analyse du contexte
   page + nom du fichier)
4. Persiste dans phare_image_audits
5. Crée des actions correctives : patches HTML pour ajouter alt + lazy
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import agents, repo

logger = logging.getLogger(__name__)


USER_AGENT = "TriskellLePhare-ImageSEO/0.1"
HEAD_TIMEOUT = 10


def audit_page(url: str, html: Optional[str] = None) -> list[dict]:
    """Audit toutes les <img> d'une page. Retourne une liste de dicts."""
    if html is None:
        try:
            r = requests.get(url, timeout=15,
                             headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            html = r.text
        except requests.RequestException as exc:
            logger.warning("image_seo fetch %s: %s", url, exc)
            return []

    soup = BeautifulSoup(html, "html.parser")
    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if not src:
            continue
        full_src = urljoin(url, src)
        alt = img.get("alt", "")
        loading = img.get("loading", "")
        srcset = img.get("srcset", "")
        fmt = _guess_format(full_src)
        size_kb = _head_size(full_src)
        issues = []
        if not alt or alt.strip() == "":
            issues.append("alt_missing")
        elif len(alt) > 125:
            issues.append("alt_too_long")
        if fmt in ("jpg", "jpeg", "png") and size_kb and size_kb > 200:
            issues.append("size_too_big")
        if fmt in ("jpg", "jpeg", "png"):
            issues.append("format_outdated")
        if loading != "lazy":
            issues.append("not_lazy")
        if not srcset:
            issues.append("no_srcset")
        images.append({
            "image_src": full_src,
            "has_alt": bool(alt),
            "alt_text": alt,
            "format": fmt,
            "size_kb": size_kb,
            "is_lazy": loading == "lazy",
            "has_srcset": bool(srcset),
            "issues": issues,
        })
    return images


def _guess_format(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in ("avif", "webp", "svg", "gif", "png", "jpeg", "jpg"):
        if path.endswith("." + ext):
            return ext
    return ""


def _head_size(url: str) -> Optional[int]:
    try:
        r = requests.head(url, timeout=HEAD_TIMEOUT, allow_redirects=True,
                          headers={"User-Agent": USER_AGENT})
        if r.status_code >= 400:
            return None
        cl = r.headers.get("content-length")
        return int(cl) // 1024 if cl else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
class AltGenerator(agents.Agent):
    name = "alt_generator"
    role = """Tu es l'AltGenerator de Le Phare. Tu écris un alt SEO court
(50-100 caractères max) qui décrit objectivement une image dans le contexte
d'une page web. L'alt doit aider à la fois l'accessibilité ET le SEO.

Règles :
- 50 à 100 caractères
- Langage descriptif, pas marketing
- Pas de "image de", "photo de"
- Si la page parle d'un produit, on peut mentionner le produit

Format JSON strict : {"alt": str}"""

    def run(self, *, image_src: str, page_title: str,
            page_h1: str, app_state=None) -> str:
        prompt = f"""IMAGE : {image_src}
PAGE : {page_title}
H1 : {page_h1}

Filename de l'image : {image_src.split("/")[-1]}

Génère l'alt au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return (out.get("alt") or "")[:120] if isinstance(out, dict) else ""


# ---------------------------------------------------------------------------
def run_image_seo(site_id: str, *, max_pages: int = 20,
                  generate_alts: bool = True,
                  app_state=None) -> dict:
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    pages = repo.list_pages(site_id, limit=max_pages)
    sb = repo._sb()
    audited = 0
    images_with_issues = 0
    alts_generated = 0
    alt_gen = AltGenerator()
    patches: list[dict] = []
    for p in pages[:max_pages]:
        url = p.get("url")
        if not url:
            continue
        images = audit_page(url)
        for img in images:
            if sb is not None:
                try:
                    sb.table("phare_image_audits").insert({
                        "site_id": site_id,
                        "page_path": p.get("path") or "/",
                        **img,
                    }).execute()
                except Exception as exc:
                    logger.debug("image_audit insert: %s", exc)
            if img["issues"]:
                images_with_issues += 1
            if generate_alts and "alt_missing" in img["issues"]:
                try:
                    alt = alt_gen.run(
                        image_src=img["image_src"],
                        page_title=p.get("title") or "",
                        page_h1=p.get("h1") or "",
                        app_state=app_state,
                    )
                    if alt:
                        patches.append({
                            "page_path": p.get("path"),
                            "image_src": img["image_src"],
                            "alt": alt,
                        })
                        alts_generated += 1
                except Exception as exc:
                    logger.debug("alt gen: %s", exc)
        audited += 1

    if patches:
        repo.insert_action({
            "site_id": site_id,
            "agent": "image_seo",
            "kind": "recommandation",
            "title": (f"Image SEO : {alts_generated} alts générés, "
                      f"{images_with_issues} images à corriger"),
            "detail_md": _format_image_md(patches, images_with_issues),
            "status": "draft",
            "impact": 3, "effort": 2,
        })

    return {"ok": True, "pages_audited": audited,
            "images_with_issues": images_with_issues,
            "alts_generated": alts_generated}


def _format_image_md(patches: list[dict], total_issues: int) -> str:
    lines = [f"**{total_issues} images** présentent au moins un problème.",
             f"**{len(patches)} alts** ont été générés automatiquement :", ""]
    for p in patches[:20]:
        lines.append(f"- Page `{p['page_path']}` — `{p['image_src'].split('/')[-1]}`")
        lines.append(f"  → `alt=\"{p['alt']}\"`")
    return "\n".join(lines)
