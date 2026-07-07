"""Alerte « crédit IA épuisé » — pour ne plus jamais avoir de panne silencieuse.

Le 07/07/2026, le crédit Anthropic est tombé à zéro. Résultat : l'Exécuteur
SEO, l'écriture des mails de prospection et l'assistant se sont bloqués EN
SILENCE — la page Santé n'y voyait rien (elle surveille les robots et la base,
jamais le solde de l'IA payante).

Ce module comble le trou :
- `record_ai_error(where, err)` : appelé quand un appel IA échoue. Si c'est un
  épuisement de crédit/quota, il pose un drapeau en base + envoie une
  notification push (dédoublonnée sur 12 h).
- `note_ai_ok()` : appelé quand un appel IA réussit → lève le drapeau. Throttlé
  en mémoire (une vérif base toutes les 5 min max) pour ne pas peser sur l'egress.
- `ai_credit_status()` : lu par la page Santé pour afficher l'alerte.

Best-effort partout : ce module ne lève JAMAIS et ne bloque jamais un envoi.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

SHARED_KEY = "ai_credit_alert"
_PUSH_COOLDOWN_H = 12          # une push max toutes les 12 h
_OK_CHECK_THROTTLE_S = 300     # vérif base « ça remarche » au plus toutes les 5 min

# Motifs d'épuisement de crédit / quota — tous fournisseurs confondus.
_CREDIT_RE = re.compile(
    r"credit balance is too low|insufficient (?:funds|credit|quota|balance)|"
    r"quota exceeded|exceeded your current quota|billing hard limit|"
    r"payment required|plans?\s*&?\s*billing|purchase to (?:continue|access)|"
    r"insufficient_quota|billing_hard_limit_reached",
    re.IGNORECASE,
)

# Throttle en mémoire (par process) pour note_ai_ok().
_last_ok_check: float = 0.0


def looks_like_credit_exhausted(msg) -> bool:
    """True si le message d'erreur ressemble à un crédit/quota épuisé."""
    return bool(_CREDIT_RE.search(str(msg or "")))


def _client():
    try:
        from triskell_core.db import get_client
        c = get_client()
        return c if (c is not None and getattr(c, "is_authenticated", False)) else None
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def record_ai_error(where: str, err, *, provider: str = "") -> bool:
    """Si `err` est un épuisement de crédit : pose le drapeau + push (12 h).
    Renvoie True si une alerte a été (ré)armée. Ne lève jamais."""
    try:
        if not looks_like_credit_exhausted(err):
            return False
        now = _now()
        now_iso = now.isoformat()
        c = _client()
        prev = {}
        if c is not None:
            try:
                prev = c.get_shared_setting(SHARED_KEY, {}) or {}
            except Exception:
                prev = {}
        if not isinstance(prev, dict):
            prev = {}
        last_push = prev.get("last_push_at") or ""
        do_push = True
        if last_push:
            try:
                do_push = (now - datetime.fromisoformat(last_push)) > timedelta(hours=_PUSH_COOLDOWN_H)
            except Exception:
                do_push = True
        flag = {
            "active": True,
            "at": now_iso,
            "where": (where or "")[:80],
            "provider": (provider or "")[:30],
            "message": str(err)[:300],
            "first_seen_at": prev.get("first_seen_at") or now_iso,
            "last_push_at": now_iso if do_push else last_push,
        }
        if c is not None:
            try:
                from .shared_settings_db import upsert_setting
                upsert_setting(c, SHARED_KEY, flag)
            except Exception as exc:
                logger.debug("ai_health: upsert KO (%s)", exc)
        if do_push:
            try:
                from ..web.push import send_push
                send_push(
                    "🔴 Crédit IA épuisé",
                    "L'IA payante ne répond plus (crédit vide). "
                    "Recharge sur console.anthropic.com → Billing. En attendant, "
                    "le SEO, l'écriture des mails et l'assistant sont bloqués.",
                    user_id="jordan", priority="urgent",
                    tag="ai-credit", tag_group="ai-credit", url="/#health",
                )
            except Exception as exc:
                logger.debug("ai_health: push KO (%s)", exc)
        logger.warning("ALERTE crédit IA épuisé (%s) : %s", where, str(err)[:150])
        return True
    except Exception as exc:
        logger.debug("ai_health.record_ai_error: %s", exc)
        return False


def note_ai_ok() -> None:
    """Un appel IA a réussi → lève le drapeau s'il était posé. Throttlé en
    mémoire (une vérif base toutes les 5 min max) pour ne pas peser sur l'egress."""
    global _last_ok_check
    try:
        now_ts = time.time()
        if (now_ts - _last_ok_check) < _OK_CHECK_THROTTLE_S:
            return
        _last_ok_check = now_ts
        c = _client()
        if c is None:
            return
        prev = c.get_shared_setting(SHARED_KEY, {}) or {}
        if isinstance(prev, dict) and prev.get("active"):
            prev["active"] = False
            prev["cleared_at"] = _now().isoformat()
            from .shared_settings_db import upsert_setting
            upsert_setting(c, SHARED_KEY, prev)
            logger.info("ai_health: crédit IA de nouveau OK — alerte levée.")
    except Exception as exc:
        logger.debug("ai_health.note_ai_ok: %s", exc)


def ai_credit_status(client=None) -> dict:
    """Pour la page Santé : {ok, active, at, where, message}. Ne lève jamais."""
    try:
        c = client or _client()
        if c is None:
            return {"ok": True, "active": False}
        f = c.get_shared_setting(SHARED_KEY, {}) or {}
        if not isinstance(f, dict):
            return {"ok": True, "active": False}
        active = bool(f.get("active"))
        return {
            "ok": not active,
            "active": active,
            "at": f.get("at", ""),
            "where": f.get("where", ""),
            "message": f.get("message", ""),
        }
    except Exception:
        return {"ok": True, "active": False}
