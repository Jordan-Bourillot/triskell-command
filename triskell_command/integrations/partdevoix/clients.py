"""Registre local des clients Porte-Voix suivis.

La source unique est le fichier ~/.triskell-command/partdevoix_clients.json :
aucune donnée de client en dur dans le code. Chaque fiche porte
l'entreprise, le métier, la ou les villes, les concurrents désignés
(3 au maximum : ceux que le client veut voir dans son rapport), les
questions personnalisées éventuelles (sinon les formulations d'audit du
métier servent), le palier d'abonnement et la date d'entrée.

Un client désactivé (résiliation, pause) reste dans le fichier — son
historique de mesures garde un sens — mais sort des listes de travail.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import audit, moteur

logger = logging.getLogger(__name__)

FICHIER = Path.home() / ".triskell-command" / "partdevoix_clients.json"

# Le rapport compare le client à SES concurrents désignés : au-delà de
# trois, la page devient un annuaire et la comparaison perd son sens.
MAX_CONCURRENTS = 3

# Les champs modifiables après coup. Le reste (id, date de création) est
# figé : l'historique des relevés est accroché à l'id.
_CHAMPS_MODIFIABLES = {"entreprise", "metier", "villes", "concurrents",
                       "questions", "palier", "entree_le", "actif",
                       "fait", "avenir"}


def _charger() -> list:
    try:
        return json.loads(FICHIER.read_text(encoding="utf-8"))
    except Exception:
        return []


def _sauver(entrees: list) -> None:
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    FICHIER.write_text(json.dumps(entrees, ensure_ascii=False, indent=1),
                       encoding="utf-8")


def _slug(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = re.sub(r"[^a-z0-9]+", "-", texte.lower()).strip("-")
    return texte[:40] or "client"


def _en_liste(valeur) -> list[str]:
    """Accepte une chaîne ou une liste, rend une liste de textes propres."""
    if isinstance(valeur, str):
        valeur = [valeur]
    return [str(v).strip() for v in (valeur or []) if str(v).strip()]


def _verifier_concurrents(entreprise: str, concurrents: list[str]) -> None:
    """Refuse un concurrent qui se confond avec le client ou avec un
    autre concurrent désigné : l'agrégation du moteur fusionnerait les
    libellés voisins et le rapport montrerait deux fois le même chiffre
    sous deux noms."""
    for i, nom in enumerate(concurrents):
        if moteur.correspond(entreprise, nom):
            raise ValueError(
                f"le concurrent « {nom} » se confond avec le client "
                f"« {entreprise} » (même nom au sens large) : la mesure "
                f"leur donnerait le même chiffre")
        for autre in concurrents[i + 1:]:
            if moteur.correspond(nom, autre):
                raise ValueError(
                    f"les concurrents « {nom} » et « {autre} » se "
                    f"confondent (même nom au sens large) : n'en garder "
                    f"qu'un")


def _trouver_dans(entrees: list, ident: str) -> dict | None:
    """Fiche par id exact, sinon par nom d'entreprise (les actifs d'abord)."""
    ident = (ident or "").strip()
    if not ident:
        return None
    for e in entrees:
        if e.get("id") == ident:
            return e
    for lot in ([e for e in entrees if e.get("actif", True)],
                [e for e in entrees if not e.get("actif", True)]):
        for e in lot:
            if moteur.correspond(e.get("entreprise") or "", ident):
                return e
    return None


def ajouter_client(entreprise: str, metier: str, villes,
                   concurrents=None, questions=None, palier: str = "",
                   entree_le: str = "") -> dict:
    """Crée la fiche d'un client suivi et la renvoie.

    Refuse les doublons parmi les clients ACTIFS (même entreprise au sens
    de moteur.correspond) : un ancien client résilié peut revenir, sa
    nouvelle fiche prend alors un id distinct."""
    entreprise = (entreprise or "").strip()
    if not entreprise:
        raise ValueError("l'entreprise est obligatoire")
    if not (metier or "").strip():
        raise ValueError("le métier est obligatoire")
    villes = _en_liste(villes)
    if not villes:
        raise ValueError("au moins une ville est obligatoire")
    concurrents = _en_liste(concurrents)
    if len(concurrents) > MAX_CONCURRENTS:
        raise ValueError(f"{MAX_CONCURRENTS} concurrents désignés au maximum")
    _verifier_concurrents(entreprise, concurrents)
    entrees = _charger()
    for e in entrees:
        if e.get("actif", True) and moteur.correspond(
                e.get("entreprise") or "", entreprise):
            raise ValueError(
                f"un client actif porte déjà ce nom : {e.get('entreprise')} "
                f"(id {e.get('id')})")
    base = _slug(entreprise)
    existants = {e.get("id") for e in entrees}
    ident, n = base, 2
    while ident in existants:
        ident, n = f"{base}-{n}", n + 1
    client = {
        "id": ident,
        "entreprise": entreprise,
        "metier": metier.strip(),
        "villes": villes,
        "concurrents": concurrents,
        "questions": _en_liste(questions),
        "palier": (palier or "").strip(),
        "entree_le": ((entree_le or "").strip()
                      or datetime.now(timezone.utc).date().isoformat()),
        "actif": True,
        # Rubriques libres du prochain rapport, posées au fil du mois.
        "fait": [],
        "avenir": [],
        "cree_ts": datetime.now(timezone.utc).isoformat(),
    }
    entrees.append(client)
    _sauver(entrees)
    logger.info("partdevoix client ajouté : %s", ident)
    return client


def lister_clients(actifs: bool = True) -> list[dict]:
    """Les fiches du registre (par défaut : les clients actifs seulement)."""
    entrees = _charger()
    if actifs:
        entrees = [e for e in entrees if e.get("actif", True)]
    return entrees


def trouver_client(ident: str) -> dict | None:
    """Retrouve une fiche par id exact, sinon par nom d'entreprise."""
    return _trouver_dans(_charger(), ident)


def modifier_client(ident: str, **champs) -> dict:
    """Modifie une fiche existante (seuls les champs prévus passent).
    Les garde-fous de l'ajout rejouent : doublon parmi les actifs (au
    renommage comme à la réactivation), concurrents qui se confondent."""
    inconnus = set(champs) - _CHAMPS_MODIFIABLES
    if inconnus:
        raise ValueError(f"champ(s) inconnu(s) : {', '.join(sorted(inconnus))}")
    entrees = _charger()
    client = _trouver_dans(entrees, ident)
    if client is None:
        raise ValueError(f"client introuvable : {ident}")
    propres = {}
    for nom, valeur in champs.items():
        if nom in {"villes", "concurrents", "questions", "fait", "avenir"}:
            valeur = _en_liste(valeur)
            if nom == "villes" and not valeur:
                raise ValueError("au moins une ville est obligatoire")
            if nom == "concurrents" and len(valeur) > MAX_CONCURRENTS:
                raise ValueError(
                    f"{MAX_CONCURRENTS} concurrents désignés au maximum")
        elif nom == "actif":
            valeur = bool(valeur)
        else:
            valeur = str(valeur or "").strip()
            if nom in {"entreprise", "metier"} and not valeur:
                raise ValueError(f"le champ {nom} ne peut pas être vide")
        propres[nom] = valeur
    if "entreprise" in propres or "concurrents" in propres:
        _verifier_concurrents(
            propres.get("entreprise", client.get("entreprise") or ""),
            propres.get("concurrents", client.get("concurrents") or []))
    if ("entreprise" in propres
            or (propres.get("actif") and not client.get("actif", True))):
        entreprise_finale = propres.get(
            "entreprise", client.get("entreprise") or "")
        for autre in entrees:
            if (autre is not client and autre.get("actif", True)
                    and moteur.correspond(
                        autre.get("entreprise") or "", entreprise_finale)):
                raise ValueError(
                    f"un client actif porte déjà ce nom : "
                    f"{autre.get('entreprise')} (id {autre.get('id')})")
    client.update(propres)
    _sauver(entrees)
    return client


def desactiver_client(ident: str) -> dict:
    """Sort un client des listes de travail (historique conservé)."""
    return modifier_client(ident, actif=False)


def questions_du_client(client: dict) -> list[str]:
    """Les questions à poser pour ce client : les siennes si on lui en a
    posé, sinon les formulations d'audit de son métier, ville par ville.
    NE PAS reformuler en cours de suivi : la comparaison d'un mois à
    l'autre exige des questions strictement identiques."""
    perso = _en_liste(client.get("questions"))
    if perso:
        return perso
    questions: list[str] = []
    for ville in _en_liste(client.get("villes")):
        for q in audit.questions_pour(client.get("metier") or "", ville):
            if q not in questions:
                questions.append(q)
    return questions
