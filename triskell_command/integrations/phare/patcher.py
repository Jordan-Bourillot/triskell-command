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


# ---------------------------------------------------------------------
# Patches de l'Exécuteur (bouton « OK, fais-le » d'une recommandation).
# Différence avec localize_patches : chaque patch vise une PAGE précise
# (page_path), ce qui permet de désambiguïser quand le même texte vit
# dans plusieurs fichiers, et d'insérer dans le <head> d'une page donnée.
# ---------------------------------------------------------------------
_SAFE_NEW_FILE_EXTS = (".xml", ".txt", ".html", ".htm")


def _norm_page_path(p: str) -> str:
    """Normalise un chemin de page fourni par l'IA : « /index.html » → « / »,
    « /demo.html » → « /demo », « demo » → « /demo ». Les agents glissent
    parfois un nom de fichier à la place du chemin d'URL — on rattrape."""
    p = (p or "/").split("?")[0].split("#")[0].strip().lower()
    if not p.startswith("/"):
        p = "/" + p
    for suf in (".html", ".htm"):
        if p.endswith(suf):
            p = p[: -len(suf)]
    if p.endswith("/index"):
        p = p[: -len("/index")] or "/"
    if p != "/" and p.endswith("/"):
        p = p[:-1]
    return p or "/"


def _files_matching_page(root: Path, exts: tuple[str, ...],
                         page_path: str, page_title: str = "") -> list[Path]:
    """Fichiers source candidats pour une page du site (par convention
    de nommage, puis par son <title> actuel)."""
    rel = _norm_page_path(page_path).strip("/").lower()
    wanted_rel = ({"index.html", "index.htm"} if not rel
                  else {f"{rel}.html", f"{rel}.htm",
                        f"{rel}/index.html", f"{rel}/index.htm"})
    by_name: list[Path] = []
    for f in _walk(root, exts):
        relstr = str(f.relative_to(root)).replace("\\", "/").lower()
        if relstr in wanted_rel:
            by_name.append(f)
    if len(by_name) == 1:
        return by_name
    if page_title:
        hits = _find_unique_match(root, exts, page_title)
        files = [h for h, _ in hits]
        if len(files) == 1:
            return files
        inter = [c for c in by_name if c in files]
        if len(inter) == 1:
            return inter
    return by_name


def localize_executor_patches(workdir: str, stack: str,
                              exec_patches: list[dict],
                              pages: Optional[list[dict]] = None) -> dict:
    """Convertit les patches de l'agent Exécuteur en patches fichier.

    Formats d'entrée (cf. agents.Executeur) :
      - {field: title|meta_description|h1, page_path, old, new}
      - {field: head_insert, page_path, new}   → insertion avant </head>
      - {field: new_file, file, new}           → création de fichier

    Renvoie {"applicable": [...], "needs_review": [...]} — même contrat
    que localize_patches, consommable par git_pipeline.apply_and_open_pr.
    """
    root = Path(workdir)
    exts = EXTENSIONS_BY_STACK.get(stack, EXTENSIONS_BY_STACK["any"])
    titles_by_path = {_norm_page_path(p.get("path") or "/"): (p.get("title") or "")
                      for p in (pages or [])}

    applicable: list[dict] = []
    needs_review: list[dict] = []

    for p in exec_patches or []:
        field = (p.get("field") or "").lower()
        page_path = _norm_page_path(p.get("page_path") or "/")
        old = p.get("old") or ""
        new = p.get("new") or ""
        page_title = titles_by_path.get(page_path, "")

        if field == "new_file":
            rel = (p.get("file") or "").replace("\\", "/").strip().lstrip("/")
            if (not rel or ".." in rel
                    or not rel.lower().endswith(_SAFE_NEW_FILE_EXTS)):
                needs_review.append({"field": field, "old": "", "new": new[:200],
                                     "candidates": [rel],
                                     "reason": "chemin de fichier refusé"})
                continue
            if (root / rel).exists():
                needs_review.append({"field": field, "old": "", "new": new[:200],
                                     "candidates": [rel],
                                     "reason": "le fichier existe déjà"})
                continue
            applicable.append({"file": rel, "old": "", "new": new,
                               "field": field, "create": True,
                               "rationale": p.get("rationale") or ""})
            continue

        if field == "head_insert":
            files = _files_matching_page(root, exts, page_path, page_title)
            files = [f for f in files
                     if "</head>" in _read_text_safe(f)]
            if len(files) != 1:
                needs_review.append({
                    "field": field, "old": "", "new": new[:200],
                    "candidates": [str(f.relative_to(root)) for f in files[:5]],
                    "reason": (f"{len(files)} fichiers possibles pour la page "
                               f"{page_path}"),
                })
                continue
            if not new.strip():
                needs_review.append({"field": field, "old": "", "new": "",
                                     "candidates": [], "reason": "patch vide"})
                continue
            target = files[0]
            rel = str(target.relative_to(root))
            content = _read_text_safe(target)
            remaining = new
            # Balises uniques : si la page a DÉJÀ un <title> ou une meta
            # description et que l'insertion en apporte, on REMPLACE
            # l'existante au lieu d'empiler un doublon (vécu le 12/06/2026 :
            # double <title> sur pixel-pros.fr — le premier gagnait, le
            # changement restait invisible).
            for unique_field, rx in (
                ("title",
                 re.compile(r"<title>.*?</title>", re.IGNORECASE | re.DOTALL)),
                ("meta_description",
                 re.compile(r"<meta\s[^>]*name=[\"']description[\"'][^>]*>",
                            re.IGNORECASE)),
            ):
                m_new = rx.search(remaining)
                if not m_new:
                    continue
                m_old = rx.search(content)
                if not m_old:
                    continue   # la balise n'existe pas : l'insertion est saine
                applicable.append({
                    "file": rel, "old": m_old.group(0), "new": m_new.group(0),
                    "field": unique_field,
                    "rationale": p.get("rationale") or "",
                })
                remaining = remaining.replace(m_new.group(0), "", 1)
            remaining = remaining.strip()
            if remaining:
                applicable.append({
                    "file": rel,
                    "old": "</head>",
                    "new": remaining + "\n</head>",
                    "field": field, "rationale": p.get("rationale") or "",
                })
            continue

        # title / meta_description / h1 → flux classique, désambiguïsé
        # par la page visée quand plusieurs fichiers contiennent le texte.
        old_wrapped, new_wrapped = _build_replacement(field, old, new)
        hits = _find_unique_match(root, exts, old_wrapped)
        if not hits and old and old != old_wrapped:
            hits = _find_unique_match(root, exts, old)
            if hits:
                old_wrapped, new_wrapped = old, new
        if len(hits) > 1:
            page_files = set(_files_matching_page(root, exts, page_path, page_title))
            narrowed = [(f, e) for f, e in hits if f in page_files]
            if len(narrowed) == 1:
                hits = narrowed
        if not hits:
            needs_review.append({"field": field, "old": old, "new": new,
                                 "candidates": [],
                                 "reason": "texte actuel introuvable dans le code"})
            continue
        if len(hits) > 1:
            needs_review.append({
                "field": field, "old": old, "new": new,
                "candidates": [str(h.relative_to(root)) for h, _ in hits[:5]],
                "reason": f"{len(hits)} fichiers contiennent ce texte (ambiguïté)",
            })
            continue
        target_path, exact_old = hits[0]
        applicable.append({
            "file": str(target_path.relative_to(root)),
            "old": exact_old,
            "new": new_wrapped if "<" in exact_old else new,
            "field": field, "rationale": p.get("rationale") or "",
        })

    return {"applicable": applicable, "needs_review": needs_review}


def _read_text_safe(f: Path) -> str:
    try:
        return f.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


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
