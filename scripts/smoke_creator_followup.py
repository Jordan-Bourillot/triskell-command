# -*- coding: utf-8 -*-
"""Smoke SANS RÉSEAU : robot de relances créateurs (creator_followup).

Teste la LOGIQUE PURE du module (aucun IMAP, aucun Supabase, aucun push) :
- extraction du prénom (greet) pour des noms variés ;
- rendu du corps de relance (bon demo_url, pas de tiret cadratin, etc.) ;
- décision « faut-il relancer ? » selon contacted_at / next_follow_up_at /
  réponse / déjà-relancé ;
- aiguillage Email vs Instagram/TikTok.

Usage : python scripts/smoke_creator_followup.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

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


from triskell_command.integrations import creator_followup as CF  # noqa: E402


# --- 1) Extraction du prénom (greet) ---------------------------------------
check("marque sans prénom gardée entière (Mamie Crochet)",
      CF.creator_greet("Mamie Crochet") == "Mamie Crochet")
check("parenthèses : pseudo (Marie) -> Marie",
      CF.creator_greet("hibouchoucaillou (Marie)") == "Marie")
check("parenthèses : 1er mot du contenu (Julie Pointurier) -> Julie",
      CF.creator_greet("Atelier des Premières (Julie Pointurier)") == "Julie")
check("nom simple -> 1er mot (Éloïse Dubois -> Éloïse)",
      CF.creator_greet("Éloïse Dubois") == "Éloïse")
check("prénom seul -> lui-même",
      CF.creator_greet("Kevin") == "Kevin")
check("vide -> vide",
      CF.creator_greet("") == "")
check("espaces autour -> nettoyé",
      CF.creator_greet("  Marie  ") == "Marie")
check("ponctuation collée nettoyée (Marie, -> Marie)",
      CF.creator_greet("Marie, créatrice") == "Marie")
check("parenthèses prioritaires sur le pseudo de tête",
      CF.creator_greet("super_pseudo (Thomas B.)") == "Thomas")
check("marque 'Atelier ...' sans parenthèses gardée entière",
      CF.creator_greet("Atelier du Fil") == "Atelier du Fil")


# --- 2) Rendu du corps de relance ------------------------------------------
body = CF.render_followup_body("Marie", "https://demo.triskell/club/marie")
check("corps contient le bon demo_url",
      "https://demo.triskell/club/marie" in body)
check("corps commence par 'Coucou Marie !'",
      body.startswith("Coucou Marie !"))
check("corps SANS tiret cadratin —", "—" not in body)
check("corps SANS 'sans pression'", "sans pression" not in body.lower())
check("corps SANS impératif 'réponds'/'répondez'",
      "réponds" not in body.lower() and "répondez" not in body.lower())
check("corps SANS appel téléphonique",
      "appel" not in body.lower() and "téléphone" not in body.lower()
      and "appelle" not in body.lower())

body_noname = CF.render_followup_body("", "https://x.fr/c")
check("sans prénom -> 'Coucou !' (pas 'Coucou  !')",
      body_noname.startswith("Coucou !"))
check("sujet relance court et léger",
      CF.followup_subject() == "Je reviens vers toi :)")


# --- 3) Aiguillage par plateforme ------------------------------------------
check("Email -> email", CF.route_creator("Email") == "email")
check("email minuscule -> email", CF.route_creator("email") == "email")
check("Instagram -> social", CF.route_creator("Instagram") == "social")
check("TikTok -> social", CF.route_creator("TikTok") == "social")
check("tiktok minuscule -> social", CF.route_creator("tiktok") == "social")
check("YouTube -> ignore", CF.route_creator("YouTube") == "ignore")
check("vide -> ignore", CF.route_creator("") == "ignore")


# --- 4) Décision « faut-il relancer ? » ------------------------------------
now = datetime(2026, 6, 19, 12, 0, 0, tzinfo=timezone.utc)
past = (now - timedelta(days=1)).isoformat()      # échéance dépassée
future = (now + timedelta(days=3)).isoformat()    # échéance pas encore là
contacted = (now - timedelta(days=8)).isoformat()

check("relance OK : contacté + échéance passée + jamais relancé",
      CF.should_relance(
          {"id": "a", "contacted_at": contacted, "next_follow_up_at": past},
          now, set()) is True)

check("PAS de relance si jamais contacté",
      CF.should_relance(
          {"id": "b", "contacted_at": "", "next_follow_up_at": past},
          now, set()) is False)

check("PAS de relance si échéance dans le futur",
      CF.should_relance(
          {"id": "c", "contacted_at": contacted, "next_follow_up_at": future},
          now, set()) is False)

check("PAS de relance si échéance vide (= a répondu / déjà traité)",
      CF.should_relance(
          {"id": "d", "contacted_at": contacted, "next_follow_up_at": None},
          now, set()) is False)

check("PAS de relance si déjà relancé (id mémorisé)",
      CF.should_relance(
          {"id": "e", "contacted_at": contacted, "next_follow_up_at": past},
          now, {"e"}) is False)

check("PAS de relance si next illisible",
      CF.should_relance(
          {"id": "f", "contacted_at": contacted, "next_follow_up_at": "pas une date"},
          now, set()) is False)

check("échéance pile maintenant -> relance (>=)",
      CF.should_relance(
          {"id": "g", "contacted_at": contacted, "next_follow_up_at": now.isoformat()},
          now, set()) is True)


# --- 5) Parsing de dates robuste -------------------------------------------
check("parse ISO avec Z",
      CF._parse_dt("2026-06-19T12:00:00Z") is not None)
check("parse ISO avec offset",
      CF._parse_dt("2026-06-19T12:00:00+00:00") is not None)
check("parse date seule",
      CF._parse_dt("2026-06-19") is not None)
check("parse None -> None", CF._parse_dt(None) is None)
check("parse vide -> None", CF._parse_dt("") is None)
check("parse texte -> None", CF._parse_dt("bonjour") is None)
check("naïf vs aware ne plante pas",
      CF.should_relance(
          {"id": "h", "contacted_at": contacted,
           "next_follow_up_at": "2026-06-18T00:00:00"},
          now, set()) is True)


print("\n=== smoke_creator_followup : %d OK / %d KO ===" % (OK, KO))
sys.exit(1 if KO else 0)
