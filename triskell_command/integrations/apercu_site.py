"""Aperçu de site personnalisé pour la prospection.

Idée (demande Jordan, 14/06/2026) : dans le mail de prospection, montrer au
prospect À QUOI POURRAIT RESSEMBLER SON SITE. C'est ce qui fait répondre quand
on vend des sites — surtout aux commerces qui n'en ont PAS (cible la plus
chaude, et justement celle pour qui aucune capture n'existe aujourd'hui).

Ce module fabrique une image PNG : une maquette de site (cadre navigateur +
hero personnalisé avec le nom de l'entreprise, son métier, sa ville). 100 %
auto-contenu (CSS en ligne, pas d'image externe à charger → rapide et jamais
de visuel cassé). Rendu via Playwright (déjà installé côté serveur — utilisé
par Argus). Sans Playwright : renvoie None (le mail part alors sans aperçu).

Usage :
    from triskell_command.integrations import apercu_site
    png = apercu_site.render_preview_png("Boulangerie Morvan", "boulangerie", "Vannes")
"""
from __future__ import annotations

import base64
import hashlib
import html as _html
import logging
import os
import re
import unicodedata

logger = logging.getLogger(__name__)

# Couleur d'accent + emoji décoratif par famille de métier. Volontairement
# court : un défaut élégant couvre tout le reste. L'emoji évite toute photo
# (donc zéro risque de « mauvaise image » et zéro chargement réseau).
_SECTOR_STYLE: dict[str, tuple[str, str, str]] = {
    # mot-clé (sans accent)      accent1     accent2     emoji
    "boulang":      ("#b45309", "#f59e0b", "🥖"),
    "patiss":       ("#be185d", "#f472b6", "🧁"),
    "boucher":      ("#b91c1c", "#ef4444", "🥩"),
    "fleur":        ("#be185d", "#fb7185", "🌸"),
    "restaur":      ("#9a3412", "#fb923c", "🍽️"),
    "pizz":         ("#b91c1c", "#f87171", "🍕"),
    "bar":          ("#7c2d12", "#f59e0b", "🍸"),
    "coiff":        ("#7c3aed", "#c084fc", "✂️"),
    "beaut":        ("#be185d", "#f9a8d4", "💅"),
    "estheti":      ("#be185d", "#f9a8d4", "💆"),
    "spa":          ("#0f766e", "#5eead4", "🌿"),
    "sport":        ("#1d4ed8", "#60a5fa", "🏋️"),
    "plomb":        ("#1d4ed8", "#38bdf8", "🔧"),
    "electric":     ("#a16207", "#facc15", "💡"),
    "chauffag":     ("#c2410c", "#fb923c", "🔥"),
    "peintr":       ("#7c3aed", "#a78bfa", "🎨"),
    "menuis":       ("#92400e", "#d97706", "🪚"),
    "macon":        ("#57534e", "#a8a29e", "🧱"),
    "carrel":       ("#0e7490", "#22d3ee", "◼️"),
    "couvr":        ("#9a3412", "#f97316", "🏠"),
    "jardin":       ("#15803d", "#4ade80", "🌳"),
    "paysag":       ("#15803d", "#4ade80", "🌳"),
    "garage":       ("#334155", "#64748b", "🚗"),
    "auto":         ("#334155", "#64748b", "🚗"),
    "immobil":      ("#0f766e", "#2dd4bf", "🏡"),
    "photograph":   ("#4338ca", "#818cf8", "📷"),
    "avocat":       ("#1e3a8a", "#3b82f6", "⚖️"),
    "comptab":      ("#1e40af", "#60a5fa", "📊"),
    "dentist":      ("#0e7490", "#22d3ee", "🦷"),
    "medecin":      ("#0e7490", "#22d3ee", "🩺"),
    "veterin":      ("#15803d", "#4ade80", "🐾"),
    "pharmaci":     ("#047857", "#34d399", "➕"),
    "coach":        ("#7c3aed", "#a78bfa", "🎯"),
    "boutique":     ("#9d174d", "#f472b6", "🛍️"),
    "hotel":        ("#1e40af", "#60a5fa", "🛎️"),
}
_DEFAULT_STYLE = ("#4f46e5", "#818cf8", "✦")  # indigo élégant par défaut


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")


def _style_for(metier: str) -> tuple[str, str, str]:
    key = _strip_accents((metier or "").lower())
    for frag, style in _SECTOR_STYLE.items():
        if frag in key:
            return style
    return _DEFAULT_STYLE


def _domain_slug(nom: str) -> str:
    """« Boulangerie Morvan » → « boulangerie-morvan.fr » (juste pour la
    barre d'adresse de la maquette — ce n'est pas un vrai domaine)."""
    s = _strip_accents((nom or "votre-entreprise").lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = re.sub(r"-+", "-", s) or "votre-entreprise"
    return f"{s[:34].strip('-')}.fr"


def _initials(nom: str) -> str:
    """Initiales de l'entreprise pour le monogramme (1-2 lettres). Robuste
    partout (police Poppins) — pas d'emoji, donc jamais de carré vide serveur."""
    skip = {"de", "du", "des", "la", "le", "les", "d", "l", "au", "aux", "et", "a"}
    words = [w for w in re.split(r"[^0-9A-Za-zÀ-ÿ]+", nom or "") if w]
    sig = [w for w in words if _strip_accents(w.lower()) not in skip] or words
    return ("".join(w[0] for w in sig[:2]).upper()) or "✦"


# Vraies photos par métier (téléchargées + vérifiées à l'œil le 14/06/2026 ;
# Unsplash, libres). Embarquées dans la maquette pour faire sérieux — fini
# l'emoji « jeu vidéo ». Un métier non couvert → photo « default » (devanture
# élégante neutre, jamais hors-sujet).
_PHOTO_DIR = os.path.join(os.path.dirname(__file__), "apercu_photos")
_PHOTO_MAP: dict[str, str] = {
    "boulang": "boulangerie.jpg", "patiss": "boulangerie.jpg", "pain": "boulangerie.jpg",
    "fleur": "fleuriste.jpg",
    "restaur": "restaurant.jpg", "pizz": "restaurant.jpg", "bar": "restaurant.jpg",
    "traiteur": "restaurant.jpg", "brasser": "restaurant.jpg", "creperie": "restaurant.jpg",
    "coiff": "coiffeur.jpg",
    "beaut": "beaute.jpg", "estheti": "beaute.jpg", "spa": "beaute.jpg",
    "ongle": "beaute.jpg", "manucure": "beaute.jpg", "massage": "beaute.jpg",
    "plomb": "batiment.jpg", "electric": "batiment.jpg", "chauffag": "batiment.jpg",
    "peintr": "batiment.jpg", "menuis": "batiment.jpg", "macon": "batiment.jpg",
    "carrel": "batiment.jpg", "couvr": "batiment.jpg", "platr": "batiment.jpg",
    "plaqu": "batiment.jpg", "renov": "batiment.jpg", "batiment": "batiment.jpg",
    "artisan": "batiment.jpg", "serrur": "batiment.jpg", "charpent": "batiment.jpg",
    "jardin": "jardin.jpg", "paysag": "jardin.jpg", "elagag": "jardin.jpg",
    "garage": "garage.jpg", "auto": "garage.jpg", "mecanic": "garage.jpg",
    "carross": "garage.jpg", "pneu": "garage.jpg",
}
_photo_cache: dict[str, str] = {}


def _photo_file_for(metier: str) -> str:
    key = _strip_accents((metier or "").lower())
    for frag, fn in _PHOTO_MAP.items():
        if frag in key:
            return fn
    return "default.jpg"


def _photo_base64(metier: str) -> str:
    """Photo du métier encodée en base64 (embarquée dans la maquette). "" si
    absente — la maquette retombe alors sur un fond dégradé + monogramme."""
    fn = _photo_file_for(metier)
    if fn in _photo_cache:
        return _photo_cache[fn]
    try:
        with open(os.path.join(_PHOTO_DIR, fn), "rb") as f:
            b = base64.b64encode(f.read()).decode("ascii")
    except Exception:
        b = ""
    _photo_cache[fn] = b
    return b


def build_preview_html(nom: str, metier: str = "", ville: str = "") -> str:
    """HTML auto-contenu d'une maquette de site (cadre navigateur + hero)."""
    nom = (nom or "Votre entreprise").strip()
    metier = (metier or "").strip()
    ville = (ville or "").strip()
    c1, c2, _emoji = _style_for(metier)
    slug = _domain_slug(nom)
    initials = _initials(nom)
    photo_b64 = _photo_base64(metier)
    if photo_b64:
        # Vraie photo du métier en fond du panneau, avec un léger voile sombre
        # en bas (lisibilité du badge) + une touche de couleur de marque.
        right_style = (f"background-image:linear-gradient(to top,"
                       f"rgba(0,0,0,.55),rgba(0,0,0,0) 52%),"
                       f"linear-gradient(135deg,{c1}33,transparent 55%),"
                       f"url('data:image/jpeg;base64,{photo_b64}');"
                       f"background-size:cover;background-position:center;")
        right_inner = ""
    else:
        right_style = f"background:linear-gradient(135deg,{c1},{c2});"
        right_inner = f'<div class="mono">{_html.escape(initials)}</div>'

    # Eyebrow : « MÉTIER · VILLE » (ou juste l'un, ou un défaut).
    eyebrow_bits = [b for b in (metier.upper(), ville.upper()) if b]
    eyebrow = " · ".join(eyebrow_bits) or "VOTRE ACTIVITÉ"
    # Sous-titre simple, jamais mensonger (pas d'avis/chiffres inventés).
    sub = f"Le site qui donne envie de pousser votre porte"
    if ville:
        sub += f", à {ville}"
    sub += "."

    e = _html.escape
    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@500;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:1000px; height:640px; background:#e9eef5;
         font-family:'Inter',system-ui,sans-serif; display:flex;
         align-items:center; justify-content:center; }}
  .win {{ width:920px; height:560px; background:#fff; border-radius:14px;
          overflow:hidden; box-shadow:0 30px 70px rgba(15,23,42,.28); }}
  .chrome {{ height:42px; background:#f1f5f9; display:flex; align-items:center;
             gap:8px; padding:0 16px; border-bottom:1px solid #e2e8f0; }}
  .dot {{ width:12px; height:12px; border-radius:50%; }}
  .url {{ flex:1; margin-left:14px; height:24px; background:#fff;
          border:1px solid #e2e8f0; border-radius:999px; display:flex;
          align-items:center; padding:0 14px; font-size:12.5px; color:#64748b; }}
  .nav {{ height:58px; display:flex; align-items:center; justify-content:space-between;
          padding:0 34px; border-bottom:1px solid #f1f5f9; }}
  .logo {{ font-family:'Poppins'; font-weight:800; font-size:18px; color:#0f172a; }}
  .logo b {{ color:{c1}; }}
  .menu {{ display:flex; gap:24px; font-size:13.5px; color:#475569; font-weight:500; }}
  .menu .cta {{ background:{c1}; color:#fff; padding:8px 16px; border-radius:999px;
                font-weight:600; }}
  .hero {{ height:calc(560px - 42px - 58px); display:flex; }}
  .left {{ flex:1.15; padding:48px 40px; display:flex; flex-direction:column;
           justify-content:center; }}
  .eyebrow {{ display:inline-block; align-self:flex-start; font-family:'Poppins';
              font-weight:700; font-size:11.5px; letter-spacing:1.5px;
              color:{c1}; background:{c1}14; padding:7px 13px; border-radius:999px;
              margin-bottom:20px; }}
  h1 {{ font-family:'Poppins'; font-weight:800; font-size:46px; line-height:1.06;
        color:#0f172a; letter-spacing:-1px; text-wrap:balance; }}
  .sub {{ margin-top:18px; font-size:16.5px; line-height:1.5; color:#475569;
          max-width:430px; text-wrap:pretty; }}
  .ctas {{ margin-top:30px; display:flex; gap:14px; align-items:center; }}
  .btn1 {{ background:{c1}; color:#fff; font-weight:600; font-size:15px;
           padding:14px 26px; border-radius:11px; box-shadow:0 10px 24px {c1}40; }}
  .btn2 {{ color:#0f172a; font-weight:600; font-size:15px; padding:14px 8px; }}
  .right {{ flex:1; position:relative; display:flex; align-items:center;
            justify-content:center; overflow:hidden; }}
  .mono {{ width:190px; height:190px; border-radius:50%;
           background:rgba(255,255,255,.16); border:2px solid rgba(255,255,255,.45);
           display:flex; align-items:center; justify-content:center;
           font-family:'Poppins'; font-weight:800; font-size:78px; color:#fff;
           letter-spacing:1px; box-shadow:0 18px 44px rgba(0,0,0,.20); }}
  .badge {{ position:absolute; bottom:26px; left:26px; right:26px;
            background:rgba(255,255,255,.92); border-radius:12px; padding:13px 16px;
            font-size:13px; color:#0f172a; font-weight:600;
            box-shadow:0 12px 28px rgba(0,0,0,.16); }}
  .badge span {{ color:{c1}; }}
</style></head><body>
  <div class="win">
    <div class="chrome">
      <div class="dot" style="background:#ff5f57"></div>
      <div class="dot" style="background:#febc2e"></div>
      <div class="dot" style="background:#28c840"></div>
      <div class="url">🔒 https://www.{e(slug)}</div>
    </div>
    <div class="nav">
      <div class="logo">{e(nom)}</div>
      <div class="menu"><span>Accueil</span><span>Services</span><span>Avis</span><span class="cta">Contact</span></div>
    </div>
    <div class="hero">
      <div class="left">
        <span class="eyebrow">{e(eyebrow)}</span>
        <h1>{e(nom)}</h1>
        <div class="sub">{e(sub)}</div>
        <div class="ctas">
          <span class="btn1">Demander un devis</span>
          <span class="btn2">Voir nos réalisations →</span>
        </div>
      </div>
      <div class="right" style="{right_style}">
        {right_inner}
        <div class="badge">✓ Site moderne, rapide et <span>adapté au mobile</span></div>
      </div>
    </div>
  </div>
</body></html>"""


def render_preview_png(nom: str, metier: str = "", ville: str = "",
                       output_path=None) -> bytes | None:
    """Rend la maquette en PNG. Renvoie les octets (ou écrit le fichier si
    output_path est fourni). None si Playwright est indisponible / erreur —
    le mail part alors simplement sans aperçu (jamais bloquant)."""
    html_doc = build_preview_html(nom, metier, ville)
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        logger.info("apercu_site : Playwright absent — aperçu sauté.")
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(
                    viewport={"width": 1000, "height": 640},
                    device_scale_factor=2)
                page.set_content(html_doc, wait_until="domcontentloaded")
                try:
                    page.evaluate("async () => { await document.fonts.ready; }")
                except Exception:
                    pass
                page.wait_for_timeout(700)
                png = page.screenshot(
                    clip={"x": 0, "y": 0, "width": 1000, "height": 640})
            finally:
                browser.close()
        if output_path:
            with open(output_path, "wb") as f:
                f.write(png)
            return None
        return png
    except Exception as exc:
        logger.warning("apercu_site : rendu échoué : %s", exc)
        return None


# ---------------------------------------------------------------------------
# Hébergement (Supabase Storage) + bloc <img> prêt pour le mail
# ---------------------------------------------------------------------------
_BUCKET = "pp-client-photos"  # bucket public déjà en place


def _sb_client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        return c if getattr(c, "is_authenticated", False) else None
    except Exception:
        return None


def _public_url(path: str) -> str:
    base = (os.environ.get("SUPABASE_URL")
            or os.environ.get("PIXEL_PROS_SUPABASE_URL") or "").rstrip("/")
    return f"{base}/storage/v1/object/public/{_BUCKET}/{path}" if base else ""


def preview_image_url(nom: str, metier: str = "", ville: str = "") -> str:
    """Génère l'aperçu, l'héberge sur Supabase Storage, renvoie l'URL publique.
    Renvoie "" si indisponible (Playwright/Supabase absents) — jamais bloquant."""
    png = render_preview_png(nom, metier, ville)
    if not png:
        return ""
    c = _sb_client()
    if c is None:
        return ""
    key = hashlib.sha1(f"{nom}|{metier}|{ville}".encode("utf-8")).hexdigest()[:20]
    path = f"apercus/{key}.png"
    try:
        c.raw.storage.from_(_BUCKET).upload(
            path=path, file=png,
            file_options={"content-type": "image/png", "upsert": "true"})
    except Exception as exc:
        logger.warning("apercu_site : upload échoué : %s", exc)
        return ""
    return _public_url(path)


def preview_img_html(nom: str, metier: str = "", ville: str = "") -> str:
    """Bloc <img> prêt à coller dans un mail (ou "" si pas d'aperçu)."""
    url = preview_image_url(nom, metier, ville)
    if not url:
        return ""
    return (f'<img src="{url}" alt="Apercu de votre futur site" '
            'style="max-width:100%;height:auto;border-radius:10px;'
            'border:1px solid #e5e7eb;display:block;margin:0 0 16px;">')


__all__ = ["build_preview_html", "render_preview_png",
           "preview_image_url", "preview_img_html"]
