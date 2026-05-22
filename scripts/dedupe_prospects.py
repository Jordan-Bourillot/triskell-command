"""Scan/nettoie les doublons d'emails dans la base prospects (sous-etape 1.1
du chantier Auto-pilote v2).

Detection : 2 prospects sont en doublon s'ils partagent au moins UN email
(lowercased, trime).

Modes :
  --scan       (defaut) diagnostic seul, ne touche a rien.
  --apply      (a venir) executera la fusion + nettoyage.

Usage :
  python scripts/dedupe_prospects.py
  python scripts/dedupe_prospects.py --scan
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CORE_ROOT_CANDIDATES = [
    HERE.parent / "triskell-core",
    HERE.parent / "Triskell Core",
]
for candidate in CORE_ROOT_CANDIDATES:
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
sys.path.insert(0, str(HERE))

import json  # noqa: E402

from triskell_core.db.client import SupabaseConfig, SupabaseNotConfigured  # noqa: E402
from triskell_core.prospect.core.prospect import norm_email  # noqa: E402


def get_service_client():
    """Cree un client Supabase avec la service_role_key (bypass RLS).

    Lecture de la cle dans ~/.triskell-command/settings.json (section supabase).
    Renvoie un client supabase-py ou None si la cle est absente.
    """
    settings_path = Path.home() / ".triskell-command" / "settings.json"
    if not settings_path.exists():
        return None, "settings.json introuvable"
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"settings.json illisible : {exc}"
    sb = data.get("supabase") or {}
    url = sb.get("url") or ""
    key = sb.get("service_role_key") or sb.get("service_key") or ""
    if not url or not key:
        return None, "service_role_key absente du settings.json"
    try:
        from supabase import create_client
    except ImportError:
        return None, "module 'supabase' manquant : pip install supabase"
    try:
        return create_client(url, key), None
    except Exception as exc:
        return None, f"creation client echec : {exc}"


class UnionFind:
    """Structure pour grouper les prospects connectes par un email commun."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
            return x
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        cur = x
        while self.parent[cur] != root:
            nxt = self.parent[cur]
            self.parent[cur] = root
            cur = nxt
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for x in self.parent:
            out[self.find(x)].append(x)
        return dict(out)


def load_prospects(sb) -> list[dict]:
    """Charge tous les prospects avec leurs emails et metadonnees."""
    all_rows: list[dict] = []
    PAGE = 1000
    start = 0
    while True:
        res = (sb.table("prospects")
               .select("id, name, emails, status, created_at, sources")
               .range(start, start + PAGE - 1)
               .execute())
        rows = res.data or []
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < PAGE:
            break
        start += PAGE
    return all_rows


def count_attachments(sb, prospect_ids: list[str]) -> dict:
    """Compte l'historique et les brouillons rattaches aux prospects."""
    if not prospect_ids:
        return {"history": 0, "drafts": 0}
    BATCH = 100
    history = 0
    drafts = 0
    for i in range(0, len(prospect_ids), BATCH):
        chunk = prospect_ids[i:i + BATCH]
        try:
            r1 = (sb.table("email_history").select("id", count="exact")
                  .in_("prospect_id", chunk).execute())
            history += r1.count or 0
        except Exception as exc:
            print(f"  [WARN] email_history check failed for chunk: {exc}")
        try:
            r2 = (sb.table("prospect_drafts").select("id", count="exact")
                  .in_("prospect_id", chunk).execute())
            drafts += r2.count or 0
        except Exception as exc:
            print(f"  [WARN] prospect_drafts check failed for chunk: {exc}")
    return {"history": history, "drafts": drafts}


def _common_emails(rows: list[dict]) -> list[str]:
    """Renvoie les emails (normalises) communs a au moins 2 rows du cluster."""
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        seen: set[str] = set()
        for e in (r.get("emails") or []):
            ne = norm_email(e)
            if ne and ne not in seen:
                counts[ne] += 1
                seen.add(ne)
    return sorted([e for e, c in counts.items() if c > 1])


def _sources_summary(row: dict) -> str:
    srcs = row.get("sources") or []
    names: list[str] = []
    for s in srcs:
        if isinstance(s, dict):
            nm = s.get("name") or ""
            if nm and nm not in names:
                names.append(nm)
    return ",".join(names) if names else "?"


def scan(sb) -> None:
    """Mode --scan : diagnostic seul."""
    print("=== Scan des doublons d'emails dans la base prospects ===\n")

    print("-> Chargement des prospects depuis Supabase...")
    rows = load_prospects(sb)
    print(f"  [OK] {len(rows)} prospects charges.\n")

    if not rows:
        print("Aucun prospect en base. Rien a faire.")
        return

    email_to_ids: dict[str, list[str]] = defaultdict(list)
    id_to_row: dict[str, dict] = {}
    prospects_with_email = 0
    for r in rows:
        pid = r.get("id")
        if not pid:
            continue
        id_to_row[pid] = r
        normed: set[str] = set()
        for e in (r.get("emails") or []):
            ne = norm_email(e)
            if ne:
                normed.add(ne)
        if normed:
            prospects_with_email += 1
            for e in sorted(normed):
                email_to_ids[e].append(pid)

    print(f"-> {prospects_with_email} prospects ont au moins un email valide.\n")

    uf = UnionFind()
    for pid in id_to_row:
        uf.find(pid)
    for email, pids in email_to_ids.items():
        if len(pids) > 1:
            base = pids[0]
            for other in pids[1:]:
                uf.union(base, other)

    groups = uf.groups()
    duplicate_clusters = [pids for pids in groups.values() if len(pids) > 1]
    duplicate_clusters.sort(key=lambda c: -len(c))

    if not duplicate_clusters:
        print("[OK] Aucun doublon detecte ! La base est propre.")
        return

    total_dups = sum(len(c) - 1 for c in duplicate_clusters)
    print(f"[ALERTE] {len(duplicate_clusters)} groupes de doublons trouves.")
    print(f"         -> {total_dups} prospects en trop a fusionner.\n")

    losers_total: list[str] = []
    for cluster in duplicate_clusters:
        rows_in = [id_to_row[pid] for pid in cluster]
        rows_in.sort(key=lambda r: r.get("created_at") or "")
        for r in rows_in[1:]:
            losers_total.append(r["id"])

    print("-> Decompte des dependances a transferer aux gagnants...")
    counts = count_attachments(sb, losers_total)
    print(f"  - {counts['history']} entrees d'historique mail a transferer.")
    print(f"  - {counts['drafts']} brouillons en attente a transferer.\n")

    SHOW = 20
    print(f"--- Detail des {min(SHOW, len(duplicate_clusters))} premiers groupes ---\n")
    for i, cluster in enumerate(duplicate_clusters[:SHOW], 1):
        rows_in = [id_to_row[pid] for pid in cluster]
        rows_in.sort(key=lambda r: r.get("created_at") or "")
        winner = rows_in[0]
        losers = rows_in[1:]
        common = _common_emails(rows_in)
        common_disp = ", ".join(common[:3]) + (" ..." if len(common) > 3 else "")
        print(f"#{i} | {len(cluster)} prospects | email(s) commun(s) : {common_disp}")
        print(f"   GAGNANT : {(winner.get('name') or '(sans nom)')[:50]:<50}"
              f" [{winner.get('status', '?'):<10}]"
              f" cree {(winner.get('created_at') or '?')[:10]}"
              f" src={_sources_summary(winner)}")
        for L in losers:
            print(f"   doublon : {(L.get('name') or '(sans nom)')[:50]:<50}"
                  f" [{L.get('status', '?'):<10}]"
                  f" cree {(L.get('created_at') or '?')[:10]}"
                  f" src={_sources_summary(L)}")
        print()

    if len(duplicate_clusters) > SHOW:
        print(f"... et {len(duplicate_clusters) - SHOW} autres groupes.\n")

    print("=== Resume ===")
    print(f"  - {len(duplicate_clusters)} groupes de doublons")
    print(f"  - {total_dups} prospects a fusionner et supprimer")
    print(f"  - {counts['history']} mails d'historique a conserver")
    print(f"  - {counts['drafts']} brouillons a conserver")
    print()
    print("-> Aucune modification n'a ete faite (mode --scan).")
    print("   Quand tu auras valide, lance avec --apply pour executer.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="store_true",
                        help="Mode diagnostic (defaut, ne touche a rien)")
    parser.add_argument("--apply", action="store_true",
                        help="Mode execution (a venir, pas encore implemente)")
    args = parser.parse_args()

    if args.apply:
        print("[INFO] Le mode --apply n'est pas encore implemente.")
        print("       Lance d'abord en mode scan : python scripts/dedupe_prospects.py")
        return 1

    try:
        cfg = SupabaseConfig.resolve()
        print(f"[OK] Projet Supabase : {cfg.url}")
    except SupabaseNotConfigured as exc:
        print(f"[ERR] {exc}")
        return 1

    sb, err = get_service_client()
    if sb is None:
        print(f"[ERR] {err}")
        return 1
    print("[OK] Client service connecte (lecture autorisee sur toutes les tables).\n")

    scan(sb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
