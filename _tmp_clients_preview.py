"""Preview-only : compte les 'faux clients' (prospects copies a tort)
sans rien supprimer. Affiche aussi 10 exemples."""
import json
from pathlib import Path
from supabase import create_client

cfg = json.loads((Path.home() / ".triskell-command" / "settings.json").read_text(encoding="utf-8"))
sb_cfg = cfg["supabase"]
sb = create_client(sb_cfg["url"], sb_cfg.get("service_role_key") or sb_cfg.get("service_key"))

# Total clients
total = sb.table("clients_360").select("id", count="exact").execute()
print(f"Total clients actuels : {total.count}")

# Clients sans aucun intake/facture/projet et sans Stripe/paiement
# = ceux qui n'ont JAMAIS rempli un formulaire et JAMAIS paye
rows = sb.table("clients_360").select(
    "id, email, sources, lagriffe_count, rankus_count, wow_count, "
    "invoices_count, projects_count, stripe_customer_id, total_paid_cents, "
    "first_paid_at"
).execute().data or []

to_delete = [
    r for r in rows
    if (r.get("lagriffe_count") or 0) == 0
    and (r.get("rankus_count") or 0) == 0
    and (r.get("wow_count") or 0) == 0
    and (r.get("invoices_count") or 0) == 0
    and (r.get("projects_count") or 0) == 0
    and not (r.get("stripe_customer_id") or "")
    and (r.get("total_paid_cents") or 0) == 0
    and not r.get("first_paid_at")
]
to_keep = [r for r in rows if r not in to_delete]

print(f"A supprimer (faux clients = prospects copies) : {len(to_delete)}")
print(f"A garder (vrais clients) : {len(to_keep)}")
print()
print("--- 10 exemples a supprimer ---")
for r in to_delete[:10]:
    print(f"  - {r.get('email')} (sources={r.get('sources')})")
print()
print("--- 10 exemples a garder ---")
for r in to_keep[:10]:
    print(f"  - {r.get('email')} (sources={r.get('sources')}, "
          f"intakes={r.get('lagriffe_count')+r.get('rankus_count')+r.get('wow_count')}, "
          f"factures={r.get('invoices_count')}, paye={r.get('total_paid_cents')})")
