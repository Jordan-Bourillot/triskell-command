"""Publication chez les clients Porte-Voix (la brique WordPress).

Le service promet un accès de publication LIMITÉ : le client crée un
compte « Auteur » dédié avec un mot de passe d'application, révocable
en un clic (voir portevoix/vente/guide-acces-wordpress.md). Avec cet
accès, ce module ne sait faire que trois choses : AJOUTER du contenu
(en brouillon par défaut), LISTER ce que nous avons ajouté, et RETIRER
ce que nous avons ajouté. Modifier ou supprimer un contenu existant du
client est impossible par construction : chaque retrait exige que le
contenu soit signé par notre compte ET porte la marque Porte-Voix,
sinon refus.

Pour les clients sans WordPress (ou qui préfèrent garder la main),
generer_livrable() fabrique le mode « contenu livré » : un fichier prêt
à coller + un mode d'emploi en français simple.

Rien ici ne s'exécute tout seul : ces fonctions ne partent que d'un
geste explicite (scripts/pdv_wordpress.py ou le code appelant).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from . import moteur

logger = logging.getLogger(__name__)

# La signature invisible posée dans chaque contenu ajouté. C'est elle,
# avec le compte auteur, qui borne le droit de retrait : pas de marque,
# pas de retrait.
MARQUE_TEXTE = "Contenu ajouté par Porte-Voix"
MARQUE_HTML = (f"<!-- {MARQUE_TEXTE} (Triskell Studio). Il s'ajoute au site "
               "sans rien remplacer et se retire à tout moment. -->")

_STATUTS_FR = {"draft": "brouillon", "pending": "en attente",
               "publish": "en ligne", "future": "programmé",
               "private": "privé", "trash": "corbeille"}

# Mémorise, par site, la forme d'adresse que son interface accepte
# (certains WordPress ont les adresses simplifiées désactivées et ne
# répondent que sur la forme ?rest_route=).
_FLAVEURS: dict[str, str] = {}

# Mémorise, par adresse saisie, l'adresse réelle du site après une
# éventuelle redirection (exemple.fr -> www.exemple.fr).
_RACINES: dict[str, str] = {}


# ------------------------------------------------------------ plomberie

def _racine(url: str) -> str:
    """Adresse propre du site : https par défaut, sans barre finale,
    sans le /wp-json ou le /wp-admin que certains collent en croyant
    bien faire."""
    u = (url or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.IGNORECASE):
        u = "https://" + u
    # Le nom de domaine ne connaît pas les majuscules ; le chemin, si
    # (un WordPress peut vivre dans un sous-dossier).
    m = re.match(r"^(https?)://([^/]+)(.*)$", u, re.IGNORECASE)
    if m:
        u = m.group(1).lower() + "://" + m.group(2).lower() + m.group(3)
    u = u.rstrip("/")
    for suffixe in ("/wp-json", "/wp-admin", "/wp-login.php"):
        if u.lower().endswith(suffixe):
            u = u[: -len(suffixe)]
    return u.rstrip("/")


def _requete(methode: str, url: str, identifiant: str = "", mdp: str = "",
             corps: dict | None = None, params: dict | None = None) -> dict:
    """Un appel vers le site du client, normalisé en dict
    {status, json, texte}. Panne réseau = status 0 avec la cause dans
    texte. Les batteries de test remplacent cette fonction : rien
    d'autre dans ce module ne touche au réseau."""
    try:
        import requests
        r = requests.request(
            methode, url,
            auth=(identifiant, mdp) if identifiant else None,
            json=corps, params=params, timeout=25,
            headers={"User-Agent":
                     "PorteVoix (Triskell Studio; contact@triskell-studio.fr)"},
        )
        try:
            data = r.json()
        except Exception:
            data = None
        return {"status": r.status_code, "json": data, "texte": r.text[:400],
                "url": r.url}
    except Exception as exc:
        logger.info("partdevoix wordpress %s %s: %s", methode, url, exc)
        return {"status": 0, "json": None, "texte": str(exc), "url": url}


def _canonicaliser(racine: str) -> str:
    """Suit une éventuelle redirection du site (exemple.fr redirigé vers
    www.exemple.fr, cas très courant) et travaille ensuite sur l'adresse
    finale. Indispensable : sur une redirection qui change d'hôte, la
    bibliothèque HTTP retire les identifiants en route (sécurité), ce
    qui donnerait de faux « mot de passe refusé »."""
    if not racine:
        return racine
    if racine in _RACINES:
        return _RACINES[racine]
    r = _requete("GET", f"{racine}/wp-json/")
    finale = (r.get("url") or "").split("/wp-json", 1)[0].rstrip("/")
    canonique = finale if "://" in finale else racine
    if r["status"] != 0:  # une panne passagère ne mérite pas d'être retenue
        _RACINES[racine] = canonique
    return canonique


def _url_route(racine: str, route: str, flaveur: str) -> str:
    if flaveur == "parametre":
        return f"{racine}/?rest_route={route}"
    return f"{racine}/wp-json{route}"


def _appel(racine: str, route: str, methode: str = "GET",
           identifiant: str = "", mdp: str = "",
           corps: dict | None = None, params: dict | None = None) -> dict:
    """Appelle une route de l'interface WordPress en s'adaptant aux
    sites dont les adresses simplifiées (permaliens) sont désactivées.

    Un 404 SANS corps lisible = l'adresse n'existe pas sous cette forme,
    on essaie l'autre écriture. Un 404 AVEC corps lisible = une vraie
    réponse de WordPress, on la rend telle quelle. La forme mémorisée
    passe en premier mais l'autre reste toujours essayée : un site
    reconfiguré (permaliens changés) se répare tout seul."""
    flaveurs = ["chemin", "parametre"]
    if _FLAVEURS.get(racine) == "parametre":
        flaveurs.reverse()
    derniere = {"status": 0, "json": None, "texte": "aucun appel"}
    for flaveur in flaveurs:
        derniere = _requete(methode, _url_route(racine, route, flaveur),
                            identifiant=identifiant, mdp=mdp,
                            corps=corps, params=params)
        if derniere["status"] == 0:
            return derniere
        if derniere["status"] == 404 and derniere["json"] is None:
            continue
        _FLAVEURS[racine] = flaveur
        return derniere
    return derniere


def _erreur_connexion(reponse: dict) -> str:
    """Traduit un refus du site en français utile, sans jargon."""
    statut = reponse.get("status")
    code = ""
    if isinstance(reponse.get("json"), dict):
        code = reponse["json"].get("code") or ""
    if statut == 0:
        return ("Le site ne répond pas. Vérifier l'adresse, et que le site "
                "est bien en ligne.")
    if statut == 401:
        # WordPress distingue « identifiants faux » et « identifiants
        # jamais reçus » (certains hébergeurs les bloquent en route) :
        # deux diagnostics, deux remèdes très différents.
        if code == "rest_not_logged_in":
            return ("Les identifiants n'arrivent pas jusqu'à WordPress : "
                    "l'hébergeur du site les bloque en route (réglage "
                    "connu chez certains hébergeurs). Demander au client "
                    "de signaler le point au support de son hébergeur, ou "
                    "passer en mode contenu livré.")
        return ("Le site a refusé l'identifiant ou le mot de passe "
                "d'application. Il a peut-être été révoqué : le client peut "
                "en recréer un en deux minutes (voir le guide d'accès). "
                "Autre cause possible, un WordPress trop ancien (il faut la "
                "version 5.6, sortie fin 2020).")
    if statut == 403:
        return ("Le compte fourni existe mais n'a pas les droits "
                "nécessaires. Demander au client de mettre le compte en "
                "« Auteur », comme dans le guide d'accès.")
    if statut == 404:
        return ("Ce WordPress ne connaît pas cette adresse de publication. "
                "Il est peut-être trop ancien : passer en mode contenu "
                "livré en attendant sa mise à jour.")
    return f"Réponse inattendue du site (code {statut})."


def _entier(valeur):
    """int() sans plantage : None si la valeur n'est pas un nombre
    entier (un site déformé par une extension peut renvoyer n'importe
    quoi, et un doute sur l'auteur doit produire un refus, pas une
    exception)."""
    try:
        return int(valeur)
    except Exception:
        return None


def _qui_suis_je(racine: str, identifiant: str, mdp: str):
    """La fiche de notre compte chez le client. Renvoie (fiche, "") ou
    (None, erreur en français)."""
    r = _appel(racine, "/wp/v2/users/me", identifiant=identifiant, mdp=mdp,
               params={"context": "edit"})
    if (r["status"] == 200 and isinstance(r["json"], dict)
            and r["json"].get("id")):
        return r["json"], ""
    if r["status"] == 404 and r["json"] is None:
        return None, ("Ce site ne semble pas être un WordPress, ou son "
                      "point d'accès de publication est désactivé. Passer "
                      "en mode contenu livré.")
    return None, _erreur_connexion(r)


# ------------------------------------------------------------ connexion

def tester_connexion(url: str, identifiant: str,
                     mdp_application: str) -> dict:
    """Vérifie tout ce qu'il faut avant le premier envoi chez un client :
    le site répond, c'est un WordPress assez récent, le compte et le mot
    de passe d'application marchent, et le compte a le droit de publier.

    Renvoie {"ok": bool, "erreur": str, ...}, jamais d'exception."""
    racine = _racine(url)
    if not racine:
        return {"ok": False, "erreur": "Adresse du site manquante."}
    if not (identifiant or "").strip() or not (mdp_application or "").strip():
        return {"ok": False, "site": racine,
                "erreur": ("Identifiant ou mot de passe d'application "
                           "manquant.")}
    racine = _canonicaliser(racine)

    # 1) Le site parle-t-il le WordPress ? (lecture anonyme de l'index)
    index = _appel(racine, "/")
    if index["status"] == 0:
        return {"ok": False, "site": racine,
                "erreur": ("Le site ne répond pas. Vérifier l'adresse "
                           f"({racine}), et que le site est bien en ligne.")}
    if index["status"] == 404 and index["json"] is None:
        return {"ok": False, "site": racine,
                "erreur": ("Ce site ne semble pas être un WordPress, ou "
                           "son point d'accès de publication est "
                           "désactivé. Passer en mode contenu livré.")}
    if isinstance(index.get("json"), dict):
        espaces = index["json"].get("namespaces")
        if isinstance(espaces, list) and "wp/v2" not in espaces:
            return {"ok": False, "site": racine,
                    "erreur": ("Ce site répond, mais pas comme un "
                               "WordPress normal : son point d'accès de "
                               "publication est incomplet. Passer en mode "
                               "contenu livré.")}
        # WordPress liste ici ses façons de se connecter ; les mots de
        # passe d'application n'existent que depuis la version 5.6.
        connexions = index["json"].get("authentication")
        if connexions is not None:
            noms = (connexions.keys() if isinstance(connexions, dict)
                    else connexions)
            if "application-passwords" not in list(noms or []):
                return {"ok": False, "site": racine,
                        "erreur": ("Les mots de passe d'application sont "
                                   "indisponibles sur ce site : WordPress "
                                   "trop ancien (il faut la version 5.6, "
                                   "sortie fin 2020), ou un réglage de "
                                   "sécurité qui les coupe (l'extension "
                                   "Wordfence le fait d'office). Demander "
                                   "la mise à jour ou le déblocage, ou "
                                   "passer en mode contenu livré.")}
    # Un index bloqué aux visiteurs anonymes (401/403) n'est pas un
    # problème : l'étape suivante, elle, se présente avec nos clés.

    # 2) Le compte et le mot de passe d'application marchent-ils ?
    fiche, erreur = _qui_suis_je(racine, identifiant, mdp_application)
    if erreur:
        return {"ok": False, "site": racine, "erreur": erreur}

    # 3) Que peut faire ce compte ?
    droits = fiche.get("capabilities") or {}
    peut_pages = bool(droits.get("edit_pages"))
    peut_articles = bool(droits.get("edit_posts")) or not droits
    if droits and not (peut_pages or peut_articles):
        return {"ok": False, "site": racine,
                "erreur": ("Le compte fourni ne peut rien publier (rôle "
                           "trop limité). Demander au client de le passer "
                           "en « Auteur », comme dans le guide d'accès.")}
    avertissements = []
    if not droits:
        avertissements.append("Impossible de lire les droits du compte ; "
                              "le premier envoi tranchera.")
    if not peut_pages:
        avertissements.append("Compte « Auteur » : les contenus partiront "
                              "comme des articles, pas comme des pages "
                              "(fonctionnement prévu, rien à changer).")
    return {"ok": True, "erreur": "", "site": racine,
            "utilisateur": fiche.get("name") or identifiant,
            "peut_pages": peut_pages, "peut_articles": peut_articles,
            "genre_publication": "page" if peut_pages else "article",
            "avertissements": avertissements}


# ----------------------------------------------------------- publication

def publier_page(url: str, identifiant: str, mdp_application: str,
                 titre: str, contenu_html: str,
                 en_ligne: bool = False) -> dict:
    """Ajoute UN contenu neuf sur le site du client : une page si le
    compte y a droit, un article sinon (c'est le cas du rôle « Auteur »).

    Brouillon par défaut : rien ne devient visible du public sans un
    accord explicite (en_ligne=True). N'écrase jamais rien d'existant."""
    # Le vrai True et rien d'autre : un « oui » flou venu d'un JSON
    # (la chaîne "false", un 1...) ne met JAMAIS en ligne.
    en_ligne = en_ligne is True
    racine = _racine(url)
    if not racine:
        return {"ok": False, "erreur": "Adresse du site manquante."}
    if not (titre or "").strip():
        return {"ok": False, "erreur": "Titre manquant."}
    if not (contenu_html or "").strip():
        return {"ok": False, "erreur": "Contenu manquant."}
    racine = _canonicaliser(racine)
    fiche, erreur = _qui_suis_je(racine, identifiant, mdp_application)
    if erreur:
        return {"ok": False, "erreur": erreur}
    droits = fiche.get("capabilities") or {}
    if droits.get("edit_pages"):
        collection, genre = "pages", "page"
    elif droits.get("edit_posts") or not droits:
        # Droits illisibles : on tente l'article, le site tranchera.
        collection, genre = "posts", "article"
    else:
        return {"ok": False,
                "erreur": ("Le compte fourni ne peut rien publier (rôle "
                           "trop limité). Demander au client de le passer "
                           "en « Auteur », comme dans le guide d'accès.")}
    contenu = (contenu_html if MARQUE_TEXTE in contenu_html
               else MARQUE_HTML + "\n" + contenu_html)
    r = _appel(racine, f"/wp/v2/{collection}", methode="POST",
               identifiant=identifiant, mdp=mdp_application,
               corps={"title": titre, "content": contenu,
                      "status": "publish" if en_ligne else "draft"})
    if (r["status"] in (200, 201) and isinstance(r["json"], dict)
            and r["json"].get("id")):
        return {"ok": True, "erreur": "", "id": r["json"]["id"],
                "genre": genre,
                "statut": "en ligne" if en_ligne else "brouillon",
                "lien": r["json"].get("link", ""), "titre": titre}
    code = (r["json"].get("code", "") if isinstance(r.get("json"), dict)
            else "")
    if code == "rest_cannot_create":
        return {"ok": False,
                "erreur": ("Le site a refusé l'ajout : le compte n'a pas "
                           "le droit de publier ici. Demander au client de "
                           "passer le compte en « Auteur ».")}
    return {"ok": False, "erreur": _erreur_connexion(r)}


def lister_nos_pages(url: str, identifiant: str,
                     mdp_application: str) -> dict:
    """La liste de ce que NOUS avons ajouté chez ce client, et rien
    d'autre : uniquement les contenus signés par notre compte dédié.
    Sert au rapport mensuel et au retrait."""
    racine = _racine(url)
    if not racine:
        return {"ok": False, "erreur": "Adresse du site manquante.",
                "pages": []}
    racine = _canonicaliser(racine)
    fiche, erreur = _qui_suis_je(racine, identifiant, mdp_application)
    if erreur:
        return {"ok": False, "erreur": erreur, "pages": []}
    moi = _entier(fiche.get("id"))
    if moi is None:
        return {"ok": False, "pages": [],
                "erreur": ("Réponse illisible du site (notre compte n'a "
                           "pas de numéro). Réessayer, puis vérifier le "
                           "site avec le client.")}
    pages = []
    for collection, genre in (("pages", "page"), ("posts", "article")):
        # Au-delà de 100 contenus chez un même client on paginerait ;
        # le service en publie quelques-uns par mois, on en est loin.
        r = _appel(racine, f"/wp/v2/{collection}",
                   identifiant=identifiant, mdp=mdp_application,
                   params={"author": moi,
                           "status": "draft,pending,publish",
                           "context": "edit", "per_page": 100})
        if r["status"] == 403:
            # Rayon hors des droits du compte (le rôle « Auteur » ne
            # voit pas les pages) : rien de nous ne peut s'y trouver.
            continue
        if r["status"] != 200 or not isinstance(r["json"], list):
            # Tout autre échec est une vraie panne : dire « rien de
            # nous » serait un mensonge dans le rapport mensuel.
            return {"ok": False, "pages": [],
                    "erreur": ("Impossible de lire la liste des contenus. "
                               + _erreur_connexion(r))}
        for item in r["json"]:
            if _entier(item.get("author")) != moi:
                continue  # ceinture : jamais le contenu d'un autre
            titre = item.get("title")
            if isinstance(titre, dict):
                titre = titre.get("raw") or titre.get("rendered") or ""
            pages.append({
                "id": item.get("id"),
                "genre": genre,
                "titre": titre or "",
                "statut": _STATUTS_FR.get(item.get("status"),
                                          item.get("status") or ""),
                "lien": item.get("link", ""),
                "date": (item.get("date") or "")[:10],
            })
    pages.sort(key=lambda p: p["date"] or "", reverse=True)
    return {"ok": True, "erreur": "", "pages": pages}


def retirer_page(url: str, identifiant: str, mdp_application: str,
                 numero, genre: str = "") -> dict:
    """Retire (met à la corbeille) UN contenu que nous avons ajouté.

    Double verrou avant d'agir : le contenu doit être signé par notre
    compte ET porter la marque Porte-Voix. Tout le reste est refusé,
    même si le compte aurait techniquement le droit. La corbeille de
    WordPress garde le contenu 30 jours : rien n'est définitif."""
    racine = _racine(url)
    if not racine:
        return {"ok": False, "erreur": "Adresse du site manquante."}
    try:
        numero = int(numero)
    except Exception:
        return {"ok": False, "erreur": "Numéro de contenu invalide."}
    racine = _canonicaliser(racine)
    fiche, erreur = _qui_suis_je(racine, identifiant, mdp_application)
    if erreur:
        return {"ok": False, "erreur": erreur}
    moi = _entier(fiche.get("id"))
    if moi is None:
        return {"ok": False,
                "erreur": ("Réponse illisible du site (notre compte n'a "
                           "pas de numéro). Dans le doute, on ne retire "
                           "pas.")}
    collections = {"page": [("pages", "page")],
                   "article": [("posts", "article")]}.get(
        genre, [("pages", "page"), ("posts", "article")])
    item, coll_trouvee, genre_trouve, vu_refus = None, "", "", False
    for collection, g in collections:
        r = _appel(racine, f"/wp/v2/{collection}/{numero}",
                   identifiant=identifiant, mdp=mdp_application,
                   params={"context": "edit"})
        if r["status"] == 200 and isinstance(r["json"], dict):
            item, coll_trouvee, genre_trouve = r["json"], collection, g
            break
        if r["status"] == 403:
            vu_refus = True
    if item is None:
        if vu_refus:
            return {"ok": False,
                    "erreur": ("Refusé : ce contenu n'a pas été ajouté par "
                               "notre compte (le site n'en donne même pas "
                               "la lecture). On ne touche jamais aux "
                               "contenus du client.")}
        return {"ok": False,
                "erreur": (f"Aucun contenu numéro {numero} sur ce site. Il "
                           "a peut-être déjà été retiré.")}
    auteur = _entier(item.get("author"))
    if auteur is None or auteur != moi:
        return {"ok": False,
                "erreur": ("Refusé : ce contenu n'a pas été ajouté par "
                           "notre compte. On ne touche jamais aux contenus "
                           "du client.")}
    brut = item.get("content")
    if isinstance(brut, dict):
        brut = brut.get("raw") or brut.get("rendered") or ""
    if MARQUE_TEXTE not in (brut or ""):
        return {"ok": False,
                "erreur": ("Refusé : ce contenu ne porte pas la marque "
                           "Porte-Voix. Dans le doute, on ne retire pas.")}
    # Jamais de suppression définitive (pas de force=true) : la
    # corbeille de WordPress laisse 30 jours pour se raviser.
    r = _appel(racine, f"/wp/v2/{coll_trouvee}/{numero}", methode="DELETE",
               identifiant=identifiant, mdp=mdp_application)
    if r["status"] == 200:
        return {"ok": True, "erreur": "", "id": numero,
                "genre": genre_trouve, "corbeille": True}
    code = (r["json"].get("code", "") if isinstance(r.get("json"), dict)
            else "")
    if code == "rest_already_trashed":
        return {"ok": True, "erreur": "", "id": numero,
                "genre": genre_trouve, "corbeille": True,
                "note": "était déjà à la corbeille"}
    return {"ok": False, "erreur": _erreur_connexion(r)}


# --------------------------------------------------------- contenu livré

def _nom_fichier(titre: str) -> str:
    nom = re.sub(r"[^a-z0-9]+", "-", moteur.normaliser(titre)).strip("-")
    return nom[:60] or "contenu"


def generer_livrable(titre: str, contenu_html: str, dossier) -> dict:
    """Le mode « contenu livré » : pour les clients sans WordPress, ou
    qui préfèrent garder la main. Fabrique un fichier prêt à coller et
    un mode d'emploi en français simple, à transmettre tels quels au
    client ou à la personne qui s'occupe de son site."""
    if not (titre or "").strip():
        return {"ok": False, "erreur": "Titre manquant."}
    if not (contenu_html or "").strip():
        return {"ok": False, "erreur": "Contenu manquant."}
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    nom = _nom_fichier(titre)
    contenu = (contenu_html if MARQUE_TEXTE in contenu_html
               else MARQUE_HTML + "\n" + contenu_html)
    contenu = contenu.strip() + "\n"
    # Deux exemplaires du même contenu : le .html pour VOIR la page dans
    # un navigateur, le .txt pour COPIER le contenu (il s'ouvre en texte
    # brut d'un double-clic, sur PC comme sur Mac, là où un .html
    # s'afficherait mis en forme).
    chemin_html = dossier / f"{nom}.html"
    chemin_html.write_text(contenu, encoding="utf-8")
    chemin_texte = dossier / f"{nom}-a-coller.txt"
    chemin_texte.write_text(contenu, encoding="utf-8")
    date_txt = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    mode_demploi = f"""VOTRE NOUVEAU CONTENU : {titre}
Préparé le {date_txt} par Porte-Voix, un service de Triskell Studio.

CE QUE C'EST
Un nouveau contenu pour votre site, prêt à l'emploi. Il S'AJOUTE à
votre site : il ne remplace rien, il ne modifie rien d'existant.
- "{nom}.html" : l'aperçu. Double-cliquez dessus pour voir la page
  dans votre navigateur.
- "{nom}-a-coller.txt" : le contenu à copier, en version texte. Il
  s'ouvre d'un double-clic, sur PC comme sur Mac.

COMMENT L'AJOUTER (environ 5 minutes)

Si votre site est un WordPress :
 1. Ouvrez le fichier "{nom}-a-coller.txt" d'un double-clic.
 2. Sélectionnez tout (Ctrl+A, ou Cmd+A sur Mac), puis copiez
    (Ctrl+C, ou Cmd+C sur Mac).
 3. Dans WordPress, ouvrez "Pages" puis "Ajouter une page".
 4. Donnez-lui ce titre : {titre}
 5. Passez la zone de texte en mode code : le menu aux trois petits
    points, en haut à droite de l'écran, puis "Éditeur de code".
    Si vous voyez plutôt deux onglets "Visuel" et "Texte" au-dessus
    de la zone de texte, cliquez sur "Texte".
 6. Collez le texte copié (Ctrl+V, ou Cmd+V sur Mac).
 7. Cliquez sur "Publier", puis confirmez en cliquant une seconde
    fois sur "Publier". C'est terminé.

Si votre site n'est pas un WordPress, ou si quelqu'un s'en occupe pour
vous : transmettez-lui ce dossier tel quel. Ces fichiers lui suffisent,
il saura quoi en faire.

POUR LE RETIRER UN JOUR
Supprimez simplement la page "{titre}" de votre site. Rien d'autre
n'est touché.

UNE QUESTION, UN DOUTE ?
Écrivez-nous : contact@triskell-studio.fr. On s'en occupe.
"""
    chemin_note = dossier / f"{nom}-mode-demploi.txt"
    chemin_note.write_text(mode_demploi, encoding="utf-8")
    return {"ok": True, "erreur": "", "nom": nom,
            "html": str(chemin_html), "a_coller": str(chemin_texte),
            "mode_demploi": str(chemin_note)}
