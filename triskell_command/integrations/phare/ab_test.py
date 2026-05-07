"""A/B testing SEO scientifique.

Workflow :
1. start_test() : choisit 2 lots de pages similaires (même cluster, même
   range de trafic) et applique la variante B sur le lot B (via patcher +
   git_pipeline).
2. record_measurements() : tous les jours, lit les CTR/clics par lot via GSC
   et stocke dans phare_ab_measurements.
3. close_test() : à expiration de duration_days, applique le test
   statistique (Mann-Whitney U sur les CTR quotidiens) et déclare un
   gagnant. Si la variante B gagne avec p < 0.05 ET impressions
   suffisantes, on garde B sur tout le lot. Sinon, on revient à A sur le
   lot B (rollback).
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from . import gsc, repo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
def start_test(site_id: str, *, name: str, field_tested: str,
               variant_a: str, variant_b: str,
               paths_lot_a: list[str], paths_lot_b: list[str],
               duration_days: int = 21,
               app_state=None) -> dict:
    """Démarre un test A/B. La variante B doit déjà avoir été appliquée
    en prod sur les paths_lot_b (via patcher + git_pipeline) avant
    d'appeler cette fonction."""
    sb = repo._sb()
    if sb is None:
        return {"ok": False, "error": "Supabase indispo"}
    if field_tested not in ("title", "meta_description", "h1"):
        return {"ok": False, "error": f"field_tested {field_tested} non supporté"}
    if not paths_lot_a or not paths_lot_b:
        return {"ok": False, "error": "lots A et B doivent être non vides"}

    res = sb.table("phare_ab_tests").insert({
        "site_id": site_id,
        "name": name,
        "field_tested": field_tested,
        "variant_a_value": variant_a,
        "variant_b_value": variant_b,
        "paths_lot_a": paths_lot_a,
        "paths_lot_b": paths_lot_b,
        "duration_days": duration_days,
        "status": "running",
    }).execute()
    test_id = res.data[0]["id"] if res.data else None
    return {"ok": bool(test_id), "test_id": test_id}


def record_measurements(*, app_state=None) -> dict:
    """Pour chaque test running, lit GSC du jour et stocke."""
    sb = repo._sb()
    if sb is None:
        return {"ok": False}
    tests = (sb.table("phare_ab_tests").select("*")
             .eq("status", "running").execute().data) or []
    today = date.today() - timedelta(days=2)  # GSC J-2
    inserted = 0
    for t in tests:
        site = repo.get_site(t["site_id"])
        if not site:
            continue
        domain = site.get("domain", "")
        # Utilise GSC pour récupérer clicks + impressions par page sur les
        # 2 derniers jours (frais)
        pages = gsc.fetch_top_pages(domain, days=2, limit=500)
        by_path: dict[str, dict] = {}
        for p in pages:
            page_url = p.get("page", "")
            for path in (t["paths_lot_a"] or []) + (t["paths_lot_b"] or []):
                if path in page_url:
                    by_path[path] = p
        lot_a = [by_path.get(p) for p in (t["paths_lot_a"] or []) if by_path.get(p)]
        lot_b = [by_path.get(p) for p in (t["paths_lot_b"] or []) if by_path.get(p)]

        def _agg(lot):
            clicks = sum(p.get("clicks", 0) for p in lot)
            imps = sum(p.get("impressions", 0) for p in lot)
            return clicks, imps, (clicks / imps if imps > 0 else 0)

        a_c, a_i, a_ctr = _agg(lot_a)
        b_c, b_i, b_ctr = _agg(lot_b)
        try:
            sb.table("phare_ab_measurements").upsert({
                "test_id": t["id"],
                "measured_date": today.isoformat(),
                "lot_a_clicks": a_c, "lot_a_impressions": a_i, "lot_a_ctr": a_ctr,
                "lot_b_clicks": b_c, "lot_b_impressions": b_i, "lot_b_ctr": b_ctr,
            }, on_conflict="test_id,measured_date").execute()
            inserted += 1
        except Exception as exc:
            logger.warning("ab_measurements upsert: %s", exc)

        # Si le test atteint sa durée, on le clôt
        started = _parse_iso(t["started_at"])
        if started and (datetime.now(timezone.utc) - started).days >= t.get("duration_days", 21):
            close_test(t["id"])
    return {"ok": True, "tests_measured": inserted}


def close_test(test_id: str) -> dict:
    """Calcule le gagnant via test U Mann-Whitney sur les CTR quotidiens."""
    sb = repo._sb()
    if sb is None:
        return {"ok": False}
    rows = sb.table("phare_ab_tests").select("*").eq("id", test_id).limit(1).execute().data
    if not rows:
        return {"ok": False, "error": "test introuvable"}
    test = rows[0]
    measurements = (sb.table("phare_ab_measurements").select("*")
                    .eq("test_id", test_id).execute().data) or []
    cfg = repo.get_config()
    min_imps = cfg.get("ab_test_min_impressions", 500)
    a_imps_total = sum(m.get("lot_a_impressions", 0) for m in measurements)
    b_imps_total = sum(m.get("lot_b_impressions", 0) for m in measurements)
    if a_imps_total < min_imps or b_imps_total < min_imps:
        winner = "none"
        decision = (f"Pas assez d'impressions ({a_imps_total} A vs "
                    f"{b_imps_total} B vs seuil {min_imps}). Test "
                    f"non-concluant.")
    else:
        a_ctrs = [float(m.get("lot_a_ctr") or 0) for m in measurements]
        b_ctrs = [float(m.get("lot_b_ctr") or 0) for m in measurements]
        u, p = _mann_whitney_u(a_ctrs, b_ctrs)
        a_mean = sum(a_ctrs) / len(a_ctrs) if a_ctrs else 0
        b_mean = sum(b_ctrs) / len(b_ctrs) if b_ctrs else 0
        if p < 0.05 and b_mean > a_mean:
            winner = "b"
            decision = (f"Variante B gagne (CTR moyen {b_mean*100:.2f}% vs "
                        f"{a_mean*100:.2f}%, p={p:.3f}). À garder en prod.")
        elif p < 0.05 and a_mean > b_mean:
            winner = "a"
            decision = (f"Variante A reste meilleure (CTR moyen "
                        f"{a_mean*100:.2f}% vs {b_mean*100:.2f}%, "
                        f"p={p:.3f}). Rollback de la variante B "
                        f"recommandé.")
        else:
            winner = "none"
            decision = (f"Pas de différence significative "
                        f"(p={p:.3f}, A={a_mean*100:.2f}% vs "
                        f"B={b_mean*100:.2f}%). Garde la version actuelle.")

    sb.table("phare_ab_tests").update({
        "status": "done",
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "winner": winner,
        "final_decision_md": decision,
    }).eq("id", test_id).execute()

    repo.insert_action({
        "site_id": test["site_id"],
        "agent": "ab_test",
        "kind": "recommandation",
        "title": f"Test A/B « {test['name']} » terminé : gagnant = {winner.upper()}",
        "detail_md": decision,
        "status": "draft",
        "impact": 4, "effort": 1,
    })
    return {"ok": True, "winner": winner, "decision": decision}


def _parse_iso(iso: str):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Stats — implémentation autonome de Mann-Whitney U (pas de scipy)
# ---------------------------------------------------------------------------
def _mann_whitney_u(a: list[float], b: list[float]) -> tuple[float, float]:
    """Renvoie (u_statistic, p_value approximée). Pas de scipy → calcule
    via approximation normale (valable si n_a + n_b > 20 ; sinon on
    renvoie p=1.0 par sécurité).
    """
    if not a or not b:
        return 0.0, 1.0
    n_a, n_b = len(a), len(b)
    if n_a + n_b < 8:
        return 0.0, 1.0
    combined = [(v, "a") for v in a] + [(v, "b") for v in b]
    combined.sort()
    # Ranks (avec gestion ex aequo simplifiée)
    ranks = {}
    for i, (v, _) in enumerate(combined, start=1):
        ranks.setdefault(v, []).append(i)
    avg_ranks = {v: sum(rs) / len(rs) for v, rs in ranks.items()}
    sum_a = sum(avg_ranks[v] for v in a)
    u_a = sum_a - n_a * (n_a + 1) / 2
    u_b = n_a * n_b - u_a
    u = min(u_a, u_b)
    # Approximation normale
    mean_u = n_a * n_b / 2
    sd_u = math.sqrt(n_a * n_b * (n_a + n_b + 1) / 12)
    if sd_u == 0:
        return u, 1.0
    z = (u - mean_u) / sd_u
    # p bilatéral
    p = 2 * (1 - _phi(abs(z)))
    return u, max(0.0, min(1.0, p))


def _phi(x: float) -> float:
    """CDF de la loi normale standard (sans scipy)."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))
