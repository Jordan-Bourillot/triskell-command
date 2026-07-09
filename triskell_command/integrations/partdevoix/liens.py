"""Index des audits Porte-Voix générés par prospect.

Le générateur d'audits enregistre ici « cette fiche → cette page d'audit »,
et le moteur de mails vient y chercher {lien_audit} au moment de l'envoi.
Best-effort assumé : fiche inconnue = lien vers l'accueil, jamais un trou
dans un mail.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import moteur

logger = logging.getLogger(__name__)

FICHIER = Path.home() / ".triskell-command" / "partdevoix_liens.json"
BASE_URL = "https://portevoix.triskell-studio.fr"


def _charger() -> list:
    try:
        return json.loads(FICHIER.read_text(encoding="utf-8"))
    except Exception:
        return []


def enregistrer_lien(email: str, entreprise: str, ville: str,
                     url: str, issue: str = "") -> None:
    """Mémorise l'audit généré pour une fiche (écrase l'ancien s'il y en a un)."""
    entrees = _charger()
    cle_mail = (email or "").strip().lower()
    entrees = [e for e in entrees
               if not (cle_mail and (e.get("email") or "").lower() == cle_mail)
               and not (not cle_mail
                        and moteur.correspond(e.get("entreprise") or "",
                                              entreprise)
                        and moteur.normaliser(e.get("ville") or "")
                        == moteur.normaliser(ville))]
    entrees.append({
        "email": cle_mail,
        "entreprise": entreprise or "",
        "ville": ville or "",
        "url": url,
        "issue": issue,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    FICHIER.write_text(json.dumps(entrees, ensure_ascii=False, indent=1),
                       encoding="utf-8")


def issue_for(email: str = "", entreprise: str = "", ville: str = "") -> str:
    """L'issue de l'audit d'une fiche ('concurrents', 'deja_cite', 'vide')
    ou "" si aucun audit n'a été généré. Sert à l'aiguillage des modèles :
    on n'écrit jamais « vous n'apparaissez pas » à quelqu'un qui apparaît."""
    entrees = _charger()
    cle_mail = (email or "").strip().lower()
    if cle_mail:
        for e in reversed(entrees):
            if (e.get("email") or "").lower() == cle_mail:
                return e.get("issue") or ""
    if (entreprise or "").strip():
        for e in reversed(entrees):
            if (moteur.correspond(e.get("entreprise") or "", entreprise)
                    and (not ville or moteur.normaliser(e.get("ville") or "")
                         == moteur.normaliser(ville))):
                return e.get("issue") or ""
    return ""


def audit_url_for(email: str = "", entreprise: str = "",
                  ville: str = "") -> str:
    """L'adresse de l'audit d'une fiche. Priorité au mail (identifiant le
    plus sûr), sinon entreprise+ville. Introuvable = "" (l'appelant met
    son propre repli)."""
    entrees = _charger()
    cle_mail = (email or "").strip().lower()
    if cle_mail:
        for e in reversed(entrees):
            if (e.get("email") or "").lower() == cle_mail:
                return e.get("url") or ""
    if (entreprise or "").strip():
        for e in reversed(entrees):
            if (moteur.correspond(e.get("entreprise") or "", entreprise)
                    and (not ville or moteur.normaliser(e.get("ville") or "")
                         == moteur.normaliser(ville))):
                return e.get("url") or ""
    return ""
