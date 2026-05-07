"""Génère un JWT Clerk longue durée pour Triskell Command.

Usage :
    python tools/generate_clerk_jwt.py

Lit CLERK_SECRET_KEY depuis l'env var ou demande interactivement.
Crée un template "triskell-command" si manquant (1 an de validité).
Crée une session pour le user spécifié et en sort un JWT.
Teste le JWT contre l'API AlphaCast prod.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse

import requests


CLERK_API = "https://api.clerk.com/v1"
ALPHACAST_API = "https://reseauxapi-production.up.railway.app"
TEMPLATE_NAME = "triskell-command"
TEMPLATE_LIFETIME_SECONDS = 60 * 60 * 24 * 365  # 1 an


def get_secret() -> str:
    secret = os.environ.get("CLERK_SECRET_KEY")
    if secret:
        return secret
    print("CLERK_SECRET_KEY non trouvé dans l'env.")
    print("Colle ta clé sk_test_… ou sk_live_… (entrée vide = abandon) :")
    secret = input("> ").strip()
    if not secret:
        sys.exit(1)
    return secret


def list_templates(secret: str) -> list[dict]:
    r = requests.get(
        f"{CLERK_API}/jwt_templates",
        headers={"Authorization": f"Bearer {secret}"},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return data if isinstance(data, list) else []


def create_template(secret: str) -> dict:
    """Crée le template `triskell-command` s'il n'existe pas."""
    body = {
        "name": TEMPLATE_NAME,
        "claims": {},
        "lifetime": TEMPLATE_LIFETIME_SECONDS,
        "allowed_clock_skew": 5,
        "custom_signing_key": False,
    }
    r = requests.post(
        f"{CLERK_API}/jwt_templates",
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        },
        json=body, timeout=15,
    )
    if r.status_code >= 400:
        print(f"Erreur création template : HTTP {r.status_code}")
        print(r.text)
        r.raise_for_status()
    return r.json()


def ensure_template(secret: str) -> str:
    existing = list_templates(secret)
    for t in existing:
        if t.get("name") == TEMPLATE_NAME:
            print(f"✓ Template '{TEMPLATE_NAME}' déjà présent (id={t.get('id')}).")
            return t["id"]
    print(f"… Création du template '{TEMPLATE_NAME}' (validité 1 an).")
    t = create_template(secret)
    print(f"✓ Template créé (id={t.get('id')}).")
    return t["id"]


def list_users(secret: str) -> list[dict]:
    r = requests.get(
        f"{CLERK_API}/users?limit=50",
        headers={"Authorization": f"Bearer {secret}"},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("data", [])


def pick_user(users: list[dict]) -> dict:
    if not users:
        print("Aucun user dans cette instance Clerk.")
        sys.exit(1)
    if len(users) == 1:
        u = users[0]
        print(f"✓ Un seul user trouvé : {label_of(u)}")
        return u
    print("\nUsers disponibles :")
    for i, u in enumerate(users, 1):
        print(f"  [{i}] {label_of(u)}")
    while True:
        choice = input("Choisis un numéro : ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(users):
                return users[idx]
        except ValueError:
            pass
        print("Numéro invalide.")


def label_of(u: dict) -> str:
    emails = u.get("email_addresses") or []
    primary = emails[0]["email_address"] if emails else "(no email)"
    return f"{primary}  ·  id={u.get('id', '?')}"


def create_session(secret: str, user_id: str) -> str:
    """Crée une nouvelle session pour `user_id`. Renvoie session_id."""
    r = requests.post(
        f"{CLERK_API}/sessions",
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        },
        json={"user_id": user_id}, timeout=15,
    )
    if r.status_code >= 400:
        print(f"Erreur création session : HTTP {r.status_code}")
        print(r.text)
        r.raise_for_status()
    sid = r.json()["id"]
    print(f"✓ Session créée (id={sid}).")
    return sid


def issue_token(secret: str, session_id: str) -> str:
    """Émet un JWT à partir de la session, via le template."""
    template = urllib.parse.quote(TEMPLATE_NAME, safe="")
    r = requests.post(
        f"{CLERK_API}/sessions/{session_id}/tokens/{template}",
        headers={"Authorization": f"Bearer {secret}"},
        timeout=15,
    )
    if r.status_code >= 400:
        print(f"Erreur émission JWT : HTTP {r.status_code}")
        print(r.text)
        r.raise_for_status()
    return r.json()["jwt"]


def smoke_test(jwt: str) -> bool:
    """Tape /api/v1/workspaces avec le JWT — accepte 200 ou 404 (pas de workspace)."""
    r = requests.get(
        f"{ALPHACAST_API}/api/v1/workspaces",
        headers={"Authorization": f"Bearer {jwt}"},
        timeout=15,
    )
    if r.status_code == 401:
        print(f"✗ JWT rejeté par AlphaCast : HTTP 401")
        return False
    print(f"✓ JWT accepté par AlphaCast : HTTP {r.status_code}")
    return True


def main():
    secret = get_secret()
    instance_kind = "TEST" if secret.startswith("sk_test_") else "LIVE"
    print(f"\n→ Mode Clerk : {instance_kind}\n")

    ensure_template(secret)

    users = list_users(secret)
    user = pick_user(users)
    user_id = user["id"]

    session_id = create_session(secret, user_id)
    jwt = issue_token(secret, session_id)

    print("\n" + "=" * 60)
    print("JWT (1 an) :")
    print("=" * 60)
    print(jwt)
    print("=" * 60)

    print("\nSmoke-test contre AlphaCast prod…")
    smoke_test(jwt)

    print("\nCopie ce JWT et colle-le dans :")
    print("  Triskell Command > Réglages > Service AlphaCast > JWT Clerk")


if __name__ == "__main__":
    main()
