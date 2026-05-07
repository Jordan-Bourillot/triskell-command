"""CTR-Hacker — détecte les pages avec beaucoup d'impressions Google
mais un CTR faible, et propose une réécriture du title + meta.

Logique :
1. Lit GSC : pour chaque page sur 28j, calcule (impressions, ctr, position)
2. Filtre les "underperformers" : impressions > seuil ET ctr < attendu
   (CTR attendu = courbe standard par position : pos 1=30%, 2=15%, 3=10%, etc.)
3. Pour chaque underperformer, demande à un LLM léger une nouvelle version
4. Génère un patch via le patcher pour mise en prod
"""

from __future__ import annotations

import logging
from typing import Optional

from . import agents, gsc, repo, voice

logger = logging.getLogger(__name__)


# Courbe CTR moyenne par position (étude consolidée 2024-2025)
EXPECTED_CTR_BY_POSITION = {
    1: 0.32, 2: 0.18, 3: 0.11, 4: 0.08, 5: 0.06,
    6: 0.05, 7: 0.04, 8: 0.03, 9: 0.025, 10: 0.02,
}
DEFAULT_CTR_TAIL = 0.01  # au-delà de la position 10


def expected_ctr(position: float) -> float:
    """Renvoie le CTR attendu pour une position moyenne (interpolation)."""
    if position is None or position <= 0:
        return DEFAULT_CTR_TAIL
    p_low = int(position)
    p_high = p_low + 1
    if p_low >= 10:
        return DEFAULT_CTR_TAIL
    ctr_low = EXPECTED_CTR_BY_POSITION.get(p_low, DEFAULT_CTR_TAIL)
    ctr_high = EXPECTED_CTR_BY_POSITION.get(p_high, DEFAULT_CTR_TAIL)
    frac = position - p_low
    return ctr_low + (ctr_high - ctr_low) * frac


def find_underperformers(domain: str,
                          *,
                          min_impressions: int = 200,
                          min_gap: float = 0.4) -> list[dict]:
    """Renvoie les pages avec impressions élevées et CTR < expected*(1-min_gap).

    `min_gap=0.4` → ne signale que les pages dont le CTR est ≥40% en
    dessous de l'attendu pour leur position.
    """
    pages = gsc.fetch_top_pages(domain, days=28, limit=200)
    out = []
    for p in pages:
        imps = p.get("impressions", 0) or 0
        if imps < min_impressions:
            continue
        pos = p.get("position", 0) or 0
        ctr = p.get("ctr", 0) or 0
        exp = expected_ctr(pos)
        if exp <= 0:
            continue
        gap = (exp - ctr) / exp if exp > 0 else 0
        if gap >= min_gap:
            out.append({
                **p,
                "expected_ctr": round(exp, 4),
                "ctr_gap": round(gap, 3),
                "potential_clicks": int(imps * (exp - ctr)),
            })
    out.sort(key=lambda x: -x["potential_clicks"])
    return out


# ---------------------------------------------------------------------------
class CTRRewriter(agents.Agent):
    """Mini-agent dédié réécriture title+meta pour booster le CTR."""

    name = "ctr_rewriter"
    role = """Tu es le CTR-Hacker de Le Phare.

Mission : à partir d'une page Google avec beaucoup d'impressions mais un
faible taux de clic, proposer un nouveau title (≤60 chars) et une nouvelle
meta description (≤155 chars) qui donnent envie de cliquer.

Règles :
- Garde le mot-clé principal en début de title
- Ajoute un déclencheur émotionnel ou un chiffre dans les 3 premiers mots
- Promets une valeur concrète dans la meta (résultat, économie, gain de temps)
- Pas de clickbait creux, on tient les promesses
- Voix Triskell (préambule)

Format JSON strict :
{
  "old_title": str, "old_meta": str,
  "new_title": str, "new_meta": str,
  "rationale": str (≤80 mots, pourquoi ça va mieux marcher)
}"""

    def run(self, *, page: dict, gsc_stats: dict, app_state=None) -> dict:
        prompt = f"""URL : {page.get('url')}
Mot-clé principal estimé : {(gsc_stats.get('top_query') or '?')}

DONNÉES GSC (28 jours) :
- Impressions : {gsc_stats.get('impressions')}
- Clics : {gsc_stats.get('clicks')}
- CTR : {round((gsc_stats.get('ctr') or 0) * 100, 2)}%
- CTR attendu pour la position {gsc_stats.get('position')} : {round(gsc_stats.get('expected_ctr', 0) * 100, 2)}%
- Clics potentiels gagnés si on atteint le CTR attendu : {gsc_stats.get('potential_clicks')}

PAGE ACTUELLE :
- Title : {page.get('title')}
- Meta description : {page.get('meta_description')}
- H1 : {page.get('h1')}

Propose au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


def run_ctr_optim(site_id: str, *, app_state=None,
                  max_actions: int = 3) -> dict:
    """Détecte les underperformers et génère une recommandation pour les
    `max_actions` plus prometteurs."""
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    domain = site.get("domain") or ""
    candidates = find_underperformers(domain)
    if not candidates:
        return {"ok": True, "candidates": 0, "actions_created": 0,
                "message": "aucune page sous-performante détectée"}

    pages = repo.list_pages(site_id, limit=500)
    by_url = {p.get("url"): p for p in pages}

    rewriter = CTRRewriter()
    created = 0
    for cand in candidates[:max_actions]:
        page = by_url.get(cand.get("page"))
        if not page:
            continue
        try:
            rewrite = rewriter.run(
                page=page,
                gsc_stats={
                    "impressions": cand.get("impressions"),
                    "clicks": cand.get("clicks"),
                    "ctr": cand.get("ctr"),
                    "position": cand.get("position"),
                    "expected_ctr": cand.get("expected_ctr"),
                    "potential_clicks": cand.get("potential_clicks"),
                    "top_query": "",
                },
                app_state=app_state,
            )
        except Exception as exc:
            logger.warning("CTRRewriter LLM: %s", exc)
            continue
        if not rewrite or not rewrite.get("new_title"):
            continue
        repo.insert_action({
            "site_id": site_id,
            "agent": "ctr_hacker",
            "kind": "recommandation",
            "title": (f"CTR boost : {cand['page']} "
                      f"(+{cand.get('potential_clicks', 0)} clics potentiels)"),
            "detail_md": (f"**Title actuel** : {rewrite.get('old_title')}\n\n"
                          f"**Title proposé** : {rewrite.get('new_title')}\n\n"
                          f"**Meta actuelle** : {rewrite.get('old_meta')}\n\n"
                          f"**Meta proposée** : {rewrite.get('new_meta')}\n\n"
                          f"**Pourquoi** : {rewrite.get('rationale')}"),
            "status": "draft",
            "impact": 4, "effort": 1,
        })
        created += 1
    return {"ok": True, "candidates": len(candidates),
            "actions_created": created}
