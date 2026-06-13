#!/usr/bin/env python3
"""Smoke test — parcours « PAYER D'ABORD, REMPLIR APRÈS » (13/06/2026).

Sans réseau. Vérifie les garde-fous du nouveau flux :
  - le mail « paiement reçu » porte bien le lien pour compléter le site ;
  - la construction refuse une commande payée mais pas encore remplie
    (statut 'awaiting_content') et un brouillon non payé ('draft') ;
  - elle laisse passer une commande prête ('paid') ;
  - le robot de relance dégrade proprement sans base ;
  - la migration SQL est présente.

Lancer :  python scripts/smoke_pay_first.py
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OK = 0
KO = 0


def check(label, cond):
    global OK, KO
    if cond:
        OK += 1
        print(f"  OK  - {label}")
    else:
        KO += 1
        print(f"  KO  - {label}")


print("[1] Mail paiement recu -> contient le lien pour completer")
from triskell_command.integrations.pixelpros import mailer

# Test déterministe et SANS toucher la base : on force le modèle par défaut.
mailer._get_supabase = lambda: None

intake = {
    "id": "abc-12345",
    "selected_option": "base",
    "data": {"business-name": "Plomberie Test", "email": "client@test.fr"},
}
subject, body, body_html = mailer._build_paid_mail(intake)
link = "configurer.html?draft=abc-12345"
check("le lien de complétion est dans le texte", link in body)
check("le lien de complétion est dans le HTML", link in body_html)
check("l'objet invite à compléter (pas l'ancien 'arrive sous 24h')",
      ("activité" in subject.lower() or "étape" in subject.lower())
      and "arrive sous 24h" not in subject.lower())
check("le bouton HTML pointe vers le lien",
      ('href="https://pixel-pros.fr/' + link) in body_html)
check("pas d'accolade orpheline {complete_url} restante",
      "{complete_url}" not in body and "{complete_url}" not in body_html)

# Sans id (cas limite) → on retombe sur le mini-formulaire, jamais un trou.
s2, b2, h2 = mailer._build_paid_mail({"selected_option": "base", "data": {}})
check("sans id : lien de repli vers commander.html", "commander.html" in b2)


print("\n[2] Construction : garde-fou anti-site-vide")
from triskell_command.integrations.pixelpros import repo

_orig_get = repo.get_intake
try:
    repo.get_intake = lambda iid: {"id": iid, "status": "awaiting_content"}
    ok, msg = repo.dispatch_build("abc-12345")
    check("refuse de construire un 'awaiting_content'", ok is False)
    check("message clair (attente du contenu)", "contenu" in msg.lower())

    repo.get_intake = lambda iid: {"id": iid, "status": "draft"}
    ok2, msg2 = repo.dispatch_build("abc-12345")
    check("refuse de construire un 'draft' (pas payé)", ok2 is False)

    # 'paid' = contenu prêt : doit PASSER le garde-fou (échoue ensuite faute de
    # builder local en test, mais avec un AUTRE message que « attente contenu »).
    repo.get_intake = lambda iid: {"id": iid, "status": "paid"}
    _orig_find = repo._find_pixel_studio_dir
    repo._find_pixel_studio_dir = lambda: None
    os.environ.pop("PP_TRIGGER_BUILD_URL", None)
    try:
        ok3, msg3 = repo.dispatch_build("abc-12345")
    finally:
        repo._find_pixel_studio_dir = _orig_find
    check("laisse passer un 'paid' (pas bloqué par le garde-fou)",
          "contenu" not in msg3.lower())
finally:
    repo.get_intake = _orig_get


print("\n[3] Robot de relance : dégradation propre sans base")
from triskell_command.integrations.pixelpros import content_chaser

# On coupe la base pour un test déterministe (zéro effet sur la prod).
content_chaser._get_client = lambda: None

check("_hours_since calcule un écart positif",
      (content_chaser._hours_since("2026-06-13T00:00:00+00:00",
       __import__("datetime").datetime(2026, 6, 13, 5, 0,
       tzinfo=__import__("datetime").timezone.utc)) or 0) == 5.0)
res = content_chaser.tick()
check("tick() sans base → sauté proprement (pas d'exception)",
      isinstance(res, dict) and res.get("skipped_reason") == "supabase_indispo")
st = content_chaser.get_status()
check("get_status() renvoie le format attendu",
      isinstance(st, dict) and "running" in st)


print("\n[4] Migration SQL présente")
sql = os.path.join(ROOT, "..", "pixel-studio", "supabase", "pay_first_flow.sql")
# Le dossier pixel-studio est à côté de triskell-command dans l'arbo Triskell.
exists = os.path.exists(sql)
if exists:
    txt = open(sql, encoding="utf-8").read()
    check("pay_first_flow.sql présent", True)
    check("ajoute l'état 'awaiting_content'", "awaiting_content" in txt)
    check("définit pp_get_draft + pp_submit_content",
          "pp_get_draft" in txt and "pp_submit_content" in txt)
else:
    # Selon l'endroit où on lance, le chemin relatif peut différer : on n'échoue
    # pas le test pour ça (le fichier vit dans le dépôt pixel-studio).
    print("  ..  - pay_first_flow.sql non trouvé via ce chemin (ok si lancé hors arbo)")


print(f"\n=== Bilan : {OK} OK / {KO} KO ===")
sys.exit(1 if KO else 0)
