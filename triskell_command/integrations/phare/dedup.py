"""Anti-doublons des actions Le Phare.

Le bug d'origine : chaque passage d'un agent (audit du lundi, plan du mois…)
réinsérait ses recommandations sans regarder ce qui existait déjà → des
cartes en double dans « À toi de jouer » (constaté le 12/06/2026 : 14 cartes
pour 9 sujets sur Pixel Pros, 263 actions ouvertes au total).

Stratégie — comparaison de titres normalisés, trois règles :
  1. même site + même agent + titres très proches (ratio ≥ 0.70) → doublon ;
  2. même site + même agent + titres moyennement proches (ratio ≥ 0.50)
     MAIS même page visée ET même type de balise/outil → doublon
     (attrape « Corriger le title de /demo » vs « Réécrire le title de /demo ») ;
  3. même site + agents différents : doublon seulement si quasi identiques
     (ratio ≥ 0.92) — on ne fusionne pas deux angles différents.

On ne recrée pas non plus une action :
  - qu'un humain a refusée il y a moins de 60 jours (respect du choix) ;
  - qui a été validée il y a moins de 14 jours (laisser le temps au crawl
    de voir le changement).

Tout est volontairement déterministe (pas d'appel IA) : testable hors ligne
par scripts/smoke_phare_apply.py.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Statuts considérés « ouverts » (l'action est encore dans le bac à valider)
OPEN_STATUSES = ("draft", "preview", "pending_review", "checks_ok", "checks_ko")

# Fenêtres de silence après décision humaine / publication
REJECTED_QUIET_DAYS = 60
MERGED_QUIET_DAYS = 14

# Seuils de similarité (calés sur les doublons réels du stock du 12/06/2026 :
# les variantes title-/demo et PageSpeed tombent à 0.478-0.496, le faux
# positif de référence — title home vs noindex légales — à 0.308 ; la règle
# ciblée exige EN PLUS la même page et la même famille de balise)
SAME_AGENT_RATIO = 0.70
SAME_AGENT_TARGETED_RATIO = 0.42
CROSS_AGENT_RATIO = 0.92

# Familles de balises / outils repérables dans un titre ou un détail.
# Sert à la règle 2 : deux formulations différentes qui visent la même
# balise sur la même page sont un seul et même sujet.
_FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "title": ("title", "titre"),
    "meta": ("meta description", "meta-description", "metadescription", "meta desc"),
    "canonical": ("canonical",),
    "noindex": ("noindex", "robots"),
    "h1": ("h1",),
    "schema": ("schema", "json-ld", "jsonld", "donnees structurees"),
    "sitemap": ("sitemap",),
    "pagespeed": ("pagespeed", "page speed", "lighthouse", "cwv", "core web vitals"),
    "alt": ("balise alt", "attribut alt", "texte alternatif"),
    "gsc": ("search console",),
    "maillage": ("maillage", "liens internes"),
}

_URL_RE = re.compile(r"https?://[^\s,;)\]»]+", re.IGNORECASE)
_PATH_RE = re.compile(r"(?<![\w:/])/[a-z0-9][a-z0-9_\-./]*", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s/]", re.UNICODE)


def normalize_title(s: str) -> str:
    """Minuscule, sans accents ni ponctuation, espaces tassés."""
    s = (s or "").lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _PUNCT_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()


def title_ratio(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def extract_paths(text: str) -> set[str]:
    """Chemins de pages mentionnés (« /configurer?option=seo » → « /configurer »)."""
    out: set[str] = set()
    text = text or ""
    for m in _URL_RE.findall(text):
        try:
            p = urlparse(m).path or "/"
        except ValueError:
            continue
        out.add(_clean_path(p))
    for m in _PATH_RE.findall(text):
        out.add(_clean_path(m))
    return {p for p in out if p}


def _clean_path(p: str) -> str:
    p = (p or "").split("?")[0].split("#")[0].strip().lower()
    # On écarte ce qui ressemble à un fichier de code mentionné par hasard
    if p.endswith((".js", ".css", ".py", ".png", ".jpg", ".svg")):
        return ""
    if p != "/" and p.endswith("/"):
        p = p[:-1]
    return p


def extract_fields(text: str) -> set[str]:
    """Familles de balises/outils mentionnées dans un texte."""
    norm = normalize_title(text)
    found: set[str] = set()
    for family, hints in _FIELD_HINTS.items():
        for h in hints:
            if normalize_title(h) in norm:
                found.add(family)
                break
    return found


def is_duplicate(new_action: dict, existing: dict) -> bool:
    """Les deux actions parlent-elles du même sujet ?"""
    if (new_action.get("site_id") or "") != (existing.get("site_id") or ""):
        return False
    r = title_ratio(new_action.get("title") or "", existing.get("title") or "")
    same_agent = (new_action.get("agent") or "") == (existing.get("agent") or "")
    if not same_agent:
        return r >= CROSS_AGENT_RATIO
    if r >= SAME_AGENT_RATIO:
        return True
    if r < SAME_AGENT_TARGETED_RATIO:
        return False
    # Règle ciblée : même page visée + même famille de balise/outil
    new_text = f"{new_action.get('title') or ''}\n{new_action.get('detail_md') or ''}"
    old_text = f"{existing.get('title') or ''}\n{existing.get('detail_md') or ''}"
    paths_new, paths_old = extract_paths(new_text), extract_paths(old_text)
    fields_new, fields_old = extract_fields(new_text), extract_fields(old_text)
    if not (fields_new & fields_old):
        return False
    if paths_new and paths_old:
        return bool(paths_new & paths_old)
    # Aucun chemin des deux côtés (conseils « global ») : la famille suffit
    return not paths_new and not paths_old


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def blocks_reinsert(existing: dict, *, now: Optional[datetime] = None) -> bool:
    """Cette action existante doit-elle empêcher une réinsertion ?

    - ouverte → oui ;
    - refusée il y a < 60 j → oui (on respecte le refus de Jordan) ;
    - validée il y a < 14 j → oui (le crawl n'a pas encore vu le changement) ;
    - sinon (vieille, expirée, archivée…) → non.
    """
    now = now or datetime.now(timezone.utc)
    status = (existing.get("status") or "").lower()
    if status in OPEN_STATUSES:
        return True
    if status == "rejected":
        dt = _parse_dt(existing.get("rejected_at")) or _parse_dt(existing.get("created_at"))
        return bool(dt and (now - dt) < timedelta(days=REJECTED_QUIET_DAYS))
    if status == "merged":
        dt = _parse_dt(existing.get("merged_at")) or _parse_dt(existing.get("created_at"))
        return bool(dt and (now - dt) < timedelta(days=MERGED_QUIET_DAYS))
    return False


def find_blocking_duplicate(candidates: list[dict], new_action: dict) -> Optional[dict]:
    """Parmi des actions existantes, la première qui rend l'insertion inutile."""
    for existing in candidates or []:
        try:
            if blocks_reinsert(existing) and is_duplicate(new_action, existing):
                return existing
        except Exception as exc:  # une fiche malformée ne bloque jamais l'insertion
            logger.debug("dedup candidate KO: %s", exc)
    return None


def group_duplicates(actions: list[dict]) -> list[list[dict]]:
    """Regroupe une liste d'actions (même site) en grappes de doublons.

    Utilisé par le script de nettoyage du stock. Chaque grappe est triée
    par date de création décroissante (la plus récente d'abord = celle
    qu'on garde).
    """
    remaining = list(actions or [])
    remaining.sort(key=lambda a: str(a.get("created_at") or ""), reverse=True)
    groups: list[list[dict]] = []
    used: set[int] = set()
    for i, a in enumerate(remaining):
        if i in used:
            continue
        group = [a]
        used.add(i)
        for j in range(i + 1, len(remaining)):
            if j in used:
                continue
            b = remaining[j]
            # Doublon de N'IMPORTE QUEL membre de la grappe (transitif)
            if any(is_duplicate(b, member) for member in group):
                group.append(b)
                used.add(j)
        groups.append(group)
    return groups
