"""Les 8 agents Le Phare — équivalent agence SEO embarquée.

Chaque agent =
  - un nom court (`auditeur`, `optimiseur_onpage`, etc.)
  - un system prompt préfixé par la voix Triskell
  - une méthode `run(...)` qui collecte le contexte, appelle Claude, parse JSON
  - un modèle préféré (Sonnet par défaut, Opus pour le Chef d'Orchestre)

Les retours sont toujours en JSON strict (parsing tolérant fenced blocks).
Les agents ne touchent JAMAIS directement à Git ou Supabase ; ils renvoient
des suggestions structurées que l'orchestrateur applique.

Modèles :
  - claude-sonnet-4-6 : par défaut (audits, rédaction, optim, analyse)
  - claude-opus-4-7   : Chef d'Orchestre uniquement (stratégie mensuelle)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from . import repo, voice

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"
STRATEGY_MODEL = "claude-opus-4-7"


# ---------------------------------------------------------------------------
# Couche LLM — réutilise call_anthropic de triskell_core.ai.providers
# ---------------------------------------------------------------------------
def _resolve_api_key(app_state) -> str:
    """Récupère la clé Anthropic depuis l'app_state (pattern claude_advisor)."""
    if app_state is None:
        return ""
    try:
        ai = app_state.get("ai", default={}) or {}
        keys = ai.get("api_keys") or {}
        return keys.get("anthropic") or ""
    except Exception:
        return ""


def _resolve_api_key_from_supabase() -> str:
    """Fallback : clé Anthropic depuis shared_settings.ai si présent."""
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return ""
        if not c.is_authenticated:
            return ""
        sb = getattr(c, "client", None) or getattr(c, "_client", None)
        if sb is None:
            return ""
        rows = (sb.table("shared_settings").select("value")
                .eq("key", "ai_keys").limit(1).execute().data)
        if not rows:
            return ""
        return (rows[0].get("value") or {}).get("anthropic") or ""
    except Exception:
        return ""


def call_llm(prompt: str, *, model: str = DEFAULT_MODEL,
             app_state=None, max_tokens: int = 4096) -> str:
    """Appelle Claude via providers.call_anthropic. Renvoie le texte brut."""
    key = _resolve_api_key(app_state) or _resolve_api_key_from_supabase()
    if not key:
        raise RuntimeError("Clé Anthropic manquante dans la config Triskell.")
    try:
        from triskell_core.ai.providers import call_anthropic
    except ImportError as exc:
        raise RuntimeError(f"triskell_core indisponible: {exc}")
    return call_anthropic(prompt, model, key)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _parse_json(raw: str) -> dict | list:
    """Parse JSON tolérant fenced blocks."""
    if not raw:
        return {}
    m = _FENCE_RE.search(raw)
    candidate = m.group(1).strip() if m else raw.strip()
    # Découpe au premier { ou [ et au dernier } ou ]
    starts = [i for i in (candidate.find("{"), candidate.find("[")) if i >= 0]
    if starts:
        s = min(starts)
        e = max(candidate.rfind("}"), candidate.rfind("]"))
        if e > s:
            candidate = candidate[s:e + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.debug("agents: parse JSON KO (%s) sur %s", exc, candidate[:200])
        return {}


# ---------------------------------------------------------------------------
# Base agent
# ---------------------------------------------------------------------------
class Agent:
    name: str = "agent"
    role: str = ""
    model: str = DEFAULT_MODEL

    def system(self) -> str:
        return voice.system_preamble(self.role)

    def call(self, user_prompt: str, *, app_state=None) -> dict | list:
        full = f"{self.system()}\n\n---\n\n{user_prompt}"
        raw = call_llm(full, model=self.model, app_state=app_state)
        return _parse_json(raw)


# ---------------------------------------------------------------------------
# 1. Auditeur Technique
# ---------------------------------------------------------------------------
class AuditeurTechnique(Agent):
    name = "auditeur"
    role = """Tu es l'Auditeur Technique de Le Phare, l'agence SEO interne
de Triskell Studio.

Mission : analyser un audit technique brut (résultats du crawler + Lighthouse
+ PageSpeed) et produire :
1. Un score global de santé technique (0-100)
2. Top 5 problèmes critiques (ordre d'impact décroissant)
3. Top 5 quick wins (effort < 30 min chacun)
4. Un résumé Markdown lisible (max 200 mots, ton Jordan)

Format de sortie : JSON strict.

{
  "health_score": int,
  "critical_issues": [{"title": str, "impact": "haut"|"moyen"|"bas", "fix_hint": str}],
  "quick_wins": [{"title": str, "page_or_global": str, "fix_hint": str}],
  "summary_md": str
}"""

    def run(self, *, site: dict, crawl: dict, psi: dict, app_state=None) -> dict:
        prompt = f"""SITE : {site.get('name')} ({site.get('domain')})

CRAWL (résumé) :
- Pages crawlées : {len(crawl.get('pages', []))}
- Liens cassés : {len(crawl.get('broken_links', []))}
- Redirections (chaînes) : {crawl.get('redirects', 0)}

LIGHTHOUSE (PSI mobile) :
{json.dumps(psi.get('lighthouse', {}), ensure_ascii=False)}

CWV :
{json.dumps(psi.get('cwv', {}), ensure_ascii=False)}

ÉCHANTILLON DE PAGES (titres + word_count) :
{json.dumps([{"url": p.get("url"), "title": p.get("title"), "wc": p.get("word_count")}
             for p in crawl.get("pages", [])[:15]], ensure_ascii=False, indent=2)}

LIENS CASSÉS DÉTECTÉS :
{json.dumps(crawl.get("broken_links", [])[:10], ensure_ascii=False, indent=2)}

Produis ton analyse au format JSON spécifié."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------------------
# 2. Veilleur Mots-Clés
# ---------------------------------------------------------------------------
class VeilleurMotsCles(Agent):
    name = "veilleur"
    role = """Tu es le Veilleur Mots-Clés de Le Phare.

Mission : à partir d'un site Triskell + son inventaire de pages + son top
requêtes GSC + ses concurrents SERP, produire :
1. 10 mots-clés cibles prioritaires (volume FR > 50, intent claire, opportunité)
2. 20 mots-clés long-traîne à attaquer en cluster
3. Un cluster sémantique (thème pivot + sous-thèmes)

Format JSON strict :
{
  "primary_keywords": [{"keyword": str, "intent": "info"|"comm"|"trans"|"nav",
                        "estimated_volume": int, "target_url_hint": str,
                        "rationale": str}],
  "long_tail": [{"keyword": str, "intent": str, "cluster": str}],
  "cluster_pivot": str,
  "cluster_subthemes": [str]
}"""

    def run(self, *, site: dict, top_queries: list, top_pages: list,
            serp_examples: list, app_state=None) -> dict:
        prompt = f"""SITE : {site.get('name')} ({site.get('domain')})
NOTES : {site.get('notes', '')}

TOP REQUÊTES GSC ACTUELLES (28j) :
{json.dumps(top_queries[:30], ensure_ascii=False, indent=2)}

TOP PAGES GSC (28j) :
{json.dumps(top_pages[:20], ensure_ascii=False, indent=2)}

EXEMPLES SERP CONCURRENTS (top 10 sur quelques requêtes pivot) :
{json.dumps(serp_examples[:30], ensure_ascii=False, indent=2)}

Produis ta stratégie keyword au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------------------
# 3. Rédacteur
# ---------------------------------------------------------------------------
class Redacteur(Agent):
    name = "redacteur"
    role = """Tu es le Rédacteur de Le Phare.

Mission : produire un brief d'article SEO + sa rédaction complète à partir
d'un mot-clé cible. Voix Triskell impérative (cf. préambule).

Contraintes contenu :
- Longueur cible : 1000-1500 mots
- Structure : H1 → 4-6 H2 → H3 si utile
- Mot-clé cible dans le titre (H1 et meta), 1er paragraphe, et 1 H2
- Variantes sémantiques disséminées naturellement
- Pas de bourrage, pas de fluff
- Prose dense, exemples concrets, ton breton chaleureux pro
- Conclusion qui ajoute (pas qui reformule)

Format JSON strict :
{
  "slug": str,
  "title": str (≤60 chars),
  "meta_description": str (≤155 chars),
  "h1": str,
  "outline": [{"h": "h2"|"h3", "text": str}],
  "content_md": str (article complet en Markdown),
  "internal_link_suggestions": [{"anchor": str, "target_path_hint": str}]
}"""

    def run(self, *, site: dict, target_keyword: str,
            secondary_keywords: list[str], cluster: str = "",
            existing_pages_titles: list[str] | None = None,
            app_state=None) -> dict:
        existing = existing_pages_titles or []
        prompt = f"""SITE : {site.get('name')} ({site.get('domain')})
SECTEUR/NOTES : {site.get('notes', '')}

MOT-CLÉ CIBLE : {target_keyword}
MOTS-CLÉS SECONDAIRES : {', '.join(secondary_keywords)}
CLUSTER PARENT : {cluster or '(libre)'}

PAGES EXISTANTES DU SITE (pour suggestions de maillage) :
{json.dumps(existing[:40], ensure_ascii=False, indent=2)}

Rédige l'article complet (1000-1500 mots) au format JSON."""
        out = self.call(prompt, app_state=app_state, )
        return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------------------
# 4. Optimiseur On-Page
# ---------------------------------------------------------------------------
class OptimiseurOnPage(Agent):
    name = "optimiseur_onpage"
    role = """Tu es l'Optimiseur On-Page de Le Phare.

Mission : analyser une page existante et proposer les modifications de balises
HTML pour améliorer son SEO sans toucher au corps éditorial.

Champs modifiables (LISTE BLANCHE STRICTE) :
- <title> du <head>
- <meta name="description">
- balises Hn (texte uniquement, pas la structure)
- attribut alt des <img>
- bloc JSON-LD <script type="application/ld+json"> (ajout/maj)

INTERDIT : modifier le corps de l'article, le CSS, les composants framework,
la navigation, les liens internes (Tisseur s'en occupe), les attributs onclick.

Format JSON strict :
{
  "score_before": int (0-100),
  "score_after_estimated": int (0-100),
  "patches": [
    {"field": "title"|"meta_description"|"h1"|"h2"|"alt"|"jsonld",
     "old": str, "new": str, "selector_hint": str, "rationale": str}
  ],
  "summary_md": str (≤120 mots)
}"""

    def run(self, *, site: dict, page: dict, target_keyword: str = "",
            app_state=None) -> dict:
        prompt = f"""SITE : {site.get('name')} ({site.get('domain')})

PAGE :
- URL : {page.get('url')}
- Path : {page.get('path')}
- Title actuel : {page.get('title')}
- Meta description actuelle : {page.get('meta_description')}
- H1 actuel : {page.get('h1')}
- Outline Hn :
{json.dumps(page.get('h_outline', []), ensure_ascii=False, indent=2)}
- Word count : {page.get('word_count')}
- Schema.org détectés : {page.get('schema_types', [])}

MOT-CLÉ CIBLE (si fourni) : {target_keyword or '(à déduire du contenu)'}

Propose tes patches au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------------------
# 5. Tisseur (maillage interne intra + inter-sites Triskell)
# ---------------------------------------------------------------------------
class Tisseur(Agent):
    name = "tisseur"
    role = """Tu es le Tisseur de Le Phare. Tu construis le maillage interne
ET inter-sites de l'écosystème Triskell Studio.

Mission : à partir de l'inventaire de pages d'un site + l'inventaire global
des sites Triskell, proposer :
1. Liens internes manquants (intra-site)
2. Liens inter-sites Triskell (cocon sémantique global)
3. Pages orphelines (à reconnecter)

Règle d'or : pertinence sémantique avant tout. Aucun lien forcé. Anchor
naturel, jamais sur-optimisé.

Format JSON strict :
{
  "intra_site_links": [
    {"from_path": str, "to_path": str, "anchor": str, "rationale": str}
  ],
  "inter_site_links": [
    {"from_site_domain": str, "from_path": str,
     "to_site_domain": str, "to_path": str, "anchor": str, "rationale": str}
  ],
  "orphan_pages": [{"path": str, "suggested_links_in": int}],
  "summary_md": str
}"""

    def run(self, *, site: dict, pages: list, ecosystem: list[dict],
            app_state=None) -> dict:
        prompt = f"""SITE FOCAL : {site.get('name')} ({site.get('domain')})

INVENTAIRE PAGES SITE FOCAL :
{json.dumps([{"path": p.get("path"), "title": p.get("title"),
              "h1": p.get("h1"), "wc": p.get("word_count")}
             for p in pages[:60]], ensure_ascii=False, indent=2)}

ÉCOSYSTÈME TRISKELL (autres sites + thèmes) :
{json.dumps([{"domain": s.get("domain"), "name": s.get("name"),
              "notes": s.get("notes", "")}
             for s in ecosystem if s.get("domain") != site.get("domain")],
            ensure_ascii=False, indent=2)}

Propose le maillage au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------------------
# 6. Chasseur Backlinks
# ---------------------------------------------------------------------------
class ChasseurBacklinks(Agent):
    name = "chasseur_backlinks"
    role = """Tu es le Chasseur Backlinks de Le Phare.

Mission : à partir du profil backlinks actuel d'un site Triskell + des
backlinks de ses concurrents directs, identifier :
1. Top 10 opportunités d'acquisition (concurrents qui ont, nous pas)
2. 5 opportunités HARO/expert quotes envisageables
3. 5 brand mentions non liées (à transformer en lien)

Format JSON strict :
{
  "opportunities": [
    {"source_domain": str, "kind": "concurrent_gap"|"haro"|"unlinked_mention"|"resource_page",
     "score": int (0-100), "approach_hint": str, "estimated_effort": "S"|"M"|"L"}
  ],
  "summary_md": str
}"""

    def run(self, *, site: dict, our_backlinks_summary: dict,
            competitor_domains: list[str], app_state=None) -> dict:
        prompt = f"""SITE : {site.get('name')} ({site.get('domain')})

NOTRE PROFIL BACKLINKS (résumé) :
{json.dumps(our_backlinks_summary, ensure_ascii=False, indent=2)}

CONCURRENTS DIRECTS IDENTIFIÉS :
{json.dumps(competitor_domains[:20], ensure_ascii=False)}

Propose les opportunités au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------------------
# 7. Analyste
# ---------------------------------------------------------------------------
class Analyste(Agent):
    name = "analyste"
    role = """Tu es l'Analyste de Le Phare.

Mission : à partir des métriques GSC sur 30 jours + l'historique d'actions
récentes + les conversions Stripe (si fournies), produire un bulletin :
1. Tendance globale (hausse/baisse/plateau) avec chiffres
2. Pages qui décollent (top 5)
3. Pages qui décrochent (top 5)
4. ROI estimé des actions Phare
5. Une recommandation pour la semaine

Format JSON strict :
{
  "trend": "hausse"|"baisse"|"plateau",
  "trend_summary_md": str (≤80 mots),
  "rising_pages": [{"path": str, "delta_clicks": int, "note": str}],
  "falling_pages": [{"path": str, "delta_clicks": int, "note": str}],
  "actions_roi_summary": str,
  "next_week_recommendation": str
}"""

    def run(self, *, site: dict, metrics_30d: list, recent_actions: list,
            conversions: Optional[list] = None, app_state=None) -> dict:
        prompt = f"""SITE : {site.get('name')} ({site.get('domain')})

MÉTRIQUES GSC 30 DERNIERS JOURS :
{json.dumps(metrics_30d, ensure_ascii=False, indent=2)}

ACTIONS PHARE RÉCENTES (status / impact) :
{json.dumps([{"agent": a.get("agent"), "kind": a.get("kind"),
              "title": a.get("title"), "status": a.get("status"),
              "merged_at": a.get("merged_at")}
             for a in recent_actions[:30]], ensure_ascii=False, indent=2)}

CONVERSIONS (si dispo) :
{json.dumps(conversions or [], ensure_ascii=False)}

Produis le bulletin au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------------------
# 8. Chef d'Orchestre (Opus)
# ---------------------------------------------------------------------------
class ChefOrchestre(Agent):
    name = "chef_orchestre"
    model = STRATEGY_MODEL
    role = """Tu es le Chef d'Orchestre de Le Phare. Modèle Opus utilisé,
réservé pour la stratégie mensuelle qui guide les 7 autres agents.

Mission : à partir de l'état complet de l'écosystème Triskell (audits récents,
métriques 30j, actions livrées, backlog), produire le plan du mois :
1. 3 sites prioritaires du mois (impact/effort)
2. 1 chantier transverse (ex: schema.org cross-sites, refonte cluster, etc.)
3. Briefs cadrés pour chaque agent (ce qu'ils doivent faire en priorité)
4. Critères de succès chiffrés à 30 jours

Format JSON strict :
{
  "month_label": str,
  "priority_sites": [{"domain": str, "rationale": str, "expected_impact": str}],
  "transverse_initiative": {"title": str, "scope": str, "owner_agent": str},
  "agent_briefs": {
      "auditeur": str, "veilleur": str, "redacteur": str,
      "optimiseur_onpage": str, "tisseur": str,
      "chasseur_backlinks": str, "analyste": str
  },
  "success_criteria": [{"metric": str, "target": str}]
}"""

    def run(self, *, ecosystem_snapshot: dict, app_state=None) -> dict:
        prompt = f"""ÉTAT GLOBAL ÉCOSYSTÈME TRISKELL :
{json.dumps(ecosystem_snapshot, ensure_ascii=False, indent=2)}

Produis le plan stratégique du mois au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------------------
# Registre
# ---------------------------------------------------------------------------
AGENTS: dict[str, type[Agent]] = {
    AuditeurTechnique.name: AuditeurTechnique,
    VeilleurMotsCles.name: VeilleurMotsCles,
    Redacteur.name: Redacteur,
    OptimiseurOnPage.name: OptimiseurOnPage,
    Tisseur.name: Tisseur,
    ChasseurBacklinks.name: ChasseurBacklinks,
    Analyste.name: Analyste,
    ChefOrchestre.name: ChefOrchestre,
}


def get_agent(name: str) -> Optional[Agent]:
    cls = AGENTS.get(name)
    return cls() if cls else None
