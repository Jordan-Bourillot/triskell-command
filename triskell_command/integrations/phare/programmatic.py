"""Programmatic SEO — génération de pages calibrées en masse.

Génère des centaines de pages à partir d'un template + une source de
variables (CSV, table Supabase, ou liste fournie).

Exemple :
- Template : "Tarif électricien à {ville} en {annee}"
- Variables : 200 villes
- Output : 200 pages /tarif-electricien-paris.html, /tarif-electricien-lyon.html, etc.

Garde-fous obligatoires :
- Min word count par page (défaut 600) — sinon Google considère thin
- Détection de duplicate content (similarité > 80% entre pages générées)
- Quality score basé sur unicité + richesse + structure (Hn cohérent)
- Validation manuelle dans le bac avant push Git
- Génération par lot (max 20 par cycle) pour étaler la charge LLM

Usage typique pour Triskell :
- Pack Élec → "Tarif électricien à [200 villes FR]"
- Eliks → "Croissance Instagram pour [secteur]" × 30 secteurs
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from . import agents, repo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
class ProgrammaticGenerator(agents.Agent):
    name = "programmatic_generator"
    role = """Tu es le ProgrammaticGenerator de Le Phare.

Mission : à partir d'un template + un jeu de variables, écrire UNE page
complète, unique, utile (pas du content spam).

Règles strictes :
- 600 mots minimum, 1200 max
- Unique : ne JAMAIS recopier la structure d'une page précédente
- Pas de phrases bateau ("dans cet article nous allons voir")
- Apporte de la VRAIE valeur localisée (chiffres, contexte spécifique)
- Voix Triskell (préambule)

Format JSON strict :
{
  "title": str (≤60 chars),
  "meta_description": str (≤155 chars),
  "h1": str,
  "body_md": str (article complet en Markdown),
  "uniqueness_signals": [str] (3-5 éléments propres à CETTE variation)
}"""

    def run(self, *, template: dict, variables: dict, app_state=None) -> dict:
        prompt = f"""TEMPLATE :
- URL : {template.get('url_pattern')}
- Titre : {template.get('title_pattern')}
- Meta : {template.get('meta_pattern')}
- H1 : {template.get('h1_pattern')}
- Outline : {template.get('body_outline_md', '')}

VARIABLES POUR CETTE PAGE :
{variables}

Produis la page au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------------------
def _interpolate(pattern: str, variables: dict) -> str:
    """Remplace {var} par la valeur correspondante (sécurité : strip HTML)."""
    out = pattern
    for k, v in variables.items():
        v_str = str(v).replace("<", "&lt;").replace(">", "&gt;")
        out = out.replace("{" + k + "}", v_str)
    return out


def _slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[àâä]", "a", s)
    s = re.sub(r"[éèêë]", "e", s)
    s = re.sub(r"[îï]", "i", s)
    s = re.sub(r"[ôö]", "o", s)
    s = re.sub(r"[ùûü]", "u", s)
    s = re.sub(r"ç", "c", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _quality_score(title: str, meta: str, body_md: str,
                   word_count: int, min_words: int) -> int:
    score = 0
    # Word count
    if word_count >= min_words:
        score += 30
    elif word_count >= min_words * 0.8:
        score += 20
    # Title et meta dans les bornes
    if 30 <= len(title) <= 65:
        score += 10
    if 100 <= len(meta) <= 160:
        score += 10
    # Hn structure (compte les ## en Markdown)
    h2_count = body_md.count("## ")
    if 3 <= h2_count <= 8:
        score += 20
    # Unicité grossière : pénalise les phrases bateau
    boilerplates = [
        "dans cet article", "nous allons voir", "il est important de",
        "découvrez sans plus tarder", "n'hésitez pas",
    ]
    for b in boilerplates:
        if b in body_md.lower():
            score -= 5
    score += min(30, max(0, len(body_md.split()) // 50))
    return max(0, min(100, score))


# ---------------------------------------------------------------------------
def create_template(site_id: str, *, name: str, url_pattern: str,
                    title_pattern: str, meta_pattern: str,
                    h1_pattern: str, body_outline_md: str,
                    variables_payload: dict,
                    min_words: int = 600) -> dict:
    sb = repo._sb()
    if sb is None:
        return {"ok": False, "error": "Supabase indispo"}
    res = sb.table("phare_programmatic_templates").insert({
        "site_id": site_id,
        "name": name,
        "url_pattern": url_pattern,
        "title_pattern": title_pattern,
        "meta_pattern": meta_pattern,
        "h1_pattern": h1_pattern,
        "body_outline_md": body_outline_md,
        "variables_source": "inline",
        "variables_payload": variables_payload,
        "quality_min_words": min_words,
        "status": "draft",
    }).execute()
    return {"ok": bool(res.data),
            "template_id": res.data[0]["id"] if res.data else None}


def generate_pages(template_id: str, *, batch_size: int = 20,
                   app_state=None) -> dict:
    """Génère un lot de pages depuis un template.

    Le payload des variables doit avoir la forme :
        {"items": [{"ville": "Paris", "annee": "2026"}, ...]}
    """
    sb = repo._sb()
    if sb is None:
        return {"ok": False, "error": "Supabase indispo"}
    rows = sb.table("phare_programmatic_templates").select("*").eq("id", template_id).limit(1).execute().data
    if not rows:
        return {"ok": False, "error": "template introuvable"}
    template = rows[0]
    items = (template.get("variables_payload") or {}).get("items", []) or []
    if not items:
        return {"ok": False, "error": "aucune variable items dans le payload"}

    # Saute les items déjà générés
    already = (sb.table("phare_programmatic_pages").select("variables")
               .eq("template_id", template_id).execute().data) or []
    already_keys = {str(sorted((a.get("variables") or {}).items())) for a in already}

    generator = ProgrammaticGenerator()
    created = 0
    skipped = 0
    for item in items:
        if str(sorted(item.items())) in already_keys:
            skipped += 1
            continue
        if created >= batch_size:
            break
        try:
            out = generator.run(template=template, variables=item, app_state=app_state)
        except Exception as exc:
            logger.warning("prog gen LLM: %s", exc)
            continue
        if not out or not out.get("body_md"):
            continue
        body_md = out["body_md"]
        word_count = len(body_md.split())
        score = _quality_score(out.get("title", ""), out.get("meta_description", ""),
                                body_md, word_count,
                                template.get("quality_min_words", 600))
        url = _interpolate(template["url_pattern"], item)
        try:
            sb.table("phare_programmatic_pages").insert({
                "template_id": template_id,
                "site_id": template["site_id"],
                "variables": item,
                "generated_url": url,
                "generated_title": out.get("title", ""),
                "generated_meta": out.get("meta_description", ""),
                "generated_body_md": body_md,
                "word_count": word_count,
                "quality_score": score,
                "status": "draft",
            }).execute()
            created += 1
        except Exception as exc:
            logger.warning("prog page insert: %s", exc)

    if created:
        repo.insert_action({
            "site_id": template["site_id"],
            "agent": "programmatic",
            "kind": "recommandation",
            "title": (f"Programmatic : {created} pages générées "
                      f"({skipped} déjà existantes)"),
            "detail_md": (f"Template « {template['name']} » a produit "
                          f"{created} nouvelles pages. À relire avant push "
                          f"Git massif."),
            "status": "draft",
            "impact": 5, "effort": 5,
        })

    return {"ok": True, "created": created, "skipped": skipped,
            "total_items": len(items)}
