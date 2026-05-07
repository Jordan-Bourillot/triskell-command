"""Ajoute Teddy Mail au catalogue apps.json (idempotent)."""
import json
from pathlib import Path

APPS_JSON = Path("C:/Users/jorda/OneDrive/Bureau/Triskell Studio/Triskell 0 - Lanceur/apps.json")

TEDDY = {
    "id": "teddy-mail",
    "name": "Teddy Mail",
    "tagline": "Ton client mail desktop sobre, sans pub, sans tracking.",
    "category": "quotidien",
    "tier": "free",
    "icon": "assets/apps/teddy-mail.png",
    "featured": False,
    "featuredLabel": "",
    "price": None,
    "priceOriginal": None,
    "priceNote": "Gratuit",
    "installed": True,
    "exePath": r"C:\Users\jorda\AppData\Local\Teddy Mail\teddy-mail-shell.exe",
    "buyUrl": "",
    "salesPitch": (
        "Un client mail qui te respecte. Pas de pub, pas de tracking, "
        "pas d'abonnement. Multi-comptes IMAP, dark mode, raccourcis "
        "clavier — tout ce qu'il faut, rien de plus."
    ),
    "motto": "Pour qui en a marre des clients mail bavards.",
    "description": "",
    "features": [],
    "personas": [],
    "links": [],
}


def main() -> int:
    data = json.loads(APPS_JSON.read_text(encoding="utf-8"))
    if any(a.get("id") == "teddy-mail" for a in data.get("apps", [])):
        print("[SKIP] Teddy Mail deja present dans apps.json")
        return 0
    data["apps"].append(TEDDY)
    APPS_JSON.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Teddy Mail ajoute (apps total: {len(data['apps'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
