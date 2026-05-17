"""Catalogue d'offres CENTRAL — partagé entre toutes les campagnes du Convoi.

Source unique de vérité pour la prospection IA. Renvoie la liste de produits
qu'on propose actuellement aux prospects, au format simple attendu par
convoy_runner / drip_runner / multichannel_followup / dormant_recycler.

Composition (par ordre de priorité) :
1. Catalogue principal Triskell (`catalog_central.get_full()`) : apps.json
   embarqué + sites hardcodés + overrides Supabase. Filtré par `is_active`.
2. Offres custom du Convoi (`shared_settings.convoy_catalog`) : entrées
   ajoutées manuellement pour la prospection. Si une entrée porte le même
   nom qu'un produit du catalogue principal, elle override son pitch
   (utile pour personnaliser le ton commercial sans toucher au catalogue).
3. Fichier local `~/.triskell-command/catalog.json` (miroir offline).
4. Liste DEFAULTS hardcodée (premier lancement, jamais connecté).

Le toggle on/off (`catalog_overrides.disabled_ids`) est respecté : un
produit désactivé dans le catalogue principal disparaît aussi de la
prospection — y compris pour les entrées custom dont le nom matche un
produit désactivé (best-effort par nom).

Format d'une entrée :
    {
        "name": "Pack Électricien Pro",
        "pitch": "Site web + outils métier pour électriciens",
        "keywords": "électricien, électricité, courant, BTP",
        "url": "https://pack-elec.triskell-studio.fr",
    }
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


SHARED_KEY = "convoy_catalog"
LOCAL_FILE = Path.home() / ".triskell-command" / "catalog.json"


# Offres par défaut au tout premier lancement (Jordan / Triskell Studio).
# Quand le produit sera vendu, ce default sera vidé / remplacé par un
# onboarding où le client saisit lui-même son catalogue.
DEFAULTS: list[dict[str, str]] = [
    {
        "name": "Pack Électricien Pro",
        "pitch": "Site web + outils métier pour électriciens",
        "keywords": "électricien, électricité, courant, BTP, artisan bâtiment",
        "url": "https://pack-elec.triskell-studio.fr",
    },
    {
        "name": "Triskell Studio (sites)",
        "pitch": "Site vitrine clé en main pour artisans et commerçants",
        "keywords": "artisan, commerçant, plombier, paysagiste, garagiste, "
                    "salon, restaurant, boulangerie",
        "url": "https://triskell-studio.fr",
    },
    {
        "name": "Le Dénicheur",
        "pitch": "Outil de prospection desktop, paiement unique 129 €",
        "keywords": "agence, freelance, prospection, growth, marketing, B2B",
        "url": "https://denicheur.triskell-studio.fr",
    },
]


# ---------------------------------------------------------------------------
# Backend Supabase (best-effort)
# ---------------------------------------------------------------------------
def _supabase_client():
    """Renvoie le client Supabase si auth, sinon None."""
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        if c.is_authenticated:
            return c
        return None
    except ImportError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers : normalisation d'une entrée catalogue
# ---------------------------------------------------------------------------
def _clean_entry(raw: Any) -> dict[str, str] | None:
    """Normalise une entrée en dict de strings non-nulles. Renvoie None si
    l'entrée n'a même pas de nom (inutilisable)."""
    if not isinstance(raw, dict):
        return None
    name = (raw.get("name") or "").strip()
    if not name:
        return None
    return {
        "name": name,
        "pitch": (raw.get("pitch") or "").strip(),
        "keywords": (raw.get("keywords") or "").strip(),
        "url": (raw.get("url") or "").strip(),
    }


def _clean_catalog(items: Any) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, str]] = []
    for raw in items:
        c = _clean_entry(raw)
        if c is not None:
            out.append(c)
    return out


def _norm_name(n: str) -> str:
    """Pour le matching tolérant entre catalogues."""
    return (n or "").strip().casefold()


# ---------------------------------------------------------------------------
# Conversion catalogue principal -> format prospection
# ---------------------------------------------------------------------------
def _product_to_prospect_entry(p: dict) -> dict[str, str] | None:
    """Map un produit `catalog_central` au format simple de la prospection.

    Priorise les champs dédiés à la prospection (`prospect_pitch`, `keywords`)
    s'ils sont remplis, sinon retombe sur les champs commerciaux du produit.
    """
    name = (p.get("name") or "").strip()
    if not name:
        return None
    pitch = (
        (p.get("prospect_pitch") or "").strip()
        or (p.get("sales_pitch") or "").strip()
        or (p.get("tagline") or "").strip()
        or (p.get("motto") or "").strip()
    )
    keywords = (p.get("keywords") or "").strip()
    if not keywords:
        bits = [name]
        if p.get("category"):
            bits.append(str(p["category"]))
        if p.get("tagline"):
            bits.append(str(p["tagline"]))
        keywords = ", ".join(bits)
    url = (p.get("buy_url") or "").strip()
    return {
        "name":     name,
        "pitch":    pitch,
        "keywords": keywords,
        "url":      url,
    }


def _load_main_catalog_entries() -> tuple[list[dict[str, str]], set[str]]:
    """Charge les produits actifs du catalogue principal au format prospection.

    Renvoie (entries, disabled_names_normalisés) — le 2e élément sert à
    filtrer aussi les éventuelles entrées custom du convoy_catalog dont le
    nom matche un produit désactivé.
    """
    try:
        from . import catalog_central
        full = catalog_central.get_full() or {}
    except Exception as exc:
        logger.debug("catalog_central indisponible : %s", exc)
        return [], set()

    products = full.get("products") or []
    disabled_names: set[str] = set()
    entries: list[dict[str, str]] = []
    for p in products:
        if not isinstance(p, dict):
            continue
        name = (p.get("name") or "").strip()
        if not name:
            continue
        if not p.get("is_active", True):
            disabled_names.add(_norm_name(name))
            continue
        entry = _product_to_prospect_entry(p)
        if entry is not None:
            entries.append(entry)
    return entries, disabled_names


# ---------------------------------------------------------------------------
# Lecture / écriture local
# ---------------------------------------------------------------------------
def _load_local() -> list[dict[str, str]] | None:
    """Lit le catalogue depuis le fichier local. Renvoie None si absent
    OU illisible (pour permettre un fallback explicite aux DEFAULTS)."""
    if not LOCAL_FILE.exists():
        return None
    try:
        data = json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("items", [])
        items = _clean_catalog(data)
        return items if items else None
    except Exception as exc:
        logger.warning("Lecture catalogue local impossible : %s", exc)
        return None


def _save_local(items: list[dict[str, str]]) -> bool:
    """Écrit le catalogue dans le fichier local (UTF-8 atomique)."""
    try:
        LOCAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {"items": items}
        tmp = LOCAL_FILE.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(LOCAL_FILE)
        return True
    except Exception as exc:
        logger.warning("Écriture catalogue local impossible : %s", exc)
        return False


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def get_catalog() -> list[dict[str, str]]:
    """Renvoie le catalogue actuellement proposé en prospection.

    Union du catalogue principal Triskell (produits is_active) + des
    entrées custom du convoy_catalog Supabase, dédupliqué par nom (priorité
    aux entrées custom : si Jordan a re-pitché un produit pour la prospection,
    on prend son texte). Filtre les noms désactivés via `catalog_overrides`.

    Si rien n'est disponible (jamais connecté + pas de cache local) → DEFAULTS.
    Le résultat est TOUJOURS une liste (jamais None), même vide.
    """
    # 1. Catalogue principal Triskell (apps.json + sites + overrides Supabase)
    main_entries, disabled_names = _load_main_catalog_entries()

    # 2. Catalogue custom Convoi (Supabase ou local fallback)
    custom_entries: list[dict[str, str]] = []
    sb = _supabase_client()
    if sb is not None:
        try:
            raw = sb.get_shared_setting(SHARED_KEY, {}) or {}
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            items_raw = raw.get("items") if isinstance(raw, dict) else None
            custom_entries = _clean_catalog(items_raw)
            if custom_entries:
                _save_local(custom_entries)
        except Exception as exc:
            logger.debug("get_catalog Supabase a échoué : %s", exc)
    if not custom_entries:
        custom_entries = _load_local() or []

    # 3. Fusion priorité aux entrées custom (override par nom)
    if main_entries or custom_entries:
        merged: dict[str, dict[str, str]] = {}
        for e in main_entries:
            merged[_norm_name(e["name"])] = e
        for e in custom_entries:
            key = _norm_name(e["name"])
            if key in disabled_names:
                continue  # produit désactivé dans le catalogue principal
            merged[key] = e
        # On retire aussi les entrées dont le nom est désactivé (au cas où elles
        # viendraient uniquement du catalogue principal et auraient slippé)
        return [v for k, v in merged.items() if k not in disabled_names]

    # 4. Defaults (premier lancement, jamais connecté)
    return [dict(o) for o in DEFAULTS]


def set_catalog(items: list[dict[str, str]]) -> bool:
    """Enregistre le catalogue central (Supabase + miroir local).

    Renvoie True si AU MOINS une persistance a réussi.
    """
    cleaned = _clean_catalog(items)

    ok_remote = False
    sb = _supabase_client()
    if sb is not None:
        try:
            sb.set_shared_setting(SHARED_KEY, {"items": cleaned})
            ok_remote = True
        except Exception as exc:
            logger.warning("set_catalog Supabase a échoué : %s", exc)

    ok_local = _save_local(cleaned)

    return ok_remote or ok_local


def is_default(items: list[dict[str, str]] | None = None) -> bool:
    """Renvoie True si le catalogue courant est encore aux valeurs par défaut
    (utile pour proposer un onboarding au premier lancement)."""
    if items is None:
        items = get_catalog()
    if len(items) != len(DEFAULTS):
        return False
    for a, b in zip(items, DEFAULTS):
        if (a.get("name") or "") != b.get("name", ""):
            return False
    return True
