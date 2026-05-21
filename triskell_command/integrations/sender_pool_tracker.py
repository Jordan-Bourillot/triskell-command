"""Tracker des envois 24h glissantes par adresse mail expéditrice.

Sert au Convoi multi-adresses : on tient un compteur par account_id des
mails envoyés dans les 24 dernières heures, en lisant l'historique
partagé `email_history` (cross-Convoi + autres outils Triskell).

Logique de réveil 24h glissantes :
- Une adresse est dispo si elle a envoyé STRICTEMENT MOINS que son cap
  sur la fenêtre [now - 24h, now].
- Si elle est au plafond, elle se réveille quand son mail le plus ancien
  de la fenêtre sort des 24h (donc ts_oldest + 24h).
- Le pool entier se réveille au premier "slot libre" parmi les adresses.

API publique :
    counts = count_sent_24h_by_account([id1, id2, ...])
    next_free_at = next_free_account_at(pool)
    account_id = pick_random_available_account(pool)
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connexion Supabase (réutilise les helpers existants)
# ---------------------------------------------------------------------------
def _sb():
    """Renvoie un client Supabase (service-role préféré, user en fallback)."""
    # On tente service-role via les helpers obelisk (DRY)
    try:
        from .obelisk import repo as obelisk_repo
        c = obelisk_repo._sb()
        if c is not None:
            return c
    except Exception as exc:
        logger.debug("sender_pool_tracker._sb obelisk fallback: %s", exc)
    # Fallback user-authed
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        if not getattr(c, "is_authenticated", False):
            return None
        return getattr(c, "client", None) or getattr(c, "_client", None) or c
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Lecture des envois 24h glissantes
# ---------------------------------------------------------------------------
def _read_sends_24h() -> list[dict]:
    """Lit toutes les lignes email_history kind='email_sent' des dernières
    24h, en ne ramenant que les colonnes utiles. Renvoie une liste de
    {'ts': iso, 'account_id': str, 'from_email': str} (best-effort)."""
    sb = _sb()
    if sb is None:
        return []
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        res = (sb.table("email_history")
                 .select("ts, extra")
                 .eq("kind", "email_sent")
                 .gte("ts", since)
                 .order("ts", desc=False)
                 .limit(5000)
                 .execute())
        rows = res.data or []
        out: list[dict] = []
        for r in rows:
            extra = r.get("extra") or {}
            if isinstance(extra, str):
                # Au cas où extra est stocké comme string JSON
                try:
                    import json as _json
                    extra = _json.loads(extra)
                except Exception:
                    extra = {}
            acc = (extra.get("account_id") if isinstance(extra, dict)
                   else "") or ""
            from_email = (extra.get("from") if isinstance(extra, dict)
                          else "") or ""
            out.append({
                "ts":         r.get("ts") or "",
                "account_id": str(acc).strip() or "primary",
                "from_email": str(from_email).strip().lower(),
            })
        return out
    except Exception as exc:
        logger.warning("sender_pool_tracker._read_sends_24h: %s", exc)
        return []


def count_sent_24h_by_account(account_ids: list[str] | None = None) -> dict[str, int]:
    """Renvoie {account_id: nb_envois_24h}. Si account_ids est fourni, on
    initialise les clés à 0 même pour ceux qui n'ont rien envoyé."""
    sends = _read_sends_24h()
    counts: dict[str, int] = {a: 0 for a in (account_ids or [])}
    for s in sends:
        acc = s.get("account_id") or "primary"
        counts[acc] = counts.get(acc, 0) + 1
    return counts


def oldest_send_ts_24h(account_id: str) -> Optional[datetime]:
    """Renvoie le timestamp du mail le PLUS ANCIEN sur la fenêtre 24h
    pour cette adresse. Permet de calculer quand un slot va se libérer
    (oldest + 24h). Renvoie None si rien."""
    sends = _read_sends_24h()
    target = account_id or "primary"
    oldest = None
    for s in sends:
        if (s.get("account_id") or "primary") != target:
            continue
        ts_str = s.get("ts") or ""
        if not ts_str:
            continue
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            continue
        if oldest is None or dt < oldest:
            oldest = dt
    return oldest


# ---------------------------------------------------------------------------
# Choix d'une adresse pour le prochain envoi
# ---------------------------------------------------------------------------
def available_accounts(pool: list[dict],
                       counts: dict[str, int] | None = None) -> list[dict]:
    """Filtre les entrées de pool dont le cap n'est PAS atteint sur 24h.

    pool : liste de {"account_id": str, "daily_cap": int}.
    counts : dict {account_id: nb_envois_24h}. Si None, on le calcule.
    """
    if not pool:
        return []
    if counts is None:
        ids = [str(p.get("account_id") or "").strip() for p in pool]
        counts = count_sent_24h_by_account([i for i in ids if i])
    out = []
    for p in pool:
        acc = str(p.get("account_id") or "").strip()
        if not acc:
            continue
        cap = int(p.get("daily_cap") or 0)
        if cap <= 0:
            continue  # cap 0 = adresse désactivée
        if counts.get(acc, 0) < cap:
            out.append(p)
    return out


def pick_random_available_account(pool: list[dict]) -> Optional[dict]:
    """Tire aléatoirement une adresse du pool qui a encore de la marge.
    Renvoie None si toutes sont au plafond."""
    avail = available_accounts(pool)
    if not avail:
        return None
    return random.choice(avail)


def next_free_account_at(pool: list[dict]) -> Optional[datetime]:
    """Si toutes les adresses sont saturées, renvoie l'heure UTC à laquelle
    la PREMIÈRE adresse retrouvera un slot (= oldest_send + 24h). Renvoie
    None si au moins une adresse est déjà dispo, ou si le pool est vide."""
    if not pool:
        return None
    ids = [str(p.get("account_id") or "").strip() for p in pool
           if (p.get("account_id") or "")]
    counts = count_sent_24h_by_account(ids)
    # Si quelqu'un est dispo → pas d'attente
    for p in pool:
        acc = str(p.get("account_id") or "").strip()
        cap = int(p.get("daily_cap") or 0)
        if cap > 0 and counts.get(acc, 0) < cap:
            return None
    # Sinon : pour chaque adresse, calcule quand son slot suivant se libère.
    # On garde le minimum (= la première à se réveiller).
    best: Optional[datetime] = None
    for p in pool:
        acc = str(p.get("account_id") or "").strip()
        oldest = oldest_send_ts_24h(acc)
        if oldest is None:
            # Pas d'envoi récent et pourtant saturée ? Pool incohérent,
            # on considère dispo immédiatement.
            return None
        wakeup = oldest + timedelta(hours=24)
        if best is None or wakeup < best:
            best = wakeup
    return best


def pool_status_for_ui(pool: list[dict]) -> dict:
    """Snapshot lisible pour affichage UI : par adresse, on dit combien
    envoyés / cap / restant + l'heure UTC de réveil estimée si saturée."""
    ids = [str(p.get("account_id") or "").strip() for p in pool
           if (p.get("account_id") or "")]
    counts = count_sent_24h_by_account(ids)
    out_accounts = []
    for p in pool:
        acc = str(p.get("account_id") or "").strip()
        cap = int(p.get("daily_cap") or 0)
        sent = counts.get(acc, 0)
        wakeup = None
        if cap > 0 and sent >= cap:
            old = oldest_send_ts_24h(acc)
            if old is not None:
                wakeup = (old + timedelta(hours=24)).isoformat()
        out_accounts.append({
            "account_id": acc,
            "daily_cap":  cap,
            "sent_24h":   sent,
            "remaining":  max(0, cap - sent),
            "saturated":  cap > 0 and sent >= cap,
            "wakeup_at":  wakeup,
        })
    return {
        "ok": True,
        "accounts":           out_accounts,
        "total_remaining":    sum(a["remaining"] for a in out_accounts),
        "next_free_at":       (next_free_account_at(pool) or "").isoformat()
                              if isinstance(next_free_account_at(pool), datetime)
                              else None,
    }
