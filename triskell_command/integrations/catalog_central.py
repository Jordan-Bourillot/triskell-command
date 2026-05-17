"""Catalogue central editable (produits + packs) — source de verite UI.

Combine :
- les produits par defaut (apps.json embarque + sites hardcodes Lagriffe / RankUs
  / WoW connus du frontend),
- les overrides utilisateur stockes dans Supabase
  `shared_settings.catalog_central` :
    {
      "products":     [ {id, name, tagline, ...} ],  # override / nouveau
      "deleted_ids":  ["bobeez", ...],               # cache du catalogue
      "disabled_ids": ["alphapitch", ...],           # toggle off (compat
                                                    #   avec catalog_overrides)
      "bundles":      [ {id, name, product_ids, ...} ],
    }

Les overrides ECRASENT les champs par defaut. Si un produit a le meme id qu'un
defaut, ses champs editables remplacent ceux du defaut (sauf la categorie qui
sert au groupement et reste figee pour les apps existantes).

Compat : la clef `disabled_ids` est partagee avec `catalog_overrides.py` pour
ne pas casser le toggle deja en place.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SHARED_KEY = "catalog_central"


# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------
def _client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        return c if c.is_authenticated else None
    except ImportError:
        return None
    except Exception:
        return None


def _read() -> dict:
    c = _client()
    if c is None:
        return {}
    try:
        raw = c.get_shared_setting(SHARED_KEY, {}) or {}
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:
        logger.debug("catalog_central _read: %s", exc)
        return {}


def _write(data: dict) -> bool:
    c = _client()
    if c is None:
        return False
    try:
        c.set_shared_setting(SHARED_KEY, data)
        return True
    except Exception as exc:
        logger.warning("catalog_central _write: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Defauts (apps.json + sites hardcodes connus du frontend)
# ---------------------------------------------------------------------------
# Mapping id -> slug logo (recopie depuis api.get_apps_catalog)
_ID_TO_SLUG = {
    "suite-des-heros":      ("suite-des-heros", "png"),
    "delinote":             ("delinote", "png"),
    "studio-pdf":           ("studio-pdf", "png"),
    "bobeez":               ("bobeez", "png"),
    "le-denicheur":         ("le-denicheur", "png"),
    "artisia-studio":       ("artisia-studio", "png"),
    "triskell-studio-sites":("triskell-studio-sites", "png"),
    "eliks-studio":         ("eliks-studio", "png"),
    "le-heraut":            ("le-heraut", "png"),
    "ultimate-prompt-builder":("ultimate-prompt-builder", "png"),
    "alphapitch":           ("alphapitch", "png"),
    "outils-batiment":      ("outils-batiment", "png"),
    "pack-electricien-pro": ("pack-electricien-pro", "png"),
    "teddy-mail":           ("teddy-mail", "png"),
    "clik-clik":            ("clik-clik", "png"),
}


# Sites Triskell hardcodes cote frontend (catalogue.js SITES). Recopie ici
# pour les rendre editables comme les autres produits.
_DEFAULT_SITES = [
    {
        "id": "lagriffe",
        "name": "Lagriffe Studio",
        "tagline": "Sites web premium pour artisans et indépendants.",
        "description": "Lagriffe Studio crée des sites vitrines élégants pour artisans, "
                       "indépendants et petites entreprises. Design soigné, performance, "
                       "SEO de base, hébergement géré. Tarif unique sans abonnement.",
        "sales_pitch": "Un site qui ressemble à ton métier, pas à un template Wix.",
        "motto": "Pour les pros qui veulent un vrai site, pas un site bricolé.",
        "category": "sites",
        "kind": "service",
        "buy_url": "https://lagriffe-studio.fr",
        "logo": "",
        "color": "#d4af37",
        "initial": "L",
        "features": [
            {"title": "Design sur-mesure", "detail": "Pas de template figé. Chaque site est dessiné à partir de ton métier et de ton univers."},
            {"title": "SEO de base inclus", "detail": "Structure propre, balises optimisées, pages locales — tu apparais dans Google sans surcoût."},
            {"title": "Hébergement géré",   "detail": "On s'occupe du domaine, du HTTPS, des sauvegardes. Tu n'as rien à toucher."},
        ],
        "is_builtin": True,
    },
    {
        "id": "rankus",
        "name": "RankUs Studio",
        "tagline": "Agence SEO — on fait monter ton site dans Google.",
        "description": "RankUs Studio est l'agence SEO de l'écosystème Triskell. On audite "
                       "ton site, on corrige les blocages techniques, on rédige du contenu "
                       "qui répond aux vraies recherches de tes clients, et on suit les "
                       "positions mois après mois.",
        "sales_pitch": "Tu veux apparaître quand tes clients cherchent — on t'y emmène.",
        "motto": "Pour qui en a marre de payer Google Ads pour exister.",
        "category": "sites",
        "kind": "service",
        "buy_url": "https://rankus.fr",
        "logo": "",
        "color": "#10b981",
        "initial": "R",
        "features": [
            {"title": "Audit technique", "detail": "On scanne ton site, on repère ce qui bloque (vitesse, balises, structure, mobile)."},
            {"title": "Contenu ciblé",   "detail": "On rédige les pages qui correspondent aux requêtes que tes clients tapent vraiment."},
            {"title": "Suivi mensuel",   "detail": "Tableau de bord clair des positions, du trafic et des conversions. Rien de magique, juste du résultat."},
        ],
        "is_builtin": True,
    },
    {
        "id": "wow",
        "name": "Studio WoW",
        "tagline": "Sites haut de gamme avec effets immersifs.",
        "description": "Studio WoW conçoit des sites premium pour marques et marques "
                       "personnelles qui veulent un effet « waouh » à l'arrivée. Animations, "
                       "scroll cinématique, typographie travaillée, performance maintenue.",
        "sales_pitch": "Quand un site classique ne suffit pas à raconter qui tu es.",
        "motto": "Pour les marques qui veulent marquer.",
        "category": "sites",
        "kind": "service",
        "buy_url": "https://studio-wow.fr",
        "logo": "",
        "color": "#C9A572",
        "initial": "W",
        "features": [
            {"title": "Direction artistique", "detail": "Univers visuel sur-mesure : typo, couleurs, photos, ambiance — tout est pensé pour ta marque."},
            {"title": "Effets immersifs",     "detail": "Animations subtiles, scroll cinématique, transitions soignées. Sans plomber la vitesse."},
            {"title": "Optimisé Apple-style", "detail": "Performance, accessibilité, mobile parfait. On vise le niveau des sites des grandes marques."},
        ],
        "is_builtin": True,
    },
]


def _load_apps_json() -> list[dict]:
    """Charge la copie embarquee de apps.json (defauts apps Triskell)."""
    here = Path(__file__).resolve()
    candidates = []
    for depth, sub in (
        (2, ("data", "apps.json")),
        (4, ("Triskell 0 - Lanceur", "apps.json")),
        (5, ("Triskell 0 - Lanceur", "apps.json")),
    ):
        try:
            candidates.append(here.parents[depth].joinpath(*sub))
        except IndexError:
            continue
    for p in candidates:
        if p.exists():
            try:
                return (json.loads(p.read_text(encoding="utf-8")) or {}).get("apps", [])
            except Exception as exc:
                logger.warning("apps.json parse fail: %s", exc)
                return []
    return []


def _apps_json_to_product(app: dict) -> dict | None:
    slug_info = _ID_TO_SLUG.get(app.get("id"))
    if not slug_info:
        return None
    slug, ext = slug_info
    return {
        "id":             app.get("id"),
        "name":           app.get("name"),
        "tagline":        app.get("tagline", ""),
        "category":       app.get("category", ""),
        "pro_section":    app.get("proSection", ""),
        "tier":           app.get("tier", ""),
        "kind":           app.get("kind", ""),
        "price":          app.get("price"),
        "price_original": app.get("priceOriginal"),
        "price_from":     app.get("priceFrom"),
        "price_note":     app.get("priceNote", ""),
        "buy_url":        app.get("buyUrl", ""),
        "exe_path":       app.get("exePath", ""),
        "installed":      bool(app.get("installed")),
        "coming_soon":    bool(app.get("comingSoon")),
        "featured":       bool(app.get("featured")),
        "featured_label": app.get("featuredLabel", ""),
        "logo":           f"assets/apps/{slug}.{ext}",
        "motto":          app.get("motto", ""),
        "sales_pitch":    app.get("salesPitch", ""),
        "description":    app.get("description", ""),
        "features":       app.get("features", []) or [],
        "personas":       app.get("personas", []) or [],
        "links":          app.get("links", []) or [],
        "service":        app.get("service", {}) or {},
        "plans":          app.get("plans", []) or [],
        "is_builtin":     True,
    }


def _defaults() -> list[dict]:
    out = list(_DEFAULT_SITES)
    for app in _load_apps_json():
        p = _apps_json_to_product(app)
        if p:
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Normalisation d'un produit fourni par le client (formulaire d'edition)
# ---------------------------------------------------------------------------
_STR_FIELDS = (
    "name", "tagline", "description", "motto", "sales_pitch",
    "category", "pro_section", "tier", "kind",
    "price_from", "price_note", "buy_url", "exe_path",
    "featured_label", "logo", "color", "initial",
    "keywords", "prospect_pitch",
)
_NUM_FIELDS = ("price", "price_original")
_BOOL_FIELDS = ("installed", "coming_soon", "featured")
_LIST_FIELDS = ("features", "personas", "links", "plans")
_DICT_FIELDS = ("service",)


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or f"item-{int(time.time())}"


def _clean_product(raw: Any, *, existing_id: str = "") -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = (raw.get("name") or "").strip()
    if not name:
        return None
    pid = (raw.get("id") or existing_id or _slugify(name)).strip()
    out: dict = {"id": pid, "name": name}
    for f in _STR_FIELDS:
        if f == "name":
            continue
        v = raw.get(f)
        if v is None:
            continue
        if isinstance(v, str):
            out[f] = v.strip()
        else:
            out[f] = str(v)
    for f in _NUM_FIELDS:
        v = raw.get(f)
        if v is None or v == "":
            continue
        try:
            out[f] = float(v) if "." in str(v) else int(v)
        except (TypeError, ValueError):
            try:
                out[f] = float(v)
            except (TypeError, ValueError):
                pass
    for f in _BOOL_FIELDS:
        if f in raw:
            out[f] = bool(raw.get(f))
    for f in _LIST_FIELDS:
        v = raw.get(f)
        if isinstance(v, list):
            out[f] = v
    for f in _DICT_FIELDS:
        v = raw.get(f)
        if isinstance(v, dict):
            out[f] = v
    # is_builtin n'est pas editable depuis le client
    return out


def _clean_bundle(raw: Any, *, existing_id: str = "") -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = (raw.get("name") or "").strip()
    if not name:
        return None
    bid = (raw.get("id") or existing_id or _slugify("pack-" + name)).strip()
    product_ids = raw.get("product_ids") or []
    if not isinstance(product_ids, list):
        product_ids = []
    product_ids = [str(p).strip() for p in product_ids if str(p).strip()]
    out: dict = {
        "id":           bid,
        "name":         name,
        "tagline":      (raw.get("tagline") or "").strip(),
        "description":  (raw.get("description") or "").strip(),
        "logo":         (raw.get("logo") or "").strip(),
        "color":        (raw.get("color") or "#6366F1").strip(),
        "buy_url":      (raw.get("buy_url") or "").strip(),
        "price_note":   (raw.get("price_note") or "").strip(),
        "product_ids":  product_ids,
    }
    if raw.get("price") not in (None, ""):
        try:
            out["price"] = float(raw["price"]) if "." in str(raw["price"]) else int(raw["price"])
        except (TypeError, ValueError):
            pass
    return out


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def get_full() -> dict:
    """Renvoie {products, bundles, disabled_ids} prets pour le frontend.

    Produits = defauts merges avec overrides. Les `is_active` reflete les
    `disabled_ids`. Produits supprimes (deleted_ids) sont exclus.
    """
    state = _read()
    overrides = {p.get("id"): p for p in (state.get("products") or []) if isinstance(p, dict) and p.get("id")}
    deleted = {str(i) for i in (state.get("deleted_ids") or []) if i}
    disabled = {str(i) for i in (state.get("disabled_ids") or []) if i}

    products: list[dict] = []
    seen: set[str] = set()
    # 1) defauts merges avec overrides
    for d in _defaults():
        pid = d.get("id")
        if not pid or pid in deleted:
            continue
        merged = dict(d)
        if pid in overrides:
            ov = overrides[pid]
            for k, v in ov.items():
                if k == "id":
                    continue
                merged[k] = v
        merged["is_active"] = pid not in disabled
        products.append(merged)
        seen.add(pid)
    # 2) produits crees a la main (id non present dans les defauts)
    for pid, ov in overrides.items():
        if pid in seen or pid in deleted:
            continue
        prod = dict(ov)
        prod["is_active"] = pid not in disabled
        prod.setdefault("is_builtin", False)
        products.append(prod)

    bundles: list[dict] = []
    for b in (state.get("bundles") or []):
        if not isinstance(b, dict) or not b.get("id"):
            continue
        bb = dict(b)
        bb["is_active"] = bb.get("id") not in disabled
        bundles.append(bb)

    return {
        "products":     products,
        "bundles":      bundles,
        "disabled_ids": sorted(disabled),
    }


def save_product(payload: Any) -> dict:
    """Sauve un produit (cree ou met a jour). Renvoie le produit normalise."""
    p = _clean_product(payload)
    if p is None:
        return {"ok": False, "error": "invalid_product"}
    state = _read()
    items = [x for x in (state.get("products") or []) if isinstance(x, dict)]
    items = [x for x in items if x.get("id") != p["id"]]
    items.append(p)
    state["products"] = items
    # Si le produit etait dans deleted_ids, on le retire
    deleted = [i for i in (state.get("deleted_ids") or []) if i != p["id"]]
    if deleted != state.get("deleted_ids"):
        state["deleted_ids"] = deleted
    if _write(state):
        return {"ok": True, "product": p}
    return {"ok": False, "error": "write_failed"}


def delete_product(product_id: str) -> dict:
    pid = (product_id or "").strip()
    if not pid:
        return {"ok": False, "error": "no_id"}
    state = _read()
    state["products"] = [x for x in (state.get("products") or [])
                         if isinstance(x, dict) and x.get("id") != pid]
    # Si c'est un produit builtin, on le cache via deleted_ids
    builtin_ids = {d.get("id") for d in _defaults()}
    if pid in builtin_ids:
        deleted = set(state.get("deleted_ids") or [])
        deleted.add(pid)
        state["deleted_ids"] = sorted(deleted)
    if _write(state):
        return {"ok": True, "id": pid}
    return {"ok": False, "error": "write_failed"}


def save_bundle(payload: Any) -> dict:
    b = _clean_bundle(payload)
    if b is None:
        return {"ok": False, "error": "invalid_bundle"}
    state = _read()
    items = [x for x in (state.get("bundles") or []) if isinstance(x, dict)]
    items = [x for x in items if x.get("id") != b["id"]]
    items.append(b)
    state["bundles"] = items
    if _write(state):
        return {"ok": True, "bundle": b}
    return {"ok": False, "error": "write_failed"}


def delete_bundle(bundle_id: str) -> dict:
    bid = (bundle_id or "").strip()
    if not bid:
        return {"ok": False, "error": "no_id"}
    state = _read()
    state["bundles"] = [x for x in (state.get("bundles") or [])
                        if isinstance(x, dict) and x.get("id") != bid]
    if _write(state):
        return {"ok": True, "id": bid}
    return {"ok": False, "error": "write_failed"}


def set_active(item_id: str, active: bool) -> dict:
    """Toggle d'un produit OU d'un bundle. Reutilise la meme cle disabled_ids
    pour rester compatible avec catalog_overrides."""
    iid = (item_id or "").strip()
    if not iid:
        return {"ok": False, "error": "no_id"}
    state = _read()
    disabled = set(state.get("disabled_ids") or [])
    if active:
        disabled.discard(iid)
    else:
        disabled.add(iid)
    state["disabled_ids"] = sorted(disabled)
    if _write(state):
        # Compat : on miroir dans catalog_overrides aussi (au cas ou)
        try:
            from . import catalog_overrides
            catalog_overrides.set_disabled(iid, disabled=not active)
        except Exception:
            pass
        return {"ok": True, "id": iid, "active": active}
    return {"ok": False, "error": "write_failed"}
