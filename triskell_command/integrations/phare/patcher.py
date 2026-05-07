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

import html as _html
import logging
import re
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Fuzzy matching — tolère les différences typographiques mineures entre
# le texte proposé par l'agent IA et le HTML du repo.
#
# Sources de mismatch :
#   - tirets        : —, –, -, ‒ → tous équivalents
#   - apostrophes   : ', ', ' → équivalents
#   - guillemets    : ", ", ", « » → équivalents
#   - HTML entities : &amp; ⇄ &, &nbsp; ⇄ espace, etc.
#   - espaces       : multiples / sauts de ligne / tabs ⇄ 1 espace
# ---------------------------------------------------------------------
_DASH_RE  = re.compile(r"[‐‑‒–—―−-]")
_APOS_RE  = re.compile(r"[‘’ʼ´`]")
_QUOTE_RE = re.compile(r"[“”«»]")
_WS_RE    = re.compile(r"\s+")


def _normalize_for_compare(s: str) -> str:
    """Normalise un texte pour matching fuzzy (apostrophes, tirets, espaces, entities)."""
    if not s:
        return ""
    # Décode les HTML entities (&amp; → &, &nbsp; → espace, etc.)
    s = _html.unescape(s)
    # Normalise les tirets, apostrophes, guillemets
    s = _DASH_RE.sub("-", s)
    s = _APOS_RE.sub("'", s)
    s = _QUOTE_RE.sub('"', s)
    # Espaces : tabs, sauts de ligne, multiples espaces → 1 espace
    s = _WS_RE.sub(" ", s).strip()
    return s


def _fuzzy_find_exact(content: str, needle: str) -> Optional[str]:
    """Cherche `needle` dans `content` de façon tolérante.

    Retourne la sous-chaîne EXACTE de `content` qui matche (utilisable
    directement pour content.replace(exact, new)). Retourne None si pas
    trouvé.
    """
    # Fast path : match strict
    if needle and needle in content:
        return needle
    needle_norm = _normalize_for_compare(needle)
    if not needle_norm:
        return None
    # Construit une regex tolérante à partir de la version décodée du needle
    decoded = _html.unescape(needle)
    pattern = re.escape(decoded)
    # Remplace chaque caractère "famille" par sa classe équivalente
    # On opère sur le pattern échappé : \\- pour -, \\' pour ', etc.
    pattern = re.sub(r"\\?[‐-―−\-]", r"[‐-―−\\-]", pattern)
    pattern = re.sub(r"\\?[‘’ʼ'`]", r"[‘’ʼ'`]|&(apos|#39|rsquo|lsquo);", pattern)
    pattern = re.sub(r'\\?[“”«»"]',
                     r'[“”«»"]|&(quot|laquo|raquo|ldquo|rdquo);',
                     pattern)
    # Espaces flexibles
    pattern = re.sub(r"\\? ", r"(?:\\s|&nbsp;)+", pattern)
    # & → & ou &amp;
    pattern = pattern.replace(r"\&", r"(?:&|&amp;)")
    try:
        m = re.search(pattern, content)
    except re.error:
        return None
    if m:
        return m.group(0)
    return None

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
                       needle: str) -> list[tuple[Path, str]]:
    """Renvoie tous les (fichier, texte_exact) contenant `needle`.

    Le `texte_exact` peut différer de `needle` si on a fait du fuzzy
    matching (par ex. needle utilise — et le HTML utilise -). Le replace
    devra utiliser ce texte_exact.
    """
    if not needle:
        return []
    hits: list[tuple[Path, str]] = []
    for f in _walk(workdir, exts):
        try:
            content = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        exact = _fuzzy_find_exact(content, needle)
        if exact is not None:
            hits.append((f, exact))
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
                "candidates": [str(h.relative_to(root)) for h, _ in hits[:5]],
                "reason": f"{len(hits)} fichiers contiennent ce texte (ambiguïté)",
            })
            continue

        target_path, exact_old = hits[0]
        # Si fuzzy a trouvé un texte légèrement différent du `old_wrapped`,
        # on adapte le `new` pour préserver le wrap (balises) et utiliser
        # l'exact pour le replace.
        if exact_old != old_wrapped:
            # Remplace seulement la partie variable (sans le wrap) si possible
            applicable.append({
                "file": str(target_path.relative_to(root)),
                "old": exact_old,
                "new": new_wrapped if "<" in exact_old else new,
                "field": field, "rationale": rationale,
                "fuzzy": True,
            })
        else:
            applicable.append({
                "file": str(target_path.relative_to(root)),
                "old": exact_old,
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
