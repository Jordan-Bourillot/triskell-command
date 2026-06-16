# -*- coding: utf-8 -*-
"""Batterie « réputation des boîtes d'envoi » — sans réseau.

Vérifie que le système ne produit QUE des faits vérifiés et des verdicts
honnêtes :
  - l'historique réel est correctement attribué à chaque boîte ;
  - une boîte sans envoi est « froide », jamais « chaude » ;
  - une chauffe non terminée reste « en chauffe » ;
  - un fort taux de rebond ou une authentification incomplète passe en alerte ;
  - une lecture impossible donne « non vérifié », surtout pas « froide » ;
  - le docteur DNS (réutilisé) classe bien SPF/DKIM/DMARC/MX.

Tout est injecté (timestamps, lignes d'historique, résolveurs DNS) : aucun
appel réseau, exécution < 1 s.

    python -X utf8 scripts/smoke_mail_reputation.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "triskell-core"))

from triskell_command.integrations import mail_reputation as MR  # noqa: E402
from triskell_command.integrations.mail_dns_doctor import check_domain  # noqa: E402

NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNTS = [
    {"id": "primary", "from_email": "contact@triskell-studio.com", "is_primary": True},
    {"id": "lagriffe", "from_email": "contact@lagriffe-studio.fr"},
]

_passed = 0
_failed = 0


def check(label: str, cond: bool):
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        print(f"  ECHEC : {label}")


def iso(delta_hours: float) -> str:
    return (NOW - timedelta(hours=delta_hours)).isoformat()


# ---------------------------------------------------------------------------
# 1) Utilitaires purs
# ---------------------------------------------------------------------------
check("_domain_of extrait le domaine",
      MR._domain_of("Contact@Lagriffe-Studio.FR") == "lagriffe-studio.fr")
check("_domain_of vide -> ''", MR._domain_of("") == "")
check("_parse_ts naïf -> UTC",
      MR._parse_ts("2026-06-16T10:00:00").tzinfo is not None)

# ---------------------------------------------------------------------------
# 2) Attribution de l'historique à la bonne boîte
# ---------------------------------------------------------------------------
# Par adresse expéditrice (extra.from), même sans account_id.
rows = [{"ts": iso(2), "kind": "email_sent", "account_id": "",
         "from_email": "contact@lagriffe-studio.fr"}]
agg = MR.aggregate_for_accounts(rows, ACCOUNTS, now=NOW)
check("attribution par adresse expéditrice", agg["lagriffe"]["sent_24h"] == 1)
check("la boîte non concernée reste à 0", agg["primary"]["sent_24h"] == 0)

# Par identifiant (account_id) quand l'adresse manque.
rows = [{"ts": iso(2), "kind": "email_sent", "account_id": "lagriffe",
         "from_email": ""}]
agg = MR.aggregate_for_accounts(rows, ACCOUNTS, now=NOW)
check("attribution par identifiant", agg["lagriffe"]["sent_24h"] == 1)

# Ni adresse ni identifiant -> compte principal (jamais perdu).
rows = [{"ts": iso(2), "kind": "email_sent", "account_id": "", "from_email": ""}]
agg = MR.aggregate_for_accounts(rows, ACCOUNTS, now=NOW)
check("repli vers le compte principal", agg["primary"]["sent_24h"] == 1)

# Pas de double comptage : une ligne = une seule boîte.
total = sum(a["sent_24h"] for a in agg.values())
check("aucun double comptage", total == 1)

# Fenêtres 24h / 7j / 30j + jours actifs + premier envoi.
rows = [
    {"ts": iso(2),        "kind": "email_sent", "account_id": "lagriffe", "from_email": ""},
    {"ts": iso(48),       "kind": "email_sent", "account_id": "lagriffe", "from_email": ""},
    {"ts": iso(24 * 10),  "kind": "email_sent", "account_id": "lagriffe", "from_email": ""},
    {"ts": iso(24 * 80),  "kind": "email_sent", "account_id": "lagriffe", "from_email": ""},
    {"ts": iso(24 * 5),   "kind": "status_bounced",     "account_id": "lagriffe", "from_email": ""},
    {"ts": iso(24 * 5),   "kind": "reply_received",     "account_id": "lagriffe", "from_email": ""},
    {"ts": iso(24 * 5),   "kind": "status_unsubscribed","account_id": "lagriffe", "from_email": ""},
]
agg = MR.aggregate_for_accounts(rows, ACCOUNTS, now=NOW)
la = agg["lagriffe"]
check("fenêtre 24h", la["sent_24h"] == 1)
check("fenêtre 7j", la["sent_7d"] == 2)
check("fenêtre 30j", la["sent_30d"] == 3)
check("fenêtre complète", la["sent_window"] == 4)
check("rebonds 30j", la["bounces_30d"] == 1)
check("réponses 30j", la["replies_30d"] == 1)
check("désinscriptions 30j", la["unsub_30d"] == 1)
check("jours actifs 30j", la["active_days_30d"] == 3)
check("premier envoi daté", isinstance(la["first_seen"], datetime))

# ---------------------------------------------------------------------------
# 3) Verdicts honnêtes (classify)
# ---------------------------------------------------------------------------
FROIDE = {"sent_30d": 0, "sent_window": 0, "bounces_30d": 0, "replies_30d": 0,
          "unsub_30d": 0, "active_days_30d": 0, "first_seen": None}

v = MR.classify(dict(FROIDE), auth=None, warmup_age_days=None,
                history_ok=True, now=NOW)
check("0 envoi = froide (jamais 'chaude')", v["warmth"] == "froide")
check("froide -> libellé 'Jamais utilisée'", v["label"] == "Jamais utilisée")

# Boîte d'1-2 mois qui n'envoie pas, chauffe interne juste commencée -> en chauffe.
v = MR.classify(dict(FROIDE, sent_window=4, sent_30d=4,
                     first_seen=NOW - timedelta(days=8)),
                auth=None, warmup_age_days=8, history_ok=True, now=NOW)
check("chauffe non finie = en chauffe", v["warmth"] == "en_chauffe")
check("en chauffe -> pas 'établie'", v["status"] != "etablie")

# Vrai historique d'envoi -> établie.
v = MR.classify({"sent_30d": 150, "sent_window": 400, "bounces_30d": 1,
                 "replies_30d": 12, "unsub_30d": 0, "active_days_30d": 20,
                 "first_seen": NOW - timedelta(days=45)},
                auth=None, warmup_age_days=None, history_ok=True, now=NOW)
check("historique réel solide = établie", v["warmth"] == "etablie")

# Chauffe interne TERMINÉE -> établie même avec peu d'envois réels.
v = MR.classify(dict(FROIDE, sent_window=2, sent_30d=2,
                     first_seen=NOW - timedelta(days=2)),
                auth=None, warmup_age_days=30, history_ok=True, now=NOW)
check("chauffe terminée = établie", v["warmth"] == "etablie")

# Fort taux de rebond -> alerte qui prime sur tout.
v = MR.classify({"sent_30d": 100, "sent_window": 100, "bounces_30d": 10,
                 "replies_30d": 0, "unsub_30d": 0, "active_days_30d": 10,
                 "first_seen": NOW - timedelta(days=40)},
                auth=None, warmup_age_days=None, history_ok=True, now=NOW)
check("rebonds élevés = à risque", v["status"] == "risque")
check("à risque -> alerte rebond", v["bounce_alert"] is True)

# Authentification incomplète -> à corriger.
auth_ko = {"ok": True, "checks": [
    {"id": "spf", "label": "SPF", "ok": True},
    {"id": "dkim", "label": "DKIM", "ok": False},
    {"id": "dmarc", "label": "DMARC", "ok": True},
    {"id": "mx", "label": "Réception (MX)", "ok": True},
]}
v = MR.classify({"sent_30d": 150, "sent_window": 400, "bounces_30d": 0,
                 "replies_30d": 5, "unsub_30d": 0, "active_days_30d": 20,
                 "first_seen": NOW - timedelta(days=45)},
                auth=auth_ko, warmup_age_days=None, history_ok=True, now=NOW)
check("authentification incomplète = à corriger", v["status"] == "a_corriger")
check("tampons manquants listés", "DKIM" in v["auth_missing"])

# Lecture impossible -> 'non vérifié', jamais 'froide'.
v = MR.classify(dict(FROIDE), auth=None, warmup_age_days=None,
                history_ok=False, now=NOW)
check("base injoignable = non vérifié", v["warmth"] == "inconnu")
check("non vérifié -> pas 'froide'", v["status"] != "froide")

# Aucune phrase de verdict ne doit jamais affirmer « chaude » sans preuve.
for vv in (MR.classify(dict(FROIDE), history_ok=True, now=NOW),
           MR.classify(dict(FROIDE, sent_window=2, sent_30d=2,
                            first_seen=NOW - timedelta(days=3)),
                       warmup_age_days=5, history_ok=True, now=NOW)):
    check("pas de 'chaude' non prouvée", "chaud" not in vv["summary"].lower())

# ---------------------------------------------------------------------------
# 4) Docteur DNS réutilisé (résolveurs injectés, sans réseau)
# ---------------------------------------------------------------------------
def txt_ok(name: str):
    if name == "lagriffe-studio.fr":
        return ["v=spf1 include:_spf.ionos.com ~all"]
    if name == "_dmarc.lagriffe-studio.fr":
        return ["v=DMARC1; p=quarantine; rua=mailto:contact@lagriffe-studio.fr"]
    if name.startswith("google._domainkey."):
        return ["v=DKIM1; k=rsa; p=ABC"]
    return []


def any_ok(name: str, rtype: str):
    return rtype == "MX"


res = check_domain("lagriffe-studio.fr", txt_resolver=txt_ok, any_resolver=any_ok)
check("DNS complet -> 4/4", res.get("all_good") is True)

def txt_partiel(name: str):
    if name == "lagriffe-studio.fr":
        return ["v=spf1 ~all"]
    return []   # ni DMARC ni DKIM

res = check_domain("lagriffe-studio.fr", txt_resolver=txt_partiel,
                   any_resolver=lambda n, t: False)
check("DNS incomplet détecté", res.get("all_good") is False)
missing = [c["id"] for c in res["checks"] if not c["ok"]]
check("manques DNS repérés (dmarc/dkim/mx)",
      {"dmarc", "dkim", "mx"}.issubset(set(missing)))

# Branchement DNS incomplet -> verdict 'à corriger'.
v = MR.classify({"sent_30d": 150, "sent_window": 400, "bounces_30d": 0,
                 "replies_30d": 5, "unsub_30d": 0, "active_days_30d": 20,
                 "first_seen": NOW - timedelta(days=45)},
                auth=res, warmup_age_days=None, history_ok=True, now=NOW)
check("DNS incomplet -> à corriger", v["status"] == "a_corriger")

# ---------------------------------------------------------------------------
print("-" * 60)
print(f"Réputation des boîtes : {_passed} OK, {_failed} échec(s).")
sys.exit(1 if _failed else 0)
