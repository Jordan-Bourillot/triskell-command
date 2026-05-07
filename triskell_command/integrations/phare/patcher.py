"""Convertit les patches abstraits de l'Optimiseur On-Page en patches fichier.

L'Optimiseur renvoie des modifications de balises HTML sans savoir où elles
vivent dans le code source (Astro `.astro`, Next `.tsx`, HTML pur, etc.).
Ce module clone le repo, parcourt les fichiers candidats, repère les
occurrences uniques par grep et produit des patches de remplacement
texte-à-texte applicables par `git_pipeline.apply_and_open_pr`.

Stratégie de localisation :
  - title         → grep `<title>...</title>` ou `title:` (frontmatter Astro)
  - meta_desc     → grep `<meta name="description"`
  - h1/h2         → grep `<h1>...</h1>` ou variantes JSX
  - alt           → grep `alt="..."` adjacent à `src` correspondant
  - jsonld        → ajout en bas du `<head>` du layout principal

Si la localisation est ambiguë (>1 fichier candidat), on liste tout dans
`needs_review` au lieu de pousser un patch foireux.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# Extensions où chercher les patches (par stack)
EXTENSIONS_BY_STACK = {
    "astro":  (".astro", ".html", ".md", ".mdx"),
    "next":   (".tsx", ".jsx", ".html", ".mdx"),
    "html":   (".html", ".htm"),
    "any":    (".astro", ".tsx", ".jsx", ".html", ".htm", ".md", ".mdx"),
}

# Dossiers à ignorer
IGNORE_DIRS = {"node_modules", ".git", "dist", "build", ".next", ".astro",
               "public", ".cache"}


def _walk(root: Path, exts: tuple[str, ...]) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in IGNORE_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in exts:
            yield p


def _find_unique_match(workdir: Path, exts: tuple[str, ...],
                       needle: str) -> list[Path]:
    """Renvoie tous les fichiers contenant `needle` exactement."""
    if not needle:
        return []
    hits: list[Path] = []
    for f in _walk(workdir, exts):
        try:
            content = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if needle in content:
            hits.append(f)
    return hits


def _build_replacement(field: str, old: str, new: str) -> tuple[str, str]:
    """Construit (old_text, new_text) pour replace direct dans le fichier.

    Pour title/meta/h1, on essaie d'abord la version exacte avec balise
    autour. Si l'old fourni par l'agent est déjà la balise complète,
    on la garde telle quelle.
    """
    if "<" in old and ">" in old:
        return old, new
    # Wraps usuels
    wraps = {
        "title":            (f"<title>{old}</title>",
                             f"<title>{new}</title>"),
        "meta_description": (f'content="{old}"',
                             f'content="{new}"'),
        "h1":               (f"<h1>{old}</h1>",
                             f"<h1>{new}</h1>"),
        "h2":               (f"<h2>{old}</h2>",
                             f"<h2>{new}</h2>"),
    }
    return wraps.get(field, (old, new))


def localize_patches(workdir: str, stack: str,
                     agent_patches: list[dict]) -> dict:
    """Convertit les patches Optimiseur abstraits en patches fichier.

    Renvoie :
        {
          "applicable": [{"file": str, "old": str, "new": str,
                          "field": str, "rationale": str}],
          "needs_review": [{"field": str, "old": str, "new": str,
                            "candidates": [str], "reason": str}],
        }
    """
    root = Path(workdir)
    exts = EXTENSIONS_BY_STACK.get(stack, EXTENSIONS_BY_STACK["any"])

    applicable: list[dict] = []
    needs_review: list[dict] = []

    for p in agent_patches:
        field = (p.get("field") or "").lower()
        old = p.get("old") or ""
        new = p.get("new") or ""
        rationale = p.get("rationale") or ""

        if field == "jsonld":
            # Cas particulier : ajout dans le <head> du layout principal
            layout_files = _find_layout_candidates(root, exts)
            if not layout_files:
                needs_review.append({"field": field, "old": old, "new": new,
                                      "candidates": [], "reason": "aucun layout détecté"})
                continue
            if len(layout_files) > 1:
                needs_review.append({
                    "field": field, "old": old, "new": new,
                    "candidates": [str(f.relative_to(root)) for f in layout_files],
                    "reason": f"{len(layout_files)} layouts possibles",
                })
                continue
            target = layout_files[0]
            applicable.append({
                "file": str(target.relative_to(root)),
                "old": "</head>",
                "new": f"<script type=\"application/ld+json\">{new}</script>\n</head>",
                "field": field, "rationale": rationale,
            })
            continue

        old_wrapped, new_wrapped = _build_replacement(field, old, new)
        hits = _find_unique_match(root, exts, old_wrapped)

        if not hits and old != old_wrapped:
            # Tente la version brute
            hits = _find_unique_match(root, exts, old)
            if hits:
                old_wrapped, new_wrapped = old, new

        if not hits:
            needs_review.append({
                "field": field, "old": old, "new": new,
                "candidates": [],
                "reason": "old introuvable dans le repo",
            })
            continue

        if len(hits) > 1:
            needs_review.append({
                "field": field, "old": old, "new": new,
                "candidates": [str(h.relative_to(root)) for h in hits[:5]],
                "reason": f"{len(hits)} fichiers contiennent ce texte (ambiguïté)",
            })
            continue

        target = hits[0]
        applicable.append({
            "file": str(target.relative_to(root)),
            "old": old_wrapped,
            "new": new_wrapped,
            "field": field, "rationale": rationale,
        })

    return {"applicable": applicable, "needs_review": needs_review}


def _find_layout_candidates(root: Path, exts: tuple[str, ...]) -> list[Path]:
    """Cherche le(s) layout(s) principaux (Astro Layout.astro, Next layout.tsx,
    fichiers HTML avec </head>).
    """
    candidates: list[Path] = []
    name_hints = ("layout", "Layout", "_app", "BaseLayout", "Document")
    for f in _walk(root, exts):
        if not any(h in f.stem for h in name_hints):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "</head>" in text:
            candidates.append(f)
    if candidates:
        return candidates
    # Fallback : tout fichier avec </head> et contenant "<title>"
    for f in _walk(root, exts):
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "</head>" in text and "<title>" in text:
            candidates.append(f)
    return candidates
