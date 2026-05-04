"""Helper pour appliquer l'icône Triskell sur n'importe quel Toplevel custom."""

from __future__ import annotations

import sys
from pathlib import Path


_CACHED_PATH: Path | None = None
_RESOLVED = False


def _resolve_icon_path() -> Path | None:
    """Cherche assets/triskell.ico en mode dev ou PyInstaller frozen."""
    global _CACHED_PATH, _RESOLVED
    if _RESOLVED:
        return _CACHED_PATH
    _RESOLVED = True
    # Mode frozen (PyInstaller)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / "assets" / "triskell.ico"
        if p.exists():
            _CACHED_PATH = p
            return p
    # Mode dev
    here = Path(__file__).resolve()
    for parent in (here.parent.parent.parent, here.parent.parent.parent.parent):
        p = parent / "assets" / "triskell.ico"
        if p.exists():
            _CACHED_PATH = p
            return p
    return None


def apply_window_icon(window) -> None:
    """Applique l'icône Triskell sur la barre de titre d'une fenêtre Tk/CTk."""
    icon_path = _resolve_icon_path()
    if icon_path is None:
        return
    try:
        window.iconbitmap(str(icon_path))
    except Exception:
        # Fallback : essaye via wm_iconphoto avec PIL
        try:
            from PIL import Image, ImageTk
            png_path = icon_path.parent / "triskell.png"
            if png_path.exists():
                img = Image.open(png_path).convert("RGBA")
                img.thumbnail((64, 64), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                window.wm_iconphoto(True, photo)
                # Garde une réf pour empêcher le GC
                window._triskell_icon_ref = photo  # type: ignore
        except Exception:
            pass
