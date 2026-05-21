"""Lecture des templates de prospection (table triskell_email_templates,
category='prospection') pour les utiliser dans le Convoi.

Le Convoi peut "piocher" dans une liste de templates rédigés à la main
pour un produit donné, au lieu de laisser l'IA générer chaque mail
from scratch. Ce module fournit les fonctions de lecture nécessaires.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _sb():
    """Réutilise le client Supabase de l'intégration lagriffe (qui hé-
    berge déjà le repo des templates, par convention historique)."""
    try:
        from .lagriffe.repo import _sb as lagriffe_sb
        return lagriffe_sb()
    except Exception as exc:
        logger.debug("prospection_templates._sb fallback: %s", exc)
        return None


# Labels lisibles des produits déjà connus de Triskell. Pour un produit
# inconnu (custom Pixel Pros, etc.), on affichera le slug brut tel quel.
KNOWN_PRODUCT_LABELS = {
    "lagriffe":  "Lagriffe Studio",
    "rankus":    "RankUs Studio",
    "wow":       "Studio WoW",
    "pixelpros": "Pixel Pros",
    "shared":    "Triskell (transversal)",
}


def list_products_with_prospection_templates() -> dict:
    """Renvoie {ok, products: [{product, label, count}]} : les produits qui
    ont au moins UN template de prospection activé. Sert au sélecteur UI."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré", "products": []}
    try:
        rows = (sb.table("triskell_email_templates")
                  .select("product, enabled")
                  .eq("category", "prospection")
                  .execute().data or [])
        counts: dict[str, int] = {}
        for r in rows:
            if r.get("enabled") is False:
                continue
            p = (r.get("product") or "").strip() or "shared"
            counts[p] = counts.get(p, 0) + 1
        products = [
            {
                "product": p,
                "label":   KNOWN_PRODUCT_LABELS.get(p, p),
                "count":   c,
            }
            for p, c in sorted(counts.items())
        ]
        return {"ok": True, "products": products}
    except Exception as exc:
        logger.warning("prospection_templates.list_products: %s", exc)
        return {"ok": False, "error": str(exc), "products": []}


def list_prospection_templates(product: str) -> list[dict]:
    """Liste les templates 'prospection' d'un produit (activés uniquement).

    Chaque dict contient les champs utiles pour l'IA :
    - key, label, description, subject, body_text, placeholders.
    """
    if not product:
        return []
    sb = _sb()
    if sb is None:
        return []
    try:
        rows = (sb.table("triskell_email_templates")
                  .select("key, label, description, subject, body_text, "
                          "body_html, placeholders, enabled, category, product")
                  .eq("product", product.strip())
                  .eq("category", "prospection")
                  .execute().data or [])
        return [r for r in rows if r.get("enabled") is not False]
    except Exception as exc:
        logger.warning("prospection_templates.list(%s): %s", product, exc)
        return []
