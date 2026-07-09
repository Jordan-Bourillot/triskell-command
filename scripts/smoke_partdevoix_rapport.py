# -*- coding: utf-8 -*-
"""Batterie « vérité » du rapport mensuel Porte-Voix. Sans réseau, < 10 s.

  python scripts/smoke_partdevoix_rapport.py
"""
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from triskell_command.integrations.partdevoix import (  # noqa: E402
    clients, rapport, rapporteur, stockage)

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


def leve(fonction):
    """Vrai si l'appel refuse proprement (ValueError)."""
    try:
        fonction()
        return False
    except ValueError:
        return True


def mesure_ou(citations, total=6, ts="2026-07-01T10:00:00+00:00"):
    """Fabrique une mesure du moteur sans réseau : {nom: nombre de
    réponses valides qui le citent} sur `total` réponses."""
    runs = []
    for i in range(total):
        cites = [nom for nom, nb in citations.items() if i < nb]
        runs.append({
            "question": "quel courtier choisir à Rennes ?",
            "provider": "openai" if i % 2 == 0 else "google",
            "ok": True,
            "reponse": ("Je citerais " + ", ".join(cites) + "."
                        if cites else "Aucun nom précis à donner."),
            "cites": cites,
        })
    return {"runs": runs, "ts": ts, "nb_reponses": total}


# Tout le smoke travaille en mode fichier seul, sur un dossier
# temporaire : jamais la base partagée, jamais les vrais fichiers.
_tmp = tempfile.TemporaryDirectory()
_vrais_fichiers = dict(stockage.FICHIERS)
_vrai_mode = stockage.MODE_FICHIER_SEUL
stockage.MODE_FICHIER_SEUL = True
stockage.FICHIERS = {nom: Path(_tmp.name) / f"{nom}.json"
                     for nom in _vrais_fichiers}

try:
    print("— registre : ajout")
    check("registre vide au départ", clients.lister_clients() == [])
    c1 = clients.ajouter_client(
        "Cabinet Durand", "courtier en assurance", "Rennes",
        concurrents=["Le Goff Assurances", "Agence Kermarrec"],
        palier="essentiel")
    check("ajout : id posé", bool(c1.get("id")))
    check("ajout : ville normalisée en liste", c1["villes"] == ["Rennes"])
    check("ajout : date d'entrée posée (AAAA-MM-JJ)",
          len(c1.get("entree_le") or "") == 10)
    check("lister retrouve le client",
          [x["id"] for x in clients.lister_clients()] == [c1["id"]])

    print("— registre : garde-fous")
    check("doublon refusé (même entreprise au sens large)",
          leve(lambda: clients.ajouter_client(
              "Durand Assurances", "courtier", "Brest")))
    check("plus de 3 concurrents refusé",
          leve(lambda: clients.ajouter_client(
              "Autre Cabinet", "courtier", "Brest",
              concurrents=["A1", "B2", "C3", "D4"])))
    check("entreprise vide refusée",
          leve(lambda: clients.ajouter_client("", "courtier", "Brest")))
    check("ville manquante refusée",
          leve(lambda: clients.ajouter_client("Sans Ville", "courtier", [])))
    check("concurrent qui se confond avec le client refusé",
          leve(lambda: clients.ajouter_client(
              "Assurances Le Goff", "courtier", "Brest",
              concurrents=["Le Goff Immobilier"])))
    check("deux concurrents qui se confondent refusés",
          leve(lambda: clients.ajouter_client(
              "Cabinet Neuf", "courtier", "Brest",
              concurrents=["Agence Kermarrec", "Kermarrec Courtage"])))
    check("concurrent = client refusé aussi à la modification",
          leve(lambda: clients.modifier_client(
              c1["id"], concurrents=["Durand Assurances"])))
    check("date d'entrée au format libre refusée",
          leve(lambda: clients.ajouter_client(
              "Date Douteuse", "courtier", "Brest",
              entree_le="28/07/2026")))
    c_date = clients.ajouter_client("Date Propre", "courtier", "Lannion",
                                    entree_le="2026-06-15")
    check("date d'entrée AAAA-MM-JJ acceptée telle quelle",
          c_date["entree_le"] == "2026-06-15")
    clients.desactiver_client(c_date["id"])
    check("adresse mail invalide refusée",
          leve(lambda: clients.ajouter_client(
              "Mail Douteux", "courtier", "Brest", email="pas-un-mail")))
    check("adresse mail normalisée en minuscules",
          clients.modifier_client(
              c1["id"], email="Contact@Durand.FR")["email"]
          == "contact@durand.fr")

    print("— registre : modification")
    c1 = clients.modifier_client(c1["id"], palier="serenite")
    check("modifier le palier", c1["palier"] == "serenite")
    check("champ inconnu refusé",
          leve(lambda: clients.modifier_client(c1["id"], couleur="rouge")))
    trouve = clients.trouver_client("Durand")
    check("retrouvé par nom approchant",
          trouve is not None and trouve["id"] == c1["id"])

    print("— questions du client")
    qs = clients.questions_du_client(c1)
    check("questions du métier avec la ville",
          len(qs) == 3 and all("Rennes" in q for q in qs))
    c1 = clients.modifier_client(c1["id"], villes=["Rennes", "Nantes"])
    qs2 = clients.questions_du_client(c1)
    check("multi-villes : questions pour chaque ville",
          len(qs2) == 6 and any("Nantes" in q for q in qs2))
    c1 = clients.modifier_client(
        c1["id"], questions=["où trouver un courtier fiable près de Rennes ?"])
    check("questions personnalisées prioritaires",
          clients.questions_du_client(c1)
          == ["où trouver un courtier fiable près de Rennes ?"])
    c1 = clients.modifier_client(c1["id"], questions=[], villes=["Rennes"])

    print("— registre : désactivation")
    c2 = clients.ajouter_client("Boulangerie Madec", "boulangerie", "Brest")
    check("client sans concurrent accepté", c2["concurrents"] == [])
    clients.desactiver_client(c2["id"])
    check("désactivé : sorti de la liste des actifs",
          [x["id"] for x in clients.lister_clients()] == [c1["id"]])
    check("désactivé : toujours dans la liste complète",
          any(x["id"] == c2["id"]
              for x in clients.lister_clients(actifs=False)))
    c2b = clients.ajouter_client("Boulangerie Madec", "boulangerie", "Brest")
    check("ré-ajout après désactivation, id distinct",
          c2b["id"] != c2["id"])
    check("réactivation en doublon refusée",
          leve(lambda: clients.modifier_client(c2["id"], actif=True)))

    print("— mesure et historique")
    check("historique vide : rapport refusé proprement",
          leve(lambda: rapport.generer_rapport(c1)))
    check("mesure muette : relevé non archivé",
          leve(lambda: rapport.mesurer_client(
              c1, mesure={"runs": [], "ts": "2026-07-01T00:00:00+00:00",
                          "nb_reponses": 0})))
    check("mesure sans détail (compteur seul) : refusée aussi",
          leve(lambda: rapport.mesurer_client(
              c1, mesure={"ts": "2026-07-01T00:00:00+00:00",
                          "nb_reponses": 6})))
    r1 = rapport.mesurer_client(c1, passes=2, mesure=mesure_ou(
        {"Le Goff Assurances": 3, "Agence Kermarrec": 2}))
    check("client absent des réponses = part 0", r1["part_client"] == 0.0)
    parts1 = {c["nom"]: c["part"] for c in r1["concurrents"]}
    check("concurrent cité 3/6 = 50 %",
          parts1.get("Le Goff Assurances") == 50.0)
    check("concurrent cité 2/6 = 33,3 %",
          parts1.get("Agence Kermarrec") == 33.3)
    check("relevé archivé", len(rapport.historique_client(c1["id"])) == 1)
    check("nombre de réponses recompté depuis les réponses réelles",
          r1["nb_reponses"] == 6)
    check("passages archivés = ce qui a vraiment tourné (jamais 0)",
          rapport.mesurer_client(
              c2b, passes=0,
              mesure=mesure_ou({"Boulangerie Madec": 1},
                               ts="2026-06-01T10:00:00+00:00"))["passes"] == 1)

    print("— comparaison au relevé précédent")
    rap1 = rapport.generer_rapport(c1)
    check("premier relevé : sens « premier »",
          rap1["evolution"]["sens"] == "premier")
    check("moyenne des concurrents calculée",
          rap1["moyenne_concurrents"] == round((50.0 + 33.3) / 2, 1))
    rapport.mesurer_client(c1, passes=2, mesure=mesure_ou(
        {"Cabinet Durand": 3, "Le Goff Assurances": 3},
        ts="2026-08-01T10:00:00+00:00"))
    rap2 = rapport.generer_rapport(c1)
    check("hausse détectée", rap2["evolution"]["sens"] == "hausse"
          and rap2["evolution"]["delta"] == 50.0)
    evs2 = {c["nom"]: c["evolution"] for c in rap2["concurrents"]}
    check("concurrent stable détecté",
          evs2["Le Goff Assurances"]["sens"] == "stable")
    check("concurrent en baisse détecté",
          evs2["Agence Kermarrec"]["sens"] == "baisse")
    check("série pour le graphique (datée, ordonnée)",
          [p["part"] for p in rap2["serie"]] == [0.0, 50.0])
    rapport.mesurer_client(c1, passes=2, mesure=mesure_ou(
        {"Cabinet Durand": 3, "Le Goff Assurances": 3},
        ts="2026-09-01T10:00:00+00:00"))
    rap3 = rapport.generer_rapport(c1)
    check("stable détecté (client)", rap3["evolution"]["sens"] == "stable")
    rapport.mesurer_client(c1, passes=2, mesure=mesure_ou(
        {"Le Goff Assurances": 3}, ts="2026-10-01T10:00:00+00:00"))
    rap4 = rapport.generer_rapport(c1)
    check("baisse détectée (client)", rap4["evolution"]["sens"] == "baisse"
          and rap4["evolution"]["delta"] == -50.0)
    check("date du relevé précédent portée par l'évolution",
          rap4["evolution"]["precedent_ts"][:10] == "2026-09-01")
    check("extraction morte (zéro nom partout après un historique non "
          "nul) : relevé refusé",
          leve(lambda: rapport.mesurer_client(
              c1, passes=2,
              mesure=mesure_ou({}, ts="2026-11-01T10:00:00+00:00"))))

    print("— client sans concurrent")
    rapport.mesurer_client(c2b, passes=2,
                           mesure=mesure_ou({"Boulangerie Madec": 6}))
    rap_solo = rapport.generer_rapport(c2b)
    check("part du client seul = 100 %", rap_solo["part_client"] == 100.0)
    check("sans concurrent : pas de moyenne inventée",
          rap_solo["moyenne_concurrents"] is None
          and rap_solo["concurrents"] == [])
    page_solo = rapport.rendre_html(rap_solo).lower()
    check("sans concurrent : la page le dit",
          "aucun concurrent désigné" in page_solo)
    check("sans concurrent : pas de titre « vos concurrents »",
          "vos concurrents désignés" not in page_solo)

    print("— rubriques fait / à venir")
    rap_fait = rapport.generer_rapport(
        c1, fait=["2 pages publiées"], avenir=["3 avis à collecter"])
    check("rubriques passées en paramètre reprises",
          rap_fait["fait"] == ["2 pages publiées"]
          and rap_fait["avenir"] == ["3 avis à collecter"])
    check("rubriques remplies : aucune alerte", rap_fait["alertes"] == [])
    check("règle de rétention : alertes quand les rubriques manquent",
          len(rap4["alertes"]) == 2)
    c1 = clients.modifier_client(c1["id"],
                                 fait=["Fiche Google complétée"],
                                 avenir=["Page avis en préparation"])
    rap5 = rapport.generer_rapport(c1)
    check("rubriques stockées sur la fiche reprises par défaut",
          rap5["fait"] == ["Fiche Google complétée"]
          and rap5["avenir"] == ["Page avis en préparation"])

    print("— rendu de la page")
    page = rapport.rendre_html(rap5)
    plate = re.sub(r"\s+", " ", page.lower())
    visible = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page).lower())
    check("mention de variabilité obligatoire",
          "les réponses des ia varient" in plate)
    check("le mot « tendance » figure", "tendance" in plate)
    check("le mot « robot » n'apparaît pas dans le texte visible",
          "robot" not in visible)
    check("aucune promesse de citation",
          "garantie de citation" not in visible
          and "vous serez cité" not in visible)
    check("méthode affichée (passages)", "passages par question" in plate)
    check("les questions posées figurent",
          "vers quel courtier en assurance se tourner à rennes" in plate)
    check("rubrique « fait » visible", "fiche google complétée" in visible)
    check("rubrique « à venir » visible",
          "page avis en préparation" in visible)
    check("flèche d'évolution affichée", "↘" in page and "→" in page)
    check("pas de balise non fermée évidente",
          page.count("<div") == page.count("</div>"))
    check("couleurs dans des variables CSS en tête",
          ":root" in page and "--encre" in page and "--papier" in page)
    check("nombres en écriture française (virgule)",
          "33,3" in rapport.rendre_html(dict(rap5, part_client=33.3))
          and rapport.texte_evolution({"sens": "baisse", "delta": -5.5,
                                       "precedent_ts": "2026-06-02"})
          == "En baisse de 5,5 points par rapport au relevé du 2 juin 2026")
    check("aucune affirmation « recherche web » invérifiable",
          "recherche web" not in plate)
    check("pied de page : IA jamais inventées quand la liste manque",
          "chatgpt" not in re.sub(r"<[^>]+>", " ",
                                  rapport.rendre_html(dict(rap5, ias=[]))).lower()
          and "les ia interrogées" in re.sub(
              r"\s+", " ", re.sub(r"<[^>]+>", " ",
                                  rapport.rendre_html(dict(rap5, ias=[])))).lower())
    page_un = rapport.rendre_html(dict(rap5, nb_reponses=1, nb_passes=1,
                                       ias=["ChatGPT"]))
    check("accords au singulier (1 réponse, 1 passage)",
          "1 réponse recueillie" in page_un
          and "1 passage par question" in page_un)
    check("échappement HTML du nom du client",
          "<script>" not in rapport.rendre_html(
              dict(rap5, entreprise="Cabinet <script>alert(1)</script>")))
    check("échappement HTML du nom d'un concurrent",
          "<img" not in rapport.rendre_html(
              dict(rap5, concurrents=[{
                  "nom": "<img src=x>", "part": 10.0,
                  "evolution": {"sens": "premier", "delta": None,
                                "precedent_ts": ""}}])))

    print("— rendu : cas particuliers")
    check("libellé « premier » adapté aux concurrents",
          rapport.texte_evolution({"sens": "premier", "delta": None,
                                   "precedent_ts": ""}, pour_concurrent=True)
          == "Première mesure pour ce concurrent")
    c3 = clients.ajouter_client("Garage Tanguy", "garagiste", "Lorient",
                                concurrents=["Atelier Le Bihan"])
    rapport.mesurer_client(c3, passes=2, mesure=mesure_ou(
        {"Garage Tanguy": 2, "Atelier Le Bihan": 3}))
    page_c3 = rapport.rendre_html(
        rapport.generer_rapport(c3, fait=["x"], avenir=["y"])).lower()
    check("premier rapport : « point de référence » pas répété sous les barres",
          page_c3.count("point de référence") == 2)
    c3 = clients.modifier_client(
        c3["id"], concurrents=["Atelier Le Bihan", "Carrosserie Salaun"])
    rapport.mesurer_client(c3, passes=2, mesure=mesure_ou(
        {"Garage Tanguy": 2, "Atelier Le Bihan": 3},
        ts="2026-08-01T10:00:00+00:00"))
    page_c3b = rapport.rendre_html(
        rapport.generer_rapport(c3, fait=["x"], avenir=["y"])).lower()
    check("concurrent ajouté en cours de suivi : libellé dédié",
          "première mesure pour ce concurrent" in page_c3b)
    check("« votre point de référence » jamais sous une barre de concurrent",
          "votre point de référence" not in page_c3b)
    c4 = clients.ajouter_client("Menuiserie Riou", "menuisier", "Vannes")
    rapport.mesurer_client(c4, passes=2, mesure=mesure_ou(
        {"Autre Nom": 3}, ts="2026-07-01T09:00:00+00:00"))
    rapport.mesurer_client(c4, passes=2, mesure=mesure_ou(
        {"Menuiserie Riou": 3}, ts="2026-07-15T09:00:00+00:00"))
    rap_c4 = rapport.generer_rapport(c4, fait=["x"], avenir=["y"])
    check("graphique : une colonne par mois (la re-mesure remplace)",
          len(rap_c4["serie"]) == 1 and rap_c4["serie"][0]["part"] == 50.0)
    check("point de départ hors graphique rappelé en toutes lettres",
          "point de départ : 0&nbsp;% le 1er juillet 2026"
          in rapport.rendre_html(rap_c4).lower())

    print("— archive des rapports")
    entree = rapport.archiver_rapport(rap_c4)
    check("rapport archivé avec un id non devinable",
          len(entree.get("id") or "") >= 9)
    check("archive retrouvée par client",
          [r["id"] for r in rapport.rapports_archives(c4["id"])]
          == [entree["id"]])
    check("rapport retrouvé par id",
          (rapport.rapport_par_id(entree["id"]) or {}).get("entreprise")
          == "Menuiserie Riou")
    check("id d'archive inconnu = None",
          rapport.rapport_par_id("inconnu-xyz") is None)
    rap_recycle = rapport.generer_rapport(c4, fait=["x"], avenir=["y"])
    rapport.alerte_rubriques_perimees(c4, rap_recycle)
    check("rubriques inchangées depuis le dernier rapport : alerte de "
          "recyclage posée",
          any("inchangées" in a for a in rap_recycle["alertes"]))
    c4 = clients.modifier_client(c4["id"], fait=["Nouvelle action du mois"])
    rap_frais = rapport.generer_rapport(c4)
    rapport.alerte_rubriques_perimees(c4, rap_frais)
    check("rubriques fraîchement mises à jour : pas d'alerte de recyclage",
          not any("inchangées" in a for a in rap_frais["alertes"]))
    envoye = rapport.marquer_envoye(entree["id"], "Client@Riou.fr")
    check("rapport marqué envoyé (date + adresse en minuscules)",
          envoye and len(envoye.get("envoye_le") or "") >= 10
          and envoye.get("envoye_a") == "client@riou.fr")
    check("marquage visible en relisant l'archive",
          (rapport.rapport_par_id(entree["id"]) or {}).get("envoye_a")
          == "client@riou.fr")
    check("marquage d'un rapport inconnu = None",
          rapport.marquer_envoye("inconnu-xyz", "x@y.fr") is None)

    print("— journal automatique du travail fait")
    c4 = clients.noter_fait(c4["id"], "Page publiée par le connecteur")
    check("noter_fait ajoute une ligne au journal",
          "Page publiée par le connecteur" in c4["fait"])
    c4 = clients.noter_fait(c4["id"], "Page publiée par le connecteur")
    check("noter_fait ne double jamais une ligne identique",
          c4["fait"].count("Page publiée par le connecteur") == 1)
    check("noter_fait refuse un client inconnu",
          leve(lambda: clients.noter_fait("fantome-inconnu", "x")))
    check("noter_fait refuse une note vide",
          leve(lambda: clients.noter_fait(c4["id"], "   ")))

    print("— robot mensuel : qui est dû ? (logique pure)")
    from datetime import datetime, timezone  # noqa: E402

    tous = clients.lister_clients()
    avant_le_2 = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    check("avant le 2 du mois : personne n'est dû",
          rapporteur.clients_dus(tous, [], avant_le_2) == [])
    le_2 = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
    dus = {c["id"] for c in rapporteur.clients_dus(tous, [], le_2)}
    check("le 2 du mois : les clients actifs du mois passé sont dus",
          c1["id"] in dus and c4["id"] in dus)
    check("client désactivé jamais dû",
          c2["id"] not in dus)
    deja = [{"client_id": c1["id"],
             "archive_ts": "2026-08-01T09:00:00+00:00"}]
    check("rapport déjà archivé ce mois-ci : plus dû (idempotent)",
          c1["id"] not in {c["id"] for c in
                           rapporteur.clients_dus(tous, deja, le_2)})
    nouveau = {"id": "tout-neuf", "actif": True, "entree_le": "2026-08-01"}
    check("client entré ce mois-ci : premier rapport le mois suivant",
          rapporteur.clients_dus([nouveau], [], le_2) == [])
    check("le mois suivant, le nouveau client devient dû",
          rapporteur.clients_dus(
              [nouveau], [],
              datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc))
          == [nouveau])

    print("— stockage : une panne de base ne ment jamais")

    class _BaseCassee:
        def table(self, *_a, **_k):
            raise RuntimeError("base cassée (simulation)")

    _vrai_client_base = stockage._client_base
    stockage.MODE_FICHIER_SEUL = False
    stockage._client_base = lambda: _BaseCassee()
    try:
        check("lecture en panne de base : refus propre (jamais une vue "
              "tronquée qui écraserait tout à l'écriture suivante)",
              leve(lambda: clients.lister_clients(actifs=False)))
        check("écriture en panne de base : refus propre (rien de perdu "
              "en silence)",
              leve(lambda: clients.modifier_client(c1["id"],
                                                   palier="panne-test")))
    finally:
        stockage._client_base = _vrai_client_base
        stockage.MODE_FICHIER_SEUL = True
    check("après la panne : le palier n'a pas bougé",
          (clients.trouver_client(c1["id"]) or {}).get("palier")
          == "serenite")

    print("— enregistrement")
    with tempfile.TemporaryDirectory() as tmp2:
        fichiers = rapport.enregistrer(rap5, tmp2)
        check("HTML écrit", Path(fichiers["html"]).exists())
        check("JSON écrit",
              Path(fichiers["html"]).with_suffix(".json").exists())
        check("jeton non devinable dans le nom",
              len(Path(fichiers["html"]).stem.rsplit("-", 1)[-1]) >= 6)
        check("adresse relative sous rapports/",
              fichiers["url_relative"].startswith("rapports/"))
        donnees = json.loads(Path(fichiers["html"]).with_suffix(".json")
                             .read_text(encoding="utf-8"))
        check("JSON relisible", donnees["entreprise"] == "Cabinet Durand")
finally:
    stockage.FICHIERS = _vrais_fichiers
    stockage.MODE_FICHIER_SEUL = _vrai_mode
    _tmp.cleanup()

print()
print(f"{OK} ok, {KO} KO")
sys.exit(1 if KO else 0)
