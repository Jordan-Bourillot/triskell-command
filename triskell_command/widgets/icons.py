"""Génération à la volée d'icônes vectorielles propres pour la sidebar
et les boutons. Stratégie : PIL pur, traits fins, couleur dynamique selon
l'état (muted / actif / hover).

Les icônes sont monochromes — la couleur est passée à chaque appel pour
qu'elles s'adaptent au thème (clair/sombre) et à l'état (actif=or, normal=gris).
"""

from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageDraw

import customtkinter as ctk


# Cache CTkImage par (name, color, size) pour éviter de redessiner à chaque frame
_CACHE: dict[tuple, ctk.CTkImage] = {}


def _hex_to_rgba(hex_str: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return (r, g, b, alpha)


# ---------------------------------------------------------------------------
# Primitives de dessin (traits fins, qualité supérieure via supersampling 2x)
# ---------------------------------------------------------------------------
def _supersampled(draw_fn, size: int, color: tuple) -> Image.Image:
    """Dessine en 2x puis downsample LANCZOS pour avoir des contours lisses."""
    factor = 4
    big = Image.new("RGBA", (size * factor, size * factor), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    draw_fn(d, size * factor, color)
    return big.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Icônes individuelles
# ---------------------------------------------------------------------------
def _draw_search(d, s, color):
    # loupe
    r = s * 0.30
    cx, cy = s * 0.42, s * 0.42
    w = max(2, s // 12)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=w)
    # poignée
    d.line(
        (cx + r * 0.72, cy + r * 0.72, s * 0.84, s * 0.84),
        fill=color, width=w,
    )


def _draw_pen(d, s, color):
    # crayon en diagonale
    w = max(2, s // 12)
    # corps
    d.line((s * 0.20, s * 0.78, s * 0.74, s * 0.24), fill=color, width=w)
    # pointe
    d.polygon(
        [(s * 0.18, s * 0.76), (s * 0.18, s * 0.84), (s * 0.26, s * 0.84)],
        fill=color,
    )
    # gomme arrière
    d.line((s * 0.74, s * 0.24, s * 0.86, s * 0.36), fill=color, width=w)


def _draw_doc(d, s, color):
    # document avec coin replié + 3 lignes
    w = max(2, s // 14)
    margin = s * 0.20
    fold = s * 0.34
    pts = [
        (margin, s * 0.18),
        (margin + fold, s * 0.18),
        (s - margin, s * 0.18 + fold),
        (s - margin, s * 0.86),
        (margin, s * 0.86),
    ]
    d.line(pts + [pts[0]], fill=color, width=w, joint="curve")
    # coin du fold
    d.line(
        (margin + fold, s * 0.18, margin + fold, s * 0.18 + fold),
        fill=color, width=w,
    )
    d.line(
        (margin + fold, s * 0.18 + fold, s - margin, s * 0.18 + fold),
        fill=color, width=w,
    )
    # 3 lignes texte
    for i, y in enumerate([0.62, 0.72, 0.82]):
        x_end = s * (0.74 if i < 2 else 0.62)
        d.line((s * 0.30, s * y, x_end, s * y), fill=color, width=w)


def _draw_mail(d, s, color):
    # enveloppe simple
    w = max(2, s // 12)
    margin_x = s * 0.16
    top = s * 0.30
    bottom = s * 0.74
    d.rectangle(
        (margin_x, top, s - margin_x, bottom),
        outline=color, width=w,
    )
    # rabat (V)
    d.line((margin_x, top, s / 2, s * 0.55), fill=color, width=w)
    d.line((s / 2, s * 0.55, s - margin_x, top), fill=color, width=w)


def _draw_broadcast(d, s, color):
    # antenne avec ondes (3 arcs)
    w = max(2, s // 12)
    cx, cy = s / 2, s * 0.74
    # point central
    d.ellipse(
        (cx - s * 0.05, cy - s * 0.05, cx + s * 0.05, cy + s * 0.05),
        fill=color,
    )
    # antenne (mât)
    d.line((cx, cy, cx, s * 0.20), fill=color, width=w)
    # haut
    d.ellipse(
        (cx - s * 0.06, s * 0.16, cx + s * 0.06, s * 0.28),
        outline=color, width=w,
    )
    # 2 ondes latérales
    for i, offset in enumerate([(0.12, 0.55), (0.20, 0.65)]):
        ox, scale = offset
        d.arc(
            (cx - s * scale / 2, s * 0.30, cx + s * scale / 2, s * 0.85),
            start=200, end=340,
            fill=color, width=w,
        )


def _draw_chart(d, s, color):
    # 3 barres verticales croissantes
    w = max(2, s // 9)
    base_y = s * 0.78
    bars = [(0.22, 0.62), (0.42, 0.46), (0.62, 0.28)]
    bar_w = s * 0.10
    for x_pct, top_pct in bars:
        x = s * x_pct
        top = s * top_pct
        d.rectangle((x, top, x + bar_w, base_y), fill=color)
    # base line
    d.line((s * 0.16, base_y, s * 0.80, base_y), fill=color, width=max(1, w // 2))


def _draw_settings(d, s, color):
    # engrenage simplifié : disque + 6 dents + centre creux
    w = max(2, s // 12)
    cx, cy = s / 2, s / 2
    r_outer = s * 0.30
    r_tooth_out = s * 0.40
    r_inner = s * 0.10
    # dents (rectangles radiaux)
    for i in range(8):
        ang = math.radians(i * 45)
        x1 = cx + math.cos(ang) * (r_outer - 1)
        y1 = cy + math.sin(ang) * (r_outer - 1)
        x2 = cx + math.cos(ang) * r_tooth_out
        y2 = cy + math.sin(ang) * r_tooth_out
        d.line((x1, y1, x2, y2), fill=color, width=max(3, s // 8))
    # cercle externe
    d.ellipse((cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer),
              outline=color, width=w)
    # cercle interne (trou)
    d.ellipse((cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner),
              outline=color, width=w)


def _draw_refresh(d, s, color):
    # flèche circulaire (refresh)
    w = max(2, s // 12)
    cx, cy = s / 2, s / 2
    r = s * 0.30
    d.arc(
        (cx - r, cy - r, cx + r, cy + r),
        start=30, end=320,
        fill=color, width=w,
    )
    # tête de flèche
    arrow_x = cx + r * math.cos(math.radians(30))
    arrow_y = cy + r * math.sin(math.radians(30))
    d.polygon([
        (arrow_x, arrow_y - s * 0.12),
        (arrow_x + s * 0.10, arrow_y),
        (arrow_x - s * 0.04, arrow_y + s * 0.04),
    ], fill=color)


def _draw_plus(d, s, color):
    w = max(3, s // 8)
    d.line((s * 0.30, s / 2, s * 0.70, s / 2), fill=color, width=w)
    d.line((s / 2, s * 0.30, s / 2, s * 0.70), fill=color, width=w)


def _draw_external(d, s, color):
    """Icône lien externe : carré + flèche sortant en haut-droite."""
    w = max(2, s // 12)
    # Cadre bas-gauche
    d.rectangle(
        (s * 0.18, s * 0.30, s * 0.65, s * 0.82),
        outline=color, width=w,
    )
    # Flèche diagonale
    d.line(
        (s * 0.42, s * 0.58, s * 0.82, s * 0.18),
        fill=color, width=w,
    )
    # Pointe de flèche
    d.line((s * 0.82, s * 0.18, s * 0.60, s * 0.18), fill=color, width=w)
    d.line((s * 0.82, s * 0.18, s * 0.82, s * 0.40), fill=color, width=w)


def _draw_save(d, s, color):
    # Disquette : carré + onglet en haut + écran d'écriture
    w = max(2, s // 12)
    margin = s * 0.20
    d.rectangle(
        (margin, margin, s - margin, s - margin),
        outline=color, width=w,
    )
    # Onglet écriture en haut
    d.rectangle(
        (margin + s * 0.10, margin,
         s - margin - s * 0.10, margin + s * 0.18),
        fill=color,
    )
    # Cadre intérieur (label)
    d.rectangle(
        (margin + s * 0.05, s - margin - s * 0.30,
         s - margin - s * 0.05, s - margin - s * 0.05),
        outline=color, width=w,
    )


def _draw_trash(d, s, color):
    w = max(2, s // 12)
    # couvercle (rectangle plat horizontal)
    lid_y = s * 0.30
    d.line(
        (s * 0.18, lid_y, s * 0.82, lid_y),
        fill=color, width=max(3, w + 1),
    )
    # poignée
    d.line(
        (s * 0.40, s * 0.22, s * 0.60, s * 0.22),
        fill=color, width=max(3, w + 1),
    )
    d.line((s * 0.40, s * 0.22, s * 0.40, lid_y), fill=color, width=w)
    d.line((s * 0.60, s * 0.22, s * 0.60, lid_y), fill=color, width=w)
    # corps de la poubelle
    d.line((s * 0.26, lid_y, s * 0.30, s * 0.84), fill=color, width=w)
    d.line((s * 0.74, lid_y, s * 0.70, s * 0.84), fill=color, width=w)
    d.line((s * 0.30, s * 0.84, s * 0.70, s * 0.84), fill=color, width=w)
    # 2 traits verticaux (lignes intérieures)
    d.line((s * 0.42, s * 0.40, s * 0.42, s * 0.78), fill=color, width=max(1, w // 2))
    d.line((s * 0.58, s * 0.40, s * 0.58, s * 0.78), fill=color, width=max(1, w // 2))


def _draw_duplicate(d, s, color):
    # 2 documents superposés en décalé
    w = max(2, s // 14)
    margin = s * 0.16
    # doc arrière
    d.rectangle(
        (margin + s * 0.14, margin, s - margin, s - margin - s * 0.14),
        outline=color, width=w,
    )
    # doc avant (un peu en avant)
    d.rectangle(
        (margin, margin + s * 0.14, s - margin - s * 0.14, s - margin),
        outline=color, width=w,
    )


def _draw_copy(d, s, color):
    """Identique au duplicate mais plus stylisé (presse-papiers)."""
    w = max(2, s // 12)
    # Plaque presse-papiers
    margin = s * 0.18
    d.rectangle(
        (margin, margin + s * 0.06, s - margin, s - margin),
        outline=color, width=w,
    )
    # Pince haute
    d.rectangle(
        (s * 0.36, margin, s * 0.64, margin + s * 0.16),
        outline=color, width=w,
    )


def _draw_send(d, s, color):
    # Avion en papier (paper plane)
    w = max(2, s // 12)
    # silhouette triangle
    d.polygon([
        (s * 0.16, s * 0.78),    # arrière bas
        (s * 0.86, s * 0.18),    # pointe avant
        (s * 0.46, s * 0.50),    # pli inférieur
    ], outline=color, width=w)
    # pli interne
    d.line(
        (s * 0.16, s * 0.78, s * 0.46, s * 0.50),
        fill=color, width=w,
    )
    d.line(
        (s * 0.46, s * 0.50, s * 0.50, s * 0.84),
        fill=color, width=w,
    )


def _draw_sparkle(d, s, color):
    # Étoile à 4 branches (sparkle)
    w = max(2, s // 12)
    cx, cy = s / 2, s / 2
    # Croix principale
    d.line((cx, s * 0.14, cx, s * 0.86), fill=color, width=w)
    d.line((s * 0.14, cy, s * 0.86, cy), fill=color, width=w)
    # Diagonales plus courtes
    short = s * 0.16
    d.line(
        (cx - short, cy - short, cx + short, cy + short),
        fill=color, width=max(1, w - 1),
    )
    d.line(
        (cx - short, cy + short, cx + short, cy - short),
        fill=color, width=max(1, w - 1),
    )


def _draw_target(d, s, color):
    # Cible : 3 cercles concentriques + point central
    w = max(2, s // 12)
    cx, cy = s / 2, s / 2
    for r in [s * 0.36, s * 0.22]:
        d.ellipse((cx - r, cy - r, cx + r, cy + r),
                  outline=color, width=w)
    d.ellipse((cx - s * 0.06, cy - s * 0.06,
               cx + s * 0.06, cy + s * 0.06), fill=color)


def _draw_download(d, s, color):
    # Flèche vers le bas + ligne horizontale
    w = max(2, s // 10)
    cx = s / 2
    # Tige
    d.line((cx, s * 0.16, cx, s * 0.66), fill=color, width=w)
    # Pointe
    d.line((s * 0.30, s * 0.46, cx, s * 0.70), fill=color, width=w)
    d.line((s * 0.70, s * 0.46, cx, s * 0.70), fill=color, width=w)
    # Plateau bas
    d.line((s * 0.20, s * 0.84, s * 0.80, s * 0.84), fill=color, width=w)


def _draw_close(d, s, color):
    w = max(2, s // 10)
    d.line((s * 0.26, s * 0.26, s * 0.74, s * 0.74), fill=color, width=w)
    d.line((s * 0.74, s * 0.26, s * 0.26, s * 0.74), fill=color, width=w)


def _draw_globe(d, s, color):
    w = max(2, s // 12)
    cx, cy = s / 2, s / 2
    r = s * 0.34
    d.ellipse((cx - r, cy - r, cx + r, cy + r),
              outline=color, width=w)
    # Méridien vertical
    d.ellipse((cx - r * 0.4, cy - r, cx + r * 0.4, cy + r),
              outline=color, width=max(1, w - 1))
    # Équateur horizontal
    d.line((cx - r, cy, cx + r, cy), fill=color, width=max(1, w - 1))


def _draw_check(d, s, color):
    w = max(2, s // 8)
    d.line((s * 0.22, s * 0.52, s * 0.42, s * 0.72),
            fill=color, width=w)
    d.line((s * 0.42, s * 0.72, s * 0.78, s * 0.30),
            fill=color, width=w)


def _draw_arrow_right(d, s, color):
    """Flèche droite simple — pour les boutons "Suivant"."""
    w = max(2, s // 9)
    # Tige horizontale
    d.line((s * 0.22, s / 2, s * 0.74, s / 2), fill=color, width=w)
    # Pointe
    d.line((s * 0.50, s * 0.28, s * 0.74, s / 2), fill=color, width=w)
    d.line((s * 0.50, s * 0.72, s * 0.74, s / 2), fill=color, width=w)


def _draw_arrow_left(d, s, color):
    w = max(2, s // 9)
    d.line((s * 0.78, s / 2, s * 0.26, s / 2), fill=color, width=w)
    d.line((s * 0.50, s * 0.28, s * 0.26, s / 2), fill=color, width=w)
    d.line((s * 0.50, s * 0.72, s * 0.26, s / 2), fill=color, width=w)


def _draw_play(d, s, color):
    """Triangle play — pour 'Lancer maintenant'."""
    w = max(2, s // 12)
    d.polygon([
        (s * 0.30, s * 0.22),
        (s * 0.30, s * 0.78),
        (s * 0.78, s / 2),
    ], outline=color, fill=color)


_DRAWERS = {
    "search":     _draw_search,
    "pen":        _draw_pen,
    "doc":        _draw_doc,
    "mail":       _draw_mail,
    "broadcast":  _draw_broadcast,
    "chart":      _draw_chart,
    "settings":   _draw_settings,
    "refresh":    _draw_refresh,
    "plus":       _draw_plus,
    "external":   _draw_external,
    "save":       _draw_save,
    "trash":      _draw_trash,
    "duplicate":  _draw_duplicate,
    "copy":       _draw_copy,
    "send":       _draw_send,
    "sparkle":    _draw_sparkle,
    "target":     _draw_target,
    "download":   _draw_download,
    "close":      _draw_close,
    "globe":      _draw_globe,
    "check":      _draw_check,
    "arrow_right":_draw_arrow_right,
    "arrow_left": _draw_arrow_left,
    "play":       _draw_play,
}


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def get_icon(name: str, color_hex: str, size: int = 20) -> ctk.CTkImage | None:
    """Renvoie un CTkImage prêt à afficher.

    `name` doit être une des clés de _DRAWERS.
    `color_hex` ex. "#9DA3B3".
    `size` taille en pixels logiques.
    """
    drawer = _DRAWERS.get(name)
    if not drawer:
        return None
    key = (name, color_hex, size)
    if key in _CACHE:
        return _CACHE[key]
    rgba = _hex_to_rgba(color_hex)
    img = _supersampled(drawer, size, rgba)
    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    _CACHE[key] = ctk_img
    return ctk_img
