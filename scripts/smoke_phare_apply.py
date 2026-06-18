"""Batterie « OK, fais-le » + anti-doublons Le Phare — sans réseau.

    py -3 scripts/smoke_phare_apply.py

Couvre :
    - dedup.py : normalisation, similarité (cas RÉELS du stock Pixel Pros
      du 12/06/2026), fenêtres de silence, grappes de doublons ;
    - repo.insert_action : doublon évité, insertion normale, retry sans
      les colonnes de la migration 48 ;
    - plain_language.py : explications sans jargon + classification du
      bouton « OK, fais-le » ;
    - patcher.localize_executor_patches : remplacement ciblé par page,
      insertion <head>, création de fichier (et refus des chemins louches) ;
    - executor._apply_one : chemins done / manual / failed, sans toucher
      ni à git ni à Supabase (tout est doublé par des mocks).
"""

from __future__ import annotations

import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Console Windows en cp1252 : on force l'UTF-8 pour les ✅/❌
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PASS = 0
FAIL = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        print(f"  ❌ {label}" + (f" — {detail}" if detail else ""))


# ===========================================================================
print("— dedup.py —")
from triskell_command.integrations.phare import dedup

check("normalisation accents/ponctuation",
      dedup.normalize_title("Réécrire le TITLE, de la home !") ==
      "reecrire le title de la home")

# Cas réels du stock Pixel Pros (12/06/2026)
A = {"site_id": "s1", "agent": "auditeur",
     "title": "Réécrire le title de la home avec le mot-clé principal",
     "detail_md": "Page: https://pixel-pros.fr/"}
B = {"site_id": "s1", "agent": "auditeur",
     "title": "Réécrire le title de la home avec le mot-clé principal",
     "detail_md": "Page: https://pixel-pros.fr/"}
check("titres identiques (home title ×2) → doublon", dedup.is_duplicate(A, B))

C1 = {"site_id": "s1", "agent": "auditeur",
      "title": "Ajouter canonical sur les 3 URLs paramétrées de /configurer",
      "detail_md": "Page: /configurer?option=domain, /configurer?option=seo"}
C2 = {"site_id": "s1", "agent": "auditeur",
      "title": "Ajouter canonical sur les trois variantes ?option= de /configurer",
      "detail_md": "Page: https://pixel-pros.fr/configurer?option=combo"}
check("variantes canonical /configurer → doublon", dedup.is_duplicate(C1, C2))

D1 = {"site_id": "s1", "agent": "auditeur",
      "title": "Corriger le title de /demo pour cibler une requête réelle",
      "detail_md": "Page: https://pixel-pros.fr/demo"}
D2 = {"site_id": "s1", "agent": "auditeur",
      "title": "Réécrire le title et le H1 de /demo",
      "detail_md": "Page: https://pixel-pros.fr/demo"}
check("deux recos title sur /demo → doublon (même page + même balise)",
      dedup.is_duplicate(D1, D2))

P1 = {"site_id": "s1", "agent": "auditeur",
      "title": "Lancer PageSpeed Insights et noter LCP / INP / CLS mobile",
      "detail_md": "Page: https://pixel-pros.fr/"}
P2 = {"site_id": "s1", "agent": "auditeur",
      "title": "Lancer et documenter un audit PageSpeed Insights complet",
      "detail_md": "Page: https://pixel-pros.fr/, /configurer, /demo"}
check("deux recos PageSpeed → doublon (même outil, même home)",
      dedup.is_duplicate(P1, P2))

E1 = {"site_id": "s1", "agent": "auditeur",
      "title": "Réécrire le title de la home avec le mot-clé principal",
      "detail_md": "Page: https://pixel-pros.fr/"}
E2 = {"site_id": "s1", "agent": "auditeur",
      "title": "Passer les 3 pages légales en noindex",
      "detail_md": "Page: /mentions-legales, /confidentialite, /cgv"}
check("title home vs noindex légales → PAS doublon",
      not dedup.is_duplicate(E1, E2))

F2 = {**E1, "site_id": "s2"}
check("même conseil sur un AUTRE site → PAS doublon",
      not dedup.is_duplicate(E1, F2))

G1 = {"site_id": "s1", "agent": "veilleur",
      "title": "Réécrire le title de la home avec le mot-clé principal",
      "detail_md": ""}
check("agents différents, titres identiques → doublon (≥ 0.92)",
      dedup.is_duplicate(E1, G1))
G2 = {"site_id": "s1", "agent": "veilleur",
      "title": "Réécrire le title de la page démo",
      "detail_md": "Page: /demo"}
check("agents différents, titres proches mais pas identiques → PAS doublon",
      not dedup.is_duplicate(D1, G2))

from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
check("action ouverte → bloque",
      dedup.blocks_reinsert({"status": "draft"}))
check("refusée hier → bloque (60 j de silence)",
      dedup.blocks_reinsert({"status": "rejected",
                             "rejected_at": (now - timedelta(days=1)).isoformat()}))
check("refusée il y a 90 j → ne bloque plus",
      not dedup.blocks_reinsert({"status": "rejected",
                                 "rejected_at": (now - timedelta(days=90)).isoformat()}))
check("validée il y a 3 j → bloque (14 j de silence)",
      dedup.blocks_reinsert({"status": "merged",
                             "merged_at": (now - timedelta(days=3)).isoformat()}))
check("expirée → ne bloque pas",
      not dedup.blocks_reinsert({"status": "expired"}))

groups = dedup.group_duplicates([
    {**A, "id": "a", "created_at": "2026-05-22"},
    {**B, "id": "b", "created_at": "2026-05-20"},
    {**E2, "id": "c", "created_at": "2026-05-21"},
])
check("grappes : 2 groupes (title×2 fusionnés, noindex à part)",
      len(groups) == 2 and sorted(len(g) for g in groups) == [1, 2])
big = next(g for g in groups if len(g) == 2)
check("grappe : la plus récente en tête", big[0]["id"] == "a")

# ===========================================================================
print("\n— repo.insert_action (dédup + retry migration 48) —")
from triskell_command.integrations.phare import repo as phare_repo


class FakeQuery:
    """Chaînable minimal pour singer supabase-py."""
    def __init__(self, table, db):
        self.table_name = table
        self.db = db
        self._insert_payload = None

    def __getattr__(self, name):
        # select/eq/order/limit/like/in_/lt/update/delete → chaînable
        def _chain(*args, **kwargs):
            return self
        return _chain

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def upsert(self, payload, **kwargs):
        self.db.setdefault("upserts", []).append(payload)
        return self

    def execute(self):
        class R:
            pass
        r = R()
        if self._insert_payload is not None:
            self.db["inserts"].append(self._insert_payload)
            if self.db.get("raise_on_insert"):
                err = self.db["raise_on_insert"]
                self.db["raise_on_insert"] = None   # une seule fois
                raise Exception(err)
            r.data = [self._insert_payload]
        else:
            r.data = list(self.db.get("rows", []))
        return r


class FakeSB:
    def __init__(self, db):
        self.db = db

    def table(self, name):
        return FakeQuery(name, self.db)


db = {"rows": [{"id": "x1", "site_id": "s1", "agent": "auditeur",
                "title": "Réécrire le title de la home avec le mot-clé principal",
                "detail_md": "Page: /", "status": "draft",
                "created_at": "2026-06-01"}],
      "inserts": []}
with mock.patch.object(phare_repo, "_sb", return_value=FakeSB(db)):
    out = phare_repo.insert_action({
        "site_id": "s1", "agent": "auditeur",
        "title": "Réécrire le title de la home avec le mot clé principal",
        "detail_md": "Page: /", "status": "draft"})
    check("doublon ouvert → pas d'insertion, renvoie l'existante",
          out and out.get("_dedup") is True and not db["inserts"])

    out2 = phare_repo.insert_action({
        "site_id": "s1", "agent": "auditeur",
        "title": "Créer un sitemap.xml et le déclarer",
        "detail_md": "Page: global", "status": "draft"})
    check("sujet nouveau → insertion réelle",
          out2 and not out2.get("_dedup") and len(db["inserts"]) == 1)

db2 = {"rows": [], "inserts": [],
       "raise_on_insert": 'column "simple_md" of relation does not exist'}
with mock.patch.object(phare_repo, "_sb", return_value=FakeSB(db2)):
    out3 = phare_repo.insert_action({
        "site_id": "s1", "agent": "auditeur", "title": "T", "detail_md": "",
        "status": "draft", "simple_md": "explication"})
    check("migration 48 absente → retry sans simple_md, insertion passée",
          out3 is not None and len(db2["inserts"]) == 2
          and "simple_md" not in db2["inserts"][1])

# upsert_pages : les variantes « ?option= » donnent le même path — un seul
# doublon dans le lot faisait tout rejeter par Postgres (table restée vide)
db3 = {"rows": [], "inserts": [], "upserts": []}
with mock.patch.object(phare_repo, "_sb", return_value=FakeSB(db3)):
    n = phare_repo.upsert_pages("s1", [
        {"url": "https://x.fr/configurer", "path": "/configurer", "title": "A"},
        {"url": "https://x.fr/configurer?option=seo", "path": "/configurer", "title": "A"},
        {"url": "https://x.fr/configurer?option=combo", "path": "/configurer", "title": "A"},
        {"url": "https://x.fr/demo", "path": "/demo", "title": "B"},
    ])
    batch = db3["upserts"][0] if db3["upserts"] else []
    check("upsert_pages : variantes ?query dédupliquées (4 pages → 2 lignes)",
          n == 2 and len(batch) == 2
          and sorted(r["path"] for r in batch) == ["/configurer", "/demo"])

# ===========================================================================
print("\n— plain_language.py —")
from triskell_command.integrations.phare import plain_language as pl

t = pl.explain({"title": "Réécrire le title de la home", "detail_md": "..."})
check("title → parle du titre dans Google, sans « title tag »",
      "Google" in t and "title tag" not in t.lower())
check("simple_md écrit par un agent → prioritaire",
      pl.explain({"simple_md": "Texte maison.", "title": "Réécrire le title"})
      == "Texte maison.")
check("canonical → parle de copies",
      "copies" in pl.explain({"title": "Ajouter canonical sur /configurer"}))
check("noindex → parle de cacher des résultats Google",
      "acher" in pl.explain({"title": "Passer les 3 pages légales en noindex"}))
check("plan du mois → à lire, rien à publier",
      "rien à publier" in pl.explain({"agent": "chef_orchestre",
                                      "title": "Plan du mois : Juin 2026"}))
check("bulletin → à lire",
      "À lire" in pl.explain({"agent": "analyste",
                              "title": "Bulletin 2026-06-12 — stable"}))
check("jamais vide", bool(pl.explain({})))

site_ok = {"repo_github": "Jordan-Bourillot/pixel-studio"}
site_ko = {"repo_github": ""}
v = pl.classify_for_apply({"status": "draft", "kind": "recommandation",
                           "title": "Réécrire le title de la home"}, site_ok)
check("title + site relié → robot peut le faire (code)",
      v["can"] and v["mode"] == "code")
v = pl.classify_for_apply({"status": "draft", "kind": "recommandation",
                           "title": "Réécrire le title de la home"}, site_ko)
check("title + site NON relié → manuel avec explication",
      not v["can"] and "relié" in v["why"])
v = pl.classify_for_apply({"status": "draft", "kind": "recommandation",
                           "title": "Vérifier la couverture d'index dans Search Console",
                           "detail_md": "Ouvrir Search Console et vérifier."},
                          site_ok)
check("Search Console SEUL → manuel (compte Google requis)",
      not v["can"] and v["mode"] == "manual")
v = pl.classify_for_apply({"status": "draft", "kind": "recommandation",
                           "title": "Ajouter canonical sur les 3 URLs paramétrées de /configurer",
                           "detail_md": "Insérer <link rel='canonical'>. "
                                        "Validation : Google Search Console > Inspection d'URL."},
                          site_ok)
check("canonical + simple mention de Search Console → le robot PEUT le faire",
      v["can"] and v["mode"] == "code")
v = pl.classify_for_apply({"status": "draft", "kind": "recommandation",
                           "title": "Vérifier et soumettre sitemap.xml dans Search Console",
                           "detail_md": "Si le fichier n'existe pas, le générer et l'uploader."},
                          site_ok)
check("sitemap + Search Console → le robot fait sa part (créer le fichier)",
      v["can"] and v["mode"] == "code")
v = pl.classify_for_apply({"status": "draft", "kind": "recommandation",
                           "title": "Lancer PageSpeed Insights et noter LCP"},
                          site_ok)
check("PageSpeed → le robot relance la mesure (tool)",
      v["can"] and v["mode"] == "tool")
v = pl.classify_for_apply({"status": "preview", "kind": "pr_modif",
                           "github_pr_url": "https://github.com/x/y/pull/1",
                           "title": "Optim on-page /"}, site_ok)
check("modif déjà préparée (PR) → pas de bouton « OK, fais-le »", not v["can"])
v = pl.classify_for_apply({"status": "draft", "kind": "recommandation",
                           "agent": "chef_orchestre",
                           "title": "Plan du mois : Juin 2026"}, site_ok)
check("plan du mois → pas automatisable", not v["can"])

# Le plan du mois s'écrit DANS la carte (avant : renvoi vers un écran
# « Bulletin > Plan mensuel » qui n'a jamais existé — plan perdu)
from triskell_command.integrations.phare import orchestrator as _orch
plan_md = _orch._strategy_detail_md({
    "vision_summary_md": "Vision du mois.",
    "priority_sites": [{"domain": "pixel-pros.fr", "rationale": "fort potentiel",
                        "target_delta_30d": "+100 clics"}],
    "transverse_initiative": {"title": "Cocon inter-sites", "scope": "3 sites"},
    "success_criteria": [{"metric": "clics organiques", "target": "+20 %"}],
    "deprioritized_sites": [{"domain": "ingrid-services.fr"}],
})
check("plan du mois mis en page dans la carte (vision + priorités + critères)",
      "Vision du mois." in plan_md and "pixel-pros.fr" in plan_md
      and "+100 clics" in plan_md and "Cocon inter-sites" in plan_md
      and "Mis en pause" in plan_md)
check("plan vide → texte de repli, jamais « Voir Bulletin »",
      "Voir Bulletin" not in _orch._strategy_detail_md({})
      and _orch._strategy_detail_md({}) != "")

# ===========================================================================
print("\n— patcher.localize_executor_patches —")
from triskell_command.integrations.phare import patcher

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "index.html").write_text(
        "<html><head><title>Pixel Pros — Un site pro pour 24,90€/mois</title>"
        "</head><body><h1>Accueil</h1></body></html>", encoding="utf-8")
    (root / "configurer.html").write_text(
        "<html><head><title>Configurer mon site — Pixel Pros</title></head>"
        "<body><h1>Configurer</h1></body></html>", encoding="utf-8")
    (root / "demo.html").write_text(
        "<html><head><title>Démo de site Pixel Pros</title></head>"
        "<body><h1>Demo</h1></body></html>", encoding="utf-8")
    pages = [
        {"path": "/", "title": "Pixel Pros — Un site pro pour 24,90€/mois"},
        {"path": "/configurer", "title": "Configurer mon site — Pixel Pros"},
        {"path": "/demo", "title": "Démo de site Pixel Pros"},
    ]

    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "title", "page_path": "/",
         "old": "Pixel Pros — Un site pro pour 24,90€/mois",
         "new": "Créer un site web professionnel à partir de 24,90€/mois — Pixel Pros"},
    ], pages)
    check("title home localisé dans index.html",
          len(loc["applicable"]) == 1
          and loc["applicable"][0]["file"] == "index.html")

    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "head_insert", "page_path": "/configurer",
         "new": '<link rel="canonical" href="https://pixel-pros.fr/configurer" />'},
    ], pages)
    check("head_insert ciblé sur configurer.html",
          len(loc["applicable"]) == 1
          and loc["applicable"][0]["file"] == "configurer.html"
          and loc["applicable"][0]["old"] == "</head>"
          and "canonical" in loc["applicable"][0]["new"]
          and loc["applicable"][0]["new"].endswith("</head>"))

    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "new_file", "file": "sitemap.xml",
         "new": "<?xml version='1.0'?><urlset></urlset>"},
    ], pages)
    check("new_file sitemap.xml accepté (create=True)",
          len(loc["applicable"]) == 1 and loc["applicable"][0].get("create"))

    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "new_file", "file": "../evil.xml", "new": "x"},
        {"field": "new_file", "file": "hack.php", "new": "x"},
        {"field": "new_file", "file": "index.html", "new": "x"},
    ], pages)
    check("new_file : ../, .php et fichier existant refusés",
          not loc["applicable"] and len(loc["needs_review"]) == 3)

    # Ambiguïté levée par la page : le même H1 vit dans 2 fichiers
    (root / "page-a.html").write_text(
        "<html><head><title>Page A unique</title></head>"
        "<body><h2>Nos services</h2></body></html>", encoding="utf-8")
    (root / "page-b.html").write_text(
        "<html><head><title>Page B unique</title></head>"
        "<body><h2>Nos services</h2></body></html>", encoding="utf-8")
    pages2 = pages + [{"path": "/page-a", "title": "Page A unique"},
                      {"path": "/page-b", "title": "Page B unique"}]
    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "h2", "page_path": "/page-a",
         "old": "Nos services", "new": "Nos prestations"},
    ], pages2)
    check("texte présent dans 2 fichiers → désambiguïsé par la page visée",
          len(loc["applicable"]) == 1
          and loc["applicable"][0]["file"] == "page-a.html")

    # L'IA met parfois un nom de fichier à la place du chemin d'URL
    # (vécu : « /index.html » au lieu de « / » au premier essai réel)
    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "head_insert", "page_path": "/index.html",
         "new": '<script type="application/ld+json">{}</script>'},
    ], pages2)
    check("page_path « /index.html » → rattrapé vers la home",
          len(loc["applicable"]) == 1
          and loc["applicable"][0]["file"] == "index.html")
    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "head_insert", "page_path": "/demo.html",
         "new": "<meta name=\"robots\" content=\"noindex, follow\" />"},
    ], pages2)
    check("page_path « /demo.html » → rattrapé vers /demo",
          len(loc["applicable"]) == 1
          and loc["applicable"][0]["file"] == "demo.html")

    # head_insert d'un <title> sur une page qui en a DÉJÀ un → remplacement,
    # jamais d'empilement (vécu : double <title> sur pixel-pros.fr)
    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "head_insert", "page_path": "/demo",
         "new": "<title>Nouveau titre démo</title>"},
    ], pages)
    check("head_insert d'un title existant → patch de remplacement",
          len(loc["applicable"]) == 1
          and loc["applicable"][0]["field"] == "title"
          and loc["applicable"][0]["old"].startswith("<title>")
          and "</head>" not in loc["applicable"][0]["new"])

    # Mixte : title (existe → remplacé) + canonical (absent → inséré)
    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "head_insert", "page_path": "/demo",
         "new": "<title>Titre frais</title>\n"
                '<link rel="canonical" href="https://pixel-pros.fr/demo" />'},
    ], pages)
    fields = sorted(p["field"] for p in loc["applicable"])
    check("head_insert mixte → title remplacé + canonical inséré",
          fields == ["head_insert", "title"]
          and all("Nouveau" not in p["new"] for p in loc["applicable"]))

    # LE désastre du 12/06 (vitrine Triskell) reproduit : la home et la page
    # produit partagent le même title générique ; le patch pour /produit ne
    # matche par grep QUE la home → il ne doit JAMAIS l'écraser
    import shutil as _sh
    desast = root / "desastre"
    (desast / "produit").mkdir(parents=True)
    (desast / "index.html").write_text(
        "<html><head><title>Studio générique — Bientôt</title></head>"
        "<body><h1>Accueil</h1></body></html>", encoding="utf-8")
    (desast / "produit" / "index.html").write_text(
        "<html><head><title>Autre chose</title></head>"
        "<body><h1>Produit</h1></body></html>", encoding="utf-8")
    loc = patcher.localize_executor_patches(str(desast), "html", [
        {"field": "title", "page_path": "/produit",
         "old": "Studio générique — Bientôt",
         "new": "Produit — La super fiche"},
    ], [{"path": "/", "title": "Studio générique — Bientôt"},
        {"path": "/produit", "title": "Studio générique — Bientôt"}])
    check("patch /produit qui ne matche que la home → REFUSÉ (needs_review)",
          not loc["applicable"] and len(loc["needs_review"]) == 1
          and "mauvaise page" in loc["needs_review"][0]["reason"])
    _sh.rmtree(desast, ignore_errors=True)

    # meta robots déjà présente → remplacée, jamais empilée
    (root / "legal.html").write_text(
        "<html><head><title>Légal unique</title>"
        '<meta name="robots" content="index, follow"></head>'
        "<body></body></html>", encoding="utf-8")
    pages3 = pages + [{"path": "/legal", "title": "Légal unique"}]
    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "head_insert", "page_path": "/legal",
         "new": '<meta name="robots" content="noindex, follow">'},
    ], pages3)
    check("head_insert d'un meta robots existant → remplacement",
          len(loc["applicable"]) == 1
          and loc["applicable"][0]["field"] == "meta_robots"
          and "index, follow" in loc["applicable"][0]["old"]
          and "noindex" in loc["applicable"][0]["new"])

# ===========================================================================
print("\n— executor._apply_one (mocks complets, ni git ni Supabase) —")
from triskell_command.integrations.phare import executor, git_pipeline, agents

ACTION = {"id": "act1", "site_id": "s1", "agent": "auditeur",
          "kind": "recommandation", "status": "draft", "apply_state": "queued",
          "title": "Réécrire le title de la home avec le mot-clé principal",
          "detail_md": "Remplacer X par Y.\n\nPage: https://pixel-pros.fr/"}
SITE = {"id": "s1", "name": "Pixel Pros", "domain": "pixel-pros.fr",
        "repo_github": "Jordan-Bourillot/pixel-studio",
        "repo_branch_main": "main", "stack": "html", "netlify_site_id": ""}
PAGES = [{"path": "/", "title": "Pixel Pros — Un site pro pour 24,90€/mois",
          "meta_description": "", "h1": "", "schema_types": []}]

updates: list[dict] = []


def fake_update(action_id, patch):
    updates.append({"id": action_id, **patch})
    return True


def run_apply(agent_out, *, clone_ok=True, pr_ok=True, merge_ok=True,
              localized=None, action_extra=None, site_extra=None,
              verify_out=None):
    """Déroule executor._apply_one avec tous les accès externes doublés."""
    updates.clear()
    fake_pr = {"ok": pr_ok, "branch": "phare/auto-test", "pr_number": 7,
               "pr_url": "https://github.com/x/y/pull/7"}
    if not pr_ok:
        fake_pr = {"ok": False, "error": "push refusé"}
    default_loc = {"applicable": [{"file": "index.html", "old": "a", "new": "b",
                                   "field": "title"}], "needs_review": []}
    action = {**ACTION, **(action_extra or {})}
    site = {**SITE, **(site_extra or {})}
    with mock.patch.object(executor, "_get_action", return_value=action), \
         mock.patch.object(executor.repo, "get_site", return_value=site), \
         mock.patch.object(executor.repo, "update_action", side_effect=fake_update), \
         mock.patch.object(executor.repo, "list_pages", return_value=PAGES), \
         mock.patch.object(executor.shutil, "which", return_value="C:/git.exe"), \
         mock.patch.object(git_pipeline, "_github_token", return_value="tok"), \
         mock.patch.object(git_pipeline, "clone_repo", return_value=clone_ok), \
         mock.patch.object(git_pipeline, "apply_and_open_pr", return_value=fake_pr), \
         mock.patch.object(git_pipeline, "merge_pr", return_value=merge_ok), \
         mock.patch.object(git_pipeline, "verify_pr",
                           return_value=verify_out or {"ok": True, "checks": {},
                                                       "decision": "merge"}), \
         mock.patch.object(executor.patcher, "localize_executor_patches",
                           return_value=localized or default_loc), \
         mock.patch.object(agents.Executeur, "run",
                           return_value=agent_out), \
         mock.patch.object(executor, "_dispatch_tick_workflow", return_value=False):
        return executor._apply_one("act1")


r = run_apply({"mode": "patches", "simple_md": "Je change le titre Google de l'accueil.",
               "patches": [{"field": "title", "page_path": "/", "old": "a", "new": "b"}]})
final = updates[-1]
check("chemin nominal → publié (merged + apply_state done)",
      r.get("ok") and final.get("status") == "merged"
      and final.get("apply_state") == "done"
      and final.get("github_pr_url", "").endswith("/7"))
check("l'explication de l'Exécuteur est gardée sur la carte",
      final.get("simple_md") == "Je change le titre Google de l'accueil.")
check("publié par un clic humain → auto_merged reste False",
      final.get("auto_merged") is False)

r = run_apply({"mode": "manual", "manual_reason": "Il faut le compte Google."})
final = updates[-1]
check("verdict manuel → apply_state=manual + raison, la carte reste ouverte",
      r.get("ok") and final.get("apply_state") == "manual"
      and "Google" in final.get("apply_error", "")
      and "status" not in final)

r = run_apply({"mode": "patches", "simple_md": "x",
               "patches": [{"field": "title", "page_path": "/", "old": "a", "new": "b"}]},
              localized={"applicable": [],
                         "needs_review": [{"reason": "texte actuel introuvable dans le code"}]})
final = updates[-1]
check("rien de localisable → failed avec explication française",
      not r.get("ok") and final.get("apply_state") == "failed"
      and "retrouvé" in final.get("apply_error", ""))

r = run_apply({"mode": "patches", "simple_md": "x",
               "patches": [{"field": "title", "page_path": "/", "old": "a", "new": "b"}]},
              merge_ok=False)
final = updates[-1]
check("merge KO → PR conservée + failed propre (publiable depuis la carte)",
      not r.get("ok") and final.get("apply_state") == "failed"
      and final.get("status") == "preview" and final.get("kind") == "pr_modif")

r = run_apply({"mode": "patches", "simple_md": "x",
               "patches": [{"field": "title", "page_path": "/", "old": "a", "new": "b"}]},
              clone_ok=False)
final = updates[-1]
check("clone KO → failed propre",
      not r.get("ok") and final.get("apply_state") == "failed")

# Contrôle impossible ≠ régression : la mesure de vitesse indisponible
# (pas de clé) ne bloque pas une publication validée par un clic humain
r = run_apply({"mode": "patches", "simple_md": "x",
               "patches": [{"field": "title", "page_path": "/", "old": "a", "new": "b"}]},
              site_extra={"netlify_site_id": "nl-123"},
              verify_out={"ok": False, "decision": "hold", "checks": {
                  "blockers": ["audit PSI indisponible (clé manquante ou réseau)"]}})
final = updates[-1]
check("mesure de vitesse indisponible → publie quand même (clic = validation)",
      r.get("ok") and final.get("status") == "merged"
      and final.get("apply_state") == "done")

# Un gros changement VISUEL sur une modif VISIBLE (h1) bloque toujours
r = run_apply({"mode": "patches", "simple_md": "x",
               "patches": [{"field": "h1", "page_path": "/services", "old": "a", "new": "b"}]},
              action_extra={"title": "Réécrire le H1 de /services",
                            "detail_md": "Changer le grand titre visible."},
              site_extra={"netlify_site_id": "nl-123"},
              verify_out={"ok": False, "decision": "hold", "checks": {
                  "blockers": ["diff visuel 42.0% > seuil 5.0%"]}})
final = updates[-1]
check("gros changement visuel sur du VISIBLE (h1) → publication bloquée",
      not r.get("ok") and final.get("apply_state") == "failed"
      and "diff visuel" in final.get("apply_error", ""))

# Modif INVISIBLE (titre) : un « diff visuel » est un faux positif → publiée
r = run_apply({"mode": "patches", "simple_md": "x",
               "patches": [{"field": "title", "page_path": "/realisations", "old": "a", "new": "b"}]},
              action_extra={"title": "Enrichir le titre de /realisations",
                            "detail_md": "Mettre à jour le titre Google."},
              site_extra={"netlify_site_id": "nl-123"},
              verify_out={"ok": False, "decision": "hold", "checks": {
                  "blockers": ["diff visuel 8.9% > seuil 5.0%"]}})
final = updates[-1]
check("titre (invisible) + faux diff visuel → publié quand même",
      r.get("ok") and final.get("status") == "merged"
      and final.get("apply_state") == "done")

# … mais une modif invisible avec un VRAI danger (vitesse) reste bloquée
r = run_apply({"mode": "patches", "simple_md": "x",
               "patches": [{"field": "title", "page_path": "/contact", "old": "a", "new": "b"}]},
              action_extra={"title": "Enrichir le titre de /contact",
                            "detail_md": "Mettre à jour le titre Google."},
              site_extra={"netlify_site_id": "nl-123"},
              verify_out={"ok": False, "decision": "hold", "checks": {
                  "blockers": ["perf preview 30 < plancher 55"]}})
final = updates[-1]
check("titre invisible mais VITESSE en chute → bloquée quand même",
      not r.get("ok") and final.get("apply_state") == "failed")

# Reprise d'une modification déjà préparée (PR ouverte au tour d'avant) :
# pas de refabrication — re-vérification puis publication directe
r = run_apply({"mode": "manual", "manual_reason": "ne doit pas être appelé"},
              action_extra={"status": "preview", "kind": "pr_modif",
                            "github_pr_url": "https://github.com/x/y/pull/9",
                            "branch": "phare/auto-old", "simple_md": "déjà prêt"})
final = updates[-1]
check("reprise PR existante → publiée sans repasser par l'IA",
      r.get("ok") and final.get("status") == "merged"
      and final.get("github_pr_url", "").endswith("/9"))

# request_apply accepte la reprise d'un échec, refuse une PR saine
with mock.patch.object(executor, "_get_action",
                       return_value={**ACTION, "status": "preview",
                                     "github_pr_url": "https://github.com/x/y/pull/9",
                                     "apply_state": "failed"}), \
     mock.patch.object(executor.repo, "get_site", return_value=dict(SITE)), \
     mock.patch.object(executor.repo, "_sb", return_value=None):
    r = executor.request_apply("act1")
    check("request_apply : reprise d'un échec acceptée (jusqu'à la mise en file)",
          "déjà préparée" not in (r.get("error") or ""))
with mock.patch.object(executor, "_get_action",
                       return_value={**ACTION, "status": "preview",
                                     "github_pr_url": "https://github.com/x/y/pull/9",
                                     "apply_state": ""}):
    r = executor.request_apply("act1")
    check("request_apply : PR saine → renvoyée vers « Publier sur le site »",
          not r.get("ok") and "déjà préparée" in r.get("error", ""))

# request_apply / process_apply_queue sans base → réponses propres
with mock.patch.object(executor, "_get_action", return_value=None):
    r = executor.request_apply("zzz")
    check("request_apply sur action inconnue → erreur claire",
          not r.get("ok") and "introuvable" in r.get("error", ""))
with mock.patch.object(executor.repo, "_sb", return_value=None):
    r = executor.process_apply_queue()
    check("process_apply_queue sans base → pas de crash",
          not r.get("ok") and r.get("processed") == 0)

# ===========================================================================
print(f"\n{'='*60}")
# ── Section ajoutée le 12/06/2026 au soir : plan B des balises uniques ──
# et filet anti-fragment du fuzzy (bug « content=" » qui avait produit la
# meta malformée d'Ingrid). Voir patcher._fuzzy_find_exact + plan B title.
def _section_plan_b():
    import tempfile, pathlib
    from triskell_command.integrations.phare.patcher import (
        localize_executor_patches, _fuzzy_find_exact)
    d = tempfile.mkdtemp()
    p = pathlib.Path(d) / "index.html"
    p.write_text(
        "<html><head><title>Ingrid Services — Ménage à Blanzy | 11 €/h après crédit d'impôt</title>"
        '<meta name="description" content="Ancienne description du site." />'
        "</head><body><h1>x</h1></body></html>", encoding="utf-8")
    pages = [{"path": "/", "title": "Ingrid Services — Ménage à Blanzy"}]

    out = localize_executor_patches(d, "html", [{
        "field": "title", "page_path": "/",
        "old": "Ingrid Services — Ménage à Blanzy | 11 €/h après crédit d'impôt",
        "new": "Ménage à domicile dès 11 €/h | Ingrid Services"}], pages)
    check("plan B title : espace insécable ne bloque plus",
          len(out["applicable"]) == 1
          and "<title>Ménage à domicile" in out["applicable"][0]["new"])

    out3 = localize_executor_patches(d, "html", [{
        "field": "title", "page_path": "/",
        "old": "Plomberie Dupont — dépannage 24h/24 à Marseille",
        "new": "N'importe quoi"}], pages)
    check("plan B : un old sans rapport part en revue humaine",
          not out3["applicable"] and bool(out3["needs_review"]))

    frag = _fuzzy_find_exact(
        '<meta name="description" content="Texte réel du site" />',
        'content="Autre chose totalement différente"')
    check("anti-fragment : plus jamais de match dégénéré « content=\" »",
          frag is None)

    leg = _fuzzy_find_exact("<p>L’artisan d’à côté</p>", "L'artisan d'à côté")
    check("le fuzzy légitime (apostrophes typographiques) marche toujours",
          leg == "L’artisan d’à côté")

_section_plan_b()

# ===========================================================================
# Section ajoutée le 17/06/2026 : texte des images (alt), plan du site
# régénéré, et badge « le robot peut le faire » honnête.
print("\n— images (alt), plan du site, badge honnête (17/06) —")

# 1) La carte « plan du site » ne doit plus parler de données structurées :
#    le mot « schemas » est dans l'URL du namespace sitemap (faux positif).
sitemap_card = {
    "agent": "sitemap_builder",
    "title": "Sitemap.xml généré (43 URLs)",
    "detail_md": ("Sitemap.xml prêt à publier dans `/public/sitemap.xml` "
                  "(2000 caractères, 43 URLs).\n\n```xml\n"
                  '<?xml version="1.0"?>\n<urlset xmlns="http://www.'
                  'sitemaps.org/schemas/sitemap/0.9"><url><loc>https://x.fr/'
                  "</loc></url></urlset>\n```"),
}
exp = pl.explain(sitemap_card)
check("carte plan du site → parle du plan du site, pas de données structurées",
      "plan du site" in exp and "structur" not in exp.lower())

# 2) maillage interne = à faire à la main (l'Exécuteur ne touche pas le corps)
v = pl.classify_for_apply({"status": "draft", "kind": "recommandation",
                           "agent": "tisseur",
                           "title": "Renforcer le maillage interne vers /demo",
                           "detail_md": "Ajouter des liens internes."}, site_ok)
check("maillage interne → à toi de le faire (pas un clic robot)",
      not v["can"] and v["mode"] == "manual" and "contenu" in v["why"])

# alt reste, lui, automatisable (le robot sait désormais le faire)
v = pl.classify_for_apply({"status": "draft", "kind": "recommandation",
                           "agent": "image_seo",
                           "title": "Ajouter le texte alternatif des images"},
                          site_ok)
check("texte des images → le robot peut le faire (code)",
      v["can"] and v["mode"] == "code")

# 3) patcher : poser un alt sur une image qui n'en a pas
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "index.html").write_text(
        "<html><head><title>Accueil</title></head><body>"
        '<img src="/img/hero-salon.jpg">'
        '<img src="/apple-touch-icon.png">'
        '<img src="/img/equipe.jpg" alt="Déjà décrite">'
        "</body></html>", encoding="utf-8")
    pgs = [{"path": "/", "title": "Accueil"}]
    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "alt", "page_path": "/", "image": "hero-salon.jpg",
         "new": "Salon de coiffure lumineux avec fauteuils design"},
    ], pgs)
    check("alt posé sur l'image qui n'en avait pas",
          len(loc["applicable"]) == 1
          and 'alt="Salon de coiffure' in loc["applicable"][0]["new"]
          and "hero-salon.jpg" in loc["applicable"][0]["new"])

    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "alt", "page_path": "/", "image": "apple-touch-icon.png",
         "new": "Icône"},
    ], pgs)
    check("icône (apple-touch-icon) → écartée, jamais d'alt forcé",
          not loc["applicable"]
          and "décorative" in loc["needs_review"][0]["reason"])

    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "alt", "page_path": "/", "image": "equipe.jpg",
         "new": "Autre texte"},
    ], pgs)
    check("image qui a DÉJÀ un alt → laissée tranquille",
          not loc["applicable"] and bool(loc["needs_review"]))

    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "alt", "page_path": "/", "image": "fantome.jpg", "new": "x"},
    ], pgs)
    check("image absente de la page → revue, jamais d'invention",
          not loc["applicable"]
          and "introuvable" in loc["needs_review"][0]["reason"])

# 4) executor : lecture déterministe des alts d'une carte Image SEO
det = ("**2 images** présentent au moins un problème.\n"
       "**2 alts** ont été générés automatiquement :\n\n"
       "- Page `/` — `hero-salon.jpg`\n  → `alt=\"Salon lumineux\"`\n"
       "- Page `/equipe` — `team.jpg`\n  → `alt=\"L'équipe au complet\"`")
parsed = executor._parse_image_seo_alts(det)
check("carte Image SEO → 2 patches alt lus (page + fichier + texte)",
      len(parsed) == 2 and parsed[0]["image"] == "hero-salon.jpg"
      and parsed[0]["page_path"] == "/"
      and parsed[0]["new"] == "Salon lumineux"
      and parsed[1]["field"] == "alt")

r = run_apply(None, action_extra={"agent": "image_seo",
                                  "detail_md": "**3 images** à corriger."})
final = updates[-1]
check("Image SEO sans alt exploitable → manuel propre, jamais d'échec",
      r.get("ok") and final.get("apply_state") == "manual"
      and "rien à faire" in final.get("apply_error", "").lower())

r = run_apply(None, action_extra={
    "agent": "image_seo",
    "detail_md": "- Page `/` — `hero.jpg`\n  → `alt=\"Un salon\"`"})
final = updates[-1]
check("Image SEO avec alt → publié comme une vraie modif (sans l'IA)",
      r.get("ok") and final.get("status") == "merged"
      and final.get("apply_state") == "done")

# 5) plan du site : équivalence (on ignore les dates) + cible
check("deux sitemaps mêmes URLs (lastmod différents) → équivalents",
      executor._sitemap_equivalent(
          "<urlset><url><loc>https://x.fr/</loc><lastmod>2026-06-01</lastmod></url></urlset>",
          "<urlset><url><loc>https://x.fr/</loc><lastmod>2026-06-17</lastmod></url></urlset>"))
check("sitemaps URLs différentes → pas équivalents",
      not executor._sitemap_equivalent(
          "<urlset><url><loc>https://x.fr/a</loc></url></urlset>",
          "<urlset><url><loc>https://x.fr/b</loc></url></urlset>"))

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "public").mkdir()
    rel, existing = patcher.resolve_sitemap_target(str(root))
    check("pas de sitemap + dossier public → créé dans public/sitemap.xml",
          rel == "public/sitemap.xml" and existing is None)
    (root / "public" / "sitemap.xml").write_text("<urlset></urlset>",
                                                  encoding="utf-8")
    rel, existing = patcher.resolve_sitemap_target(str(root))
    check("sitemap existant retrouvé dans public/ avec son contenu",
          rel == "public/sitemap.xml" and existing == "<urlset></urlset>")


def run_sitemap_apply(*, resolve_ret):
    """_apply_one sur une carte plan du site, tout accès externe doublé."""
    updates.clear()
    fake_pr = {"ok": True, "branch": "phare/auto-sm", "pr_number": 5,
               "pr_url": "https://github.com/x/y/pull/5"}
    action = {**ACTION, "agent": "sitemap_builder",
              "title": "Sitemap.xml généré (3 URLs)"}
    with mock.patch.object(executor, "_get_action", return_value=action), \
         mock.patch.object(executor.repo, "get_site", return_value=dict(SITE)), \
         mock.patch.object(executor.repo, "update_action", side_effect=fake_update), \
         mock.patch.object(executor.repo, "list_pages",
                           return_value=[{"path": "/", "url": "https://pixel-pros.fr/"}]), \
         mock.patch.object(executor.shutil, "which", return_value="C:/git.exe"), \
         mock.patch.object(git_pipeline, "_github_token", return_value="tok"), \
         mock.patch.object(git_pipeline, "clone_repo", return_value=True), \
         mock.patch.object(git_pipeline, "apply_and_open_pr", return_value=fake_pr), \
         mock.patch.object(git_pipeline, "merge_pr", return_value=True), \
         mock.patch.object(git_pipeline, "verify_pr",
                           return_value={"ok": True, "checks": {}, "decision": "merge"}), \
         mock.patch.object(patcher, "resolve_sitemap_target", return_value=resolve_ret):
        return executor._apply_one("act1")


r = run_sitemap_apply(resolve_ret=("public/sitemap.xml", None))
final = updates[-1]
check("plan du site absent → créé et publié",
      r.get("ok") and final.get("status") == "merged"
      and final.get("apply_state") == "done")

same_xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            "  <url>\n    <loc>https://pixel-pros.fr/</loc>\n"
            "    <lastmod>2020-01-01</lastmod>\n    <changefreq>weekly</changefreq>\n"
            "  </url>\n</urlset>")
r = run_sitemap_apply(resolve_ret=("public/sitemap.xml", same_xml))
final = updates[-1]
check("plan du site déjà à jour → marqué fait, aucune erreur sans fin",
      r.get("ok") and final.get("apply_state") == "done"
      and "à jour" in final.get("simple_md", ""))

# ===========================================================================
# Section ajoutée le 17/06/2026 : redirections en double étape corrigées
# automatiquement (lien interne rendu direct), faux signaux d'hébergeur écartés.
print("\n— redirections (lien rendu direct) (17/06) —")
from triskell_command.integrations.phare import crawler as _crawler

check("redirection http→https (même page) → PAS une corvée",
      not _crawler._redirect_is_actionable("http://x.fr/page", "https://x.fr/page"))
check("redirection www → non-www → PAS une corvée",
      not _crawler._redirect_is_actionable("https://www.x.fr/p", "https://x.fr/p"))
check("redirection barre de fin → PAS une corvée",
      not _crawler._redirect_is_actionable("https://x.fr/p/", "https://x.fr/p"))
check("vrai changement /ancienne → /nouvelle → à corriger",
      _crawler._redirect_is_actionable("https://x.fr/ancienne", "https://x.fr/nouvelle"))

ch = executor._parse_redirect_chain(
    "Source : https://x.fr/ancienne\nDestination finale : https://x.fr/nouvelle\nbla")
check("carte redirection lue (source + destination)",
      ch and ch["source"] == "https://x.fr/ancienne"
      and ch["final"] == "https://x.fr/nouvelle")

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "index.html").write_text(
        '<html><body><a href="/ancienne">Voir</a> '
        '<a href="https://x.fr/ancienne">aussi</a></body></html>',
        encoding="utf-8")
    (root / "autre.html").write_text(
        '<html><body><a href="/contact">Contact</a></body></html>',
        encoding="utf-8")
    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "link_redirect", "source": "https://x.fr/ancienne",
         "final": "https://x.fr/nouvelle"},
    ], [])
    fixed = next((p for p in loc["applicable"] if p["file"] == "index.html"), None)
    check("lien interne rendu direct (chemin ET URL complète)",
          fixed and 'href="/nouvelle"' in fixed["new"]
          and "/ancienne" not in fixed["new"])
    check("la page sans ce lien n'est pas touchée",
          all(p["file"] != "autre.html" for p in loc["applicable"]))

    loc = patcher.localize_executor_patches(str(root), "html", [
        {"field": "link_redirect", "source": "https://x.fr/jamais-liee",
         "final": "https://x.fr/final"},
    ], [])
    check("aucun lien vers l'adresse → revue « géré par l'hébergeur »",
          not loc["applicable"]
          and "hébergeur" in loc["needs_review"][0]["reason"])

r = run_apply(None, action_extra={
    "agent": "redirect_fixer",
    "detail_md": "Source : https://pixel-pros.fr/ancienne\n"
                 "Destination finale : https://pixel-pros.fr/nouvelle"})
final = updates[-1]
check("redirection → corrigée et publiée (sans l'IA)",
      r.get("ok") and final.get("status") == "merged"
      and final.get("apply_state") == "done")

r = run_apply(None, action_extra={
    "agent": "redirect_fixer",
    "detail_md": "Source : https://pixel-pros.fr/x\n"
                 "Destination finale : https://pixel-pros.fr/y"},
    localized={"applicable": [], "needs_review": [
        {"reason": "aucun lien interne vers cette adresse "
                   "(redirection gérée par l'hébergeur)"}]})
final = updates[-1]
check("redirection côté hébergeur → manuel propre, jamais d'échec",
      r.get("ok") and final.get("apply_state") == "manual"
      and "hébergeur" in final.get("apply_error", ""))

# ===========================================================================
# Section ajoutée le 17/06/2026 : publication qui attend la vérif GitHub
# (course async sur mergeable → 405 « not mergeable » sur les modifs de pages).
print("\n— publication : attendre la vérif GitHub avant de fusionner (17/06) —")


def _section_merge_race():
    gp = git_pipeline

    class Resp:
        def __init__(s, status, payload=None, text=""):
            s.status_code = status
            s._p = payload or {}
            s.text = text

        def json(s):
            return s._p

    class FakeReq:
        RequestException = Exception

        def __init__(s, gets, puts):
            s.gets = list(gets)
            s.puts = list(puts)

        def get(s, *a, **k):
            return s.gets.pop(0)

        def put(s, *a, **k):
            return s.puts.pop(0)

    with mock.patch.object(gp, "_github_token", return_value="tok"), \
         mock.patch.object(gp.time, "sleep", lambda *a, **k: None):
        # GitHub calcule encore (null) puis devient fusionnable → publication OK
        fake = FakeReq(gets=[Resp(200, {"mergeable": None}),
                             Resp(200, {"mergeable": True})],
                       puts=[Resp(200, {})])
        with mock.patch.object(gp, "requests", fake):
            ok = gp.merge_pr("o/r", 12)
        check("publication : attend la vérif GitHub, puis publie", ok is True)

        # 405 persistant → échec propre AVEC la vraie raison
        fake = FakeReq(gets=[Resp(200, {"mergeable": True})] * 5,
                       puts=[Resp(405, {"message": "Pull Request is not mergeable"})] * 3)
        with mock.patch.object(gp, "requests", fake):
            ok = gp.merge_pr("o/r", 12)
        check("publication : 405 persistant → échec + vraie raison remontée",
              ok is False and "405" in gp.last_merge_error)

        # conflit réel → on ne publie pas à l'aveugle
        fake = FakeReq(gets=[Resp(200, {"mergeable": False})], puts=[])
        with mock.patch.object(gp, "requests", fake):
            ok = gp.merge_pr("o/r", 12)
        check("publication : conflit réel → refus clair, pas de publication à l'aveugle",
              ok is False and "conflit" in gp.last_merge_error)


_section_merge_race()

# ===========================================================================
# Section ajoutée le 17/06/2026 : « le robot agit seul » — auto-application
# des corrections SÛRES (sans le clic de Jordan), même interrupteur que l'auto-
# publication. Refonte demandée par Jordan (outil trop complexe / trop à faire).
print("\n— le robot agit seul : auto-application des corrections sûres (17/06) —")
from triskell_command.integrations.phare import orchestrator as orch

check("titre → auto-applicable",
      orch._is_auto_safe({"agent": "auditeur", "title": "Réécrire le title de /demo"}))
check("redirection → auto-applicable",
      orch._is_auto_safe({"agent": "redirect_fixer", "title": "Lien direct"}))
check("plan du site → auto-applicable",
      orch._is_auto_safe({"agent": "sitemap_builder", "title": "Sitemap.xml généré (12 URLs)"}))
check("images → auto-applicable",
      orch._is_auto_safe({"agent": "image_seo", "title": "Image SEO : 3 alts"}))
check("maillage interne → PAS auto (touche le contenu)",
      not orch._is_auto_safe({"agent": "tisseur",
                              "title": "Renforcer le maillage interne",
                              "detail_md": "Ajouter des liens internes vers /x"}))
check("Search Console → PAS auto (besoin d'un humain)",
      not orch._is_auto_safe({"agent": "auditeur",
                              "title": "Vérifier la couverture dans Search Console",
                              "detail_md": "Ouvrir la Search Console"}))
check("conseil flou sans famille → PAS auto (jamais à l'aveugle)",
      not orch._is_auto_safe({"agent": "auditeur", "title": "Améliorer le contenu",
                              "detail_md": "Rendre la page plus riche et utile"}))
check("la PAGE D'ACCUEIL (vitrine) reste toujours la décision de Jordan",
      not orch._is_auto_safe({"agent": "auditeur",
                              "title": "Réécrire le title de la home",
                              "detail_md": "Page: https://pixel-pros.fr/"}))
check("une page interne (pas l'accueil) reste auto-applicable",
      orch._is_auto_safe({"agent": "auditeur", "title": "Réécrire le title",
                          "detail_md": "Page: https://pixel-pros.fr/realisations"}))
check("la home en MOTS (sans chemin explicite) est AUSSI protégée",
      not orch._is_auto_safe({"agent": "auditeur",
                              "title": "Réécrire le titre de la home et la méta"}))
check("« accueil » cité mais une AUTRE page visée → reste applicable",
      orch._is_auto_safe({"agent": "auditeur", "title": "Réécrire le titre de /tarifs",
                          "detail_md": "Comme sur la page d'accueil. Page: /tarifs"}))

DRAFTS = [
    {"id": "t1", "site_id": "s1", "agent": "auditeur", "status": "draft",
     "apply_state": "", "title": "Réécrire le title de /contact"},
    {"id": "m1", "site_id": "s1", "agent": "tisseur", "status": "draft",
     "apply_state": "", "title": "Maillage interne", "detail_md": "liens internes"},
    {"id": "t2", "site_id": "s1", "agent": "auditeur", "status": "draft",
     "apply_state": "queued", "title": "Title déjà en file"},
    {"id": "r1", "site_id": "s2", "agent": "redirect_fixer", "status": "draft",
     "apply_state": "", "title": "Lien direct",
     "detail_md": "Source : https://x.fr/a\nDestination finale : https://x.fr/b"},
    {"id": "a1", "site_id": "s3", "agent": "image_seo", "status": "draft",
     "apply_state": "", "title": "Image SEO : 2 alts"},
]
SITES_AA = {"s1": {"id": "s1", "repo_github": "o/r1"},
            "s2": {"id": "s2", "repo_github": "o/r2"},
            "s3": {"id": "s3", "repo_github": ""}}     # s3 pas relié au code
aa_calls = []


def _aa_upd(aid, patch):
    aa_calls.append((aid, patch))
    return True


with mock.patch.object(orch.repo, "get_config",
                       return_value={"auto_merge_enabled": False}):
    r = orch.auto_apply_safe()
    check("interrupteur éteint → le robot n'agit pas seul",
          r.get("skipped") == "disabled")

with mock.patch.object(orch.repo, "get_config",
                       return_value={"auto_merge_enabled": True}), \
     mock.patch.object(orch.repo, "list_actions",
                       return_value=[dict(d) for d in DRAFTS]), \
     mock.patch.object(orch.repo, "get_site",
                       side_effect=lambda sid: SITES_AA.get(sid)), \
     mock.patch.object(orch.repo, "update_action", side_effect=_aa_upd):
    r = orch.auto_apply_safe()
    ids = {e["id"] for e in r["enqueued"]}
    check("interrupteur allumé → met en file le titre + la redirection",
          "t1" in ids and "r1" in ids)
    check("ignore le maillage (contenu)", "m1" not in ids)
    check("ignore une carte déjà en file", "t2" not in ids)
    check("ignore une image sur un site non relié au code", "a1" not in ids)
    check("met bien les cartes en file (apply_state=queued)",
          bool(aa_calls) and all(p.get("apply_state") == "queued" for _, p in aa_calls))

with mock.patch.object(orch.repo, "get_config",
                       return_value={"auto_merge_enabled": True}), \
     mock.patch.object(orch.repo, "list_actions",
                       return_value=[dict(d) for d in DRAFTS]), \
     mock.patch.object(orch.repo, "get_site",
                       side_effect=lambda sid: SITES_AA.get(sid)), \
     mock.patch.object(orch.repo, "update_action", side_effect=_aa_upd):
    r = orch.auto_apply_safe(max_apply=1)
    check("plafond par passage respecté (max_apply)", len(r["enqueued"]) == 1)

# ===========================================================================
# Section ajoutée le 17/06/2026 : boutons « Réessayer » / « Publier sur le
# site » réparés (modif déjà préparée qui ne se republiait pas + diff visuel
# faux positif côté publication manuelle).
print("\n— boutons « Réessayer » / « Publier sur le site » réparés (17/06) —")

ru = []
with mock.patch.object(executor, "_get_action",
        return_value={"id": "p1", "apply_state": "failed", "status": "preview",
                      "github_pr_url": "https://github.com/x/y/pull/3"}), \
     mock.patch.object(executor, "_update",
        side_effect=lambda aid, patch: (ru.append(patch), True)[1]), \
     mock.patch.object(executor, "request_apply",
        side_effect=lambda aid, **k: {"ok": True, "mode": "server"}):
    r = executor.retry_apply("p1")
    check("Réessayer (PR déjà préparée) → ne vide pas l'état, relance bien",
          r.get("ok") and all("apply_state" not in p for p in ru))

ru2 = []
with mock.patch.object(executor, "_get_action",
        return_value={"id": "n1", "apply_state": "failed", "status": "draft",
                      "github_pr_url": ""}), \
     mock.patch.object(executor, "_update",
        side_effect=lambda aid, patch: (ru2.append(patch), True)[1]), \
     mock.patch.object(executor, "request_apply",
        side_effect=lambda aid, **k: {"ok": True}):
    executor.retry_apply("n1")
    check("Réessayer (sans PR) → remise à zéro complète",
          any(p.get("apply_state") == "" for p in ru2))

ma_db = {"rows": [{"id": "mp1", "site_id": "s1", "branch": "b",
                   "github_pr_url": "https://github.com/x/y/pull/9",
                   "title": "Enrichir le titre de /realisations",
                   "detail_md": "Mettre à jour le titre Google."}], "inserts": []}
ma_site = {"id": "s1", "repo_github": "x/y", "netlify_site_id": "nl"}

merged_n = []
with mock.patch.object(orch.repo, "_sb", return_value=FakeSB(ma_db)), \
     mock.patch.object(orch.repo, "get_site", return_value=ma_site), \
     mock.patch.object(orch.repo, "update_action", side_effect=lambda aid, p: True), \
     mock.patch.object(orch.git_pipeline, "verify_pr",
        return_value={"ok": False, "decision": "hold",
                      "checks": {"blockers": ["diff visuel 8.9% > seuil 5.0%"]}}), \
     mock.patch.object(orch.git_pipeline, "merge_pr",
        side_effect=lambda repo, n, **k: (merged_n.append(n), True)[1]):
    r = orch.merge_action("mp1", force=False)
    check("« Publier sur le site » titre + faux diff visuel → publié",
          r.get("ok") and 9 in merged_n)

merged_n2 = []
with mock.patch.object(orch.repo, "_sb", return_value=FakeSB(ma_db)), \
     mock.patch.object(orch.repo, "get_site", return_value=ma_site), \
     mock.patch.object(orch.repo, "update_action", side_effect=lambda aid, p: True), \
     mock.patch.object(orch.git_pipeline, "verify_pr",
        return_value={"ok": False, "decision": "hold",
                      "checks": {"blockers": ["perf preview 30 < plancher 55"]}}), \
     mock.patch.object(orch.git_pipeline, "merge_pr",
        side_effect=lambda repo, n, **k: (merged_n2.append(n), True)[1]):
    r = orch.merge_action("mp1", force=False)
    check("« Publier sur le site » + vitesse en chute → bloqué (pas publié)",
          not r.get("ok") and not merged_n2)

# ===========================================================================
# Section ajoutée le 17/06/2026 : plus JAMAIS de jargon technique montré à
# Jordan (filtre central + refus du robot nettoyé).
print("\n— plus jamais de jargon montré à Jordan (17/06) —")

check("détecte le jargon (FAQPage / schema.org / H1)",
      pl.has_jargon("Le balisage FAQPage en schema.org exige de reprendre le H1"))
check("détecte fetchpriority / balise <img>",
      pl.has_jargon('Ajouter fetchpriority="high" sur une balise <img>'))
check("français normal → aucun jargon détecté",
      not pl.has_jargon("Pour bien faire, j'ai besoin de recopier tes vraies "
                        "questions-réponses déjà écrites sur ta page."))

r = run_apply({"mode": "manual",
               "manual_reason": "Le balisage FAQPage en schema.org exige le H1."})
final = updates[-1]
check("refus en jargon → message propre sur la carte (zéro charabia)",
      final.get("apply_state") == "manual"
      and not pl.has_jargon(final.get("apply_error", "")))

check("explain : 1re ligne en jargon → phrase neutre, pas le charabia",
      not pl.has_jargon(pl.explain(
          {"detail_md": "Ajouter fetchpriority sur le <img> en haut de page."})))

# ===========================================================================
# Section ajoutée le 17/06/2026 : le robot FAIT la FAQ structurée et le
# préchargement de l'image tout seul (lecture EN DIRECT de la page).
print("\n— le robot fait la FAQ + le préchargement tout seul (17/06) —")
from triskell_command.integrations.phare import page_extract as pe

SAMPLE_FAQ = (
    '<html><body><section id="faq"><div class="faq">'
    '<details class="faq-item"><summary>Combien coûte un site ?</summary>'
    '<div>À partir de 24,90 € par mois, tout compris.</div></details>'
    '<details class="faq-item"><summary>En combien de temps ?</summary>'
    '<p>Ton site est livré en 24 heures après ta commande.</p></details>'
    '</div></section>'
    '<img src="/img/hero-photographe.jpg" alt="x"><img src="/favicon.ico">'
    '</body></html>')

pairs = pe.extract_faq_pairs(SAMPLE_FAQ)
check("lit les vraies questions-réponses de la page",
      len(pairs) == 2 and pairs[0]["q"] == "Combien coûte un site ?"
      and "24,90" in pairs[0]["a"])
jsonld = pe.build_faqpage_jsonld(pairs)
check("construit le bloc FAQ mot pour mot (jamais inventé)",
      "FAQPage" in jsonld and "Combien coûte un site ?" in jsonld and "24,90" in jsonld)
check("détecte une FAQ déjà en place",
      pe.has_faq_schema('<script>{"@type":"FAQPage"}</script>'))
check("trouve la grande image, ignore le favicon",
      (pe.find_hero_image(SAMPLE_FAQ, "https://x.fr/") or "").endswith("hero-photographe.jpg"))
check("balise de préchargement = chemin relatif au domaine",
      'rel="preload"' in pe.preload_link("https://x.fr/img/hero.jpg")
      and 'href="/img/hero.jpg"' in pe.preload_link("https://x.fr/img/hero.jpg"))

check("page visée extraite du titre (/photographe)",
      executor._card_page_path(
          {"title": "Ajouter une FAQ structurée sur /photographe"}) == "/photographe")
check("carte « de la home » → /",
      executor._card_page_path(
          {"title": "Précharger l'image principale de la home"}) == "/")

SITE_X = {"domain": "x.fr"}
with mock.patch.object(pe, "fetch_page", return_value=SAMPLE_FAQ):
    out = executor._build_faq_out(
        {"title": "Ajouter une FAQ structurée sur /photographe"}, SITE_X)
    check("FAQ visible → le robot prépare le bloc (pas de refus)",
          out["mode"] == "patches"
          and out["patches"][0]["field"] == "head_insert"
          and "FAQPage" in out["patches"][0]["new"])
with mock.patch.object(pe, "fetch_page",
                       return_value="<html><body>aucune faq ici</body></html>"):
    out = executor._build_faq_out(
        {"title": "Ajouter une FAQ structurée sur /x"}, SITE_X)
    check("pas de vraie FAQ → manuel propre (jamais inventer, zéro jargon)",
          out["mode"] == "manual" and not pl.has_jargon(out["manual_reason"]))
with mock.patch.object(pe, "fetch_page", return_value=SAMPLE_FAQ):
    out = executor._build_preload_out(
        {"title": "Précharger l'image de la home"}, SITE_X)
    check("grande image trouvée → préchargement préparé",
          out["mode"] == "patches" and "preload" in out["patches"][0]["new"])
check("page sans vraie grande image (icône + fond CSS) → le robot s'abstient",
      pe.find_hero_image('<html><body><img src="/apple-touch-icon.png">'
                         '<div style="background-image:url(/img/x.jpg)"></div>'
                         '</body></html>', "https://x.fr/") is None)
check("jamais précharger l'image de PARTAGE (og:image) toute seule",
      pe.find_hero_image('<html><head><meta property="og:image" content="/og.png">'
                         '</head><body><img src="/favicon.ico"></body></html>',
                         "https://x.fr/") is None)
with mock.patch.object(pe, "fetch_page",
                       return_value='<html><body><img src="/favicon.ico"></body></html>'):
    out = executor._build_preload_out({"title": "Précharger l'image de la home"}, SITE_X)
    check("pas d'image classique → manuel propre, sans forcer",
          out["mode"] == "manual" and not pl.has_jargon(out["manual_reason"]))

check("FAQ + préchargement = invisible → pas bloqué par le diff visuel",
      executor._is_metadata_only({"title": "Ajouter une FAQ structurée sur /x"})
      and executor._is_metadata_only({"title": "Précharger l'image de la home"}))

# Le classement reconnaît les nouvelles capacités → bouton « OK, fais-le »
check("carte FAQ → le robot peut le faire (bouton vert)",
      pl.classify_for_apply(
          {"status": "draft", "title": "Ajouter une FAQ structurée sur /x"}, site_ok)["can"])
check("carte préchargement → le robot peut le faire",
      pl.classify_for_apply(
          {"status": "draft", "title": "Précharger l'image principale de la home"}, site_ok)["can"])
check("écrire du contenu → reste à toi (pas de faux bouton vert)",
      not pl.classify_for_apply(
          {"status": "draft", "title": "Rédiger une page de service"}, site_ok)["can"])
check("convertir les images en WebP → reste à toi",
      not pl.classify_for_apply(
          {"status": "draft", "title": "Convertir les images en WebP/AVIF"}, site_ok)["can"])
fp = pl.classify_for_apply(
    {"status": "draft", "kind": "recommandation",
     "title": "Ajouter fetchpriority='high' sur l'image hero de la home",
     "detail_md": "Vérifier le gain LCP dans PageSpeed après déploiement."}, site_ok)
check("carte « fetchpriority » → à voir ensemble (pas de faux bouton « relance la mesure »)",
      fp["can"] is False and fp["mode"] == "manual")

# Bug 18/06 : une carte que le robot a DÉJÀ jugée « à la main » (apply_state
# 'manual') ne doit plus se voir recoller une pastille verte optimiste — sinon
# « le robot peut le faire » s'affiche AU-DESSUS de « il préfère ne pas y toucher ».
# Titre SANS famille ni signal de contenu → il atteint vraiment le fallback optimiste.
_declined = {"status": "draft", "kind": "recommandation", "apply_state": "manual",
             "title": "Installer la mesure d'INP via un snippet web-vitals"}
check("déjà jugée « à la main » → plus de faux bouton vert optimiste",
      pl.classify_for_apply(_declined, site_ok)["can"] is False)
# La MÊME carte jamais tentée garde sa chance (fallback optimiste assumé).
check("même carte jamais tentée → le robot regarde (optimiste)",
      pl.classify_for_apply({**_declined, "apply_state": ""}, site_ok)["can"] is True)
# Une vraie capacité (titre) PRIME sur un refus passé (capacités grandies).
check("capacité sûre (titre) → reprend la main malgré un refus passé",
      pl.classify_for_apply(
          {"status": "draft", "apply_state": "manual",
           "title": "Réécrire le title de la home"}, site_ok)["can"] is True)
# Bug 18/06 (capture Jordan) : créer/dupliquer une page ou écrire son contenu =
# hors de portée de l'Exécuteur. Le faux bouton vert venait d'un détail citant
# « Title cible : … » ou « + H1 » qui allumait à tort la famille title/h1.
_dup = pl.classify_for_apply(
    {"status": "draft", "kind": "recommandation",
     "title": "Dupliquer /carreleur en /electricien avec adaptation minimale",
     "detail_md": "Title cible : « Site internet pour électricien — Pixel Pros »."}, site_ok)
check("dupliquer une page (détail cite « Title cible ») → à la main, pas de bouton vert",
      _dup["can"] is False and _dup["mode"] == "manual")
_homecontent = pl.classify_for_apply(
    {"status": "draft", "kind": "recommandation",
     "title": "Publier un contenu minimal sur la home (300 mots + H1 ciblé)"}, site_ok)
check("publier le contenu d'une page (cite « H1 ») → à la main, pas de bouton vert",
      _homecontent["can"] is False and _homecontent["mode"] == "manual")
# Bug 18/06 (capture Jordan) : la surveillance GEO (« GEO check : 0/0 mentions »)
# est un RAPPORT à lire, pas une action → jamais de bouton vert « OK, fais-le ».
_geo = pl.classify_for_apply(
    {"status": "draft", "kind": "recommandation", "agent": "geo_surveillant",
     "title": "GEO check : 0/0 mentions (0%)"}, site_ok)
check("carte GEO check (surveillance) → à lire, pas de faux bouton vert",
      _geo["can"] is False and _geo["mode"] == "info")

print(f"Bilan : {PASS} ✅ / {FAIL} ❌ sur {PASS + FAIL} contrôles")
sys.exit(1 if FAIL else 0)
