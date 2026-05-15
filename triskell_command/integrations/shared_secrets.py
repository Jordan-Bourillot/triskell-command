"""Source de vérité unique pour les secrets partagés Jordan ↔ Thomas.

Avant : SMTP/IMAP + clés API IA stockées en local dans state.json (chacun
le sien). Conséquence : Jordan et Thomas devaient resaisir à chaque
changement, et les workers chez Thomas ne pouvaient pas envoyer un mail
"depuis" la boîte de Jordan.

Maintenant : tout dans `shared_settings` Supabase, lu par les deux.
Le state.json local sert juste de cache pour le mode preview (sans Supabase).

Schéma stocké dans `shared_settings.smtp_config` (existait déjà) :
  {smtp_host, smtp_port, smtp_user, smtp_password,
   imap_host, imap_port, imap_user, imap_password,
   from_email, from_name, daily_cap, follow_up_days}

Schéma stocké dans `shared_settings.ai_keys` (nouveau) :
  {google, anthropic, openai, mistral, xai}
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


SMTP_KEY = "smtp_config"      # déjà utilisé par post_sale_runner (compte principal)
AI_KEY   = "ai_keys"          # nouveau
MAIL_ACCOUNTS_KEY = "mail_accounts"   # liste des comptes mail secondaires
                                       # (en plus du compte principal smtp_config)


# ---------------------------------------------------------------------------
# Multi-comptes mail — comptes secondaires (en plus du compte principal)
# ---------------------------------------------------------------------------
# Schéma stocké dans `shared_settings.mail_accounts` :
#   { "accounts": [ { "id": "lagriffe", "label": "Lagriffe Studio",
#                     "from_email": "contact@lagriffe-studio.fr",
#                     "from_name": "Lagriffe Studio",
#                     "smtp_host": "smtp.ionos.fr", "smtp_port": 587,
#                     "smtp_user": "...", "smtp_password": "...",
#                     "imap_host": "imap.ionos.fr", "imap_port": 993,
#                     "imap_user": "...", "imap_password": "..." }, ... ] }
#
# Le compte "primary" (= smtp_config principal) n'est PAS dans cette liste —
# get_all_mail_accounts() le rajoute virtuellement en tête pour les vues.

def list_secondary_accounts(client=None) -> list[dict]:
    """Renvoie la liste des comptes mail secondaires (sans le principal)."""
    if client is None:
        return []
    try:
        raw = client.get_shared_setting(MAIL_ACCOUNTS_KEY, {}) or {}
        if isinstance(raw, str):
            try: raw = json.loads(raw)
            except Exception: raw = {}
        accounts = (raw.get("accounts") if isinstance(raw, dict) else None) or []
        return [a for a in accounts if isinstance(a, dict) and a.get("id")]
    except Exception as exc:
        logger.debug("list_secondary_accounts: %s", exc)
        return []


def get_all_mail_accounts(client=None, app_state=None) -> list[dict]:
    """Renvoie tous les comptes mail (principal + secondaires) au format
    uniforme. Le principal a toujours id='primary'.
    """
    out: list[dict] = []
    primary = get_smtp_config(client=client, app_state=app_state) or {}
    if primary.get("from_email") or primary.get("smtp_host"):
        out.append({
            "id": "primary",
            "label": primary.get("from_name") or primary.get("from_email") or "Compte principal",
            "from_email": primary.get("from_email", ""),
            "from_name": primary.get("from_name", ""),
            "smtp_host": primary.get("smtp_host", ""),
            "smtp_port": int(primary.get("smtp_port") or 587),
            "smtp_user": primary.get("smtp_user", ""),
            "imap_host": primary.get("imap_host", ""),
            "imap_port": int(primary.get("imap_port") or 993),
            "imap_user": primary.get("imap_user", ""),
            "is_primary": True,
            "_has_smtp_pwd": bool(primary.get("smtp_password")),
            "_has_imap_pwd": bool(primary.get("imap_password")),
        })
    for a in list_secondary_accounts(client=client):
        out.append({
            "id": a.get("id"),
            "label": a.get("label") or a.get("from_email") or a.get("id"),
            "from_email": a.get("from_email", ""),
            "from_name": a.get("from_name", ""),
            "smtp_host": a.get("smtp_host", ""),
            "smtp_port": int(a.get("smtp_port") or 587),
            "smtp_user": a.get("smtp_user", ""),
            "imap_host": a.get("imap_host", ""),
            "imap_port": int(a.get("imap_port") or 993),
            "imap_user": a.get("imap_user", ""),
            "is_primary": False,
            "_has_smtp_pwd": bool(a.get("smtp_password")),
            "_has_imap_pwd": bool(a.get("imap_password")),
        })
    return out


def add_or_update_mail_account(account: dict, client=None) -> bool:
    """Ajoute ou met à jour un compte secondaire (par id).
    Le compte principal (id='primary') n'est PAS modifiable ici — utiliser
    save_smtp_config() pour ça.
    """
    if client is None:
        return False
    aid = (account.get("id") or "").strip()
    if not aid or aid == "primary":
        return False
    accounts = list_secondary_accounts(client=client)
    # Si pas de password fourni, conserver l'existant
    existing = next((a for a in accounts if a.get("id") == aid), None)
    if existing:
        for pwd_field in ("smtp_password", "imap_password"):
            if not (account.get(pwd_field) or "").strip() and existing.get(pwd_field):
                account[pwd_field] = existing[pwd_field]
    # Remplace ou ajoute
    accounts = [a for a in accounts if a.get("id") != aid]
    accounts.append(account)
    try:
        client.set_shared_setting(MAIL_ACCOUNTS_KEY, {"accounts": accounts})
        return True
    except Exception as exc:
        logger.warning("add_or_update_mail_account: %s", exc)
        return False


def remove_mail_account(account_id: str, client=None) -> bool:
    if client is None or not account_id or account_id == "primary":
        return False
    accounts = list_secondary_accounts(client=client)
    accounts = [a for a in accounts if a.get("id") != account_id]
    try:
        client.set_shared_setting(MAIL_ACCOUNTS_KEY, {"accounts": accounts})
        return True
    except Exception as exc:
        logger.warning("remove_mail_account: %s", exc)
        return False


def get_account_by_id(account_id: str, client=None, app_state=None) -> Optional[dict]:
    """Renvoie le compte (avec mots de passe) par id, ou None.
    Inclut les mots de passe — usage backend uniquement.
    """
    if account_id == "primary":
        return get_smtp_config(client=client, app_state=app_state) or None
    for a in list_secondary_accounts(client=client):
        if a.get("id") == account_id:
            return a
    return None


# ---------------------------------------------------------------------------
# SMTP / IMAP — config mail partagée
# ---------------------------------------------------------------------------
def get_smtp_config(client=None, app_state=None) -> dict:
    """Renvoie la config mail (SMTP + IMAP). Supabase d'abord, fallback local."""
    # 1) Supabase
    if client is not None:
        try:
            raw = client.get_shared_setting(SMTP_KEY, {}) or {}
            if isinstance(raw, str):
                try: raw = json.loads(raw)
                except Exception: raw = {}
            if isinstance(raw, dict) and raw:
                return dict(raw)
        except Exception as exc:
            logger.debug("get_smtp_config supabase: %s", exc)
    # 2) Local fallback
    if app_state is not None:
        out = app_state.get("outreach", default={}) or {}
        return dict(out)
    return {}


def save_smtp_config(payload: dict, client=None, app_state=None) -> None:
    """Sauve dans Supabase + miroir local.
    Si Supabase indispo, sauve uniquement local."""
    if client is not None:
        try:
            client.set_shared_setting(SMTP_KEY, payload)
        except Exception as exc:
            logger.warning("save_smtp_config supabase: %s", exc)
    if app_state is not None:
        try:
            for k, v in (payload or {}).items():
                app_state.set("outreach", k, value=v)
            app_state.save()
        except Exception as exc:
            logger.debug("save_smtp_config local: %s", exc)


def resolve_smtp_for_send(client=None, app_state=None) -> Optional[dict]:
    """Renvoie le dict SMTP prêt pour smtp_sender.send_email,
    ou None si incomplet."""
    cfg = get_smtp_config(client=client, app_state=app_state)
    host = (cfg.get("smtp_host") or "").strip()
    user = (cfg.get("smtp_user") or "").strip()
    password = cfg.get("smtp_password") or ""
    from_email = cfg.get("from_email") or ""
    if not (host and user and password and from_email):
        return None
    return {
        "smtp_host": host,
        "smtp_port": int(cfg.get("smtp_port") or 587),
        "smtp_user": user,
        "smtp_password": password,
        "from_email": from_email,
        "from_name": cfg.get("from_name") or "",
    }


# ---------------------------------------------------------------------------
# Clés API IA — partagées
# ---------------------------------------------------------------------------
PROVIDERS = ("google", "anthropic", "openai", "mistral", "xai")


def get_ai_keys(client=None, app_state=None) -> dict[str, str]:
    """Renvoie {provider: api_key}. Supabase d'abord, fallback local."""
    out: dict[str, str] = {}
    if client is not None:
        try:
            raw = client.get_shared_setting(AI_KEY, {}) or {}
            if isinstance(raw, str):
                try: raw = json.loads(raw)
                except Exception: raw = {}
            if isinstance(raw, dict):
                for p in PROVIDERS:
                    v = raw.get(p)
                    if v:
                        out[p] = str(v)
                if out:
                    return out
        except Exception as exc:
            logger.debug("get_ai_keys supabase: %s", exc)

    # Local fallback (state.json puis Triskell Core config.json)
    if app_state is not None:
        ai = app_state.get("ai", default={}) or {}
        keys = ai.get("api_keys") or {}
        for p in PROVIDERS:
            v = keys.get(p)
            if v:
                out[p] = str(v)
    if not out:
        # Dernier fallback : Triskell Core config.json (héritage)
        try:
            from triskell_core.prospect.core.crm import CONFIG_FILE
            if CONFIG_FILE.exists():
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                for p in PROVIDERS:
                    v = cfg.get(f"{p}_api_key")
                    if v:
                        out[p] = str(v)
        except Exception:
            pass
    return out


def save_ai_keys(keys: dict[str, str], client=None, app_state=None) -> None:
    """Sauve dans Supabase + miroir local."""
    clean = {p: keys.get(p, "") for p in PROVIDERS if keys.get(p)}
    if client is not None:
        try:
            client.set_shared_setting(AI_KEY, clean)
        except Exception as exc:
            logger.warning("save_ai_keys supabase: %s", exc)
    if app_state is not None:
        try:
            existing = (app_state.get("ai", "api_keys", default={}) or {})
            existing.update(clean)
            app_state.set("ai", "api_keys", value=existing)
            app_state.save()
        except Exception as exc:
            logger.debug("save_ai_keys local: %s", exc)


def sync_ai_keys_to_core(client=None, app_state=None) -> None:
    """Recopie les clés IA actuelles vers Triskell Core config.json,
    pour que les modules Core (auto-pilote, recycler, multichannel) les
    retrouvent sans avoir à connaître Supabase."""
    keys = get_ai_keys(client=client, app_state=app_state)
    if not keys:
        return
    try:
        from triskell_core.prospect.core.crm import CONFIG_FILE, ensure_dirs
        ensure_dirs()
        current: dict[str, Any] = {}
        if CONFIG_FILE.exists():
            try:
                current = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                current = {}
        for p, v in keys.items():
            if v:
                current[f"{p}_api_key"] = v
        # Aussi sync SMTP (au cas où)
        smtp = get_smtp_config(client=client, app_state=app_state)
        for k in ("smtp_host", "smtp_port", "smtp_user", "smtp_password",
                  "from_email", "from_name", "imap_host", "imap_port",
                  "imap_user", "imap_password"):
            v = smtp.get(k)
            if v not in (None, ""):
                current[k] = v
        CONFIG_FILE.write_text(
            json.dumps(current, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("sync_ai_keys_to_core: %s", exc)
