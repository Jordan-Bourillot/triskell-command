"""Suppression : faux clients (sources=convoy, aucun intake/facture/paiement)
+ Thomas et Jordan (pas des clients de Triskell)."""
import json
from pathlib import Path
from supabase import create_client

cfg = json.loads((Path.home() / ".triskell-command" / "settings.json").read_text(encoding="utf-8"))
sb_cfg = cfg["supabase"]
sb = create_client(sb_cfg["url"], sb_cfg.get("service_role_key") or sb_cfg.get("service_key"))

rows = sb.table("clients_360").select(
    "id, email, sources, lagriffe_count, rankus_count, wow_count, "
    "invoices_count, projects_count, stripe_customer_id, total_paid_cents, "
    "first_paid_at"
).execute().data or []

OWNERS = {
    "thomas.bourillot@gmail.com",
    "jordan.bourillot@yahoo.fr",
    "jordan.bourillot.bzh@gmail.com",
}

to_delete_ids = []
for r in rows:
    email = (r.get("email") or "").lower()
    is_owner = email in OWNERS
    is_fake_client = (
        (r.get("lagriffe_count") or 0) == 0
        and (r.get("rankus_count") or 0) == 0
        and (r.get("wow_count") or 0) == 0
        and (r.get("invoices_count") or 0) == 0
        and (r.get("projects_count") or 0) == 0
        and not (r.get("stripe_customer_id") or "")
        and (r.get("total_paid_cents") or 0) == 0
        and not r.get("first_paid_at")
    )
    if is_owner or is_fake_client:
        to_delete_ids.append(r["id"])

print(f"A supprimer : {len(to_delete_ids)} fiches")

# DELETE par paquets de 50
deleted = 0
for i in range(0, len(to_delete_ids), 50):
    batch = to_delete_ids[i:i+50]
    sb.table("clients").delete().in_("id", batch).execute()
    deleted += len(batch)
    print(f"  ... {deleted}/{len(to_delete_ids)} supprimes")

# Verifie
after = sb.table("clients_360").select("id, email, sources", count="exact").execute()
print(f"\nReste {after.count} fiches dans clients :")
for r in (after.data or []):
    print(f"  - {r.get('email')} (sources={r.get('sources')})")
