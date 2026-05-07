"""Gestion locale des identifiants Supabase par prénom.

Stocke les couples (email, password) connus sur CE poste dans
`~/.triskell-command/users.json` pour que la connexion se fasse en
tapant juste le prénom au lieu de retaper email + password à chaque
fois.

Format du fichier :
    {
        "Jordan": {"email": "jordan@triskell-studio.fr", "password": "..."},
        "Thomas": {"email": "thomas@gmail.com", "password": "..."}
    }

Sécurité : le fichier est en clair (pas chiffré). C'est un compromis
volontaire — le poste de l'utilisateur est considéré comme zone de
confiance, et la base Supabase a déjà ses propres protections (RLS).
Si un jour besoin de chiffrement, on pourra dériver une clé d'un PIN
poste ou utiliser le secret store OS (Windows Credential Manager).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


USERS_FILE = Path.home() / ".triskell-command" / "users.json"


def _load_raw() -> dict:
    if not USERS_FILE.exists():
        return {}
    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def known_names() -> list[str]:
    """Liste des prénoms enregistrés sur ce poste."""
    return sorted(_load_raw().keys())


def get_credentials(name: str) -> Optional[tuple[str, str]]:
    """Renvoie (email, password) pour le prénom donné, ou None si inconnu.

    La recherche est insensible à la casse pour éviter les frustrations
    ("jordan" vs "Jordan").
    """
    if not name:
        return None
    data = _load_raw()
    needle = name.strip().lower()
    for key, val in data.items():
        if key.lower() == needle:
            email = val.get("email") or ""
            password = val.get("password") or ""
            if email and password:
                return email, password
    return None


def save_credentials(name: str, email: str, password: str) -> None:
    """Enregistre/met à jour les identifiants pour un prénom."""
    if not name or not email or not password:
        return
    data = _load_raw()
    # Normalise la clé en mettant la 1re lettre en majuscule (Jordan, Thomas)
    norm_name = name.strip()
    if norm_name:
        norm_name = norm_name[0].upper() + norm_name[1:].lower()
    data[norm_name] = {"email": email, "password": password}
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = USERS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(USERS_FILE)


def forget(name: str) -> None:
    """Supprime un prénom de la liste locale."""
    data = _load_raw()
    needle = name.strip().lower()
    to_del = [k for k in data if k.lower() == needle]
    for k in to_del:
        del data[k]
    if not data:
        try:
            USERS_FILE.unlink()
        except FileNotFoundError:
            pass
        return
    tmp = USERS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(USERS_FILE)
