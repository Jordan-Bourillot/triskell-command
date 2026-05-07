"""Normalise les logos des produits Triskell pour la sidebar web.

Pour chaque logo source (depuis Triskell 0 - Lanceur/assets/apps/) :
  1. Convertit en RGBA si RGB.
  2. Si le fond est opaque (couleur uniforme dans les coins), le rend
     transparent avec tolérance.
  3. Détecte le bounding box du contenu non-transparent et recadre serré.
  4. Ajoute un padding uniforme (8 % du côté max).
  5. Place dans une boîte carrée 256×256 transparente, contenu centré
     (resize avec préservation du ratio).
  6. Sauve dans triskell_command/web/ui/assets/apps/<id>.png.

Le SVG eliks-studio est juste copié tel quel (déjà transparent, vectoriel).

Usage : `py scripts/normalize_app_logos.py`
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageChops


# Configuration
SRC = Path("C:/Users/jorda/OneDrive/Bureau/Triskell Studio/Triskell 0 - Lanceur/assets/apps")
DEST = Path(__file__).resolve().parent.parent / "triskell_command" / "web" / "ui" / "assets" / "apps"
TARGET_SIZE = 256                # Taille finale carrée (HiDPI ready)
PAD_RATIO = 0.08                 # Padding = 8 % du côté max
BG_TOLERANCE = 18                # Tolérance pour détecter le fond uniforme

# Mapping id → fichier source. Garde le même id que dans apps.json.
LOGOS = {
    "suite-des-heros":      "suite-des-heros.png",
    "delinote":             "delinote.png",
    "studio-pdf":           "studio-pdf.png",
    "bobeez":               "bobeez.png",
    "pirate-life-mail":     "pirate-life-mail.png",
    "obelisk":              "le-denicheur.png",   # ex Le Dénicheur, marque actuelle Obelisk
    "triskell-studio-sites":"triskell-studio-sites.png",
    "eliks-studio":         "eliks-studio.svg",   # SVG, copié tel quel
    "alphacast":            "alphacast.png",
    "alphabeast":           "alphabeast.png",
    "alphapitch":           "alphapitch.png",
    "outils-batiment":      "outils-batiment.png",
    "pack-electricien-pro": "pack-electricien-pro.png",
    "teddy-mail":           "teddy-mail.png",
}


def make_bg_transparent(img: Image.Image) -> Image.Image:
    """Si le fond du PNG est uniforme (détecté dans les coins),
    le rend transparent avec une tolérance."""
    img = img.convert("RGBA")
    pixels = img.load()
    w, h = img.size

    # Échantillonne les 4 coins
    corners = [pixels[0, 0], pixels[w-1, 0], pixels[0, h-1], pixels[w-1, h-1]]
    # Si tous très proches (variance < tolérance), on considère que c'est le fond
    rs = [c[0] for c in corners]
    gs = [c[1] for c in corners]
    bs = [c[2] for c in corners]
    if (max(rs) - min(rs) > BG_TOLERANCE
        or max(gs) - min(gs) > BG_TOLERANCE
        or max(bs) - min(bs) > BG_TOLERANCE):
        # Pas de fond uniforme → on suppose que les pixels transparents
        # le sont déjà via le canal alpha
        return img

    bg = (sum(rs)//4, sum(gs)//4, sum(bs)//4)
    # Rend transparent tout pixel proche du fond
    new_pixels = []
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if (abs(r - bg[0]) <= BG_TOLERANCE
                and abs(g - bg[1]) <= BG_TOLERANCE
                and abs(b - bg[2]) <= BG_TOLERANCE):
                new_pixels.append((r, g, b, 0))
            else:
                new_pixels.append((r, g, b, a))
    out = Image.new("RGBA", (w, h))
    out.putdata(new_pixels)
    return out


def trim_to_content(img: Image.Image) -> Image.Image:
    """Recadre serré au bounding box du contenu non-transparent."""
    img = img.convert("RGBA")
    # Le bbox de l'alpha donne le contenu visible
    alpha = img.split()[-1]
    bbox = alpha.getbbox()
    if bbox is None:
        return img
    return img.crop(bbox)


def normalize_to_square(img: Image.Image, size: int = TARGET_SIZE,
                         pad_ratio: float = PAD_RATIO) -> Image.Image:
    """Place le contenu dans une boîte carrée transparente, centré,
    avec un padding uniforme."""
    img = img.convert("RGBA")
    w, h = img.size
    # Échelle pour faire entrer le contenu dans (size - 2*pad)
    pad = int(size * pad_ratio)
    inner = size - 2 * pad
    scale = min(inner / w, inner / h)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    paste_x = (size - new_w) // 2
    paste_y = (size - new_h) // 2
    out.paste(resized, (paste_x, paste_y), resized)
    return out


def process_one(slug: str, src_filename: str) -> str:
    src_path = SRC / src_filename
    if not src_path.exists():
        return f"  [WARN] {slug}: source introuvable ({src_filename})"

    # Cas SVG : copie directe
    if src_filename.lower().endswith(".svg"):
        dst_path = DEST / f"{slug}.svg"
        shutil.copy(src_path, dst_path)
        return f"  [OK]{slug}: SVG copié"

    img = Image.open(src_path)
    img = make_bg_transparent(img)
    img = trim_to_content(img)
    img = normalize_to_square(img)
    dst_path = DEST / f"{slug}.png"
    img.save(dst_path, "PNG", optimize=True)
    return f"  [OK]{slug}: {img.size[0]}×{img.size[1]} → {dst_path.name}"


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    print(f"Source : {SRC}")
    print(f"Sortie : {DEST}")
    print()
    print("Normalisation des logos…")
    for slug, src_name in LOGOS.items():
        print(process_one(slug, src_name))
    print()
    print(f"Terminé. {len(LOGOS)} logos traités.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
