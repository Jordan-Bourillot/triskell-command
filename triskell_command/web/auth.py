"""Auth HTTP simple — login partagé Jordan / Thomas.

Pour Triskell Command web (mode HTTP) uniquement. Ne touche pas à
l'auth Supabase interne (qui continue de fonctionner via api.py).

Architecture :
- 2 utilisateurs hardcodés : 'jordan' et 'thomas'
- Mots de passe stockés en bcrypt dans des env vars (.env)
- Cookie de session HTTPOnly Secure signé via itsdangerous
- Le cookie contient juste l'identifiant utilisateur (jordan/thomas)
- Une route /api/login vérifie le mdp et set le cookie
- Le middleware vérifie le cookie sur toutes les routes /api/* sauf
  les routes publiques (login, _health)

Génération des hash : `python scripts/hash_password.py`
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Optional

import bcrypt
from itsdangerous import BadSignature, URLSafeSerializer

logger = logging.getLogger(__name__)

COOKIE_NAME = "tc_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 jours

# Routes accessibles sans auth (login, healthchecks, statiques)
PUBLIC_API_PATHS = {
    "/api/_health",
    "/api/login",
    "/api/me",  # /me peut être appelé sans auth → renvoie {ok:true, connected:false}
}

# Utilisateurs reconnus (étendre ici si on ajoute du monde)
KNOWN_USERS = {
    "jordan": {"display_name": "Jordan", "env_var": "JORDAN_PASSWORD_HASH"},
    "thomas": {"display_name": "Thomas", "env_var": "THOMAS_PASSWORD_HASH"},
}


def _serializer() -> URLSafeSerializer:
    """Serializer pour signer les cookies. Lit la clé secrète une seule fois."""
    secret = os.environ.get("SESSION_SECRET", "").strip()
    if not secret:
        # Fallback : génère une clé éphémère (les sessions ne survivront pas
        # à un redémarrage). Loggue un warning bien visible.
        if not getattr(_serializer, "_warned", False):
            logger.warning(
                "SESSION_SECRET non définie ! Les sessions ne survivront pas "
                "à un redémarrage. Définis SESSION_SECRET dans ton .env."
            )
            _serializer._warned = True  # type: ignore[attr-defined]
        secret = secrets.token_urlsafe(48)
        os.environ["SESSION_SECRET"] = secret
    return URLSafeSerializer(secret, salt="tc_session_v1")


def hash_password(plain: str) -> str:
    """Hash bcrypt d'un mot de passe (à stocker dans .env)."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """Compare un mdp clair à son hash bcrypt. Constant-time."""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def authenticate(username: str, password: str) -> Optional[str]:
    """Vérifie credentials. Renvoie l'id utilisateur normalisé ou None."""
    if not username or not password:
        return None
    user_id = username.strip().lower()
    user = KNOWN_USERS.get(user_id)
    if user is None:
        return None
    hashed = os.environ.get(user["env_var"], "").strip()
    if not hashed:
        logger.warning("Pas de hash pour %s (env %s manquante)",
                       user_id, user["env_var"])
        return None
    if verify_password(password, hashed):
        return user_id
    return None


def make_session_cookie_value(user_id: str) -> str:
    """Crée la valeur du cookie de session (signée)."""
    return _serializer().dumps({"u": user_id})


def read_session_cookie(value: Optional[str]) -> Optional[str]:
    """Lit le cookie de session. Renvoie l'user_id ou None si invalide."""
    if not value:
        return None
    try:
        data = _serializer().loads(value)
        if isinstance(data, dict):
            uid = data.get("u")
            if isinstance(uid, str) and uid in KNOWN_USERS:
                return uid
    except BadSignature:
        return None
    except Exception as exc:
        logger.debug("read_session_cookie: %s", exc)
    return None


def get_display_name(user_id: str) -> str:
    user = KNOWN_USERS.get(user_id)
    return user["display_name"] if user else user_id
