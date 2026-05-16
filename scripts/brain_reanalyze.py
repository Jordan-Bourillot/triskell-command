"""Ré-analyse toutes les notes Brain existantes avec le nouveau prompt.

Usage : python scripts/brain_reanalyze.py [--all]
  Par défaut : ne re-traite que les notes 'open' (visibles dans l'UI).
  --all      : re-traite aussi 'done' et 'archived'.
"""
from __future__ import annotations
import sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from triskell_command.integrations import brain


def main() -> int:
    include_all = "--all" in sys.argv
    sb = brain._service_sb()
    if sb is None:
        print("Impossible de se connecter à Supabase (clé service-role manquante).")
        return 1

    q = sb.table(brain.TABLE).select("id,content,status,summary").order("created_at", desc=True)
    if not include_all:
        q = q.eq("status", "open")
    notes = q.execute().data or []

    print(f"{len(notes)} notes à re-traiter "
          f"({'toutes' if include_all else 'open seulement'}).")

    ok = ko = 0
    for i, n in enumerate(notes, 1):
        nid = n["id"]
        content = (n.get("content") or "").strip()
        old = (n.get("summary") or "").strip() or "(vide)"
        if not content:
            print(f"[{i}/{len(notes)}] {nid[:8]} — note vide, skip")
            continue

        analysis = brain.analyze_note(content) or {}
        if not analysis:
            print(f"[{i}/{len(notes)}] {nid[:8]} — analyse KO")
            ko += 1
            continue

        patch = {
            "category": analysis.get("category") or None,
            "summary":  analysis.get("summary") or None,
            "tags":     analysis.get("tags") or [],
            "urgency":   analysis.get("urgency"),
            "importance": analysis.get("importance"),
            "assigned_to": analysis.get("assigned_to"),
        }
        remind = analysis.get("remind_at")
        if remind:
            patch["remind_at"] = remind
            patch["reminded_at"] = None  # autorise un nouveau rappel

        if brain.update_note(nid, patch):
            new = (patch["summary"] or "").strip() or "(vide)"
            u, imp = analysis.get("urgency"), analysis.get("importance")
            print(f"[{i}/{len(notes)}] {nid[:8]}  urg={u}  imp={imp}  rappel={remind or '—'}")
            print(f"    {new[:100]}")
            ok += 1
        else:
            print(f"[{i}/{len(notes)}] {nid[:8]} — update KO")
            ko += 1

        time.sleep(0.2)  # politesse API

    print(f"\nTerminé : {ok} ok, {ko} ko.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
