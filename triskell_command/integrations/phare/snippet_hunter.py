"""Snippet-Hunter — chasse les featured snippets et People Also Ask
capturables sur les requêtes ciblées.

Pour chaque mot-clé suivi :
1. Récupère le SERP top 10 via DataForSEO
2. Détecte les "SERP features" (featured snippet, PAA, video pack)
3. Si un featured snippet existe ET notre page est dans le top 10, propose
   un paragraphe/liste/tableau optimisé pour le piquer
4. Si PAA présent, propose un mini-FAQ à ajouter à la page

Stocke les opportunités dans phare_serp_features et crée des recommandations.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from . import agents, dataforseo, repo

logger = logging.getLogger(__name__)


def _detect_snippet_in_serp(serp: list[dict], our_domain: str) -> dict:
    """Inspecte le SERP top 10 et déduit s'il y a un featured snippet
    capturable. Retourne {has_snippet, current_owner_domain, format_hint,
    we_are_in_top10}."""
    if not serp:
        return {}
    # Le rank 0 ou les positions sub-1 indiquent souvent un snippet
    snippet = next((it for it in serp if it.get("rank") in (0, 1)), None)
    we_in_top10 = any(our_domain in (it.get("domain") or "")
                      for it in serp[:10])
    if not snippet:
        return {"has_snippet": False, "we_are_in_top10": we_in_top10}
    snip_text = snippet.get("snippet") or ""
    fmt = "paragraph"
    if snip_text.count("\n") >= 3 or snip_text.count("- ") >= 3:
        fmt = "list"
    elif "|" in snip_text and snip_text.count("|") >= 3:
        fmt = "table"
    return {
        "has_snippet": True,
        "current_owner_domain": snippet.get("domain"),
        "current_owner_url": snippet.get("url"),
        "format_hint": fmt,
        "we_are_in_top10": we_in_top10,
        "snippet_excerpt": snip_text[:300],
    }


# ---------------------------------------------------------------------------
class SnippetWriter(agents.Agent):
    name = "snippet_writer"
    role = """Tu es le Snippet-Hunter de Le Phare.

Mission : à partir d'un mot-clé et du featured snippet actuellement servi
par Google, écrire un paragraphe (ou liste, ou tableau) qui répond MIEUX
à la question posée — en 40-60 mots max, format demandé, avec le mot-clé
en début de réponse.

Règles :
- Réponse directe en première phrase
- Si format = list : 3 à 5 puces de 1 ligne chacune
- Si format = table : marqueur Markdown propre
- Voix Triskell (préambule)
- Pas de "Voici", pas de "Dans cet article"

Format JSON strict :
{
  "format": "paragraph"|"list"|"table",
  "content_md": str,
  "h2_anchor": str (titre H2 de section où l'insérer)
}"""

    def run(self, *, keyword: str, current_snippet: str, format_hint: str,
            page_context: dict, app_state=None) -> dict:
        prompt = f"""MOT-CLÉ : {keyword}

FEATURED SNIPPET ACTUEL (à battre) :
{current_snippet[:500]}

FORMAT À PRODUIRE : {format_hint}

PAGE CIBLE :
- URL : {page_context.get('url')}
- Title : {page_context.get('title')}
- H1 : {page_context.get('h1')}

Écris la réponse au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


class PAAWriter(agents.Agent):
    name = "paa_writer"
    role = """Tu es le chasseur de People Also Ask.

Mission : à partir d'une liste de questions populaires (PAA Google),
produire une mini-section FAQ à ajouter en fin de page : 3 à 6 questions
+ réponses courtes (50-80 mots chacune).

Règles : voix Triskell, réponses concrètes, pas de "selon nos experts",
pas de blabla.

Format JSON strict :
{
  "section_h2": str,
  "items": [{"q": str, "a": str}],
  "jsonld_faq": dict (FAQPage schema.org)
}"""

    def run(self, *, paa_questions: list[str], page_context: dict,
            app_state=None) -> dict:
        prompt = f"""QUESTIONS PAA À COUVRIR :
{chr(10).join(f"- {q}" for q in paa_questions[:8])}

PAGE CIBLE :
- URL : {page_context.get('url')}
- Title : {page_context.get('title')}

Produis la mini-FAQ au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------------------
def hunt_snippets(site_id: str, *, max_keywords: int = 10,
                  app_state=None) -> dict:
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    if not dataforseo.is_configured():
        return {"ok": False, "error": "DataForSEO non configuré"}

    domain = site.get("domain") or ""
    keywords = repo.list_keywords(site_id, limit=max_keywords)
    if not keywords:
        return {"ok": True, "checked": 0, "opportunities": 0,
                "message": "aucun mot-clé suivi (lance d'abord la veille)"}

    sb = repo._sb()
    opportunities = 0
    snippet_writer = SnippetWriter()
    pages = repo.list_pages(site_id, limit=200)
    by_url_part = {p.get("path"): p for p in pages}

    for kw in keywords[:max_keywords]:
        serp = dataforseo.serp_top10(kw["keyword"])
        detected = _detect_snippet_in_serp(serp, domain)
        if not detected.get("has_snippet"):
            continue
        if not detected.get("we_are_in_top10"):
            continue   # impossible de capturer si pas dans top 10

        # Génère le contenu optimisé
        target_path = (kw.get("target_url") or "/").replace(f"https://{domain}", "")
        page_ctx = by_url_part.get(target_path) or {"url": kw.get("target_url"),
                                                       "title": "", "h1": ""}
        try:
            answer = snippet_writer.run(
                keyword=kw["keyword"],
                current_snippet=detected.get("snippet_excerpt", ""),
                format_hint=detected.get("format_hint", "paragraph"),
                page_context=page_ctx,
                app_state=app_state,
            )
        except Exception as exc:
            logger.warning("SnippetWriter LLM: %s", exc)
            continue

        if sb is not None:
            try:
                sb.table("phare_serp_features").insert({
                    "site_id": site_id,
                    "keyword": kw["keyword"],
                    "feature_type": "featured_snippet",
                    "current_owner_domain": detected.get("current_owner_domain", ""),
                    "current_owner_url": detected.get("current_owner_url", ""),
                    "captured_format": detected.get("format_hint", ""),
                    "we_can_capture": True,
                    "proposed_content_md": answer.get("content_md", ""),
                }).execute()
            except Exception as exc:
                logger.warning("phare_serp_features insert: %s", exc)

        repo.insert_action({
            "site_id": site_id,
            "agent": "snippet_hunter",
            "kind": "recommandation",
            "title": f"Snippet capturable : « {kw['keyword']} »",
            "detail_md": (f"**Format à produire** : {answer.get('format', '?')}\n\n"
                          f"**Section H2 suggérée** : {answer.get('h2_anchor', '?')}\n\n"
                          f"**Contenu** :\n\n{answer.get('content_md', '')}\n\n"
                          f"**Snippet actuel (à battre)** : {detected.get('current_owner_domain')}"),
            "status": "draft",
            "impact": 5, "effort": 2,
        })
        opportunities += 1

    return {"ok": True, "checked": len(keywords[:max_keywords]),
            "opportunities": opportunities}
