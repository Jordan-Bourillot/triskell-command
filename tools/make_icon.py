"""Génère l'icône Triskell Command (.ico multi-tailles) à partir du vrai logo.

Sources :
- assets/triskell_mark_square.png (variante carrée du logo officiel Triskell)
- ou fallback : génération vectorielle 3 spirales

Sortie :
- assets/triskell.ico (multi-tailles 16/24/32/48/64/128/256)
- assets/triskell.png (512×512 pour usage générique)

Usage : python tools/make_icon.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


HERE = Path(__file__).parent
ASSETS = HERE.parent / "assets"


def make_from_official_logo() -> Image.Image | None:
    """Si le logo officiel est dispo, on le réutilise comme base."""
    candidate = ASSETS / "triskell_mark_square.png"
    if not candidate.exists():
        return None
    img = Image.open(candidate).convert("RGBA")
    # Resize en 256×256 propre
    img = img.resize((256, 256), Image.LANCZOS)
    return img


def make_vectorial(size: int = 256) -> Image.Image:
    """Génère un triskell vectoriel : 3 spirales/disques colorés sur fond sombre.

    Inspiré du logo officiel triskell-studio.fr (3 spirales 120° d'écart).
    """
    INDIGO = (99, 102, 241, 255)
    VIOLET = (167, 139, 250, 255)
    ORANGE = (249, 115, 22, 255)
    GOLD = (212, 179, 90, 255)
    BG = (15, 18, 24, 255)
    HALO = (212, 179, 90, 60)

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = size // 2

    # Cercle de fond rond (ombre légère)
    r_outer = size * 0.46
    d.ellipse(
        (cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer),
        fill=BG,
    )

    # 3 disques colorés en triade équilibrée (-90°, 30°, 150°)
    colors = [INDIGO, VIOLET, ORANGE]
    disc_r = size * 0.20
    arm_r = size * 0.22

    for i, color in enumerate(colors):
        angle = math.radians(-90 + i * 120)
        x = cx + arm_r * math.cos(angle)
        y = cy + arm_r * math.sin(angle)
        # Disque
        d.ellipse(
            (x - disc_r, y - disc_r, x + disc_r, y + disc_r),
            fill=color,
        )

    # Halo or léger autour (signature Triskell)
    halo_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    h = ImageDraw.Draw(halo_layer)
    h.ellipse(
        (cx - r_outer - 4, cy - r_outer - 4,
         cx + r_outer + 4, cy + r_outer + 4),
        outline=GOLD,
        width=2,
    )
    halo_layer = halo_layer.filter(ImageFilter.GaussianBlur(2))
    img = Image.alpha_composite(img, halo_layer)
    d = ImageDraw.Draw(img)

    # Petit point central or signature
    center_r = size * 0.05
    d.ellipse(
        (cx - center_r, cy - center_r, cx + center_r, cy + center_r),
        fill=GOLD,
    )

    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)

    base = make_from_official_logo()
    if base is None:
        print("⚠ Logo officiel introuvable — génération vectorielle fallback")
        base = make_vectorial(256)
    else:
        print("✓ Logo officiel détecté — utilisation comme base")

    ico_path = ASSETS / "triskell.ico"
    base.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
               (128, 128), (256, 256)],
    )
    print(f"✓ Icône générée : {ico_path}")

    png_path = ASSETS / "triskell.png"
    if base.size != (512, 512):
        # Pour le PNG haute résolution, on utilise la variante non-square si dispo,
        # ou on régénère en vectorial 512.
        big = make_from_official_logo()
        if big is None or big.size != (512, 512):
            # On reprend l'image officielle si possible, on l'upscale pas (qualité)
            big = make_vectorial(512)
        big.save(png_path, format="PNG")
    else:
        base.save(png_path, format="PNG")
    print(f"✓ PNG 512 généré : {png_path}")


if __name__ == "__main__":
    main()
