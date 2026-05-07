"""Rapport mensuel client — généré par Le Phare.

Contrairement à `bulletin_pdf.py` (bulletin interne agrégé sur tous les
sites Triskell), ce module produit un rapport **par client externe** :
une fiche détaillée, brandée Triskell, qui couvre un seul site sur le
mois écoulé, avec découpage hebdo dans les sections pertinentes.

Sortie : `Output/phare_client_reports/<client_slug>/<YYYY-MM>.{pdf,html}`.

Structure du rapport :
  1. Récapitulatif (page de garde + 4 KPI clés + résumé Claude)
  2. Visibilité Google (clics, impressions, top mots-clés, gagnés/perdus)
  3. Santé technique (Lighthouse, CWV, problèmes détectés/résolus)
  4. Travail livré ce mois (articles, optims on-page, maillage) — découpé hebdo
  5. Backlinks (profil + nouveaux + perdus)
  6. Plan du mois prochain (généré par le Chef d'Orchestre)
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import repo

logger = logging.getLogger(__name__)


# =====================================================================
# Helpers
# =====================================================================
def _slugify(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9\-]+", "-", text)
    return text.strip("-") or "client"


def _output_dir(client_slug: str) -> Path:
    base = Path(__file__).resolve().parent.parent.parent.parent
    out = base / "Output" / "phare_client_reports" / client_slug
    out.mkdir(parents=True, exist_ok=True)
    return out


def _month_bounds(target: date) -> tuple[date, date]:
    """(début, début du mois suivant)"""
    start = target.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


def _week_bounds(start: date, end: date) -> list[tuple[date, date]]:
    """Découpe [start, end[ en semaines (lundi-dimanche)."""
    weeks = []
    cur = start
    while cur < end:
        week_end = min(cur + timedelta(days=7), end)
        weeks.append((cur, week_end))
        cur = week_end
    return weeks


def _fmt_int(n) -> str:
    if n is None:
        return "—"
    try:
        return f"{int(n):,}".replace(",", " ")
    except (ValueError, TypeError):
        return str(n)


def _fmt_delta(cur, prev) -> str:
    if cur is None or prev is None or prev == 0:
        return ""
    pct = round(((cur - prev) / prev) * 100)
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct} %"


def _delta_color(cur, prev, *, lower_is_better: bool = False) -> str:
    if cur is None or prev is None:
        return "#64748B"
    diff = cur - prev
    if diff == 0:
        return "#64748B"
    if lower_is_better:
        return "#15803D" if diff < 0 else "#B91C1C"
    return "#15803D" if diff > 0 else "#B91C1C"


def _french_month(d: date) -> str:
    months = ["janvier", "février", "mars", "avril", "mai", "juin",
              "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    return f"{months[d.month - 1]} {d.year}"


# =====================================================================
# Data gathering
# =====================================================================
def gather_data(site: dict, client: dict, target_month: Optional[date] = None) -> dict:
    """Agrège toutes les données nécessaires au rapport.

    Retourne un dict avec :
      - site, client, period (start, end, prev_start, prev_end)
      - kpis : 4 chiffres clés + leurs deltas
      - audits, keywords, pages, actions, content, backlinks, metrics
      - weekly : breakdown par semaine pour les sections 2 et 4
    """
    target = (target_month or date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    p_start, p_end = _month_bounds(target)
    prev_start, prev_end = _month_bounds(target - timedelta(days=1))
    weeks = _week_bounds(p_start, p_end)

    sb = repo._sb()
    out: dict = {
        "site": site,
        "client": client,
        "period": {
            "start": p_start, "end": p_end,
            "prev_start": prev_start, "prev_end": prev_end,
            "weeks": weeks,
        },
        "audits": [], "audits_prev": [],
        "keywords": [],
        "pages": [],
        "actions_merged": [], "actions_pending": [],
        "content_published": [],
        "backlinks_new": [], "backlinks_lost": [],
        "metrics": [], "metrics_prev": [],
        "weekly": [],
        "_status": {},
    }

    if sb is None:
        out["_status"]["db"] = "offline"
        return out

    site_id = site["id"]

    # Audits techniques (mois courant + précédent pour delta)
    try:
        out["audits"] = (sb.table("phare_audits").select("*")
                          .eq("site_id", site_id)
                          .gte("ran_at", p_start.isoformat())
                          .lt("ran_at", p_end.isoformat())
                          .order("ran_at", desc=True).execute().data) or []
        out["audits_prev"] = (sb.table("phare_audits").select("*")
                               .eq("site_id", site_id)
                               .gte("ran_at", prev_start.isoformat())
                               .lt("ran_at", prev_end.isoformat())
                               .order("ran_at", desc=True).limit(1).execute().data) or []
    except Exception as exc:
        logger.debug("client_report audits: %s", exc)

    # Mots-clés (état actuel)
    try:
        out["keywords"] = (sb.table("phare_keywords").select("*")
                            .eq("site_id", site_id)
                            .order("current_position", desc=False)
                            .limit(200).execute().data) or []
    except Exception as exc:
        logger.debug("client_report keywords: %s", exc)

    # Pages
    try:
        out["pages"] = (sb.table("phare_pages").select("*")
                         .eq("site_id", site_id)
                         .order("organic_clicks_30d", desc=True)
                         .limit(50).execute().data) or []
    except Exception as exc:
        logger.debug("client_report pages: %s", exc)

    # Actions (PR, modifs) du mois
    try:
        all_actions = (sb.table("phare_actions").select("*")
                        .eq("site_id", site_id)
                        .gte("created_at", p_start.isoformat())
                        .lt("created_at", p_end.isoformat())
                        .order("created_at", desc=False).execute().data) or []
        out["actions_merged"] = [a for a in all_actions
                                  if a.get("status") == "merged"
                                  or a.get("auto_merged")]
        out["actions_pending"] = [a for a in all_actions
                                   if a.get("status") in ("pending", "draft")]
    except Exception as exc:
        logger.debug("client_report actions: %s", exc)

    # Contenu publié ce mois
    try:
        out["content_published"] = (sb.table("phare_content_briefs").select("*")
                                      .eq("site_id", site_id)
                                      .eq("status", "published")
                                      .gte("published_at", p_start.isoformat())
                                      .lt("published_at", p_end.isoformat())
                                      .execute().data) or []
    except Exception as exc:
        logger.debug("client_report content: %s", exc)

    # Backlinks (nouveaux du mois et perdus)
    try:
        bls = (sb.table("phare_backlinks").select("*")
                .eq("site_id", site_id).execute().data) or []
        for bl in bls:
            disc = bl.get("discovered_at") or ""
            lost = bl.get("lost_at") or ""
            if disc and p_start.isoformat() <= disc < p_end.isoformat():
                out["backlinks_new"].append(bl)
            if lost and p_start.isoformat() <= lost < p_end.isoformat():
                out["backlinks_lost"].append(bl)
    except Exception as exc:
        logger.debug("client_report backlinks: %s", exc)

    # Métriques quotidiennes (clics, impressions GSC) — mois courant + précédent
    try:
        out["metrics"] = (sb.table("phare_metrics").select("*")
                           .eq("site_id", site_id)
                           .gte("metric_date", p_start.isoformat())
                           .lt("metric_date", p_end.isoformat())
                           .order("metric_date", desc=False).execute().data) or []
        out["metrics_prev"] = (sb.table("phare_metrics").select("*")
                                .eq("site_id", site_id)
                                .gte("metric_date", prev_start.isoformat())
                                .lt("metric_date", prev_end.isoformat())
                                .execute().data) or []
    except Exception as exc:
        logger.debug("client_report metrics: %s", exc)

    # Découpage hebdo
    out["weekly"] = _build_weekly_breakdown(out, weeks)

    # KPIs synthétiques
    out["kpis"] = _compute_kpis(out)

    return out


def _build_weekly_breakdown(out: dict, weeks: list[tuple[date, date]]) -> list[dict]:
    """Pour chaque semaine, agrège clics, impressions, actions mergées,
    contenu publié — utile pour les graphes hebdo dans le rapport.
    """
    breakdown = []
    for idx, (w_start, w_end) in enumerate(weeks, start=1):
        clicks = sum(int(m.get("organic_clicks") or 0)
                       for m in out["metrics"]
                       if w_start.isoformat() <= (m.get("metric_date") or "") < w_end.isoformat())
        impr = sum(int(m.get("impressions") or 0)
                     for m in out["metrics"]
                     if w_start.isoformat() <= (m.get("metric_date") or "") < w_end.isoformat())
        actions = [a for a in out["actions_merged"]
                    if w_start.isoformat() <= (a.get("merged_at") or a.get("created_at") or "")[:10] < w_end.isoformat()]
        content = [c for c in out["content_published"]
                    if w_start.isoformat() <= (c.get("published_at") or "")[:10] < w_end.isoformat()]
        breakdown.append({
            "index": idx,
            "start": w_start, "end": w_end,
            "label": f"S{idx}",
            "date_range": f"{w_start.strftime('%d/%m')} → {(w_end - timedelta(days=1)).strftime('%d/%m')}",
            "clicks": clicks,
            "impressions": impr,
            "actions": actions,
            "content_published": content,
        })
    return breakdown


def _compute_kpis(out: dict) -> dict:
    """4 KPI clés en haut du rapport, avec delta vs mois précédent."""
    metrics = out["metrics"]
    metrics_prev = out["metrics_prev"]

    clicks_cur = sum(int(m.get("organic_clicks") or 0) for m in metrics)
    clicks_prev = sum(int(m.get("organic_clicks") or 0) for m in metrics_prev)

    pos_cur = [float(m["avg_position"]) for m in metrics
                if m.get("avg_position") is not None]
    pos_prev = [float(m["avg_position"]) for m in metrics_prev
                 if m.get("avg_position") is not None]
    avg_pos_cur = round(sum(pos_cur) / len(pos_cur), 1) if pos_cur else None
    avg_pos_prev = round(sum(pos_prev) / len(pos_prev), 1) if pos_prev else None

    top10_cur = sum(1 for kw in out["keywords"]
                      if (kw.get("current_position") or 999) <= 10)

    audit_now = out["audits"][0] if out["audits"] else {}
    audit_prev = out["audits_prev"][0] if out["audits_prev"] else {}
    perf_cur = audit_now.get("lighthouse_perf")
    perf_prev = audit_prev.get("lighthouse_perf")

    return {
        "clicks": {"cur": clicks_cur, "prev": clicks_prev,
                   "delta": _fmt_delta(clicks_cur, clicks_prev),
                   "color": _delta_color(clicks_cur, clicks_prev)},
        "avg_position": {"cur": avg_pos_cur, "prev": avg_pos_prev,
                          "delta": _fmt_delta(avg_pos_cur, avg_pos_prev),
                          "color": _delta_color(avg_pos_cur, avg_pos_prev,
                                                  lower_is_better=True)},
        "top10": {"cur": top10_cur, "prev": None, "delta": "", "color": "#64748B"},
        "lighthouse_perf": {"cur": perf_cur, "prev": perf_prev,
                             "delta": _fmt_delta(perf_cur, perf_prev),
                             "color": _delta_color(perf_cur, perf_prev)},
    }


# =====================================================================
# Narrative — appel Claude pour résumé exécutif + plan du mois prochain
# =====================================================================
def _generate_narrative(data: dict, app_state=None) -> dict:
    """Appelle Claude pour produire le résumé exécutif (4-5 lignes) et
    le plan du mois prochain (3-5 priorités). Si pas de clé API, retourne
    des placeholders calculés depuis les données.
    """
    site = data["site"]
    client = data["client"]
    kpis = data["kpis"]

    # Fallback sans LLM
    fallback_summary = _fallback_summary(data)
    fallback_plan = _fallback_plan(data)

    try:
        from . import agents  # late import : évite cycle si geo_surveillant pas chargé
    except Exception:
        return {"summary": fallback_summary, "plan_md": fallback_plan,
                "_source": "fallback"}

    prompt = f"""Tu rédiges deux courts paragraphes pour un rapport SEO mensuel
destiné à un client externe. Ton : chaleureux pro, breton, pas de jargon
({client.get('contact_name', 'le client')} n'est pas un expert SEO).

Site : {site.get('name')} ({site.get('domain')})
Mois : {_french_month(data['period']['start'])}

KPI clés :
- Clics organiques Google : {kpis['clicks']['cur']} (vs {kpis['clicks']['prev']} mois précédent, {kpis['clicks']['delta']})
- Position moyenne : {kpis['avg_position']['cur']} (vs {kpis['avg_position']['prev']}, {kpis['avg_position']['delta']})
- Mots-clés en page 1 : {kpis['top10']['cur']}
- Score Lighthouse perf : {kpis['lighthouse_perf']['cur']} (vs {kpis['lighthouse_perf']['prev']})

Travail livré ce mois :
- {len(data['actions_merged'])} optimisations appliquées au site
- {len(data['content_published'])} articles publiés
- {len(data['backlinks_new'])} nouveaux backlinks
- {sum(1 for a in data['actions_merged'] if a.get('agent') == 'auditeur')} corrections techniques

Réponds en JSON strict :
{{
  "summary": str (4-5 lignes, ton chaleureux, ce qui s'est passé ce mois),
  "plan_md": str (Markdown : 3 à 5 priorités pour le mois prochain, format
    `- **Titre court** : pourquoi c'est important + ETA approximatif`)
}}"""

    try:
        out = agents.AuditeurTechnique().__class__.__bases__[0]  # noqa: F841
    except Exception:
        pass

    try:
        raw = agents.call_llm(prompt, model=agents.STRATEGY_MODEL,
                                app_state=app_state, max_tokens=1500)
        parsed = agents._parse_json(raw)
        if isinstance(parsed, dict) and parsed.get("summary"):
            return {
                "summary": parsed.get("summary") or fallback_summary,
                "plan_md": parsed.get("plan_md") or fallback_plan,
                "_source": "llm",
            }
    except Exception as exc:
        logger.debug("client_report narrative LLM failed: %s", exc)

    return {"summary": fallback_summary, "plan_md": fallback_plan,
            "_source": "fallback"}


def _fallback_summary(data: dict) -> str:
    k = data["kpis"]
    site = data["site"]
    parts = [
        f"Ce mois sur {site.get('name', 'votre site')}, "
        f"nous avons enregistré {_fmt_int(k['clicks']['cur'])} clics depuis Google "
        f"({k['clicks']['delta'] or 'stable'} vs le mois précédent)."
    ]
    if data["actions_merged"]:
        parts.append(
            f"{len(data['actions_merged'])} optimisations ont été appliquées "
            f"directement au site."
        )
    if data["content_published"]:
        parts.append(f"{len(data['content_published'])} articles ont été publiés.")
    if k["lighthouse_perf"]["cur"] is not None:
        parts.append(
            f"Le score de performance technique est de {k['lighthouse_perf']['cur']}/100."
        )
    return " ".join(parts)


def _fallback_plan(data: dict) -> str:
    """Plan basique sans LLM, dérivé des données disponibles."""
    points = []
    if data["actions_pending"]:
        points.append(f"- **Valider {len(data['actions_pending'])} optimisations en attente** : "
                       f"déjà préparées par les agents, à relire et approuver. ETA : 1 semaine.")
    audit = data["audits"][0] if data["audits"] else {}
    if audit.get("broken_links"):
        points.append(f"- **Corriger {audit['broken_links']} liens cassés** détectés "
                       f"par l'audit. ETA : 2-3 jours.")
    if not data["content_published"]:
        points.append("- **Reprendre le rythme de publication** : 2 articles ciblés "
                       "sur les mots-clés à fort volume non encore couverts. ETA : 3 semaines.")
    if not points:
        points.append("- **Continuer sur la lancée** : les fondamentaux sont bons, "
                       "on consolide les positions acquises.")
    return "\n".join(points)


# =====================================================================
# Rendering — HTML (toujours produit, sert aussi de fallback)
# =====================================================================
def _render_html(data: dict, narrative: dict) -> str:
    site = data["site"]
    client = data["client"]
    period = data["period"]
    kpis = data["kpis"]

    month_label = _french_month(period["start"]).capitalize()

    # KPIs
    kpi_cards = []
    for key, label, suffix in (
        ("clicks", "Clics organiques", ""),
        ("avg_position", "Position moyenne", ""),
        ("top10", "Mots-clés page 1", ""),
        ("lighthouse_perf", "Performance technique", "/100"),
    ):
        k = kpis[key]
        cur = k["cur"]
        cur_str = _fmt_int(cur) if cur is not None else "—"
        delta = k["delta"]
        color = k["color"]
        kpi_cards.append(f"""
        <div class="kpi-card">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value">{cur_str}{suffix}</div>
            <div class="kpi-delta" style="color:{color}">{delta or '—'}</div>
        </div>""")

    # Section 2 : Visibilité
    top_kw_rows = "\n".join(
        f"<tr><td>{kw.get('keyword', '')}</td>"
        f"<td>{kw.get('current_position') or '—'}</td>"
        f"<td>{_fmt_int(kw.get('volume'))}</td>"
        f"<td>{kw.get('intent') or '—'}</td></tr>"
        for kw in data["keywords"][:10]
    ) or "<tr><td colspan='4' class='empty'>Pas de données mots-clés ce mois.</td></tr>"

    top_pages_rows = "\n".join(
        f"<tr><td>{p.get('url', '')}</td>"
        f"<td>{_fmt_int(p.get('organic_clicks_30d'))}</td>"
        f"<td>{_fmt_int(p.get('impressions_30d'))}</td></tr>"
        for p in data["pages"][:5]
    ) or "<tr><td colspan='3' class='empty'>Pas de données de pages ce mois.</td></tr>"

    weekly_clicks_rows = "\n".join(
        f"<tr><td>{w['label']}</td><td>{w['date_range']}</td>"
        f"<td>{_fmt_int(w['clicks'])}</td>"
        f"<td>{_fmt_int(w['impressions'])}</td></tr>"
        for w in data["weekly"]
    )

    # Section 3 : Tech
    audit = data["audits"][0] if data["audits"] else {}
    audit_prev = data["audits_prev"][0] if data["audits_prev"] else {}
    tech_rows = "".join(
        f"<tr><td>{label}</td>"
        f"<td>{audit.get(field, '—') or '—'}</td>"
        f"<td>{audit_prev.get(field, '—') or '—'}</td></tr>"
        for label, field in (
            ("Lighthouse Performance", "lighthouse_perf"),
            ("Lighthouse SEO", "lighthouse_seo"),
            ("Lighthouse Accessibilité", "lighthouse_a11y"),
            ("Pages indexables", "pages_indexable"),
            ("Liens cassés", "broken_links"),
            ("Score schema.org", "schema_score"),
        )
    )
    issues_html = ""
    if audit.get("issues"):
        items = "".join(f"<li>{str(i)}</li>" for i in audit["issues"][:8])
        issues_html = f"<h4>Problèmes notables</h4><ul>{items}</ul>"

    # Section 4 : Travail livré, par semaine
    weekly_work_html = ""
    for w in data["weekly"]:
        items = []
        for a in w["actions"]:
            kind = a.get("kind", "optimisation")
            url = a.get("github_pr_url", "")
            link = f' <a href="{url}">#PR</a>' if url else ""
            items.append(f"<li>{kind.replace('_', ' ').capitalize()}{link}</li>")
        for c in w["content_published"]:
            title = c.get("title_proposed") or c.get("target_url") or ""
            items.append(f"<li>📝 Article publié : {title}</li>")
        if items:
            weekly_work_html += (f"<h4>Semaine {w['index']} "
                                  f"<span class='week-range'>· {w['date_range']}</span></h4>"
                                  f"<ul>{''.join(items)}</ul>")
    if not weekly_work_html:
        weekly_work_html = "<p class='empty'>Pas de modifications appliquées ce mois.</p>"

    # Section 5 : Backlinks
    bl_new = data["backlinks_new"]
    bl_lost = data["backlinks_lost"]
    bl_html = (f"<p><strong>{len(bl_new)} nouveaux backlinks</strong> ce mois, "
               f"<strong>{len(bl_lost)} perdus</strong>.</p>")
    if bl_new:
        items = "".join(
            f"<li>{bl.get('source_domain', '')} "
            f"<small>(autorité {bl.get('domain_authority') or '—'})</small></li>"
            for bl in bl_new[:10]
        )
        bl_html += f"<h4>Nouveaux liens (top 10)</h4><ul>{items}</ul>"
    if bl_lost:
        items = "".join(f"<li>{bl.get('source_domain', '')}</li>"
                          for bl in bl_lost[:5])
        bl_html += f"<h4>Liens perdus</h4><ul>{items}</ul>"

    return f"""<!DOCTYPE html>
<html lang="fr"><head>
<meta charset="utf-8">
<title>Rapport SEO {site.get('name', '')} — {month_label}</title>
<style>
@page {{ size: A4; margin: 1.8cm; }}
body {{
    font-family: 'Segoe UI', -apple-system, sans-serif;
    color: #1E293B; line-height: 1.5; margin: 0;
    background: #FAFAF7;
}}
.report {{
    max-width: 820px; margin: 2em auto; background: #FFF;
    padding: 3em 3em 2em; border: 1px solid #E2E8F0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}}
.brand {{ font-size: 12px; letter-spacing: 0.15em;
          text-transform: uppercase; color: #C5A572; font-weight: 600; }}
h1 {{ font-size: 32px; color: #0F172A; margin: 0.2em 0 0.1em;
      letter-spacing: -0.01em; }}
.subtitle {{ color: #64748B; font-size: 15px; margin-bottom: 2.5em; }}
h2 {{ font-size: 19px; color: #0F172A; margin-top: 2.5em;
      padding-bottom: 0.4em; border-bottom: 2px solid #C5A572; }}
h3 {{ font-size: 15px; color: #0F172A; margin-top: 1.5em;
      margin-bottom: 0.5em; }}
h4 {{ font-size: 13px; color: #334155; margin-top: 1em;
      margin-bottom: 0.3em; }}
.summary {{ background: #F8F4EC; border-left: 3px solid #C5A572;
            padding: 1.2em 1.5em; margin: 1.5em 0; font-size: 15px;
            line-height: 1.6; color: #0F172A; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr);
              gap: 0.75em; margin: 1.5em 0 2em; }}
.kpi-card {{ background: #F8FAFC; border: 1px solid #E2E8F0;
              padding: 1em; border-radius: 6px; text-align: center; }}
.kpi-label {{ font-size: 10px; color: #64748B; text-transform: uppercase;
               letter-spacing: 0.08em; margin-bottom: 0.4em; }}
.kpi-value {{ font-size: 26px; color: #0F172A; font-weight: 700;
               line-height: 1; }}
.kpi-delta {{ font-size: 12px; margin-top: 0.4em; font-weight: 600; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.8em 0;
         font-size: 13px; }}
th {{ background: #F1F5F9; text-align: left; padding: 8px 10px;
      font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
      color: #475569; border-bottom: 1px solid #CBD5E1; }}
td {{ padding: 8px 10px; border-bottom: 1px solid #E2E8F0; vertical-align: top; }}
.empty {{ color: #94A3B8; font-style: italic; }}
.week-range {{ color: #94A3B8; font-weight: 400; font-size: 12px; }}
ul {{ padding-left: 1.5em; margin: 0.5em 0; }}
li {{ margin: 0.2em 0; font-size: 13px; }}
.plan-md {{ background: #F8FAFC; border: 1px solid #E2E8F0;
             padding: 1.2em 1.5em; border-radius: 6px; margin: 1em 0;
             white-space: pre-wrap; font-size: 14px; line-height: 1.7; }}
.footer {{ margin-top: 3em; padding-top: 1.5em; border-top: 1px solid #E2E8F0;
            font-size: 11px; color: #94A3B8; text-align: center; }}
@media print {{ body {{ background: #FFF; }}
                 .report {{ box-shadow: none; border: none;
                            margin: 0; padding: 0; }} }}
</style></head>
<body><div class="report">

<div class="brand">Triskell Studio · Le Phare</div>
<h1>Rapport SEO — {site.get('name', '')}</h1>
<div class="subtitle">
    {client.get('company') or client.get('contact_name', '')} ·
    {month_label}
</div>

<!-- Section 1 — Récapitulatif -->
<div class="summary">{narrative.get('summary', '')}</div>
<div class="kpi-grid">
{''.join(kpi_cards)}
</div>

<!-- Section 2 — Visibilité -->
<h2>Visibilité Google ce mois</h2>
<h3>Évolution hebdomadaire</h3>
<table>
<thead><tr><th>Semaine</th><th>Période</th><th>Clics</th><th>Impressions</th></tr></thead>
<tbody>{weekly_clicks_rows or '<tr><td colspan=4 class=empty>Pas de données</td></tr>'}</tbody>
</table>

<h3>Top 10 mots-clés qui rapportent du trafic</h3>
<table>
<thead><tr><th>Mot-clé</th><th>Position</th><th>Volume mensuel</th><th>Intent</th></tr></thead>
<tbody>{top_kw_rows}</tbody>
</table>

<h3>Top 5 pages les plus visitées</h3>
<table>
<thead><tr><th>URL</th><th>Clics 30j</th><th>Impressions 30j</th></tr></thead>
<tbody>{top_pages_rows}</tbody>
</table>

<!-- Section 3 — Tech -->
<h2>Santé technique du site</h2>
<table>
<thead><tr><th>Indicateur</th><th>Ce mois</th><th>Mois précédent</th></tr></thead>
<tbody>{tech_rows}</tbody>
</table>
{issues_html}

<!-- Section 4 — Travail livré -->
<h2>Travail livré ce mois</h2>
{weekly_work_html}

<!-- Section 5 — Backlinks -->
<h2>Profil de backlinks</h2>
{bl_html}

<!-- Section 6 — Plan du mois prochain -->
<h2>Plan du mois prochain</h2>
<div class="plan-md">{narrative.get('plan_md', '')}</div>

<div class="footer">
    Triskell Studio · Le Phare · Rapport généré le
    {datetime.now().strftime('%d/%m/%Y à %H:%M')}
</div>

</div></body></html>"""


# =====================================================================
# Rendering — PDF (reportlab si dispo, sinon HTML uniquement)
# =====================================================================
def _try_reportlab():
    try:
        from reportlab.lib import colors  # noqa: F401
        from reportlab.lib.pagesizes import A4  # noqa: F401
        return True
    except ImportError:
        return False


def _render_pdf_via_weasy(html: str, out_path: Path) -> bool:
    """WeasyPrint si dispo (rendu fidèle au HTML/CSS)."""
    try:
        from weasyprint import HTML
        HTML(string=html).write_pdf(str(out_path))
        return True
    except Exception as exc:
        logger.debug("weasyprint failed: %s", exc)
        return False


# =====================================================================
# Email body (court HTML pour le corps du mail)
# =====================================================================
def render_email_body(data: dict, narrative: dict, *,
                       extra_personal_note: str = "") -> str:
    site = data["site"]
    client = data["client"]
    period = data["period"]
    kpis = data["kpis"]
    month_label = _french_month(period["start"]).capitalize()

    personal = ""
    if extra_personal_note.strip():
        personal = (f'<p style="background:#F8F4EC;border-left:3px solid #C5A572;'
                     f'padding:0.8em 1em;margin:1em 0;font-style:italic;">'
                     f'{extra_personal_note.strip()}</p>')

    return f"""<!DOCTYPE html>
<html><body style="font-family:'Segoe UI',sans-serif;color:#1E293B;
                    max-width:600px;margin:0 auto;line-height:1.5;">
<p style="font-size:11px;letter-spacing:0.15em;text-transform:uppercase;
           color:#C5A572;margin:0 0 0.4em;">TRISKELL STUDIO · LE PHARE</p>
<h2 style="margin:0 0 0.3em;color:#0F172A;">Rapport SEO — {month_label}</h2>
<p style="color:#64748B;margin:0 0 1.5em;">
    {site.get('name', '')} · {site.get('domain', '')}
</p>

<p>Bonjour {client.get('contact_name', '').split(' ')[0] or ''},</p>

{personal}

<p>Voici le rapport SEO pour {month_label}.</p>

<p style="background:#F8FAFC;border:1px solid #E2E8F0;padding:1em;
           border-radius:6px;">{narrative.get('summary', '')}</p>

<table style="width:100%;border-collapse:collapse;margin:1.5em 0;">
<tr>
<td style="padding:0.6em;background:#F8FAFC;border:1px solid #E2E8F0;">
    <small style="color:#64748B;">Clics organiques</small><br>
    <strong style="font-size:18px;">{_fmt_int(kpis['clicks']['cur'])}</strong>
    <span style="color:{kpis['clicks']['color']};font-size:12px;">
        {kpis['clicks']['delta'] or ''}</span>
</td>
<td style="padding:0.6em;background:#F8FAFC;border:1px solid #E2E8F0;">
    <small style="color:#64748B;">Position moyenne</small><br>
    <strong style="font-size:18px;">{kpis['avg_position']['cur'] or '—'}</strong>
    <span style="color:{kpis['avg_position']['color']};font-size:12px;">
        {kpis['avg_position']['delta'] or ''}</span>
</td>
<td style="padding:0.6em;background:#F8FAFC;border:1px solid #E2E8F0;">
    <small style="color:#64748B;">Mots-clés page 1</small><br>
    <strong style="font-size:18px;">{kpis['top10']['cur']}</strong>
</td>
</tr>
</table>

<p>Le rapport détaillé (PDF) est en pièce jointe — il couvre la visibilité
Google, la santé technique, le travail livré semaine par semaine, les
backlinks, et le plan du mois prochain.</p>

<p>À votre disposition pour toute question,<br>
<strong>Jordan · Triskell Studio</strong></p>

<p style="font-size:11px;color:#94A3B8;border-top:1px solid #E2E8F0;
           padding-top:1em;margin-top:2em;">
    Triskell Studio · Le Phare · {datetime.now().strftime('%d/%m/%Y')}
</p>
</body></html>"""


# =====================================================================
# Entry point
# =====================================================================
def generate_for_client(
    site_id: str,
    client_id: Optional[str] = None,
    *,
    target_month: Optional[date] = None,
    app_state=None,
) -> dict:
    """Produit le rapport mensuel pour un client.

    Retourne un dict :
      {ok, format ('pdf'|'html'), html_path, pdf_path, email_html, data}
    """
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "Site introuvable"}

    client = repo.get_client_by_site(site_id) if client_id is None else None
    if client_id and client is None:
        sb = repo._sb()
        if sb is not None:
            try:
                rows = (sb.table("phare_clients").select("*")
                        .eq("id", client_id).limit(1).execute().data) or []
                client = rows[0] if rows else None
            except Exception:
                client = None
    if client is None:
        return {"ok": False, "error": "Fiche client introuvable. "
                                       "Crée-la avant de générer un rapport."}

    data = gather_data(site, client, target_month)
    narrative = _generate_narrative(data, app_state=app_state)

    html = _render_html(data, narrative)
    slug = _slugify(client.get("company") or client.get("contact_name") or site.get("name") or "")
    month_str = data["period"]["start"].strftime("%Y-%m")
    out_dir = _output_dir(slug)
    html_path = out_dir / f"{month_str}.html"
    html_path.write_text(html, encoding="utf-8")

    pdf_path = None
    if _try_reportlab() or True:  # WeasyPrint d'abord (fidèle HTML)
        candidate = out_dir / f"{month_str}.pdf"
        if _render_pdf_via_weasy(html, candidate):
            pdf_path = candidate

    email_html = render_email_body(data, narrative)

    return {
        "ok": True,
        "format": "pdf" if pdf_path else "html",
        "html_path": str(html_path),
        "pdf_path": str(pdf_path) if pdf_path else None,
        "email_html": email_html,
        "narrative": narrative,
        "data": data,
    }
