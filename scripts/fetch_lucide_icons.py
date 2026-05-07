"""Télécharge les SVG Lucide nécessaires à Triskell Command.

Source : https://github.com/lucide-icons/lucide (MIT).

Lit `ICON_MAP` dans `triskell_command/widgets/icons_lucide.py` pour
savoir quoi télécharger. Skip les fichiers déjà présents.

Usage :
    python scripts/fetch_lucide_icons.py
    python scripts/fetch_lucide_icons.py --force   # re-télécharge tout
    python scripts/fetch_lucide_icons.py --extra chevron-down,grid

Dépendances : requests OU urllib stdlib (fallback).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Permet de lancer le script depuis n'importe où
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from triskell_command.widgets.icons_lucide import ICON_MAP  # noqa: E402

LUCIDE_BASE = "https://raw.githubusercontent.com/lucide-icons/lucide/main/icons"
TARGET_DIR = ROOT / "assets" / "icons_lucide"


def fetch(url: str) -> bytes:
    """Télécharge un fichier. Préfère requests, fallback urllib."""
    try:
        import requests
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.content
    except ImportError:
        import urllib.request
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.read()


def download_one(lucide_name: str, *, force: bool) -> tuple[str, str]:
    """Télécharge un seul SVG. Retourne (status, message)."""
    target = TARGET_DIR / f"{lucide_name}.svg"
    if target.exists() and not force:
        return "skip", f"déjà présent : {target.name}"
    url = f"{LUCIDE_BASE}/{lucide_name}.svg"
    try:
        content = fetch(url)
    except Exception as exc:
        return "error", f"{lucide_name} : {exc}"
    if not content.startswith(b"<svg") and b"<svg" not in content[:200]:
        return "error", f"{lucide_name} : réponse pas un SVG ({len(content)} octets)"
    target.write_bytes(content)
    return "ok", f"{target.name} ({len(content)} octets)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="re-télécharge même si le fichier existe")
    parser.add_argument("--extra", default="",
                        help="icônes Lucide supplémentaires (séparées par virgule)")
    args = parser.parse_args()

    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    needed = set(ICON_MAP.values())
    if args.extra:
        needed |= {n.strip() for n in args.extra.split(",") if n.strip()}

    print(f"⮞ Cible : {TARGET_DIR}")
    print(f"⮞ {len(needed)} icônes à vérifier")
    print()

    counts = {"ok": 0, "skip": 0, "error": 0}
    errors: list[str] = []
    for name in sorted(needed):
        status, msg = download_one(name, force=args.force)
        counts[status] += 1
        prefix = {"ok": "✓", "skip": "·", "error": "✗"}[status]
        print(f"  {prefix} {msg}")
        if status == "error":
            errors.append(msg)

    print()
    print(f"⮞ Bilan : {counts['ok']} téléchargées · {counts['skip']} déjà là · "
          f"{counts['error']} en erreur")
    if errors:
        print("\n⚠ Erreurs :")
        for e in errors:
            print(f"  - {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
