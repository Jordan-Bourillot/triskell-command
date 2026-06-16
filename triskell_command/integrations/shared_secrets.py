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


def get_account_by_address(address: str, client=None, app_state=None) -> Optional[dict]:
    """Renvoie le compte mail (avec mots de passe) dont l'adresse
    d'expéditeur (from_email) correspond, ou None. Usage backend.

    Sert au câblage modèle→adresse : un modèle de prospection qui exige
    une adresse d'envoi doit partir par le compte configuré correspondant
    — jamais par un autre. Comparaison insensible à la casse/espaces.
    Le compte principal est renvoyé avec un champ id='primary' pour la
    traçabilité (il n'en a pas dans smtp_config).
    """
    addr = (address or "").strip().lower()
    if not addr or "@" not in addr:
        return None
    primary = get_smtp_config(client=client, app_state=app_state) or {}
    if (primary.get("from_email") or "").strip().lower() == addr:
        out = dict(primary)
        out.setdefault("id", "primary")
        return out
    for a in list_secondary_accounts(client=client):
        if (a.get("from_email") or "").strip().lower() == addr:
            return dict(a)
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
# Clés « délivrabilité » — note Gmail (Postmaster) + listes noires (Spamhaus)
# ---------------------------------------------------------------------------
# Stockées dans shared_settings.deliverability_keys :
#   { "spamhaus_dqs_key": "...",
#     "postmaster": {"client_id": "...", "client_secret": "...",
#                    "refresh_token": "..."} }
# Variables d'environnement reconnues (priorité, figées côté hébergeur) :
#   SPAMHAUS_DQS_KEY, POSTMASTER_CLIENT_ID, POSTMASTER_CLIENT_SECRET,
#   POSTMASTER_REFRESH_TOKEN.
DELIVERABILITY_KEY = "deliverability_keys"


def get_deliverability_keys(client=None) -> dict:
    """Renvoie {spamhaus_dqs_key, postmaster:{client_id, client_secret,
    refresh_token}}. Variables d'environnement prioritaires, puis Supabase."""
    import os
    out = {"spamhaus_dqs_key": "",
           "postmaster": {"client_id": "", "client_secret": "", "refresh_token": ""}}
    # 1) Supabase
    if client is not None:
        try:
            raw = client.get_shared_setting(DELIVERABILITY_KEY, {}) or {}
            if isinstance(raw, str):
                try: raw = json.loads(raw)
                except Exception: raw = {}
            if isinstance(raw, dict):
                out["spamhaus_dqs_key"] = (raw.get("spamhaus_dqs_key") or "").strip()
                pm = raw.get("postmaster") or {}
                if isinstance(pm, dict):
                    for k in ("client_id", "client_secret", "refresh_token"):
                        out["postmaster"][k] = (pm.get(k) or "").strip()
        except Exception as exc:
            logger.debug("get_deliverability_keys supabase: %s", exc)
    # 2) ENV — priorité absolue (écrase la base)
    env_map = {
        "SPAMHAUS_DQS_KEY": ("spamhaus_dqs_key", None),
        "POSTMASTER_CLIENT_ID": ("postmaster", "client_id"),
        "POSTMASTER_CLIENT_SECRET": ("postmaster", "client_secret"),
        "POSTMASTER_REFRESH_TOKEN": ("postmaster", "refresh_token"),
    }
    for var, (top, sub) in env_map.items():
        v = (os.environ.get(var) or "").strip()
        if not v:
            continue
        if sub is None:
            out[top] = v
        else:
            out[top][sub] = v
    return out


def save_deliverability_keys(payload: dict, client=None) -> bool:
    """Fusionne et sauve les clés délivrabilité. Une valeur vide n'écrase pas
    l'existant (permet de mettre à jour une seule clé sans tout resaisir)."""
    if client is None:
        return False
    cur = {}
    try:
        cur = client.get_shared_setting(DELIVERABILITY_KEY, {}) or {}
        if isinstance(cur, str):
            cur = json.loads(cur)
    except Exception:
        cur = {}
    if not isinstance(cur, dict):
        cur = {}
    cur.setdefault("postmaster", {})
    p = payload or {}
    if (p.get("spamhaus_dqs_key") or "").strip():
        cur["spamhaus_dqs_key"] = p["spamhaus_dqs_key"].strip()
    pm = p.get("postmaster") or {}
    for k in ("client_id", "client_secret", "refresh_token"):
        if (pm.get(k) or "").strip():
            cur["postmaster"][k] = pm[k].strip()
    try:
        client.set_shared_setting(DELIVERABILITY_KEY, cur)
        return True
    except Exception as exc:
        logger.warning("save_deliverability_keys: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Clés API IA — partagées
# ---------------------------------------------------------------------------
PROVIDERS = ("google", "anthropic", "openai", "mistral", "xai", "deepseek")


def _env_keys() -> dict[str, str]:
    """Lit les clés IA depuis les variables d'environnement (priorité haute).
    Permet de figer les clés côté serveur (Coolify, .env) pour qu'aucune
    écriture côté app ne puisse les écraser.

    Variables reconnues :
      ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY (ou GEMINI_API_KEY),
      MISTRAL_API_KEY, XAI_API_KEY (ou GROK_API_KEY).
    """
    import os
    aliases = {
        "anthropic": ("ANTHROPIC_API_KEY",),
        "openai":    ("OPENAI_API_KEY",),
        "google":    ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        "mistral":   ("MISTRAL_API_KEY",),
        "xai":       ("XAI_API_KEY", "GROK_API_KEY"),
        "deepseek":  ("DEEPSEEK_API_KEY",),
    }
    out: dict[str, str] = {}
    for provider, vars_ in aliases.items():
        for var in vars_:
            v = (os.environ.get(var) or "").strip()
            if v:
                out[provider] = v
                break
    return out


def _clean_key(v) -> str:
    """Strip whitespace/newlines invisibles. Anthropic refuse une clé avec
    un espace en début/fin et renvoie 401 'invalid x-api-key'."""
    if not v:
        return ""
    return str(v).strip().replace("​", "").replace("﻿", "")


def get_ai_keys(client=None, app_state=None) -> dict[str, str]:
    """Renvoie {provider: api_key}. Ordre de priorité :
       1. Variables d'environnement (figées côté hébergeur) — IMMUABLES.
       2. Supabase shared_settings.
       3. ~/.triskell-command/settings.json (app_state local).
       4. Triskell Core config.json (héritage)."""
    out: dict[str, str] = {}
    # 1. ENV — priorité absolue, ne peut PAS être écrasée par l'app
    env_out = _env_keys()
    out.update(env_out)

    # 2. Supabase
    if client is not None:
        try:
            raw = client.get_shared_setting(AI_KEY, {}) or {}
            if isinstance(raw, str):
                try: raw = json.loads(raw)
                except Exception: raw = {}
            if isinstance(raw, dict):
                for p in PROVIDERS:
                    if p in out:  # déjà fourni par env
                        continue
                    v = _clean_key(raw.get(p))
                    if v:
                        out[p] = v
        except Exception as exc:
            logger.debug("get_ai_keys supabase: %s", exc)

    # 3. Local fallback (state.json)
    if app_state is not None:
        ai = app_state.get("ai", default={}) or {}
        keys = ai.get("api_keys") or {}
        for p in PROVIDERS:
            if p in out:
                continue
            v = _clean_key(keys.get(p))
            if v:
                out[p] = v

    # 4. Triskell Core config.json (héritage)
    if not all(p in out for p in PROVIDERS):
        try:
            from triskell_core.prospect.core.crm import CONFIG_FILE
            if CONFIG_FILE.exists():
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                for p in PROVIDERS:
                    if p in out:
                        continue
                    v = _clean_key(cfg.get(f"{p}_api_key"))
                    if v:
                        out[p] = v
        except Exception:
            pass
    return out


def save_ai_keys(keys: dict[str, str], client=None, app_state=None) -> None:
    """Sauve dans Supabase + miroir local. Ne touche PAS aux clés fournies
    par les variables d'environnement (elles sont immuables, prennent
    toujours le pas sur ce qu'on stocke ici).

    Strip systématique du whitespace pour éviter les 401 invisibles.
    """
    env_locked = set(_env_keys().keys())
    if env_locked:
        logger.info("save_ai_keys: clés en env vars (immuables): %s",
                    sorted(env_locked))
    clean: dict[str, str] = {}
    for p in PROVIDERS:
        v = _clean_key(keys.get(p))
        if v:
            clean[p] = v
    # On retire les providers verrouillés par env du payload Supabase
    # (pas la peine de stocker un fallback pour une clé immuable)
    to_store = {p: v for p, v in clean.items() if p not in env_locked}
    if client is not None and to_store:
        try:
            # Merge avec l'existant pour ne pas effacer les autres providers
            existing_raw = client.get_shared_setting(AI_KEY, {}) or {}
            if isinstance(existing_raw, str):
                try: existing_raw = json.loads(existing_raw)
                except Exception: existing_raw = {}
            if not isinstance(existing_raw, dict):
                existing_raw = {}
            merged = {**existing_raw, **to_store}
            client.set_shared_setting(AI_KEY, merged)
        except Exception as exc:
            logger.warning("save_ai_keys supabase: %s", exc)
    if app_state is not None and clean:
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
