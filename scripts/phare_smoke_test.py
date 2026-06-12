"""Le Phare — Smoke test (sans credentials externes).

Vérifie que les briques offline du module fonctionnent sans dépendre de
Supabase, GitHub, Netlify, GSC, DataForSEO ou Anthropic.

Tests :
  1. Import en cascade des 11 sous-modules
  2. Détecteur anti-slop sur cas positifs et négatifs
  3. Crawler sur une URL publique (triskell-studio.fr)
  4. Patcher : transformation patches abstraits → patches fichier sur un
     mini-repo factice
  5. Ecosystem overview (renvoie structure cohérente même sans Supabase)
  6. Scheduler get_status (ne plante pas avant start)

Lancement :
    cd "Triskell Command"
    py -3 scripts/phare_smoke_test.py

Code retour 0 si tout vert, 1 sinon.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Sous Windows, force UTF-8 sur stdout/stderr pour ne pas planter sur les
# accents et caractères étendus présents dans les libellés.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CORE = ROOT.parent / "Triskell Core"
for p in (str(CORE), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)


GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


PASSED = 0
FAILED = 0


def _run(label: str, fn) -> None:
    global PASSED, FAILED
    try:
        fn()
        print(f"  {GREEN}[OK]{RESET} {label}")
        PASSED += 1
    except AssertionError as exc:
        print(f"  {RED}[KO]{RESET} {label} -- {exc}")
        FAILED += 1
    except Exception as exc:
        print(f"  {RED}[KO]{RESET} {label} -- exception: {exc}")
        FAILED += 1


# ---------------------------------------------------------------------------
def test_imports() -> None:
    from triskell_command.integrations.phare import (
        voice, repo, crawler, pagespeed, gsc, dataforseo,
        agents, git_pipeline, patcher, orchestrator, scheduler,
    )
    assert all([voice, repo, crawler, pagespeed, gsc, dataforseo,
                agents, git_pipeline, patcher, orchestrator, scheduler])


def test_imports_advanced() -> None:
    from triskell_command.integrations.phare import (
        schema_architect, ctr_hacker, snippet_hunter, geo_surveillant,
        cannibalization, zombies, image_seo, refresh, sitemap,
        competitors, rollback_watch,
    )
    assert all([schema_architect, ctr_hacker, snippet_hunter, geo_surveillant,
                cannibalization, zombies, image_seo, refresh, sitemap,
                competitors, rollback_watch])


def test_imports_pro() -> None:
    from triskell_command.integrations.phare import (
        outreach, ab_test, brand_monitoring, local_seo,
        programmatic, cro, algo_watch, bulletin_pdf,
    )
    assert all([outreach, ab_test, brand_monitoring, local_seo,
                programmatic, cro, algo_watch, bulletin_pdf])


def test_ab_mann_whitney() -> None:
    from triskell_command.integrations.phare.ab_test import _mann_whitney_u
    # 2 lots significativement différents (CTR ~5% vs ~9%)
    u, p = _mann_whitney_u([0.05, 0.06, 0.05, 0.07, 0.05, 0.06],
                            [0.08, 0.09, 0.08, 0.10, 0.09, 0.08])
    assert p < 0.05, f"p={p} devrait être < 0.05"
    # 2 lots identiques
    u2, p2 = _mann_whitney_u([0.05] * 6, [0.05] * 6)
    assert p2 > 0.5, f"p2={p2} devrait être proche de 1.0"


def test_programmatic_helpers() -> None:
    from triskell_command.integrations.phare.programmatic import (
        _interpolate, _slugify, _quality_score
    )
    assert _interpolate("/{ville}-{annee}", {"ville": "Brest", "annee": "2026"}) == "/Brest-2026"
    assert _slugify("Saint-Brieuc 2026 !") == "saint-brieuc-2026"
    score = _quality_score("Titre OK 30 chars exactement aaaaaa",
                            "Meta description OK 100-160 chars " * 3,
                            "## Section A\n## Section B\n## Section C\n" + "mot " * 700,
                            word_count=700, min_words=600)
    assert score >= 50, f"score qualité {score} faible pour bonne page"


def test_bulletin_html_fallback() -> None:
    """Sans reportlab, le bulletin PDF tombe sur HTML."""
    import tempfile
    import datetime
    from triskell_command.integrations.phare.bulletin_pdf import _render_html_fallback
    data = {"month": datetime.date.today().replace(day=1),
            "sites": [{"name": "Test", "lighthouse_perf": 90,
                       "lighthouse_seo": 95, "organic_clicks_30d": 100,
                       "actions_pending": 0}],
            "totals": {"organic_clicks_30d": 100, "impressions_30d": 1000},
            "bulletins": [],
            "plan_strategique": None}
    with tempfile.TemporaryDirectory() as tmp:
        res = _render_html_fallback(data, Path(tmp))
        assert res["ok"] is True
        assert Path(res["path"]).exists()
        content = Path(res["path"]).read_text(encoding="utf-8")
        assert "Bulletin Le Phare" in content
        assert "Triskell Studio" in content


def test_scheduler_pro_missions_dispatched() -> None:
    from triskell_command.integrations.phare import scheduler
    for mission in ("outreach_drafts", "outreach_followups", "ab_record",
                     "brand_scan", "local_seo", "cro_check",
                     "algo_watch", "bulletin_pdf", "auto_merge"):
        r = scheduler.run_now(mission, "00000000-0000-0000-0000-000000000000")
        assert "mission inconnue" not in (r.get("error") or ""), \
            f"{mission} non dispatché : {r}"


def test_auto_merge_guardrails() -> None:
    """L'auto-merge respecte ses garde-fous : opt-in, fenêtre de veto,
    plafond, recommandations textuelles jamais touchées, hold conservé."""
    from datetime import datetime, timedelta
    from triskell_command.integrations.phare import orchestrator as orch
    from triskell_command.integrations.phare import repo as ph_repo

    # 1. Désactivé (défaut) → sort en skipped sans rien toucher
    saved_cfg = ph_repo.get_config
    try:
        ph_repo.get_config = lambda: {}
        r = orch.auto_merge_verified()
        assert r.get("skipped") == "auto_merge_disabled", r
    finally:
        ph_repo.get_config = saved_cfg

    # 2. Activé : merge la PR vieille+vérifiée, veto sur la fraîche,
    #    ignore la reco sans PR, garde la PR « hold » en preview
    now = datetime.now()
    old_ts = (now - timedelta(hours=3)).isoformat(timespec="seconds")
    fresh_ts = (now - timedelta(minutes=5)).isoformat(timespec="seconds")
    fake_actions = [
        {"id": "a_fresh", "github_pr_url": "https://github.com/x/y/pull/1",
         "created_at": fresh_ts, "title": "PR fraîche", "site_id": "s1"},
        {"id": "a_ok", "github_pr_url": "https://github.com/x/y/pull/2",
         "created_at": old_ts, "title": "PR vérifiée", "site_id": "s1"},
        {"id": "a_reco", "github_pr_url": "",
         "created_at": old_ts, "title": "Reco texte", "site_id": "s1"},
        {"id": "a_hold", "github_pr_url": "https://github.com/x/y/pull/3",
         "created_at": old_ts, "title": "PR douteuse", "site_id": "s1"},
    ]
    merged_calls: list[tuple] = []
    notified: list[str] = []

    saved = (ph_repo.get_config, ph_repo.list_actions, ph_repo.get_site,
             orch.merge_action)
    try:
        ph_repo.get_config = lambda: {"auto_merge_enabled": True}
        ph_repo.list_actions = lambda **kw: list(fake_actions)
        ph_repo.get_site = lambda sid: {"name": "Site test", "domain": "t.fr"}

        def fake_merge(action_id, *, force=False, auto=False):
            merged_calls.append((action_id, force, auto))
            assert force is False, "l'auto-merge ne doit JAMAIS forcer"
            assert auto is True, "l'auto-merge doit se tracer auto=True"
            if action_id == "a_hold":
                return {"ok": False, "decision": "hold", "checks": {}}
            return {"ok": True}
        orch.merge_action = fake_merge

        from triskell_command.integrations.phare import notifications as notifs
        saved_notify = getattr(notifs, "notify_auto_merged", None)
        notifs.notify_auto_merged = (
            lambda *, site, action: notified.append(action["id"]) or {})
        try:
            r = orch.auto_merge_verified(max_merges=3, min_age_minutes=45)
        finally:
            if saved_notify is not None:
                notifs.notify_auto_merged = saved_notify
    finally:
        (ph_repo.get_config, ph_repo.list_actions, ph_repo.get_site,
         orch.merge_action) = saved

    tried = {c[0] for c in merged_calls}
    assert "a_fresh" not in tried, "fenêtre de veto ignorée"
    assert "a_reco" not in tried, "recommandation textuelle touchée"
    assert "a_ok" in tried and "a_hold" in tried
    assert [m["action_id"] for m in r["merged"]] == ["a_ok"], r
    assert [h["action_id"] for h in r["held"]] == ["a_hold"], r
    assert notified == ["a_ok"], "notification du merge auto manquante"


def test_algo_watch_rss_parser() -> None:
    """Le parser RSS doit ne pas planter sur du XML invalide."""
    from triskell_command.integrations.phare.algo_watch import _fetch_rss
    # URL bidon → renvoie liste vide sans exception
    out = _fetch_rss("https://example.invalid.tld/rss")
    assert isinstance(out, list)


def test_outreach_template_rendering() -> None:
    """Les templates par défaut contiennent des placeholders attendus."""
    from triskell_command.integrations.phare.outreach import DEFAULT_TEMPLATES
    assert "broken_link" in DEFAULT_TEMPLATES
    assert "{our_url}" in DEFAULT_TEMPLATES["broken_link"]["body"]
    assert "{target_page_title}" in DEFAULT_TEMPLATES["broken_link"]["subject"]


def test_schema_product() -> None:
    from triskell_command.integrations.phare.schema_architect import generate_schemas
    out = generate_schemas(
        {"path": "/produit", "title": "Pack Élec", "meta_description": "33 modèles",
         "h1": "Pack", "h_outline": []},
        {"name": "Pack Élec", "domain": "pack-elec.triskell-studio.fr"},
        extras={"price": 27},
    )
    assert out["type_detected"] == "Product"
    assert len(out["schemas"]) >= 2  # Product + BreadcrumbList
    assert "@context" in out["schemas"][0]
    assert "Product" in out["minified_jsonld"]


def test_schema_organization() -> None:
    from triskell_command.integrations.phare.schema_architect import generate_schemas
    out = generate_schemas(
        {"path": "/", "title": "Triskell Studio", "meta_description": "",
         "h1": "Triskell"},
        {"name": "Triskell Studio", "domain": "triskell-studio.fr"},
    )
    assert out["type_detected"] == "Organization"


def test_schema_no_invented_contact() -> None:
    """RÈGLE : aucune coordonnée inventée dans le markup publié.
    Sans org_phone/org_locality configurés, is_local retombe sur
    Organization (pas de LocalBusiness avec un faux numéro), et aucun
    logo n'est émis si l'URL n'est pas connue."""
    from triskell_command.integrations.phare import schema_architect as sa
    out = sa.generate_schemas(
        {"path": "/", "title": "Pack Élec", "meta_description": "", "h1": ""},
        {"name": "Pack Élec", "domain": "pack-elec.triskell-studio.fr"},
        extras={"is_local": True},
    )
    org = out["schemas"][0]
    assert org["@type"] == "Organization", f"attendu Organization, eu {org['@type']}"
    assert "telephone" not in org, "téléphone inventé publié !"
    assert "logo" not in org, "logo deviné publié !"
    # Avec logo_url explicite sur le site → le logo sort
    out2 = sa.generate_schemas(
        {"path": "/", "title": "X", "meta_description": "", "h1": ""},
        {"name": "X", "domain": "x.fr", "logo_url": "https://x.fr/logo.png"},
    )
    assert out2["schemas"][0].get("logo") == "https://x.fr/logo.png"


def test_schema_wired_into_onpage_optim() -> None:
    """Le schema-architecte doit rester branché au flux d'optimisation
    on-page (il a passé 5 semaines orphelin sans que personne le voie)."""
    import inspect
    from triskell_command.integrations.phare import orchestrator
    src = inspect.getsource(orchestrator.run_onpage_optim)
    assert "schema_architect" in src, "schema_architect débranché de run_onpage_optim"
    assert "patches_for_page" in src


def test_ctr_curve() -> None:
    from triskell_command.integrations.phare.ctr_hacker import expected_ctr
    assert 0.30 <= expected_ctr(1.0) <= 0.34
    assert 0.16 <= expected_ctr(2.0) <= 0.20
    assert expected_ctr(11.0) <= 0.02
    # Interpolation
    mid = expected_ctr(2.5)
    assert expected_ctr(3.0) <= mid <= expected_ctr(2.0)


def test_image_audit_offline() -> None:
    from triskell_command.integrations.phare.image_seo import audit_page
    html = ('<html><body>'
            '<img src="/a.jpg">'
            '<img src="/b.png" alt="OK" loading="lazy" srcset="/b.png 1x">'
            '<img src="/c.webp" alt="Bonne pratique">'
            '</body></html>')
    out = audit_page("https://example.com/", html=html)
    assert len(out) == 3
    # Première image : alt manquant
    assert "alt_missing" in out[0]["issues"]
    # Troisième image : webp + alt → moins d'issues
    assert "format_outdated" not in out[2]["issues"]


def test_sitemap_xml() -> None:
    from triskell_command.integrations.phare.sitemap import generate_sitemap_xml
    xml = generate_sitemap_xml(
        {"domain": "pack-elec.triskell-studio.fr"},
        [{"url": "https://pack-elec.triskell-studio.fr/", "path": "/"},
         {"url": "https://pack-elec.triskell-studio.fr/a", "path": "/a",
          "last_crawled_at": "2026-05-07T08:00:00+00:00"}],
    )
    assert "<urlset" in xml
    assert "<loc>https://pack-elec.triskell-studio.fr/</loc>" in xml
    assert "<lastmod>2026-05-07</lastmod>" in xml


def test_scheduler_advanced_missions_dispatched() -> None:
    """Vérifie que toutes les nouvelles missions sont reconnues par run_now
    (renvoient autre chose que 'mission inconnue')."""
    from triskell_command.integrations.phare import scheduler
    for mission in ("ctr_optim", "snippet_hunt", "geo_check",
                     "cannibalization", "zombies", "image_seo",
                     "refresh", "sitemap", "competitors", "rollback_check"):
        r = scheduler.run_now(mission, "00000000-0000-0000-0000-000000000000")
        # On accepte ok=False (Supabase indispo) mais PAS "mission inconnue"
        assert "mission inconnue" not in (r.get("error") or ""), \
            f"{mission} non dispatché : {r}"


def test_voice_clean() -> None:
    from triskell_command.integrations.phare.voice import is_clean, detect_slop
    clean = "Le Pack Électricien Pro fournit 33 modèles Word et Excel."
    assert is_clean(clean), f"texte propre vu sale : {detect_slop(clean)}"


def test_voice_slop() -> None:
    from triskell_command.integrations.phare.voice import detect_slop
    issues = detect_slop("We leverage robust seamless solutions in today's fast-paced world.")
    kinds = {i["kind"] for i in issues}
    assert "banned_word" in kinds, f"banned_word manquant : {issues}"
    assert len(issues) >= 4, f"attendu >= 4 issues, reçu {len(issues)}"


def test_voice_em_dash() -> None:
    from triskell_command.integrations.phare.voice import detect_slop
    txt = "Court — court — court — court — court — fini."  # 5 em-dash sur 1 phrase
    issues = detect_slop(txt)
    assert any(i["kind"] == "em_dash_overuse" for i in issues), f"em-dash non détecté : {issues}"


def test_crawler_remote() -> None:
    from triskell_command.integrations.phare.crawler import quick_check
    out = quick_check("https://triskell-studio.fr/")
    assert "status" in out, f"quick_check incomplet : {out}"
    # peut être 200, 301, 404 selon état réel — on vérifie juste que ça ne crash pas
    assert out.get("status") is not None


def test_patcher() -> None:
    from triskell_command.integrations.phare.patcher import localize_patches
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "index.html").write_text(
            '<title>Vieux titre</title><meta name="description" content="old"><h1>Old H1</h1></head>',
            encoding="utf-8",
        )
        out = localize_patches(tmp, "html", [
            {"field": "title", "old": "Vieux titre", "new": "Nouveau titre"},
            {"field": "meta_description", "old": "old", "new": "new"},
            {"field": "h1", "old": "Old H1", "new": "New H1"},
            {"field": "title", "old": "Inexistant", "new": "truc"},
        ])
        assert len(out["applicable"]) == 3, f"applicable={out['applicable']}"
        assert len(out["needs_review"]) == 1, f"needs_review={out['needs_review']}"


def test_patcher_jsonld() -> None:
    from triskell_command.integrations.phare.patcher import localize_patches
    with tempfile.TemporaryDirectory() as tmp:
        layout = Path(tmp) / "Layout.html"
        layout.write_text("<head><title>X</title></head><body></body>", encoding="utf-8")
        out = localize_patches(tmp, "html", [
            {"field": "jsonld", "old": "", "new": '{"@type":"Product"}'},
        ])
        assert len(out["applicable"]) == 1
        assert "</head>" in out["applicable"][0]["old"]


def test_agents_registry() -> None:
    from triskell_command.integrations.phare.agents import AGENTS
    # 9e agent depuis le 12/06/2026 : l'Exécuteur (bouton « OK, fais-le »)
    expected = {"auditeur", "veilleur", "redacteur", "optimiseur_onpage",
                "tisseur", "chasseur_backlinks", "analyste", "chef_orchestre",
                "executeur"}
    assert set(AGENTS) == expected, f"agents={set(AGENTS)}"


def test_orchestrator_overview() -> None:
    from triskell_command.integrations.phare import orchestrator
    ov = orchestrator.ecosystem_overview()
    assert {"sites", "totals", "config_status"} <= set(ov), f"ov={list(ov)}"
    assert isinstance(ov["sites"], list)
    assert isinstance(ov["totals"], dict)


def test_scheduler_status() -> None:
    from triskell_command.integrations.phare import scheduler
    s = scheduler.get_status()
    assert {"running", "last_run_at", "last_run_result"} <= set(s)
    assert s["running"] is False  # pas démarré


def test_view_imports() -> None:
    # La vue importe customtkinter — si l'import passe, c'est bon.
    from triskell_command.views.phare import PhareView
    assert PhareView.__name__ == "PhareView"
    assert PhareView.title == "Le Phare"


def test_main_routing() -> None:
    from triskell_command.main import VIEW_REGISTRY
    assert "phare" in VIEW_REGISTRY


def test_sidebar_section() -> None:
    from triskell_command.widgets.sidebar import SIDEBAR_SECTIONS
    sections = {s[0] for s in SIDEBAR_SECTIONS}
    has_visibility = any("VISIBIL" in s for s in sections)
    assert has_visibility, f"section VISIBILITÉ manquante : {sections}"


def test_sql_files_present() -> None:
    sup = ROOT / "supabase"
    assert (sup / "06_phare.sql").exists(), "06_phare.sql manquant"
    assert (sup / "06b_phare_seed_real.sql").exists(), "06b_phare_seed_real.sql manquant"


# ---------------------------------------------------------------------------
def main() -> int:
    print(f"\n{DIM}Le Phare — Smoke test (sans credentials){RESET}\n")
    _run("Imports en cascade", test_imports)
    _run("Imports modules avancés v0.5", test_imports_advanced)
    _run("Schema-architecte — page produit", test_schema_product)
    _run("Schema-architecte — page d'accueil = Organization", test_schema_organization)
    _run("Schema-architecte — zéro coordonnée inventée", test_schema_no_invented_contact)
    _run("Schema-architecte — branché dans l'optim on-page", test_schema_wired_into_onpage_optim)
    _run("CTR-Hacker — courbe CTR par position", test_ctr_curve)
    _run("Image SEO — détection issues HTML offline", test_image_audit_offline)
    _run("Sitemap.xml — génération valide", test_sitemap_xml)
    _run("Scheduler — 10 missions avancées dispatchées", test_scheduler_advanced_missions_dispatched)
    _run("Imports modules pro v0.6", test_imports_pro)
    _run("A/B test — Mann-Whitney U", test_ab_mann_whitney)
    _run("Programmatic — interpolate / slugify / quality_score", test_programmatic_helpers)
    _run("Bulletin — fallback HTML sans reportlab", test_bulletin_html_fallback)
    _run("Scheduler — 9 missions pro dispatchées", test_scheduler_pro_missions_dispatched)
    _run("Auto-merge — garde-fous (opt-in, veto, plafond, hold)", test_auto_merge_guardrails)
    _run("Algo watch — RSS parser tolérant", test_algo_watch_rss_parser)
    _run("Outreach — templates contiennent les placeholders", test_outreach_template_rendering)
    _run("Voice — texte propre détecté propre", test_voice_clean)
    _run("Voice — slop détecté", test_voice_slop)
    _run("Voice — em-dash overuse détecté", test_voice_em_dash)
    _run("Crawler — quick_check distant", test_crawler_remote)
    _run("Patcher — patches title/meta/h1 localisés", test_patcher)
    _run("Patcher — JSON-LD inséré dans layout", test_patcher_jsonld)
    _run("Agents — 8 agents enregistrés", test_agents_registry)
    _run("Orchestrator — ecosystem_overview structure", test_orchestrator_overview)
    _run("Scheduler — get_status sans crash", test_scheduler_status)
    _run("Vue UI — PhareView importable", test_view_imports)
    _run("Routing — phare dans VIEW_REGISTRY", test_main_routing)
    _run("Sidebar — section VISIBILITÉ présente", test_sidebar_section)
    _run("SQL — 06_phare.sql + 06b_phare_seed_real.sql présents", test_sql_files_present)

    total = PASSED + FAILED
    print(f"\n{PASSED}/{total} verts.")
    if FAILED == 0:
        print(GREEN + "Smoke test OK -- Le Phare est solide cote code." + RESET)
        return 0
    print(RED + f"{FAILED} test(s) en echec." + RESET)
    return 1


if __name__ == "__main__":
    sys.exit(main())
