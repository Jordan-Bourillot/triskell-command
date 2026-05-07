"""Test A/B des sujets de mail — variantes + mesure du taux de réponse.

Comment ça marche :
  1. Tu définis des « campagnes » (groupes de sujets à comparer entre eux).
     Une campagne = un objectif (ex: "premier contact froid", "relance J+5").
  2. Pour chaque campagne, plusieurs variantes de sujet (ex: 2 à 5).
  3. Quand l'auto-pilote ou le drip envoie un mail, il appelle pick_variant()
     pour choisir un sujet (round-robin équilibré pour ne jamais favoriser
     une variante avant d'avoir des données).
  4. À chaque envoi, on incrémente sent_count de la variante choisie + on
     marque l'email_history.extra.ab_variant_id.
  5. Quand une réponse arrive, replies_poller appelle record_reply() qui
     incrémente reply_count de la variante d'origine.
  6. Le tableau de bord A/B affiche taux de réponse par variante + verdict
     statistique (Z-test des proportions à 95% de confiance).

Pas d'IA pour générer les variantes : c'est à Jordan de proposer ses
hypothèses (tutoiement vs vouvoiement, urgence vs curiosité, court vs
long, etc.). L'app mesure objectivement laquelle gagne.

Stockage : Supabase via shared_settings.subject_ab_test, fallback local.
"""

from __future__ import annotations

import json
import logging
import math
import random
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


SHARED_KEY = "subject_ab_test"
LOCAL_FILE = Path.home() / ".triskell-command" / "subject_ab_test.json"


# Format d'une campagne :
# {
#   "id": "first_contact",
#   "name": "Premier contact froid",
#   "active": True,
#   "variants": [
#     {"id": "v1", "subject": "Une idée pour {company_name}",
#      "sent_count": 47, "reply_count": 3},
#     {"id": "v2", "subject": "{company_name} — 30 secondes ?",
#      "sent_count": 49, "reply_count": 7},
#   ]
# }

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,        # off par défaut tant que pas de campagnes définies
    "campaigns": [],
    "min_sent_for_verdict": 30,   # nb minimal d'envois par variante avant de tirer un verdict
}


# ---------------------------------------------------------------------------
def _ensure_dir() -> None:
    LOCAL_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_config(client=None) -> dict:
    """Charge depuis Supabase en priorité, fallback local."""
    if client:
        try:
            raw = client.get_shared_setting(SHARED_KEY, {}) or {}
            if isinstance(raw, str):
                try: raw = json.loads(raw)
                except Exception: raw = {}
            if isinstance(raw, dict) and raw:
                return {**DEFAULT_CONFIG, **raw}
        except Exception:
            pass
    if LOCAL_FILE.exists():
        try:
            data = json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**DEFAULT_CONFIG, **data}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config: dict, client=None) -> None:
    _ensure_dir()
    LOCAL_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if client:
        try:
            client.set_shared_setting(SHARED_KEY, config)
        except Exception as exc:
            logger.debug("save_config supabase: %s", exc)


# ---------------------------------------------------------------------------
def pick_variant(campaign_id: str, client=None) -> Optional[dict]:
    """Choisit une variante de la campagne (round-robin équilibré).

    Round-robin = on choisit la variante avec le moins d'envois jusqu'ici
    (équilibre garanti). Si égalité, choix aléatoire entre celles à égalité.

    Renvoie {variant_id, subject} ou None si campagne introuvable / vide.
    """
    config = load_config(client)
    if not config.get("enabled", False):
        return None
    camp = _find_campaign(config, campaign_id)
    if not camp or not camp.get("active", True):
        return None
    variants = camp.get("variants") or []
    if not variants:
        return None

    min_sent = min(int(v.get("sent_count") or 0) for v in variants)
    pool = [v for v in variants if int(v.get("sent_count") or 0) == min_sent]
    chosen = random.choice(pool)
    return {
        "variant_id": chosen.get("id") or "",
        "subject":    chosen.get("subject") or "",
        "campaign_id": campaign_id,
    }


def record_send(campaign_id: str, variant_id: str, client=None) -> bool:
    """Incrémente sent_count de la variante."""
    config = load_config(client)
    camp = _find_campaign(config, campaign_id)
    if not camp:
        return False
    for v in (camp.get("variants") or []):
        if v.get("id") == variant_id:
            v["sent_count"] = int(v.get("sent_count") or 0) + 1
            save_config(config, client)
            return True
    return False


def record_reply(campaign_id: str, variant_id: str, client=None) -> bool:
    """Incrémente reply_count de la variante."""
    config = load_config(client)
    camp = _find_campaign(config, campaign_id)
    if not camp:
        return False
    for v in (camp.get("variants") or []):
        if v.get("id") == variant_id:
            v["reply_count"] = int(v.get("reply_count") or 0) + 1
            save_config(config, client)
            return True
    return False


# ---------------------------------------------------------------------------
def get_results(client=None) -> list[dict]:
    """Renvoie l'analyse complète : pour chaque campagne, la perf de chaque
    variante + verdict statistique (winner si différence significative)."""
    config = load_config(client)
    out = []
    min_sent = int(config.get("min_sent_for_verdict") or 30)
    for camp in config.get("campaigns", []):
        variants = list(camp.get("variants") or [])
        for v in variants:
            sent = int(v.get("sent_count") or 0)
            reply = int(v.get("reply_count") or 0)
            v["reply_rate"] = round(100.0 * reply / sent, 2) if sent > 0 else 0.0
            v["enough_data"] = sent >= min_sent

        # Trouve le winner (taux de réponse le plus haut, parmi celles qui
        # ont assez de données)
        eligible = [v for v in variants if v.get("enough_data")]
        winner = None
        verdict = ""
        if len(eligible) >= 2:
            best = max(eligible, key=lambda v: v.get("reply_rate", 0))
            others = [v for v in eligible if v is not best]
            # Z-test des proportions vs la 2e meilleure
            second = max(others, key=lambda v: v.get("reply_rate", 0))
            if _is_significant(best, second):
                winner = best.get("id")
                verdict = (
                    f"« {best.get('subject', '')[:40]}… » gagne "
                    f"({best.get('reply_rate')}% vs {second.get('reply_rate')}%, "
                    f"écart statistiquement significatif)."
                )
            else:
                verdict = (
                    f"Pas encore de gagnant net (écart non significatif). "
                    f"Continue d'envoyer pour avoir + de données."
                )
        elif len(eligible) == 1:
            verdict = (
                f"Une seule variante a assez de données (≥ {min_sent} envois). "
                f"Lance les autres."
            )
        else:
            verdict = (
                f"Pas encore assez de données. Besoin d'au moins "
                f"{min_sent} envois par variante."
            )

        out.append({
            "id": camp.get("id"),
            "name": camp.get("name"),
            "active": camp.get("active", True),
            "variants": variants,
            "winner_variant_id": winner,
            "verdict": verdict,
        })
    return out


def _is_significant(a: dict, b: dict, alpha: float = 0.05) -> bool:
    """Z-test à deux proportions (test d'égalité). Renvoie True si on
    rejette H0 (= les deux taux sont vraiment différents) à 95%."""
    n1 = int(a.get("sent_count") or 0)
    x1 = int(a.get("reply_count") or 0)
    n2 = int(b.get("sent_count") or 0)
    x2 = int(b.get("reply_count") or 0)
    if n1 == 0 or n2 == 0:
        return False
    p1 = x1 / n1
    p2 = x2 / n2
    p_pool = (x1 + x2) / (n1 + n2)
    if p_pool == 0 or p_pool == 1:
        return False
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return False
    z = (p1 - p2) / se
    # Pour alpha=0.05, |z| > 1.96
    return abs(z) > 1.96


# ---------------------------------------------------------------------------
def _find_campaign(config: dict, campaign_id: str) -> Optional[dict]:
    for camp in config.get("campaigns", []):
        if camp.get("id") == campaign_id:
            return camp
    return None


def add_campaign(name: str, variants_subjects: list[str], client=None) -> dict:
    """Crée une nouvelle campagne avec N variantes."""
    config = load_config(client)
    cid = name.lower().strip().replace(" ", "_")[:40] or f"camp_{len(config.get('campaigns', []))}"
    if _find_campaign(config, cid):
        cid = f"{cid}_{len(config.get('campaigns', []))}"
    camp = {
        "id": cid,
        "name": name,
        "active": True,
        "variants": [
            {"id": f"v{i+1}", "subject": s.strip(),
             "sent_count": 0, "reply_count": 0}
            for i, s in enumerate(variants_subjects) if s and s.strip()
        ],
    }
    config.setdefault("campaigns", []).append(camp)
    config["enabled"] = True
    save_config(config, client)
    return camp


def delete_campaign(campaign_id: str, client=None) -> bool:
    config = load_config(client)
    camps = config.get("campaigns") or []
    new = [c for c in camps if c.get("id") != campaign_id]
    if len(new) == len(camps):
        return False
    config["campaigns"] = new
    save_config(config, client)
    return True
