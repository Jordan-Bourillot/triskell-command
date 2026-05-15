"""Génère un hash bcrypt à coller dans .env (JORDAN_PASSWORD_HASH ou
THOMAS_PASSWORD_HASH).

Usage :
    python scripts/hash_password.py
    Mot de passe : ******
    Confirme    : ******

    JORDAN_PASSWORD_HASH=$2b$12$...

À coller dans .env (ou Variables d'environnement Coolify une fois en prod).
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))


def main() -> None:
    try:
        pw1 = getpass.getpass("Mot de passe : ")
        pw2 = getpass.getpass("Confirme    : ")
    except (KeyboardInterrupt, EOFError):
        print("\nAnnulé.")
        sys.exit(1)

    if not pw1:
        print("Vide, abandon.")
        sys.exit(1)
    if pw1 != pw2:
        print("Les deux saisies diffèrent. Abandon.")
        sys.exit(1)
    if len(pw1) < 8:
        print("⚠ Mot de passe trop court (< 8 caractères). Continuer quand même ? [o/N] ", end="")
        if input().strip().lower() not in ("o", "oui", "y", "yes"):
            sys.exit(1)

    from triskell_command.web.auth import hash_password

    hashed = hash_password(pw1)
    print()
    print("=" * 60)
    print("Hash généré (à coller dans .env) :")
    print()
    print(f"  JORDAN_PASSWORD_HASH={hashed}")
    print(f"  THOMAS_PASSWORD_HASH={hashed}")
    print()
    print("(Garde celui qui correspond à ton user, supprime l'autre.)")
    print("=" * 60)


if __name__ == "__main__":
    main()
