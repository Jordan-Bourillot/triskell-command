"""Nettoie les emails bidons generes par le bug d'extraction Obelisk.

Le bug : l'extracteur Obelisk (YouTube/Twitch/etc.) parse parfois des fragments
d'URL ou de texte decoratif comme s'il s'agissait d'adresses email. Resultat :
des prospects ont des emails inexistants dans leur liste.

Ce script identifie et retire ces faux emails, en preservant les vrais.

Regle de detection : on s'appuie sur clean_email() du filtre central
(triskell_core.prospect.enrichers.email_filter). Si clean_email renvoie
None pour un email, c'est qu'il est rejete par au moins une regle :
  - local-part suspect (only/online/more/info)
  - domaine commencant par www.
  - domaine factice (aaa.com, example.com, gobble.com, savagex.com, etc.)
  - domaine de plateforme (youtube.com, instagram.com, etc.)
  - format invalide

Comme on utilise le filtre central, toute regle ajoutee dans
email_filter.py profitera automatiquement a ce script.

Modes :
  --scan       (defaut) affiche ce qui serait retire, ne touche a rien
  --apply      execute pour de vrai, avec confirmation
"""
from __future__ import annotations

import argparse
import json
import sys
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

from triskell_core.db.client import SupabaseConfig, SupabaseNotConfigured  # noqa: E402
from triskell_core.prospect.enrichers.email_filter import clean_email  # noqa: E402


def is_fake_email(email: str) -> bool:
    """Renvoie True si l'email est rejete par le filtre central."""
    if not isinstance(email, str) or not email.strip():
        return False
    # clean_email applique TOUTES les regles : platform, fake domains,
    # www. prefix, local-parts suspects. Si None -> bidon.
    return clean_email(email) is None


def get_service_client():
    """Cree un client Supabase avec la service_role_key (bypass RLS)."""
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


def load_prospects(sb) -> list[dict]:
    """Charge tous les prospects avec leurs emails."""
    all_rows: list[dict] = []
    PAGE = 1000
    start = 0
    while True:
        res = (sb.table("prospects")
               .select("id, name, emails")
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


def analyze(prospects: list[dict]) -> list[dict]:
    """Pour chaque prospect, calcule la nouvelle liste d'emails (sans bidons).

    Renvoie la liste des prospects qui necessitent un update :
      {id, name, before: [...], after: [...], removed: [...]}
    """
    changes = []
    for p in prospects:
        emails = list(p.get("emails") or [])
        if not emails:
            continue
        removed = [e for e in emails if is_fake_email(e)]
        if not removed:
            continue
        kept = [e for e in emails if not is_fake_email(e)]
        changes.append({
            "id": p["id"],
            "name": p.get("name") or "(sans nom)",
            "before": emails,
            "after": kept,
            "removed": removed,
        })
    return changes


def print_changes(changes: list[dict]) -> None:
    """Affiche le rapport des modifications."""
    if not changes:
        print("[OK] Aucun email bidon trouve. La base est deja propre.")
        return
    print(f"[ALERTE] {len(changes)} prospects ont des emails a retirer :\n")
    total_removed = 0
    for c in changes:
        print(f"  - {c['name'][:55]:<55}  (id={c['id'][:8]}...)")
        for e in c["removed"]:
            print(f"      RETIRER : {e}")
        if c["after"]:
            print(f"      garde   : {', '.join(c['after'])}")
        else:
            print("      garde   : (aucun email restant)")
        total_removed += len(c["removed"])
        print()
    print(f"=== Resume : {total_removed} emails bidons a retirer "
          f"sur {len(changes)} prospects ===\n")


def apply_changes(sb, changes: list[dict]) -> int:
    """Applique les changements en base. Renvoie le nombre de prospects updates."""
    if not changes:
        return 0
    done = 0
    for c in changes:
        try:
            (sb.table("prospects")
             .update({"emails": c["after"]})
             .eq("id", c["id"])
             .execute())
            done += 1
        except Exception as exc:
            print(f"  [ERR] update de '{c['name']}' echoue : {exc}")
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Execute les changements (sinon : juste un scan)")
    args = parser.parse_args()

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
    print("[OK] Client service connecte.\n")

    print("-> Chargement des prospects...")
    prospects = load_prospects(sb)
    print(f"  [OK] {len(prospects)} prospects charges.\n")

    print("-> Analyse des emails bidons...")
    changes = analyze(prospects)
    print_changes(changes)

    if not changes:
        return 0

    if not args.apply:
        print("-> Mode --scan : aucune modification.")
        print("   Pour appliquer, relance avec --apply.")
        return 0

    print("[ATTENTION] Le mode --apply va MODIFIER la base en production.")
    print("            Tape 'oui' pour confirmer, autre chose pour annuler.")
    answer = input("            Confirmer ? ").strip().lower()
    if answer != "oui":
        print("Annule.")
        return 0

    done = apply_changes(sb, changes)
    print(f"\n[OK] {done}/{len(changes)} prospects mis a jour.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
