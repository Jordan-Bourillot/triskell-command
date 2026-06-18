# -*- coding: utf-8 -*-
"""Smoke test du tri + alertes des mails entrants (18/06/2026).

Demande Jordan : « que TOUS les mails reçus soient lus et triés par l'IA,
même ceux des gens pas encore dans ma liste, et que je sois prévenu à chaque
fois qu'un mail mérite mon attention. »

Vérifie SANS réseau et SANS toucher au vrai état :
  1. Config : valeurs par défaut, fusion d'un réglage partiel, garde-fous.
  2. attention_for_reply : intéressé = alerte forte ; non/désinscription =
     pas d'alerte (géré tout seul) ; pas-maintenant/inconnu = alerte normale.
  3. Seuils : priority_rank / passes_threshold / push_priority.
  4. should_notify : coupé, attention=False, interrupteurs inconnus/réponses,
     seuil de priorité.
  5. Repli sans IA (_fallback_triage) : on alerte quand même (mieux vaut un
     mail de trop), résumé = sujet.
  6. Nettoyage d'une sortie IA bancale (_normalize_triage).
  7. triage_stranger_mail sans clé IA → repli (aucun appel réseau).
  8. Textes d'alerte (build_reply_push / build_stranger_push).
  9. Endpoints get/save config via Api() (sans base = valeurs par défaut).

Usage :  python scripts/smoke_inbox_triage.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
CORE = HERE.parent / "triskell-core"
if CORE.exists():
    sys.path.insert(0, str(CORE))

# Console Windows = cp1252 par défaut → planterait sur « → » / emojis.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'OK  ' if cond else 'FAIL'}- {label} {detail if not cond else ''}")


from triskell_command.integrations import inbox_triage as IT  # noqa: E402


# Client factice : un simple dictionnaire en mémoire (zéro réseau).
class FakeClient:
    def __init__(self, store=None):
        self.store = dict(store or {})

    def get_shared_setting(self, key, default=None):
        return self.store.get(key, default)

    def set_shared_setting(self, key, value):
        self.store[key] = value


print("\n=== 1. Config : défauts + fusion partielle + garde-fous ===")
c = FakeClient()
cfg = IT.load_config(c)
check("défaut activé", cfg["enabled"] is True)
check("défaut alerte inconnus", cfg["notify_strangers"] is True)
check("défaut alerte réponses", cfg["notify_prospect_replies"] is True)
check("défaut seuil normal", cfg["min_priority"] == "normal")
check("défaut cible jordan", cfg["notify_user_id"] == "jordan")

# Réglage partiel : on ne pose qu'un champ, le reste garde le défaut.
c2 = FakeClient({"inbox_triage": {"notify_strangers": False}})
cfg2 = IT.load_config(c2)
check("fusion : champ posé respecté", cfg2["notify_strangers"] is False)
check("fusion : reste au défaut", cfg2["enabled"] is True)

# Valeur de seuil invalide → ramenée à normal.
c3 = FakeClient({"inbox_triage": {"min_priority": "n'importe quoi"}})
check("garde-fou seuil invalide", IT.load_config(c3)["min_priority"] == "normal")

# Config stockée en texte JSON (cas réel possible) → relue proprement.
c4 = FakeClient({"inbox_triage": '{"enabled": false}'})
check("config en texte JSON relue", IT.load_config(c4)["enabled"] is False)

# save_config écrit bien dans le store.
IT.save_config(c, {"enabled": False, "min_priority": "high"})
check("save_config écrit", c.store["inbox_triage"]["enabled"] is False)


print("\n=== 2. attention_for_reply (déterministe, zéro IA) ===")
a_int = IT.attention_for_reply("interested", 0.9)
check("intéressé = attention", a_int["attention"] is True)
check("intéressé = priorité haute", a_int["priority"] == "high")
check("pas-maintenant = attention normale",
      IT.attention_for_reply("not_now")["priority"] == "normal"
      and IT.attention_for_reply("not_now")["attention"] is True)
check("inconnu (réponse) = attention normale",
      IT.attention_for_reply("unknown")["attention"] is True)
check("non merci = PAS d'alerte",
      IT.attention_for_reply("no")["attention"] is False)
check("désinscription = PAS d'alerte",
      IT.attention_for_reply("unsubscribe")["attention"] is False)
check("catégorie inconnue = pas d'alerte",
      IT.attention_for_reply("")["attention"] is False)


print("\n=== 3. Seuils de priorité ===")
check("rang low<normal<high",
      IT.priority_rank("low") < IT.priority_rank("normal") < IT.priority_rank("high"))
check("seuil normal laisse passer high",
      IT.passes_threshold("high", "normal") is True)
check("seuil normal bloque low",
      IT.passes_threshold("low", "normal") is False)
check("seuil high bloque normal",
      IT.passes_threshold("normal", "high") is False)
check("push: high→urgent", IT.push_priority("high") == "urgent")
check("push: normal→normal", IT.push_priority("normal") == "normal")
check("push: low→low", IT.push_priority("low") == "low")


print("\n=== 4. should_notify (règle d'alerte centralisée) ===")
on = dict(IT.DEFAULT_CONFIG)
check("coupé → jamais d'alerte",
      IT.should_notify({**on, "enabled": False}, is_stranger=True,
                       attention=True, priority="high") is False)
check("attention=False → pas d'alerte",
      IT.should_notify(on, is_stranger=True, attention=False,
                       priority="high") is False)
check("inconnu + interrupteur inconnus coupé → non",
      IT.should_notify({**on, "notify_strangers": False}, is_stranger=True,
                       attention=True, priority="high") is False)
check("réponse + interrupteur réponses coupé → non",
      IT.should_notify({**on, "notify_prospect_replies": False},
                       is_stranger=False, attention=True, priority="high") is False)
check("priorité sous le seuil → non",
      IT.should_notify({**on, "min_priority": "high"}, is_stranger=True,
                       attention=True, priority="normal") is False)
check("cas nominal intéressé → oui",
      IT.should_notify(on, is_stranger=False, attention=True,
                       priority="high") is True)
check("inconnu important → oui",
      IT.should_notify(on, is_stranger=True, attention=True,
                       priority="normal") is True)


print("\n=== 5. Repli sans IA ===")
fb = IT._fallback_triage("Demande de devis", "Bonjour, j'aimerais un site.")
check("repli alerte quand même", fb["attention"] is True)
check("repli priorité normale", fb["priority"] == "normal")
check("repli résumé = sujet", fb["summary"] == "Demande de devis")
fb2 = IT._fallback_triage("", "Première ligne du corps\nDeuxième ligne")
check("repli sans sujet → 1re ligne du corps",
      fb2["summary"] == "Première ligne du corps")


print("\n=== 6. Nettoyage d'une sortie IA bancale ===")
n = IT._normalize_triage(
    {"attention": "true", "priority": "ULTRA", "category": "X" * 99,
     "summary": "  ok  ", "reason": "r"},
    subject="S", body="B")
check("attention texte 'true' → bool", n["attention"] is True)
check("priorité inconnue → normal", n["priority"] == "normal")
check("catégorie tronquée à 40", len(n["category"]) <= 40)
check("résumé nettoyé", n["summary"] == "ok")
n2 = IT._normalize_triage("pas un dict", subject="S", body="B")
check("entrée non-dict → repli sûr", n2["attention"] is True)


print("\n=== 7. triage_stranger_mail sans clé IA (aucun réseau) ===")
t = IT.triage_stranger_mail({}, from_addr="x@y.fr", subject="Coucou", body="Salut")
check("sans IA → repli", t["attention"] is True and t["category"] == "à voir")
t2 = IT.triage_stranger_mail({"provider": "", "api_key": ""},
                             from_addr="x@y.fr", subject="S", body="B")
check("provider/clé vides → repli", t2["reason"].startswith("pas d'IA"))


print("\n=== 8. Textes d'alerte ===")
ti, bo = IT.build_reply_push(display_name="Boulangerie Paul",
                             category="interested", subject="Re: votre site")
check("réponse intéressé → 🔥", ti.startswith("🔥"))
check("réponse : nom dans le corps", "Boulangerie Paul" in bo)
ti2, bo2 = IT.build_reply_push(display_name="", category="not_now",
                              subject="Plus tard")
check("réponse pas-maintenant → 📨", ti2.startswith("📨"))
ti3, bo3 = IT.build_stranger_push(
    from_addr="marie.dupont@gmail.com",
    triage={"category": "question", "summary": "Veut un devis"})
check("inconnu : titre = catégorie", "Question" in ti3)
check("inconnu : expéditeur lisible dans le corps", "marie dupont" in bo3)
check("inconnu : résumé dans le corps", "Veut un devis" in bo3)


print("\n=== 9. Endpoints API (lecture seule — on ne touche PAS la prod) ===")
# ⚠️ Sur la machine de Jordan, l'app est branchée sur la base de PROD.
# On NE teste donc PAS save_config ici (il écrirait en vrai). On vérifie
# juste que les endpoints existent et que get_config renvoie une config
# bien formée (lecture sans effet de bord).
from triskell_command.web.api import Api  # noqa: E402
api = Api()
check("endpoint get_config existe", callable(getattr(api, "inbox_triage_get_config", None)))
check("endpoint save_config existe", callable(getattr(api, "inbox_triage_save_config", None)))
r = api.inbox_triage_get_config()
check("get_config répond ok", r.get("ok") is True)
expected_keys = set(IT.DEFAULT_CONFIG.keys())
check("get_config : toutes les clés présentes",
      expected_keys.issubset(set((r.get("config") or {}).keys())))


print(f"\n{'='*52}")
print(f"  RÉSULTAT : {len(PASS)} OK, {len(FAIL)} FAIL")
if FAIL:
    print("  Échecs :")
    for f in FAIL:
        print(f"    - {f}")
print(f"{'='*52}")
sys.exit(1 if FAIL else 0)
