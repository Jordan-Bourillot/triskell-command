"""Bulletin PDF — export du rapport mensuel Le Phare en PDF présentable.

Utilise reportlab (peut être install via pip ; sinon fallback HTML+CSS
sauvegardé en .html que tu peux convertir/imprimer toi-même).

Contenu du PDF :
- Couverture (logo Triskell + mois + sites couverts)
- KPI globaux écosystème (clics, impressions, top10, conversions)
- Pour chaque site : carte avec graphique évolution + 3 actions clés du mois
- Bulletin de l'Analyste (texte rédigé)
- Plan stratégique du mois (du Chef d'Orchestre Opus)

Output dans `Triskell Command/Output/phare_bulletins/YYYY-MM.pdf`.
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from . import orchestrator, repo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
def _try_reportlab():
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                          Table, TableStyle, PageBreak)
        return {
            "colors": colors, "A4": A4,
            "styles": getSampleStyleSheet, "ParagraphStyle": ParagraphStyle,
            "cm": cm,
            "SimpleDocTemplate": SimpleDocTemplate,
            "Paragraph": Paragraph, "Spacer": Spacer,
            "Table": Table, "TableStyle": TableStyle,
            "PageBreak": PageBreak,
        }
    except ImportError:
        return None


# ---------------------------------------------------------------------------
def _gather_data(month: Optional[date] = None) -> dict:
    """Agrège les données du mois pour le bulletin."""
    month = month or date.today().replace(day=1)
    overview = orchestrator.ecosystem_overview()
    sites = overview.get("sites", [])
    totals = overview.get("totals", {})

    # Bulletins Analyste + Plan Opus du mois
    bulletins = []
    plan_strategique = None
    sb = repo._sb()
    if sb is not None:
        next_month = (month + timedelta(days=32)).replace(day=1)
        try:
            rows = (sb.table("phare_actions").select("*")
                    .gte("created_at", month.isoformat())
                    .lt("created_at", next_month.isoformat())
                    .in_("agent", ["analyste", "chef_orchestre"])
                    .order("created_at", desc=True).execute().data) or []
            bulletins = [r for r in rows if r.get("agent") == "analyste"][:10]
            plan = [r for r in rows if r.get("agent") == "chef_orchestre"]
            plan_strategique = plan[0] if plan else None
        except Exception as exc:
            logger.debug("bulletins fetch: %s", exc)

    return {
        "month": month,
        "sites": sites,
        "totals": totals,
        "bulletins": bulletins,
        "plan_strategique": plan_strategique,
    }


# ---------------------------------------------------------------------------
def render_pdf(month: Optional[date] = None,
               output_dir: Optional[Path] = None) -> dict:
    """Génère le PDF mensuel. Si reportlab indispo → HTML fallback."""
    data = _gather_data(month)
    month = data["month"]
    output_dir = output_dir or (Path(__file__).resolve().parent.parent.parent.parent
                                  / "Output" / "phare_bulletins")
    output_dir.mkdir(parents=True, exist_ok=True)

    rl = _try_reportlab()
    if rl is None:
        return _render_html_fallback(data, output_dir)

    out_file = output_dir / f"{month.strftime('%Y-%m')}.pdf"
    doc = rl["SimpleDocTemplate"](
        str(out_file),
        pagesize=rl["A4"],
        leftMargin=2 * rl["cm"], rightMargin=2 * rl["cm"],
        topMargin=2 * rl["cm"], bottomMargin=2 * rl["cm"],
    )
    styles = rl["styles"]()

    h1 = rl["ParagraphStyle"]("h1", parent=styles["Title"], fontSize=24,
                                textColor=rl["colors"].HexColor("#0F172A"),
                                spaceAfter=18)
    h2 = rl["ParagraphStyle"]("h2", parent=styles["Heading2"], fontSize=14,
                                textColor=rl["colors"].HexColor("#6366F1"),
                                spaceBefore=18, spaceAfter=6)
    body = rl["ParagraphStyle"]("body", parent=styles["BodyText"], fontSize=10,
                                  textColor=rl["colors"].HexColor("#1E293B"),
                                  leading=14, spaceAfter=8)

    story = []
    P, S = rl["Paragraph"], rl["Spacer"]

    # Couverture
    story.append(P(f"Bulletin Le Phare — {month.strftime('%B %Y').capitalize()}", h1))
    story.append(P("Triskell Studio · Agence SEO autonome embarquée", body))
    story.append(S(0, 0.5 * rl["cm"]))
    story.append(P(f"<b>{len(data['sites'])} sites surveillés.</b> "
                    f"<b>{data['totals'].get('organic_clicks_30d', 0)}</b> "
                    f"clics organiques cumulés sur 30 jours. "
                    f"<b>{data['totals'].get('impressions_30d', 0)}</b> "
                    f"impressions Google.", body))
    story.append(S(0, 0.5 * rl["cm"]))

    # Tableau des sites
    story.append(P("Vue d'ensemble par site", h2))
    table_data = [["Site", "Perf", "SEO", "Clics 30j", "Actions"]]
    for s in data["sites"][:20]:
        table_data.append([
            s.get("name", "")[:30],
            str(s.get("lighthouse_perf") or "—"),
            str(s.get("lighthouse_seo") or "—"),
            str(s.get("organic_clicks_30d", 0)),
            str(s.get("actions_pending", 0)),
        ])
    tbl = rl["Table"](table_data, colWidths=[6 * rl["cm"], 1.5 * rl["cm"],
                                                1.5 * rl["cm"], 2.5 * rl["cm"],
                                                2 * rl["cm"]])
    tbl.setStyle(rl["TableStyle"]([
        ("BACKGROUND", (0, 0), (-1, 0), rl["colors"].HexColor("#F1F5F9")),
        ("TEXTCOLOR", (0, 0), (-1, 0), rl["colors"].HexColor("#0F172A")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, rl["colors"].HexColor("#E2E8F0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)
    story.append(S(0, 0.5 * rl["cm"]))

    # Bulletins Analyste
    if data["bulletins"]:
        story.append(rl["PageBreak"]())
        story.append(P("Bulletins Analyste du mois", h2))
        for b in data["bulletins"][:8]:
            story.append(P(f"<b>{b.get('title', '')}</b>", body))
            story.append(P((b.get("detail_md") or "")[:1500], body))
            story.append(S(0, 0.3 * rl["cm"]))

    # Plan stratégique
    if data["plan_strategique"]:
        story.append(rl["PageBreak"]())
        story.append(P("Plan stratégique du mois (Chef d'Orchestre)", h2))
        ps = data["plan_strategique"]
        story.append(P(f"<b>{ps.get('title', '')}</b>", body))
        story.append(P((ps.get("detail_md") or "")[:3000], body))

    # Footer page
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(rl["colors"].HexColor("#64748B"))
        canvas.drawString(2 * rl["cm"], 1 * rl["cm"],
                           f"Triskell Studio · Le Phare · "
                           f"{datetime.now().strftime('%d/%m/%Y')}")
        canvas.drawRightString(19 * rl["cm"], 1 * rl["cm"],
                                f"Page {doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return {"ok": True, "format": "pdf", "path": str(out_file)}


def _render_html_fallback(data: dict, output_dir: Path) -> dict:
    month = data["month"]
    out_file = output_dir / f"{month.strftime('%Y-%m')}.html"
    sites_rows = "\n".join(
        f"<tr><td>{s.get('name', '')}</td>"
        f"<td>{s.get('lighthouse_perf') or '—'}</td>"
        f"<td>{s.get('lighthouse_seo') or '—'}</td>"
        f"<td>{s.get('organic_clicks_30d', 0)}</td>"
        f"<td>{s.get('actions_pending', 0)}</td></tr>"
        for s in data["sites"][:20]
    )
    bulletins_html = "\n".join(
        f"<h3>{b.get('title', '')}</h3>"
        f"<div class='md'>{(b.get('detail_md') or '')[:2000]}</div>"
        for b in data["bulletins"][:8]
    )
    plan_html = ""
    if data["plan_strategique"]:
        ps = data["plan_strategique"]
        plan_html = (f"<h2>Plan stratégique du mois</h2>"
                     f"<h3>{ps.get('title', '')}</h3>"
                     f"<div class='md'>{(ps.get('detail_md') or '')[:3000]}</div>")
    html = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Bulletin Le Phare {month.strftime('%Y-%m')}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 800px;
         margin: 2em auto; color: #1E293B; padding: 2em; }}
h1 {{ font-size: 28px; color: #0F172A; }}
h2 {{ color: #6366F1; border-bottom: 2px solid #E2E8F0; padding-bottom: 6px;
       margin-top: 2em; }}
h3 {{ color: #0F172A; margin-top: 1.5em; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid #E2E8F0; padding: 8px; text-align: left;
           font-size: 13px; }}
th {{ background: #F1F5F9; }}
.md {{ white-space: pre-wrap; line-height: 1.5; }}
footer {{ margin-top: 3em; font-size: 11px; color: #64748B;
           border-top: 1px solid #E2E8F0; padding-top: 1em; }}
</style></head><body>
<h1>Bulletin Le Phare — {month.strftime('%B %Y').capitalize()}</h1>
<p><strong>Triskell Studio · Agence SEO autonome embarquée</strong></p>
<p>{len(data['sites'])} sites surveillés ·
   {data['totals'].get('organic_clicks_30d', 0)} clics organiques 30j ·
   {data['totals'].get('impressions_30d', 0)} impressions Google.</p>

<h2>Vue d'ensemble par site</h2>
<table>
<thead><tr><th>Site</th><th>Perf</th><th>SEO</th>
<th>Clics 30j</th><th>Actions</th></tr></thead>
<tbody>{sites_rows}</tbody>
</table>

<h2>Bulletins Analyste du mois</h2>
{bulletins_html}

{plan_html}

<footer>Triskell Studio · Le Phare · Généré le
{datetime.now().strftime('%d/%m/%Y à %H:%M')}<br>
<em>(reportlab non installé — fichier HTML, imprimable directement
depuis ton navigateur en PDF)</em></footer>
</body></html>"""
    out_file.write_text(html, encoding="utf-8")
    return {"ok": True, "format": "html", "path": str(out_file)}
