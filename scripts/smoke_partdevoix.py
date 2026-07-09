# -*- coding: utf-8 -*-
"""Batterie « vérité » du module La Part de Voix. Sans réseau, < 10 s.

  python scripts/smoke_partdevoix.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from triskell_command.integrations.partdevoix import (  # noqa: E402
    audit, moteur, pilote)

OK = 0
KO = 0


def check(nom, condition):
    global OK, KO
    if condition:
        OK += 1
        print(f"  ok  {nom}")
    else:
        KO += 1
        print(f"  KO  {nom}")


def fausse_mesure():
    """Une mesure réaliste sans réseau : 6 réponses valides."""
    runs = [
        {"question": "q1", "provider": "openai", "ok": True,
         "reponse": "Je recommande le Cabinet Durand et Le Goff Assurances.",
         "cites": ["Cabinet Durand", "Le Goff Assurances"]},
        {"question": "q1", "provider": "perplexity", "ok": True,
         "reponse": "Durand est bien noté. Aussi Le Goff.",
         "cites": ["Durand Assurances", "Le Goff Assurances"]},
        {"question": "q1", "provider": "google", "ok": True,
         "reponse": "Le Cabinet Durand revient souvent.",
         "cites": ["Cabinet Durand", "Cabinet Durand"]},
        {"question": "q2", "provider": "openai", "ok": True,
         "reponse": "Le Goff Assurances est cité par plusieurs sources.",
         "cites": ["Le Goff Assurances"]},
        {"question": "q2", "provider": "perplexity", "ok": True,
         "reponse": "Pas de nom précis à donner.", "cites": []},
        {"question": "q2", "provider": "google", "ok": True,
         "reponse": "Voyez les Pages Jaunes.", "cites": []},
        {"question": "q2", "provider": "openai", "ok": False,
         "reponse": "", "cites": []},
    ]
    return {"runs": runs, "ts": "2026-07-08T12:00:00+00:00",
            "nb_reponses": 6}


print("— normalisation et correspondance")
check("normaliser accents/casse",
      moteur.normaliser("Cabinet DURAND & Fils") == "cabinet durand fils")
check("correspond inclusion",
      moteur.correspond("Cabinet Durand", "Durand Assurances Rennes"))
check("correspond jeton distinctif",
      moteur.correspond("Le Goff Assurances", "Assurances Le Goff"))
check("pas de correspondance générique",
      not moteur.correspond("Cabinet Martin", "Cabinet Petit"))
check("pas de correspondance vide",
      not moteur.correspond("", "Cabinet Petit"))

print("— agrégation de part de voix")
m = fausse_mesure()
ag = moteur.agreger(m)
durand = next((g for g in ag if moteur.correspond("Cabinet Durand", g["nom"])), None)
legoff = next((g for g in ag if moteur.correspond("Le Goff Assurances", g["nom"])), None)
check("Durand fusionné (2 libellés voisins)", durand is not None)
check("Durand cité 3 réponses sur 6 = 50 %",
      durand and durand["part"] == 50.0)
check("double citation même réponse comptée une fois",
      durand and durand["occurrences"] == 3)
check("Le Goff 50 %", legoff and legoff["part"] == 50.0)
check("part_de retrouve le prospect",
      moteur.part_de("Durand Assurances", ag) == 50.0)
check("part_de absent = 0",
      moteur.part_de("Cabinet Inconnu", ag) == 0.0)
check("agreger mesure vide = []", moteur.agreger({"runs": []}) == [])

print("— classement en 3 issues")
check("déjà cité", audit.classer(30.0, ag, "Cabinet Durand") == "deja_cite")
check("concurrents cités",
      audit.classer(0.0, ag, "Cabinet Nouveau") == "concurrents")
check("place vide", audit.classer(0.0, [], "Cabinet Nouveau") == "vide")

print("— questions par segment")
check("courtier reconnu",
      "courtier" in audit.questions_pour("Courtier en assurance", "Rennes")[0])
check("expert-comptable reconnu",
      "expert-comptable" in audit.questions_pour("cabinet d'expertise comptable", "Metz")[0])
check("immobilier reconnu",
      "immobilière" in audit.questions_pour("agence immobilière", "Pau")[0])
check("avocat reconnu",
      "avocat" in audit.questions_pour("Avocat droit du travail", "Lyon")[0])
check("métier inconnu = gabarit générique avec la ville",
      "Quimper" in audit.questions_pour("ostéopathe", "Quimper")[0])
check("3 formulations par segment",
      len(audit.questions_pour("courtier", "Rennes")) == 3)

print("— génération d'audit sans réseau (mesure injectée)")
a = audit.generer_audit("Cabinet Nouveau", "courtier", "Rennes",
                        passes=2, cles={}, mesure=fausse_mesure())
check("issue concurrents", a["issue"] == "concurrents")
check("3 concurrents max", len(a["concurrents"]) <= 3)
check("extraits présents", len(a["extraits"]) >= 1)
check("extraits bornés à ~420 caractères",
      all(len(x["texte"]) <= 430 for x in a["extraits"]))

print("— page HTML")
import re as _re  # noqa: E402
page = audit.rendre_html(a)
page_plate = _re.sub(r"\s+", " ", page.lower())
texte_visible = _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", page).lower())
check("le nom du prospect figure", "cabinet nouveau" in page_plate)
check("mention de variabilité obligatoire",
      "vos propres essais peuvent différer" in page_plate)
check("méthode affichée (passages)", "passages par question" in page_plate)
check("aucune promesse de citation",
      "garantie de citation" not in texte_visible
      and "vous serez cité" not in texte_visible)
check("le mot robot n'apparaît pas dans le texte visible",
      "robot" not in texte_visible)
check("pas de balise non fermée évidente",
      page.count("<div") == page.count("</div>"))
check("échappement HTML des noms",
      "Cabinet <script>" not in audit.rendre_html(
          dict(a, entreprise="Cabinet <script>")))

print("— enregistrement")
with tempfile.TemporaryDirectory() as tmp:
    fichiers = audit.enregistrer(a, tmp)
    check("HTML écrit", Path(fichiers["html"]).exists())
    check("JSON écrit",
          Path(fichiers["html"]).with_suffix(".json").exists())
    check("jeton non devinable dans le nom",
          len(Path(fichiers["html"]).stem.rsplit("-", 1)[-1]) >= 6)
    donnees = json.loads(Path(fichiers["html"]).with_suffix(".json")
                         .read_text(encoding="utf-8"))
    check("JSON relisible", donnees["entreprise"] == "Cabinet Nouveau")

print("— extraction (sans clé = refus propre)")
check("pas de clé anthropic = liste vide",
      moteur.extraire_noms("q", "réponse", {}) == [])
check("réponse vide = liste vide",
      moteur.extraire_noms("q", "", {"anthropic": "x"}) == [])

print("— pilote")
check("panel : cibles ET témoins",
      {e["role"] for e in pilote.PANEL} == {"cible", "temoin"})
check("panel : ids uniques",
      len({e["id"] for e in pilote.PANEL}) == len(pilote.PANEL))
check("résumé sans historique ne plante pas",
      isinstance(pilote.resume(), str))

print("— aiguillage par offre (moteur d'envoi)")
from triskell_core.prospect.pipeline import (  # noqa: E402
    PARTDEVOIX_PRODUCT, _offer_product_for, _partdevoix_segment)


class _Fiche:
    def __init__(self, industry, website=""):
        self.industry = industry
        self.website = website


check("segment courtier", _partdevoix_segment("Courtier en assurance") == "courtier")
check("segment comptable", _partdevoix_segment("cabinet d'expertise comptable") == "comptable")
check("segment avocat", _partdevoix_segment("Avocat droit des affaires") == "avocat")
check("segment immo", _partdevoix_segment("Agence immobilière") == "immo")
check("plombier hors offre", _partdevoix_segment("plombier chauffagiste") == "")
check("diagnostiqueur immobilier hors offre (faux ami)",
      _partdevoix_segment("diagnostic immobilier") == "")
check("diagnostiqueur DPE hors offre",
      _partdevoix_segment("diagnostiqueur DPE") == "")
check("courtier en travaux hors offre (faux ami)",
      _partdevoix_segment("courtier en travaux") == "")
check("courtier en énergie hors offre",
      _partdevoix_segment("courtier en énergie") == "")
check("courtier AVEC site -> Part de Voix",
      _offer_product_for(_Fiche("courtier", "https://x.fr")) == PARTDEVOIX_PRODUCT)
check("courtier SANS site -> offres sites",
      _offer_product_for(_Fiche("courtier", "")) == "")
check("immo AVEC site -> Part de Voix",
      _offer_product_for(_Fiche("agence immobilière", "https://x.fr"))
      == PARTDEVOIX_PRODUCT)
check("plombier AVEC site -> jamais Part de Voix",
      _offer_product_for(_Fiche("plombier", "https://x.fr")) == "")
check("fiche sans métier -> jamais Part de Voix",
      _offer_product_for(_Fiche("", "https://x.fr")) == "")

print("— index des liens d'audit")
from triskell_command.integrations.partdevoix import liens as _liens  # noqa: E402
_vrai_fichier = _liens.FICHIER
try:
    with tempfile.TemporaryDirectory() as tmp:
        _liens.FICHIER = Path(tmp) / "liens.json"
        _liens.enregistrer_lien("a@b.fr", "Cabinet Durand", "Rennes",
                                "https://lapartdevoix.fr/audits/x.html", "concurrents")
        check("lien retrouvé par mail",
              _liens.audit_url_for(email="A@B.FR").endswith("x.html"))
        check("lien retrouvé par entreprise+ville",
              _liens.audit_url_for(entreprise="Durand Assurances",
                                   ville="rennes").endswith("x.html"))
        check("fiche inconnue = vide (repli géré par l'appelant)",
              _liens.audit_url_for(email="inconnu@x.fr") == "")
        _liens.enregistrer_lien("a@b.fr", "Cabinet Durand", "Rennes",
                                "https://lapartdevoix.fr/audits/y.html", "vide")
        check("nouvel audit écrase l'ancien",
              _liens.audit_url_for(email="a@b.fr").endswith("y.html"))
        check("issue retrouvée par mail",
              _liens.issue_for(email="a@b.fr") == "vide")
        check("issue d'une fiche sans audit = vide (=> saut du prospect)",
              _liens.issue_for(email="inconnu@x.fr") == "")
finally:
    _liens.FICHIER = _vrai_fichier

print("— aiguillage par issue d'audit")
from triskell_core.prospect.pipeline import _filtrer_par_issue  # noqa: E402

_modeles = [{"key": "lpv_commerce_immo_a"}, {"key": "lpv_commerce_immo_b"},
            {"key": "lpv_commerce_immo_deja"}, {"key": "lpv_commerce_immo_vide"}]
check("issue concurrents -> les modèles sans marqueur (objets A et B)",
      [t["key"] for t in _filtrer_par_issue(_modeles, "concurrents")]
      == ["lpv_commerce_immo_a", "lpv_commerce_immo_b"])
check("issue déjà cité -> uniquement le modèle _deja",
      [t["key"] for t in _filtrer_par_issue(_modeles, "deja_cite")]
      == ["lpv_commerce_immo_deja"])
check("issue place vide -> uniquement le modèle _vide",
      [t["key"] for t in _filtrer_par_issue(_modeles, "vide")]
      == ["lpv_commerce_immo_vide"])
check("issue déjà cité sans modèle _deja -> liste vide (=> saut, jamais le mauvais mail)",
      _filtrer_par_issue([{"key": "lpv_commerce_immo_a"}], "deja_cite") == [])

print()
print(f"{OK} ok, {KO} KO")
sys.exit(1 if KO else 0)
