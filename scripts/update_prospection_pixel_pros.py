"""(Re)seede en base les 5 modèles de mails de prospection Pixel Pros.

Source de vérité : `scripts/_prospection_pixel_pros_data.json` (à côté).

Lance ce script si tu veux remettre la base dans l'état "version finale
validée par Jordan" — par exemple après un wipe Supabase, ou après avoir
édité le JSON pour ajuster un mail.

Usage :
    python scripts/update_prospection_pixel_pros.py
"""

from __future__ import annotations

import json
from pathlib import Path
from supabase import create_client


def main() -> int:
    here = Path(__file__).resolve().parent
    data_path = here / "_prospection_pixel_pros_data.json"
    if not data_path.exists():
        print(f"Fichier de données introuvable : {data_path}")
        return 1
    mails = json.loads(data_path.read_text(encoding="utf-8"))

    cfg_path = Path.home() / ".triskell-command" / "settings.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    sb_cfg = cfg["supabase"]
    c = create_client(sb_cfg["url"], sb_cfg["service_role_key"])

    for m in mails:
        payload = {
            "product": "pixel-pros",
            "key": m["key"],
            "label": m["label"],
            "subject": m["subject"],
            "body_html": m["body_html"],
            "body_text": m["body_text"],
            "description": m.get("description", ""),
            "placeholders": m.get("placeholders", ["first_name"]),
            "category": "prospection",
            "enabled": True,
            "updated_by": "reseed-script",
        }
        c.table("triskell_email_templates").upsert(
            payload, on_conflict="product,key"
        ).execute()
        print(f"OK  {m['label']}")

    print(f"\n{len(mails)} mails (re)seedés sous pixel-pros / prospection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
