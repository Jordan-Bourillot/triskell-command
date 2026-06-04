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

import contextvars
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Optional

import bcrypt
from itsdangerous import BadSignature, URLSafeSerializer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Identité locale (jordan / thomas) de la requête HTTP en cours.
# Le middleware d'auth pose cette valeur dès qu'il a validé le cookie de
# session ; les modules métier qui ont besoin de savoir QUI a fait l'appel
# (chat 1-à-1, etc.) la relisent via get_current_local_user().
# ---------------------------------------------------------------------------
_current_local_user: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "tc_current_local_user", default=None
)


def set_current_local_user(user_id: Optional[str]):
    """Pose l'identité locale (jordan/thomas) pour la requête courante.
    Renvoie un token qu'on peut passer à reset_current_local_user pour
    restaurer la valeur précédente en fin de requête."""
    return _current_local_user.set(user_id)


def reset_current_local_user(token) -> None:
    """Restaure l'identité locale précédente (best-effort)."""
    try:
        _current_local_user.reset(token)
    except Exception:
        pass


def get_current_local_user() -> Optional[str]:
    """Renvoie l'identité locale posée par le middleware (jordan/thomas), sinon None."""
    return _current_local_user.get()

COOKIE_NAME = "tc_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 jours

# Routes accessibles sans auth (login, healthchecks, statiques)
PUBLIC_API_PATHS = {
    "/api/_health",
    "/api/login",
    "/api/me",  # /me peut être appelé sans auth → renvoie {ok:true, connected:false}
    "/api/push/public_key",  # clé VAPID publique (pas un secret)
    "/api/billing/webhook",  # Stripe doit pouvoir poster sans cookie
    "/api/pixelpros/on_paid",   # Webhook Stripe Netlify → mail paiement + déclenche build
    "/api/pixelpros/on_built",  # Builder Python → mail "site en ligne"
    "/api/pixelpros/affiliate-login-request",  # Demande de magic link affilié (public, rate-limité)
    "/api/pixelpros/contact",  # Formulaire de contact des sites clients (public, rate-limité)
}

# Utilisateurs reconnus (étendre ici si on ajoute du monde)
# `_no_login` : participant virtuel qui n'a pas de mot de passe et ne
# peut pas se connecter (ex : Claude, qui poste des messages dans le
# chat depuis le mode vocal mais n'a pas de session).
KNOWN_USERS = {
    "jordan": {"display_name": "Jordan", "env_var": "JORDAN_PASSWORD_HASH"},
    "thomas": {"display_name": "Thomas", "env_var": "THOMAS_PASSWORD_HASH"},
    "claude": {"display_name": "Allo Claude", "env_var": "", "_no_login": True},
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
    if user is None or user.get("_no_login"):
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
                # On exclut les participants virtuels (claude…) qui ne
                # peuvent pas avoir de session humaine.
                if KNOWN_USERS[uid].get("_no_login"):
                    return None
                return uid
    except BadSignature:
        return None
    except Exception as exc:
        logger.debug("read_session_cookie: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Display names personnalisés (modifiables via la modale "Mon profil")
# ---------------------------------------------------------------------------
# Stockage : ~/.triskell-command/user_display_names.json
# Forme   : {"jordan": "Jordan Bourillot", "thomas": "Thomas X"}
# Fallback: si pas d'entrée pour user_id, on retourne KNOWN_USERS[user_id]["display_name"]
#           (le nom par défaut hardcodé).

def _display_names_file() -> Path:
    base = Path.home() / ".triskell-command"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.debug("Création %s impossible : %s", base, exc)
    return base / "user_display_names.json"


def _load_custom_names() -> dict:
    path = _display_names_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("Lecture %s impossible : %s", path, exc)
        return {}


def _save_custom_names(names: dict) -> bool:
    path = _display_names_file()
    try:
        path.write_text(json.dumps(names, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return True
    except Exception as exc:
        logger.warning("Écriture %s impossible : %s", path, exc)
        return False


def get_display_name(user_id: str) -> str:
    """Renvoie le nom à afficher pour un utilisateur. Personnalisé si défini,
    sinon nom par défaut hardcodé dans KNOWN_USERS."""
    custom = _load_custom_names()
    val = (custom.get(user_id) or "").strip()
    if val:
        return val
    user = KNOWN_USERS.get(user_id)
    return user["display_name"] if user else user_id


def set_display_name(user_id: str, name: str) -> bool:
    """Enregistre le nom personnalisé d'un utilisateur. Renvoie True si OK."""
    if user_id not in KNOWN_USERS:
        return False
    name = (name or "").strip()
    if not name:
        return False
    custom = _load_custom_names()
    custom[user_id] = name
    return _save_custom_names(custom)


# ---------------------------------------------------------------------------
# Couleur de chat personnelle (Jordan / Thomas choisissent chacun la couleur
# dans laquelle leurs propres bulles s'affichent — pour eux-mêmes ET pour
# l'autre). Stockage : ~/.triskell-command/user_chat_colors.json
# Forme : {"jordan": "#7C7FE9", "thomas": "#10b981"}
# ---------------------------------------------------------------------------

# Palette par défaut si l'user n'a jamais choisi (matching les défauts UI).
DEFAULT_CHAT_COLORS = {
    "jordan": "#7C7FE9",  # violet accent
    "thomas": "#10b981",  # vert
    "claude": "#a855f7",  # violet vif (participant virtuel, mode vocal)
}

# Palette proposée dans le sélecteur de couleur côté front.
CHAT_COLOR_PALETTE = [
    "#7C7FE9",  # violet
    "#10b981",  # vert émeraude
    "#3b82f6",  # bleu
    "#f59e0b",  # orange
    "#ef4444",  # rouge
    "#ec4899",  # rose
    "#06b6d4",  # cyan
    "#a855f7",  # violet vif
]


def _chat_colors_file() -> Path:
    base = Path.home() / ".triskell-command"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.debug("Création %s impossible : %s", base, exc)
    return base / "user_chat_colors.json"


def _load_chat_colors() -> dict:
    path = _chat_colors_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("Lecture %s impossible : %s", path, exc)
        return {}


def _save_chat_colors(colors: dict) -> bool:
    path = _chat_colors_file()
    try:
        path.write_text(json.dumps(colors, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return True
    except Exception as exc:
        logger.warning("Écriture %s impossible : %s", path, exc)
        return False


def get_chat_color(user_id: str) -> str:
    """Renvoie la couleur de chat d'un user (hex #RRGGBB). Préférence
    personnalisée si définie, sinon couleur par défaut."""
    custom = _load_chat_colors()
    val = (custom.get(user_id) or "").strip()
    if val and val.startswith("#") and len(val) in (4, 7):
        return val
    return DEFAULT_CHAT_COLORS.get(user_id, "#7C7FE9")


def set_chat_color(user_id: str, color: str) -> bool:
    """Enregistre la couleur de chat d'un user. Valide le format #RRGGBB."""
    if user_id not in KNOWN_USERS:
        return False
    color = (color or "").strip()
    if not color.startswith("#") or len(color) not in (4, 7):
        return False
    # Valide les caractères (hex)
    try:
        int(color[1:], 16)
    except ValueError:
        return False
    custom = _load_chat_colors()
    custom[user_id] = color
    return _save_chat_colors(custom)
