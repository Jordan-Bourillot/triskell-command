# -*- coding: utf-8 -*-
"""Smoke SANS RÉSEAU : brouillons créateurs (source 'creator' dans Brouillons).

Teste le module creator_drafts (stockage shared_settings, mocké) + la logique
d'extraction d'email (handle ou notes). Ne touche ni Supabase ni SMTP.
Usage : python scripts/smoke_creator_drafts.py
"""
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK = 0
KO = 0


def check(label, cond):
    global OK, KO
    if cond:
        OK += 1
    else:
        KO += 1
        print("  KO :", label)


# --- Faux client Supabase : simule la table shared_settings (key/value) ----
class _FakeQuery:
    def __init__(self, store):
        self.store = store
        self._filt = {}
        self._upd = None
        self._ins = None
        self._sel = False

    def select(self, _cols):
        self._sel = True
        return self

    def update(self, vals):
        self._upd = vals
        return self

    def insert(self, row):
        self._ins = row
        return self

    def eq(self, k, v):
        self._filt[k] = v
        return self

    def limit(self, _n):
        return self

    def execute(self):
        class _R:
            pass
        r = _R()
        if self._sel:
            key = self._filt.get("key")
            r.data = ([{"value": self.store[key]}] if key in self.store else [])
        elif self._upd is not None:
            key = self._filt.get("key")
            if key in self.store:
                self.store[key] = self._upd.get("value")
                r.data = [{"key": key}]
            else:
                r.data = []
        elif self._ins is not None:
            self.store[self._ins["key"]] = self._ins["value"]
            r.data = [self._ins]
        else:
            r.data = []
        return r


class _FakeSb:
    def __init__(self):
        self.store = {}

    def table(self, _name):
        return _FakeQuery(self.store)

    def rpc(self, *_a, **_k):
        class _R:
            data = None
        return _R()


# --- 1) creator_drafts : queue / list / get / set_status -------------------
from triskell_command.integrations import creator_drafts as CD  # noqa: E402

sb = _FakeSb()
check("liste vide au départ", CD.list_all(sb) == [])

d = CD.queue(sb, "cr1", "Sujet test")
check("queue crée un brouillon pending", bool(d) and d.get("status") == "pending"
      and d.get("creator_id") == "cr1" and d.get("subject") == "Sujet test")
check("1 pending après queue", len(CD.list_all(sb, status="pending")) == 1)
check("get retrouve le brouillon", CD.get(sb, d["id"]) is not None)

d2 = CD.queue(sb, "cr1", "Nouveau sujet")
check("re-queue même créateur = 1 seul pending", len(CD.list_all(sb, status="pending")) == 1)
check("nouveau sujet pris en compte", CD.get(sb, d2["id"]).get("subject") == "Nouveau sujet")

CD.queue(sb, "cr2", "Autre")
check("2 créateurs = 2 pending", len(CD.list_all(sb, status="pending")) == 2)

check("set_status sent OK", CD.set_status(sb, d2["id"], "sent") is True)
check("cr1 n'est plus pending", not any(x["creator_id"] == "cr1" for x in CD.list_all(sb, status="pending")))
check("cr2 reste pending", len(CD.list_all(sb, status="pending")) == 1)
check("set_status id inconnu = False", CD.set_status(sb, "zzz", "rejected") is False)


# --- 2) extraction email (handle prioritaire, sinon notes) -----------------
def creator_email(row):
    h = (row.get("handle") or "").strip()
    if ("@" in h and " " not in h and not h.startswith("http")
            and "." in h.rsplit("@", 1)[-1]):
        return h
    m = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
                  row.get("notes") or "")
    return m.group(0) if m else ""


check("email = handle quand c'en est un",
      creator_email({"handle": "samouillee51@gmail.com"}) == "samouillee51@gmail.com")
check("handle = lien YT -> email pris dans notes",
      creator_email({"handle": "https://youtube.com/channel/x",
                     "notes": "Contact possible : aquaexotic@hotmail.com (boutique)."})
      == "aquaexotic@hotmail.com")
check("aucun email (PSX) -> vide",
      creator_email({"handle": "https://youtube.com/x", "notes": "formulaire / Facebook"}) == "")

print("\n=== smoke_creator_drafts : %d OK / %d KO ===" % (OK, KO))
sys.exit(1 if KO else 0)
