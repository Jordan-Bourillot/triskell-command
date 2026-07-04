# -*- coding: utf-8 -*-
"""Smoke test : désinscription 1-clic + routage multi-adresses même marque.

Vérifie SANS réseau :
  1. Jeton signé : aller-retour, rejet d'un jeton falsifié / d'un autre
     secret, lien et en-têtes one-click, pied de mail (idempotent).
  2. prospection_headers (core) : URL + List-Unsubscribe-Post quand le
     destinataire est connu ; mailto seul sinon (rétro-compatible).
  3. Routage modèle→adresse : rotation entre adresses du MÊME domaine,
     jamais une autre marque, report quand tout est au plafond.
  4. Branchements : route /api/unsubscribe publique, garde-fou de l'envoi
     groupé, désinscription par adresse.

Usage :  python scripts/smoke_unsubscribe.py
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Secret stable AVANT tout import du module (il met le secret en cache).
os.environ["UNSUBSCRIBE_SECRET"] = "secret-de-test-stable"
os.environ["PUBLIC_BASE_URL"] = "https://command.triskell-studio.fr"

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
CORE = HERE.parent / "triskell-core"
if CORE.exists():
    sys.path.insert(0, str(CORE))

PASS, FAIL = [], []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(label); print(f"  OK  - {label}")
    else:
        FAIL.append(label); print(f"  FAIL- {label} {detail}")


# ---------------------------------------------------------------------------
print("1) Jeton signé + lien + pied…")
from triskell_command.integrations import unsubscribe as U  # noqa: E402

tok = U.make_token("Jean@Exemple.FR", "pid-123")
info = U.verify_token(tok)
check("aller-retour : email normalisé + id",
      info and info["email"] == "jean@exemple.fr"
      and info["prospect_id"] == "pid-123")
check("jeton tronqué → refusé", U.verify_token("nimporte") is None)
check("signature falsifiée → refusée",
      U.verify_token(tok[:-3] + "000") is None)

# Un autre secret ne doit pas valider le jeton.
U._SECRET_CACHE = ""
os.environ["UNSUBSCRIBE_SECRET"] = "un-autre-secret"
check("jeton d'un autre secret → refusé", U.verify_token(tok) is None)
# On restaure le secret de test.
U._SECRET_CACHE = ""
os.environ["UNSUBSCRIBE_SECRET"] = "secret-de-test-stable"
check("jeton de nouveau valide avec le bon secret",
      (U.verify_token(tok) or {}).get("email") == "jean@exemple.fr")

url = U.unsubscribe_url("jean@exemple.fr", "pid-123")
check("URL = base publique + /api/unsubscribe?u=",
      url.startswith("https://command.triskell-studio.fr/api/unsubscribe?u="))

h = U.headers_for("contact@pixel-pros.fr", "jean@exemple.fr", "pid-123")
check("en-tête List-Unsubscribe = URL + mailto",
      "/api/unsubscribe?u=" in h["List-Unsubscribe"]
      and "mailto:contact@pixel-pros.fr" in h["List-Unsubscribe"])
check("en-tête one-click présent (RFC 8058)",
      h.get("List-Unsubscribe-Post") == "List-Unsubscribe=One-Click")
check("sans destinataire → mailto seul (repli)",
      U.headers_for("contact@pixel-pros.fr", "") ==
      {"List-Unsubscribe": "<mailto:contact@pixel-pros.fr?subject=unsubscribe>"})

t2, ht2 = U.inject_footer("Bonjour.", "<p>Bonjour.</p>", "jean@exemple.fr", "pid-123")
check("pied ajouté au texte", "/api/unsubscribe?u=" in t2 and "Bonjour." in t2)
check("pied ajouté au HTML", "/api/unsubscribe?u=" in ht2 and "<p>Bonjour.</p>" in ht2)
t3, ht3 = U.inject_footer(t2, ht2, "jean@exemple.fr", "pid-123")
check("pied idempotent (pas de doublon)",
      t3.count("/api/unsubscribe?u=") == 1 and ht3.count("/api/unsubscribe?u=") == 1)
tn, htn = U.inject_footer("Corps", "", "")
check("sans destinataire → corps inchangé", tn == "Corps" and htn == "")
# Document HTML complet : le pied s'insère DANS le corps (avant </body>).
_, hdoc = U.inject_footer(
    "x", "<html><body><p>Salut</p></body></html>", "jean@exemple.fr")
check("pied inséré avant </body> (document complet)",
      hdoc.index("/api/unsubscribe?u=") < hdoc.index("</body>")
      and hdoc.endswith("</body></html>"))

# ---------------------------------------------------------------------------
print("2) prospection_headers (core)…")
from triskell_core.prospect.outreach.smtp_sender import prospection_headers  # noqa: E402

hh = prospection_headers("contact@pixel-pros.fr",
                          to_email="jean@exemple.fr", prospect_id="pid-9")
check("avec destinataire → URL + one-click",
      "/api/unsubscribe?u=" in hh.get("List-Unsubscribe", "")
      and hh.get("List-Unsubscribe-Post") == "List-Unsubscribe=One-Click")
hh2 = prospection_headers("contact@pixel-pros.fr")
check("sans destinataire → mailto seul (rétro-compatible)",
      hh2 == {"List-Unsubscribe": "<mailto:contact@pixel-pros.fr?subject=unsubscribe>"})

# ---------------------------------------------------------------------------
print("3) Routage modèle→adresse (rotation même marque)…")
from triskell_core.prospect.pipeline import _route_for_template_address as route  # noqa: E402

# Une seule adresse de la marque, dispo → elle.
r = route("contact@pixel-pros.fr", {"contact@pixel-pros.fr": "pp1"}, {"pp1": 5})
check("1 adresse dispo → ok", r == ("ok", "pp1"))

# Trois adresses pixel-pros.fr dispo → rotation (au moins 2 comptes vus).
pool = {"contact@pixel-pros.fr": "pp1", "hello@pixel-pros.fr": "pp2",
        "bonjour@pixel-pros.fr": "pp3"}
rem = {"pp1": 5, "pp2": 5, "pp3": 5}
seen = set()
for _ in range(60):
    d, aid = route("contact@pixel-pros.fr", pool, rem)
    if d == "ok":
        seen.add(aid)
check("3 adresses même marque → rotation réelle", len(seen) >= 2,
      f"(comptes vus : {seen})")
check("rotation reste dans la marque", seen <= {"pp1", "pp2", "pp3"})

# Pool mixte : jamais une autre marque que celle exigée.
mixed = {"contact@pixel-pros.fr": "pp1", "contact@studio-wow.fr": "wow"}
remm = {"pp1": 5, "wow": 5}
seen2 = set()
for _ in range(60):
    d, aid = route("contact@pixel-pros.fr", mixed, remm)
    if d == "ok":
        seen2.add(aid)
check("marque exigée respectée (jamais WoW)", seen2 == {"pp1"},
      f"(comptes vus : {seen2})")

# Toutes les adresses de la marque au plafond → report (cap).
d, aid = route("contact@pixel-pros.fr", pool, {"pp1": 0, "pp2": 0, "pp3": 0})
check("toute la marque au plafond → cap (brouillon)", d == "cap")

# Marque absente du pool → missing.
d, aid = route("contact@pixel-pros.fr", {"contact@studio-wow.fr": "wow"}, {"wow": 5})
check("marque absente du pool → missing", d == ("missing"))

# Pas d'adresse exigée → tirage libre habituel.
check("pas d'adresse exigée → none",
      route("", pool, rem) == ("none", ""))

# ---------------------------------------------------------------------------
print("4) Branchements…")
from triskell_command.web import auth as tcauth  # noqa: E402
check("route /api/unsubscribe publique (sans login)",
      "/api/unsubscribe" in tcauth.PUBLIC_API_PATHS)

from triskell_command.web import http_server  # noqa: E402
src_http = inspect.getsource(http_server)
check("serveur : route GET + POST /api/unsubscribe",
      'app.get("/api/unsubscribe")' in src_http
      and 'app.post("/api/unsubscribe")' in src_http)

from triskell_command.integrations import prospect_status as PS  # noqa: E402
check("désinscription par adresse disponible",
      callable(getattr(PS, "mark_unsubscribed_by_email", None)))

from triskell_command.web.api import Api  # noqa: E402
src_batch = inspect.getsource(Api._drafts_batch_worker)
check("envoi groupé : garde-fou plafond (montée auto)",
      "apply_ramp" in src_batch and "deferred" in src_batch)

src_appr = inspect.getsource(Api._approve_prospect_draft)
check("validation brouillon : pied de désinscription injecté",
      "inject_footer" in src_appr)

# ---------------------------------------------------------------------------
print("5) Désinscription des CRÉATEURS…")
from triskell_command.integrations import creators_book as CB  # noqa: E402


class _Res:
    def __init__(self, data): self.data = data


class _Q:
    """Faux constructeur de requête Supabase (fluent) — table/select/ilike/
    eq/update/execute — juste ce que creators_book utilise."""
    def __init__(self, store, rows=None, update=None):
        self.store = store
        self.rows = rows if rows is not None else list(store["rows"])
        self._update = update

    def select(self, *a, **k):
        return self

    def ilike(self, col, val):
        needle = val.strip("%").lower()
        exact = not val.startswith("%")
        def m(r):
            cell = (r.get(col) or "").lower()
            return cell == needle if exact else needle in cell
        return _Q(self.store, [r for r in self.rows if m(r)], self._update)

    def eq(self, col, val):
        return _Q(self.store,
                  [r for r in self.rows if str(r.get(col)) == str(val)],
                  self._update)

    def update(self, data):
        return _Q(self.store, self.rows, data)

    def execute(self):
        if self._update is not None:
            for r in self.rows:
                r.update(self._update)
            self.store["updates"] += 1
        return _Res(list(self.rows))


class FakeSB:
    def __init__(self, rows):
        self.store = {"rows": rows, "updates": 0}

    def table(self, name):
        return _Q(self.store)


def _rows():
    return [
        {"id": "c1", "handle": "emilie@crochet.fr", "notes": "",
         "unsubscribed_at": None},
        {"id": "c2", "handle": "tiktok_kevin",
         "notes": "écrire à kevin@tuto.fr", "unsubscribed_at": None},
        {"id": "c3", "handle": "bemilie@crochet.fr", "notes": "",
         "unsubscribed_at": None},   # piège : handle sur-chaîne
        {"id": "c4", "handle": "deja@out.fr", "notes": "",
         "unsubscribed_at": "2026-07-01T00:00:00Z"},   # déjà désinscrit
        {"id": "c5", "handle": "tiktok_lea",
         "notes": "contact alea@crochet.fr", "unsubscribed_at": None},  # piège notes
    ]


check("is_unsubscribed lit la colonne",
      CB.is_unsubscribed({"unsubscribed_at": "2026-07-01T00:00:00Z"}) is True
      and CB.is_unsubscribed({"unsubscribed_at": None}) is False
      and CB.is_unsubscribed({}) is False)

rows = _rows()
CB._sb = lambda: FakeSB(rows)   # type: ignore[assignment]
n = CB.mark_unsubscribed_by_email("emilie@crochet.fr")
by_id = {r["id"]: r for r in rows}
check("handle exact désinscrit (c1)", by_id["c1"]["unsubscribed_at"] and n == 1)
check("sur-chaîne du handle NON touchée (bemilie…)",
      by_id["c3"]["unsubscribed_at"] is None)

rows = _rows()
CB._sb = lambda: FakeSB(rows)   # type: ignore[assignment]
n = CB.mark_unsubscribed_by_email("kevin@tuto.fr")
by_id = {r["id"]: r for r in rows}
check("adresse citée dans les notes désinscrite (c2)",
      by_id["c2"]["unsubscribed_at"] and n == 1)

rows = _rows()
CB._sb = lambda: FakeSB(rows)   # type: ignore[assignment]
n = CB.mark_unsubscribed_by_email("lea@crochet.fr")
by_id = {r["id"]: r for r in rows}
check("sous-chaîne d'une adresse des notes NON touchée (alea…)",
      by_id["c5"]["unsubscribed_at"] is None and n == 0)

rows = _rows()
CB._sb = lambda: FakeSB(rows)   # type: ignore[assignment]
n = CB.mark_unsubscribed_by_email("deja@out.fr")
check("déjà désinscrit → non recompté (idempotent)", n == 0)

# process_unsubscribe désinscrit AUSSI les créateurs (pas que les prospects).
rows = _rows()
CB._sb = lambda: FakeSB(rows)   # type: ignore[assignment]
U._sb_client = lambda: object()             # truthy : passe le garde None
PS.mark_unsubscribed_by_email = lambda sb, email, reason="": 0  # stub prospects
res = U.process_unsubscribe(U.make_token("emilie@crochet.fr"))
check("process_unsubscribe : le clic désinscrit le créateur",
      res.get("ok") and res.get("creators") == 1)

# Câblage des 4 chemins d'envoi créateurs (en-tête + pied + blocage désinscrit).
src_appr_cr = inspect.getsource(Api._approve_creator_draft)
check("envoi créateur (SMTP) : pied + en-tête + blocage désinscrit",
      "inject_footer" in src_appr_cr and "prospection_headers" in src_appr_cr
      and "is_unsubscribed" in src_appr_cr)
src_make = inspect.getsource(Api.creators_make_draft)
check("brouillon créateur (IMAP manuel) : en-tête + pied + blocage",
      "headers_for" in src_make and "inject_footer" in src_make
      and "is_unsubscribed" in src_make)
src_queue = inspect.getsource(Api.creators_queue_draft)
check("mise en file créateur : blocage désinscrit",
      "is_unsubscribed" in src_queue)
from triskell_command.integrations import creator_followup as CF  # noqa: E402
src_cf = inspect.getsource(CF)
check("relance J+7 créateur : en-tête + pied + blocage",
      "headers_for" in src_cf and "inject_footer" in src_cf
      and "is_unsubscribed" in src_cf)

# ---------------------------------------------------------------------------
print()
print(f"=== {len(PASS)} OK, {len(FAIL)} FAIL ===")
if FAIL:
    for f in FAIL:
        print(f"  ✗ {f}")
    sys.exit(1)
print("Tout est bon.")
