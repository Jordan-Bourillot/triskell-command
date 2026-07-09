# -*- coding: utf-8 -*-
"""Batterie « vérité » du connecteur WordPress Porte-Voix. Sans réseau, < 5 s.

  python scripts/smoke_partdevoix_wordpress.py

Un faux site WordPress répond à la place du vrai : chaque garde-fou du
module (brouillon par défaut, jamais le contenu du client, marque
obligatoire, messages en français clair) est maltraité un par un.
"""
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from triskell_command.integrations.partdevoix import wordpress  # noqa: E402

OK = 0
KO = 0
ERREURS_VUES = []  # tous les messages d'erreur produits, pour le contrôle jargon


def check(nom, condition):
    global OK, KO
    if condition:
        OK += 1
        print(f"  ok  {nom}")
    else:
        KO += 1
        print(f"  KO  {nom}")


def garder_erreur(resultat):
    """Note le message d'erreur d'un résultat (pour le contrôle jargon)
    et rend le résultat tel quel."""
    if isinstance(resultat, dict) and resultat.get("erreur"):
        ERREURS_VUES.append(resultat["erreur"])
    return resultat


class FauxWordPress:
    """Un site WordPress simulé, assez vrai pour la batterie."""

    def __init__(self, role="auteur", permaliens=True, ancien=False,
                 panne=False, pas_wordpress=False, ignorer_auteur=False,
                 canonique=None, index_bloque=False, perd_auth=False,
                 panne_listing=False):
        self.role = role
        self.permaliens = permaliens
        self.ancien = ancien
        self.panne = panne
        self.pas_wordpress = pas_wordpress
        self.ignorer_auteur = ignorer_auteur
        # canonique : le site vit en réalité sur cette adresse (redirection
        # www) ; les identifiants se perdent en route vers l'autre adresse.
        self.canonique = canonique
        self.index_bloque = index_bloque      # index refusé aux anonymes
        self.perd_auth = perd_auth            # hébergeur qui bloque les identifiants
        self.panne_listing = panne_listing    # le listing des articles tombe en panne
        self.identifiant = "portevoix"
        self.mdp = "abcd efgh ijkl mnop qrst uvwx"
        self.moi = 7
        self.contenus = {}
        self.suivant = 100
        self.envois = []   # corps des ajouts reçus
        self.forces = []   # traces d'une éventuelle suppression définitive

    def ajouter_contenu(self, genre, auteur, brut, statut="publish",
                        titre="Un contenu"):
        num = self.suivant
        self.suivant += 1
        self.contenus[num] = {"id": num, "genre": genre, "author": auteur,
                              "raw": brut, "status": statut, "titre": titre,
                              "date": "2026-07-01T00:00:00"}
        return num

    def _droits(self):
        if self.role == "auteur":
            return {"edit_posts": True, "publish_posts": True}
        if self.role == "editeur":
            return {"edit_posts": True, "publish_posts": True,
                    "edit_pages": True, "publish_pages": True}
        return {"read": True}  # abonné : aucun droit de publication

    def _item(self, c):
        return {"id": c["id"], "author": c["author"],
                "title": {"raw": c["titre"], "rendered": c["titre"]},
                "content": {"raw": c["raw"], "rendered": c["raw"]},
                "status": c["status"], "date": c["date"],
                "link": f"https://client.fr/?p={c['id']}"}

    def repondre(self, methode, url, identifiant="", mdp="",
                 corps=None, params=None):
        if self.panne:
            return {"status": 0, "json": None, "texte": "délai dépassé"}
        if self.pas_wordpress:
            return {"status": 404, "json": None,
                    "texte": "<html>introuvable</html>"}
        if "rest_route=" in url:
            route = url.split("rest_route=", 1)[1].split("&", 1)[0]
        elif "/wp-json" in url:
            if not self.permaliens:
                return {"status": 404, "json": None, "texte": "<html>404</html>"}
            route = url.split("/wp-json", 1)[1] or "/"
        else:
            return {"status": 404, "json": None, "texte": "<html>404</html>"}
        params = params or {}
        mauvais_hote = bool(self.canonique) and not url.startswith(self.canonique)
        if route == "/":
            if self.index_bloque:
                return {"status": 401, "texte": "",
                        "json": {"code": "rest_cannot_access"}}
            connexions = ({} if self.ancien
                          else {"application-passwords": {"endpoints": {}}})
            rep = {"status": 200, "texte": "",
                   "json": {"namespaces": ["wp/v2"],
                            "authentication": connexions}}
            if mauvais_hote:
                # La vraie bibliothèque HTTP suit la redirection : l'URL
                # finale porte la bonne adresse.
                rep["url"] = self.canonique + "/wp-json/"
            return rep
        if identifiant and (mauvais_hote or self.perd_auth):
            # Identifiants tombés en route (redirection qui change d'hôte,
            # ou hébergeur qui bloque l'en-tête) : WordPress ne voit rien.
            return {"status": 401, "texte": "",
                    "json": {"code": "rest_not_logged_in"}}
        if identifiant != self.identifiant or mdp != self.mdp:
            return {"status": 401, "texte": "",
                    "json": {"code": "incorrect_password"}}
        if route == "/wp/v2/users/me":
            return {"status": 200, "texte": "",
                    "json": {"id": self.moi, "name": "Porte-Voix",
                             "capabilities": self._droits()}}
        m = re.match(r"^/wp/v2/(pages|posts)(?:/(\d+))?$", route)
        if not m:
            return {"status": 404, "texte": "",
                    "json": {"code": "rest_no_route"}}
        collection, num = m.group(1), m.group(2)
        genre = "page" if collection == "pages" else "article"
        droit = "edit_pages" if collection == "pages" else "edit_posts"
        if num is None and methode == "GET":
            if self.panne_listing and collection == "posts":
                return {"status": 500, "texte": "",
                        "json": {"code": "internal_server_error"}}
            if not self._droits().get(droit):
                # Comme le vrai WordPress (vérifié sur site réel le
                # 09/07/2026) : demander des brouillons d'un rayon hors
                # droits = paramètre invalide, réponse 400.
                return {"status": 400, "texte": "",
                        "json": {"code": "rest_invalid_param"}}
            voulu = str(params.get("author", ""))
            statuts = set((params.get("status") or "publish").split(","))
            items = [self._item(c) for c in self.contenus.values()
                     if c["genre"] == genre and c["status"] in statuts
                     and (self.ignorer_auteur or not voulu
                          or str(c["author"]) == voulu)]
            return {"status": 200, "json": items, "texte": ""}
        if num is None and methode == "POST":
            if not self._droits().get(droit):
                return {"status": 403, "texte": "",
                        "json": {"code": "rest_cannot_create"}}
            self.envois.append({"collection": collection, **(corps or {})})
            numero = self.ajouter_contenu(
                genre, self.moi, (corps or {}).get("content", ""),
                (corps or {}).get("status", "draft"),
                (corps or {}).get("title", ""))
            return {"status": 201, "texte": "",
                    "json": {"id": numero, "status": (corps or {}).get(
                        "status", "draft"),
                        "link": f"https://client.fr/?p={numero}"}}
        if num is not None:
            c = self.contenus.get(int(num))
            if c is None or c["genre"] != genre:
                return {"status": 404, "texte": "",
                        "json": {"code": "rest_post_invalid_id"}}
            if methode == "GET":
                return {"status": 200, "json": self._item(c), "texte": ""}
            if methode == "DELETE":
                if (params or {}).get("force") or (corps or {}).get("force"):
                    self.forces.append(int(num))
                if c["status"] == "trash":
                    # Comme le vrai WordPress : un contenu déjà à la
                    # corbeille ne se re-supprime pas.
                    return {"status": 410, "texte": "",
                            "json": {"code": "rest_already_trashed"}}
                c["status"] = "trash"
                return {"status": 200, "json": self._item(c), "texte": ""}
        return {"status": 404, "texte": "",
                "json": {"code": "rest_no_route"}}


def brancher(faux):
    wordpress._requete = faux.repondre
    return faux


IDENT = "portevoix"
MDP = "abcd efgh ijkl mnop qrst uvwx"

print("— adresse du site")
check("https ajouté et barre finale retirée",
      wordpress._racine("exemple.fr/") == "https://exemple.fr")
check("le /wp-json collé par erreur est retiré",
      wordpress._racine("https://exemple.fr/wp-json/") == "https://exemple.fr")
check("le /wp-admin collé par erreur est retiré",
      wordpress._racine("Exemple.fr/wp-admin") == "https://exemple.fr")
check("adresse vide = refus propre",
      garder_erreur(wordpress.tester_connexion("", IDENT, MDP))["erreur"]
      == "Adresse du site manquante.")
check("identifiants vides = refus propre",
      "manquant" in garder_erreur(
          wordpress.tester_connexion("https://x.fr", "", ""))["erreur"])

print("— connexion : les pannes racontées en français")
brancher(FauxWordPress(panne=True))
r = garder_erreur(wordpress.tester_connexion("https://client-panne.fr", IDENT, MDP))
check("site en panne = « ne répond pas »",
      not r["ok"] and "ne répond pas" in r["erreur"])

brancher(FauxWordPress(pas_wordpress=True))
r = garder_erreur(wordpress.tester_connexion("https://client-vitrine.fr", IDENT, MDP))
check("site non WordPress = message clair",
      not r["ok"] and "ne semble pas être un WordPress" in r["erreur"])

brancher(FauxWordPress(ancien=True))
r = garder_erreur(wordpress.tester_connexion("https://client-ancien.fr", IDENT, MDP))
check("WordPress trop vieux = message version 5.6",
      not r["ok"] and "5.6" in r["erreur"])
check("... qui nomme aussi la piste du réglage de sécurité (Wordfence)",
      "sécurité" in r["erreur"])

# Le signal « personne ne s'est présenté » (vérifié sur site réel le
# 09/07/2026) : il arrive après une révocation totale COMME quand un
# hébergeur bloque les identifiants. Le message doit donner les deux
# pistes, révocation en tête.
brancher(FauxWordPress(perd_auth=True))
r = garder_erreur(wordpress.tester_connexion("https://client-hebergeur.fr",
                                             IDENT, MDP))
check("accès non reconnu = les deux pistes données (révoqué, hébergeur)",
      not r["ok"] and "révoqué" in r["erreur"] and "hébergeur" in r["erreur"])
check("... et la révocation est citée en premier",
      not r["ok"] and r["erreur"].find("révoqué") < r["erreur"].find("hébergeur"))

brancher(FauxWordPress())
r = garder_erreur(wordpress.tester_connexion("https://client-mdp.fr", IDENT,
                                             "mauvais mot de passe"))
check("mot de passe refusé = message révocation",
      not r["ok"] and "révoqué" in r["erreur"])

brancher(FauxWordPress(role="abonne"))
r = garder_erreur(wordpress.tester_connexion("https://client-abonne.fr", IDENT, MDP))
check("compte sans droits = renvoyer vers le rôle Auteur",
      not r["ok"] and "Auteur" in r["erreur"])

print("— connexion : les cas qui marchent")
brancher(FauxWordPress())
r = wordpress.tester_connexion("https://client-auteur.fr", IDENT, MDP)
check("connexion ok (compte Auteur)", r["ok"] and r["erreur"] == "")
check("le nom du compte remonte", r["utilisateur"] == "Porte-Voix")
check("Auteur publie des articles", r["genre_publication"] == "article")
check("Auteur prévenu par une note (articles, pas pages)",
      any("article" in a for a in r["avertissements"]))

brancher(FauxWordPress(role="editeur"))
r = wordpress.tester_connexion("https://client-editeur.fr", IDENT, MDP)
check("compte avec droit pages = genre page",
      r["ok"] and r["genre_publication"] == "page" and r["peut_pages"])

brancher(FauxWordPress(permaliens=False))
r = wordpress.tester_connexion("https://client-permaliens.fr", IDENT, MDP)
check("adresses simplifiées désactivées = connexion quand même", r["ok"])

brancher(FauxWordPress(canonique="https://www.client-www.fr"))
r = wordpress.tester_connexion("https://client-www.fr", IDENT, MDP)
check("site redirigé vers www = connexion OK (pas de faux « révoqué »)",
      r["ok"])
check("l'adresse réelle (www) est adoptée",
      r["site"] == "https://www.client-www.fr")

brancher(FauxWordPress(index_bloque=True))
r = wordpress.tester_connexion("https://client-index-bloque.fr", IDENT, MDP)
check("index caché aux visiteurs anonymes = connexion quand même", r["ok"])

faux = brancher(FauxWordPress())
wordpress.tester_connexion("https://client-reconfig.fr", IDENT, MDP)
faux.permaliens = False
r = wordpress.tester_connexion("https://client-reconfig.fr", IDENT, MDP)
check("site reconfiguré (permaliens changés) = le module se répare seul",
      r["ok"])

print("— publication : brouillon par défaut, marque obligatoire")
faux = brancher(FauxWordPress())
r = wordpress.publier_page("https://client-auteur2.fr", IDENT, MDP,
                           "Les vraies questions", "<p>Contenu.</p>")
check("ajout accepté", r["ok"] and r["id"] and r["genre"] == "article")
check("BROUILLON par défaut, jamais en ligne tout seul",
      r["statut"] == "brouillon" and faux.envois[-1]["status"] == "draft")
check("compte Auteur = collection des articles",
      faux.envois[-1]["collection"] == "posts")
check("la marque Porte-Voix est posée dans le contenu",
      wordpress.MARQUE_TEXTE in faux.envois[-1]["content"])
check("la marque est un commentaire invisible",
      wordpress.MARQUE_HTML.startswith("<!--")
      and wordpress.MARQUE_HTML.endswith("-->"))

r = wordpress.publier_page("https://client-auteur2.fr", IDENT, MDP,
                           "Mise en ligne voulue", "<p>Contenu.</p>",
                           en_ligne=True)
check("en_ligne=True est le seul chemin vers la mise en ligne",
      r["ok"] and r["statut"] == "en ligne"
      and faux.envois[-1]["status"] == "publish")

r = wordpress.publier_page("https://client-auteur2.fr", IDENT, MDP,
                           "Fausse mise en ligne", "<p>x</p>",
                           en_ligne="false")
check("en_ligne exige un vrai True : la chaîne « false » reste en brouillon",
      r["ok"] and r["statut"] == "brouillon"
      and faux.envois[-1]["status"] == "draft")

r = wordpress.publier_page("https://client-auteur2.fr", IDENT, MDP,
                           "Déjà marqué", wordpress.MARQUE_HTML + "<p>x</p>")
check("jamais deux marques sur le même contenu",
      faux.envois[-1]["content"].count(wordpress.MARQUE_TEXTE) == 1)

check("titre vide = refus propre",
      "Titre manquant." == garder_erreur(wordpress.publier_page(
          "https://client-auteur2.fr", IDENT, MDP, " ", "<p>x</p>"))["erreur"])
check("contenu vide = refus propre",
      "Contenu manquant." == garder_erreur(wordpress.publier_page(
          "https://client-auteur2.fr", IDENT, MDP, "Titre", ""))["erreur"])

faux = brancher(FauxWordPress(role="editeur"))
r = wordpress.publier_page("https://client-editeur2.fr", IDENT, MDP,
                           "Une vraie page", "<p>Contenu.</p>")
check("compte avec droit pages = collection des pages",
      r["ok"] and r["genre"] == "page"
      and faux.envois[-1]["collection"] == "pages")

brancher(FauxWordPress(panne=True))
r = garder_erreur(wordpress.publier_page("https://client-panne2.fr", IDENT,
                                         MDP, "Titre", "<p>x</p>"))
check("site en panne pendant l'ajout = erreur propre, pas de plantage",
      not r["ok"] and "ne répond pas" in r["erreur"])

print("— la liste : uniquement ce qui est à nous")
faux = brancher(FauxWordPress())
faux.ajouter_contenu("article", 7, wordpress.MARQUE_HTML + "<p>x</p>",
                     "draft", "Notre brouillon")
faux.ajouter_contenu("article", 7, wordpress.MARQUE_HTML + "<p>y</p>",
                     "publish", "Notre contenu en ligne")
faux.ajouter_contenu("article", 3, "<p>l'article du client</p>",
                     "publish", "Article du client")
faux.ajouter_contenu("page", 3, "<p>l'accueil du client</p>",
                     "publish", "Accueil")
r = wordpress.lister_nos_pages("https://client-liste.fr", IDENT, MDP)
check("la liste marche", r["ok"] and len(r["pages"]) == 2)
check("le contenu du client n'y figure JAMAIS",
      all("client" not in p["titre"] for p in r["pages"]))
check("les brouillons y figurent, statut en français",
      any(p["statut"] == "brouillon" for p in r["pages"]))
check("les contenus en ligne aussi",
      any(p["statut"] == "en ligne" for p in r["pages"]))
check("les pages du client (rayon interdit au compte) ne cassent rien",
      r["erreur"] == "")

faux = brancher(FauxWordPress(ignorer_auteur=True))
faux.ajouter_contenu("article", 7, wordpress.MARQUE_HTML + "<p>x</p>",
                     "draft", "Notre brouillon")
faux.ajouter_contenu("article", 3, "<p>du client</p>", "publish",
                     "Article du client")
r = wordpress.lister_nos_pages("https://client-laxiste.fr", IDENT, MDP)
check("ceinture : un site trop bavard ne fait pas fuiter le client",
      len(r["pages"]) == 1 and r["pages"][0]["titre"] == "Notre brouillon")

faux = brancher(FauxWordPress(panne_listing=True))
faux.ajouter_contenu("article", 7, wordpress.MARQUE_HTML + "<p>x</p>",
                     "draft", "Chez nous")
r = garder_erreur(wordpress.lister_nos_pages("https://client-panne-liste.fr",
                                             IDENT, MDP))
check("panne du listing = avouée, jamais un faux « rien de nous »",
      not r["ok"] and r["erreur"] != "" and r["pages"] == [])

faux = brancher(FauxWordPress(ignorer_auteur=True))
faux.ajouter_contenu("article", 7, wordpress.MARQUE_HTML + "<p>n</p>",
                     "draft", "Normal")
num_bizarre = faux.ajouter_contenu("article", "sept",
                                   wordpress.MARQUE_HTML + "<p>d</p>",
                                   "draft", "Auteur illisible")
r = wordpress.lister_nos_pages("https://client-bizarre.fr", IDENT, MDP)
check("auteur illisible dans la liste = fiche ignorée, pas de plantage",
      r["ok"] and [p["titre"] for p in r["pages"]] == ["Normal"])
r = garder_erreur(wordpress.retirer_page("https://client-bizarre.fr", IDENT,
                                         MDP, num_bizarre))
check("auteur illisible au retrait = REFUS propre",
      not r["ok"] and "notre compte" in r["erreur"])

print("— le retrait : double verrou, corbeille seulement")
faux = brancher(FauxWordPress())
num_client = faux.ajouter_contenu("article", 3, "<p>au client</p>",
                                  "publish", "Article du client")
num_sans_marque = faux.ajouter_contenu("article", 7, "<p>sans marque</p>",
                                       "draft", "Orphelin")
r = wordpress.publier_page("https://client-retrait.fr", IDENT, MDP,
                           "À retirer", "<p>Contenu.</p>")
num_a_nous = r["id"]

r = garder_erreur(wordpress.retirer_page("https://client-retrait.fr", IDENT,
                                         MDP, num_client))
check("contenu du client = REFUS (mauvais auteur)",
      not r["ok"] and "notre compte" in r["erreur"])
check("le contenu du client est toujours là",
      faux.contenus[num_client]["status"] == "publish")

r = garder_erreur(wordpress.retirer_page("https://client-retrait.fr", IDENT,
                                         MDP, num_sans_marque))
check("contenu sans marque = REFUS (dans le doute on ne retire pas)",
      not r["ok"] and "marque" in r["erreur"])

r = wordpress.retirer_page("https://client-retrait.fr", IDENT, MDP,
                           num_a_nous)
check("notre contenu marqué = retiré", r["ok"] and r["corbeille"])
check("retiré = CORBEILLE, jamais de suppression définitive",
      faux.contenus[num_a_nous]["status"] == "trash" and faux.forces == [])

r = wordpress.retirer_page("https://client-retrait.fr", IDENT, MDP,
                           num_a_nous)
check("retirer deux fois = toléré (déjà à la corbeille)",
      r["ok"] and r.get("note", "") != "")

r = garder_erreur(wordpress.retirer_page("https://client-retrait.fr", IDENT,
                                         MDP, 99999))
check("numéro inconnu = message clair",
      not r["ok"] and "Aucun contenu" in r["erreur"])
check("numéro invalide = refus propre",
      "invalide" in garder_erreur(wordpress.retirer_page(
          "https://client-retrait.fr", IDENT, MDP, "abc"))["erreur"])

print("— les messages : français normal, zéro jargon")
check("au moins 12 messages d'erreur collectés", len(ERREURS_VUES) >= 12)
_JARGON = ["HTTP", "REST", "API", "endpoint", "401", "403", "404",
           "JSON", "token", "wp-json", "—"]
coupables = [(mot, msg) for msg in ERREURS_VUES for mot in _JARGON
             if mot in msg]
check("aucun jargon ni tiret cadratin dans les erreurs", not coupables)
if coupables:
    for mot, msg in coupables[:5]:
        print(f"      jargon « {mot} » dans : {msg}")

print("— le contenu livré (mode sans accès)")
with tempfile.TemporaryDirectory() as tmp:
    r = wordpress.generer_livrable("Plombier à Rennes : les vraies questions",
                                   "<p>Le contenu de la page.</p>",
                                   Path(tmp) / "livrables" / "client1")
    check("livrable généré", r["ok"])
    check("le fichier à coller existe", Path(r["html"]).exists())
    check("le mode d'emploi existe", Path(r["mode_demploi"]).exists())
    page = Path(r["html"]).read_text(encoding="utf-8")
    check("le fichier contient la marque et le contenu",
          wordpress.MARQUE_TEXTE in page
          and "Le contenu de la page." in page)
    check("la version texte à coller existe (lisible sur PC comme sur Mac)",
          Path(r["a_coller"]).exists())
    check("la version texte porte exactement le même contenu",
          Path(r["a_coller"]).read_text(encoding="utf-8") == page)
    note = Path(r["mode_demploi"]).read_text(encoding="utf-8")
    check("le mode d'emploi pointe la version texte",
          "-a-coller.txt" in note)
    check("consigne pour l'ancien éditeur (onglets Visuel/Texte) présente",
          '"Texte"' in note and '"Visuel"' in note)
    check("le clic « Publier » se confirme une seconde fois",
          "seconde" in note and "Publier" in note)
    check("le mode d'emploi cite le titre",
          "Plombier à Rennes" in note)
    check("le mode d'emploi donne un contact",
          "contact@triskell-studio.fr" in note)
    check("le mode d'emploi promet l'ajout sans remplacement",
          "ne remplace rien" in note)
    check("mode d'emploi sans tiret cadratin ni jargon",
          all(mot not in note for mot in ["—", "API", "REST", "wp-json",
                                          "endpoint"]))
    check("nom de fichier propre (sans accents ni espaces)",
          re.match(r"^[a-z0-9-]+\.html$", Path(r["html"]).name))
    check("titre vide = refus propre",
          not wordpress.generer_livrable("", "<p>x</p>", tmp)["ok"])
    check("contenu vide = refus propre",
          not wordpress.generer_livrable("Titre", " ", tmp)["ok"])

print()
print(f"{OK} ok, {KO} KO")
sys.exit(1 if KO else 0)
