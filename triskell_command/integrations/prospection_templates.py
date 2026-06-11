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


_AUDIENCE_LABELS = {
    "creator": "Créateurs",
    "pro":     "Pros",
}


def list_products_with_prospection_templates() -> dict:
    """Renvoie {ok, products: [{product, label, count, audience}]} : entrées
    par (produit, audience) pour le sélecteur UI du Convoi.

    Format du `product` retourné :
      - `pixel-pros#creator` si le produit a des templates des deux audiences,
        ou explicitement des templates avec audience='creator'.
      - `pixel-pros#pro` idem côté pros.
      - `pixel-pros` (sans suffixe) en rétrocompat si le produit n'a que des
        templates sans audience définie OU une seule audience.

    Le composeur de campagne peut donc proposer « Pixel Pros · Créateurs » et
    « Pixel Pros · Pros » comme deux choix distincts dans la même liste. Côté
    runner, `list_prospection_templates(product#audience)` parse le suffixe et
    filtre.
    """
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré", "products": []}
    try:
        rows = (sb.table("triskell_email_templates")
                  .select("product, audience, enabled")
                  .eq("category", "prospection")
                  .execute().data or [])
        # {(product, audience): count}
        counts: dict[tuple[str, str], int] = {}
        for r in rows:
            if r.get("enabled") is False:
                continue
            p = (r.get("product") or "").strip() or "shared"
            aud = (r.get("audience") or "creator").strip().lower()
            if aud not in ("creator", "pro"):
                aud = "creator"
            counts[(p, aud)] = counts.get((p, aud), 0) + 1

        # Regroupe par produit
        by_product: dict[str, dict[str, int]] = {}
        for (p, aud), c in counts.items():
            by_product.setdefault(p, {})[aud] = c

        products: list[dict] = []
        for p in sorted(by_product.keys()):
            base_label = KNOWN_PRODUCT_LABELS.get(p, p)
            auds = by_product[p]
            if len(auds) == 1:
                # Une seule audience → entrée simple (rétrocompat : pas de
                # suffixe si c'est uniquement 'creator', pour préserver les
                # campagnes existantes qui ont stocké `template_product=p`).
                only_aud, c = next(iter(auds.items()))
                if only_aud == "creator":
                    products.append({"product": p, "label": base_label,
                                     "count": c, "audience": "creator"})
                else:
                    products.append({
                        "product":  f"{p}#{only_aud}",
                        "label":    f"{base_label} · {_AUDIENCE_LABELS[only_aud]}",
                        "count":    c,
                        "audience": only_aud,
                    })
            else:
                # Plusieurs audiences → une entrée par audience
                for aud in ("creator", "pro"):
                    if aud not in auds:
                        continue
                    products.append({
                        "product":  f"{p}#{aud}",
                        "label":    f"{base_label} · {_AUDIENCE_LABELS[aud]}",
                        "count":    auds[aud],
                        "audience": aud,
                    })
        return {"ok": True, "products": products}
    except Exception as exc:
        logger.warning("prospection_templates.list_products: %s", exc)
        return {"ok": False, "error": str(exc), "products": []}


def list_prospection_templates(product: str,
                               audience: str = "") -> list[dict]:
    """Liste les templates 'prospection' d'un produit (activés uniquement).

    Args:
        product : slug produit. Accepte soit la forme simple (`pixel-pros`)
            soit la forme composite avec audience (`pixel-pros#pro`,
            `pixel-pros#creator`) telle que retournée par
            `list_products_with_prospection_templates`.
        audience : override explicite — si fourni, prime sur ce qui est
            extrait du slug composite. 'creator' / 'pro' / "" (vide = pas
            de filtre). Les templates sans audience définie sont considérés
            comme 'creator' (les 5 historiques Pixel Pros, migrés par la 34_).

    Chaque dict contient les champs utiles pour l'IA :
    - key, label, description, subject, body_text, placeholders, audience.
    Plus `from_address` : l'adresse d'expéditeur EXIGÉE par le modèle
    (câblage modèle→adresse). Vide = pas d'exigence, le moteur choisit
    librement dans son pool d'adresses.
    """
    if not product:
        return []
    # Parse le slug composite `pixel-pros#pro` → product=pixel-pros, aud=pro
    p_clean = product.strip()
    if "#" in p_clean and not audience:
        p_clean, aud_from_slug = p_clean.split("#", 1)
        audience = aud_from_slug
    elif "#" in p_clean:
        p_clean = p_clean.split("#", 1)[0]
    product = p_clean

    sb = _sb()
    if sb is None:
        return []
    try:
        rows = (sb.table("triskell_email_templates")
                  .select("key, label, description, subject, body_text, "
                          "body_html, placeholders, enabled, category, "
                          "product, audience, from_address")
                  .eq("product", product.strip())
                  .eq("category", "prospection")
                  .execute().data or [])
        active = [r for r in rows if r.get("enabled") is not False]
        if not audience:
            return active
        aud = audience.strip().lower()
        if aud not in ("creator", "pro"):
            return active
        # Filtre par audience. Les templates sans audience définie tombent
        # dans 'creator' par convention (les 5 historiques).
        return [r for r in active
                if (r.get("audience") or "creator").lower() == aud]
    except Exception as exc:
        logger.warning("prospection_templates.list(%s, %s): %s",
                       product, audience, exc)
        return []
