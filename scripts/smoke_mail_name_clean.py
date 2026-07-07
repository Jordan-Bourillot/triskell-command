"""Contrôles : noms d'entreprise nettoyés dans les mails + alerte crédit IA.

Sans réseau. Verrouille :
  - clean_business_name coupe les noms à rallonge / tiret-métier / CAPITALES
    et préserve les noms déjà corrects.
  - convoy_ai._clean_prospect_name applique bien ce nettoyage à la raison sociale.
  - ai_health reconnaît un épuisement de crédit et ignore les autres erreurs.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ok = _ko = 0
def check(label, cond):
    global _ok, _ko
    if cond:
        _ok += 1; print(f"  OK   {label}")
    else:
        _ko += 1; print(f"  ÉCHEC {label}")


from triskell_command.integrations.apercu_site import clean_business_name as C

print("— Nettoyage des noms d'entreprise —")
# coupe les cas signalés par Jordan
check("tiret + métier coupé", C("Karen Signour - Coiffeuse à Domicile") == "Karen Signour")
check("liste à virgules coupée",
      C("Artisan Boulanger, Pâtissier, Sandwicherie & Petite Restauration.") == "Artisan Boulanger")
check("CAPITALES -> casse naturelle",
      C("BISCUITERIE DES KORRIGANS") == "Biscuiterie des Korrigans")
check("deux-points + descriptif + CAPITALES",
      C("FABBI PATRICK PEINTURE: Artisan peintre en bâtiment Rénovation") == "Fabbi Patrick Peinture")
check("parenthèse finale retirée",
      C("Institut Embellia (Deguilhem Delphine)") == "Institut Embellia")
check("point final retiré", not C("Truc Machin.").endswith("."))
# préserve les noms corrects
check("nom mixte préservé", C("NLC coiffure") == "NLC coiffure")
check("tiret collé préservé", C("Jean-Pierre Machin") == "Jean-Pierre Machin")
check("apostrophe préservée", C("L'Atelier Créatif Bois") == "L'Atelier Créatif Bois")
check("esperluette préservée", C("JR Peinture & Façades") == "JR Peinture & Façades")
check("sigle court intact", C("YC") == "YC")
check("forme juridique jamais isolée", C("SARL: Boulangerie Martin") != "SARL")
check("vide -> vide", C("") == "")

print("— Branchement génération mail —")
from triskell_command.integrations.convoy_ai import _clean_prospect_name as clean_p
p = clean_p({"raison_sociale": "BISCUITERIE DES KORRIGANS", "ville": "Concarneau"})
check("raison_sociale nettoyée dans le prospect", p["raison_sociale"] == "Biscuiterie des Korrigans")
check("autres champs préservés", p.get("ville") == "Concarneau")
p2 = clean_p({"ville": "X"})
check("prospect sans nom -> pas de plantage", p2.get("ville") == "X")

print("— Alerte crédit IA —")
from triskell_command.integrations import ai_health as A
check("Anthropic 'credit balance too low' détecté",
      A.looks_like_credit_exhausted("Your credit balance is too low to access the Anthropic API"))
check("OpenAI insufficient_quota détecté",
      A.looks_like_credit_exhausted("Error: insufficient_quota"))
check("quota exceeded détecté",
      A.looks_like_credit_exhausted("You exceeded your current quota"))
check("timeout NON pris pour un crédit vide",
      not A.looks_like_credit_exhausted("Timeout: connection reset by peer"))
check("modèle invalide NON pris pour un crédit vide",
      not A.looks_like_credit_exhausted("invalid model name claude-x"))
check("statut par défaut = ok quand pas de base",
      A.ai_credit_status(client=None).get("active") is False)

print(f"\n{_ok} OK / {_ko} échec(s)")
sys.exit(1 if _ko else 0)
