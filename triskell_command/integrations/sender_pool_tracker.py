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
        # c.raw force l'init du SDK ; le getattr "_client" restait None en
        # mode service_role tant que rien d'autre n'avait touché le client.
        try:
            return c.raw
        except Exception:
            return None
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


# =============================================================================
# Montée automatique du volume (« rampe ») — chauffe naturelle par boîte
# =============================================================================
# Au lieu d'un plafond fixe, le plafond du jour d'une boîte marquée
# "ramp" est calculé sur son historique RÉEL d'envois (email_history) :
# plus elle a envoyé ces 30 derniers jours, plus elle a le droit d'envoyer
# aujourd'hui — c'est exactement ce que les fournisseurs de mail
# récompensent (la chauffe honnête, par opposition aux réseaux de mails
# factices que Gmail détecte et pénalise). Une boîte qui s'arrête
# longtemps redescend toute seule (sa fenêtre de 30 jours fond) ; un pic
# de rebonds récents la freine. Le plafond saisi à la main (daily_cap)
# reste le MAXIMUM jamais dépassé.
#
# Entrée de pool étendue (rétro-compatible : le pipeline ne lit que
# account_id/daily_cap, les champs en plus voyagent sans le déranger) :
#   {"account_id": "primary", "daily_cap": 50,
#    "ramp": True,                # montée auto activée pour cette boîte
#    "ramp_start": "warm"}        # "soft" (défaut, 10/j) ou "warm" (25/j)

# Barème : volume cumulé sur 30 jours glissants → plafond du jour.
# Une boîte qui envoie tous les jours grimpe d'un palier par semaine
# environ (~4 semaines pour atteindre le sommet).
RAMP_STEPS = [
    (40,  10),   # moins de  40 mails sur 30 j → 10 / jour
    (120, 15),   # moins de 120                → 15 / jour
    (250, 25),
    (450, 35),
    (800, 50),
]
RAMP_TOP_CAP = 70          # au-delà du dernier palier
RAMP_FLOOR_SOFT = 10       # plancher départ « en douceur »
RAMP_FLOOR_WARM = 25       # plancher « boîte déjà rodée » (chauffée ailleurs)
RAMP_BRAKE_MIN_BOUNCES = 3  # frein : au moins 3 rebonds sur 7 j…
RAMP_BRAKE_RATIO = 0.05     # … ET plus de 5 % des envois des 7 derniers jours
RAMP_BRAKE_FLOOR = 5        # même freinée, une boîte garde 5/j (jamais 0)


def _read_history_days(days: int, kinds: list[str]) -> list[dict] | None:
    """Lit email_history sur N jours pour les kinds donnés. Renvoie
    [{'ts': iso, 'kind': str, 'account_id': str}] (account_id best-effort
    depuis extra, vide si absent). None = lecture IMPOSSIBLE (panne), à
    distinguer de [] (rien trouvé)."""
    sb = _sb()
    if sb is None:
        return None
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        res = (sb.table("email_history")
                 .select("ts, kind, extra")
                 .in_("kind", kinds)
                 .gte("ts", since)
                 .order("ts", desc=False)
                 .limit(20000)
                 .execute())
        rows = res.data or []
        out: list[dict] = []
        for r in rows:
            extra = r.get("extra") or {}
            if isinstance(extra, str):
                try:
                    import json as _json
                    extra = _json.loads(extra)
                except Exception:
                    extra = {}
            acc = (extra.get("account_id") if isinstance(extra, dict)
                   else "") or ""
            out.append({
                "ts":         r.get("ts") or "",
                "kind":       r.get("kind") or "",
                "account_id": str(acc).strip(),
            })
        return out
    except Exception as exc:
        logger.warning("sender_pool_tracker._read_history_days: %s", exc)
        return None


def _parse_ts(ts_str: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat((ts_str or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def ramp_step_for_volume(sent_30d: int) -> int:
    """Palier du barème pour un volume cumulé sur 30 jours."""
    for threshold, step_cap in RAMP_STEPS:
        if sent_30d < threshold:
            return step_cap
    return RAMP_TOP_CAP


def apply_ramp(pool: list[dict]) -> dict:
    """Calcule les plafonds DU JOUR des boîtes en « montée auto ».

    Renvoie {"pool", "details", "ok", "reason"} :
    - pool : entrées prêtes pour le pipeline (les boîtes en rampe portent
      leur plafond du jour dans daily_cap, les autres restent intactes) ;
    - details : une entrée par boîte en rampe, pour les logs et l'UI :
      {account_id, effective_cap, step_cap, max_cap, sent_30d, sent_7d,
       bounced_7d, braked, ramp_start} ;
    - ok=False : historique illisible → pool d'origine inchangé (une
      panne de lecture ne doit ni brider ni débrider les envois).
    """
    entries = [dict(p) for p in (pool or []) if isinstance(p, dict)]
    if not any(p.get("ramp") for p in entries):
        return {"pool": entries, "details": [], "ok": True, "reason": ""}

    sends = _read_history_days(30, ["email_sent"])
    if sends is None:
        return {"pool": entries, "details": [], "ok": False,
                "reason": "historique d'envois illisible"}
    # Rebonds : bonus de protection — s'ils sont illisibles, la rampe
    # continue sans frein plutôt que de tout bloquer.
    bounces = _read_history_days(7, ["status_bounced"]) or []

    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    counts30: dict[str, int] = {}
    counts7: dict[str, int] = {}
    for s in sends:
        acc = s.get("account_id") or "primary"
        counts30[acc] = counts30.get(acc, 0) + 1
        ts = _parse_ts(s.get("ts") or "")
        if ts is not None and ts >= seven_days_ago:
            counts7[acc] = counts7.get(acc, 0) + 1
    bounces7: dict[str, int] = {}
    for b in bounces:
        acc = b.get("account_id") or ""
        if acc:  # les vieux rebonds sans account_id ne comptent pas
            bounces7[acc] = bounces7.get(acc, 0) + 1

    details: list[dict] = []
    for p in entries:
        if not p.get("ramp"):
            continue
        acc = str(p.get("account_id") or "").strip()
        max_cap = int(p.get("daily_cap") or 0)
        start = ("warm" if str(p.get("ramp_start") or "").strip().lower()
                 == "warm" else "soft")
        s30 = counts30.get(acc, 0)
        s7 = counts7.get(acc, 0)
        b7 = bounces7.get(acc, 0)
        # Plancher de départ : sur-mesure (ramp_floor) prioritaire, sinon le
        # preset soft (10) / warm (25). Permet « démarrer à 15/jour dès
        # maintenant puis monter au-dessus » : le plafond du jour ne descend
        # jamais sous le plancher, et grimpe avec le volume réellement envoyé.
        floor_custom = p.get("ramp_floor")
        if floor_custom is not None and str(floor_custom).strip() != "":
            try:
                floor = max(1, int(floor_custom))
            except (TypeError, ValueError):
                floor = RAMP_FLOOR_WARM if start == "warm" else RAMP_FLOOR_SOFT
        else:
            floor = RAMP_FLOOR_WARM if start == "warm" else RAMP_FLOOR_SOFT
        step = max(ramp_step_for_volume(s30), floor)
        braked = (b7 >= RAMP_BRAKE_MIN_BOUNCES
                  and b7 > RAMP_BRAKE_RATIO * max(s7, 1))
        if braked:
            step = max(RAMP_BRAKE_FLOOR, step // 2)
        effective = min(max_cap, step) if max_cap > 0 else 0
        p["daily_cap"] = effective
        details.append({
            "account_id":    acc,
            "effective_cap": effective,
            "step_cap":      step,
            "max_cap":       max_cap,
            "sent_30d":      s30,
            "sent_7d":       s7,
            "bounced_7d":    b7,
            "braked":        braked,
            "ramp_start":    start,
            "ramp_floor":    floor,
        })
    return {"pool": entries, "details": details, "ok": True, "reason": ""}


def pool_status_with_ramp(pool: list[dict]) -> dict:
    """Statut UI du pool avec la rampe appliquée : par boîte, le plafond
    DU JOUR (daily_cap), le maximum réglé (max_cap), les envois 24h, et
    les infos de rampe (palier, volume 30 j, frein)."""
    ramp = apply_ramp(pool)
    base = pool_status_for_ui(ramp["pool"])
    max_by_id = {str(p.get("account_id") or "").strip():
                 int(p.get("daily_cap") or 0)
                 for p in (pool or []) if isinstance(p, dict)}
    details_by_id = {d["account_id"]: d for d in ramp["details"]}
    for acc in base.get("accounts", []):
        aid = acc.get("account_id") or ""
        d = details_by_id.get(aid)
        acc["ramp"] = bool(d)
        acc["max_cap"] = max_by_id.get(aid, acc.get("daily_cap", 0))
        if d:
            acc["step_cap"] = d["step_cap"]
            acc["sent_30d"] = d["sent_30d"]
            acc["braked"] = d["braked"]
            acc["ramp_start"] = d["ramp_start"]
    base["ramp_ok"] = ramp["ok"]
    return base


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
