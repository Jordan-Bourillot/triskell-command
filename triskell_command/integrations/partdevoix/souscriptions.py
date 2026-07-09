"""Souscription Porte-Voix : du formulaire du site au client suivi.

Le parcours voulu par Jordan (09/07/2026) : le visiteur remplit le
formulaire de souscription sur portevoix.triskell-studio.fr, PAIE à ce
moment-là (abonnement Stripe), et sa fiche se crée TOUTE SEULE dans
l'écran Porte-Voix, première mesure lancée, notification à Jordan.
Plus aucun geste entre « il paie » et « son point de référence ».

Deux moitiés :
- creer_session(donnees) : appelée par l'endpoint public pdv_souscrire,
  crée la session de paiement Stripe (abonnement mensuel, prix définis
  ICI via price_data : rien à créer à la main dans Stripe) avec les
  réponses du formulaire en metadata. La fiche n'est PAS créée à ce
  stade : un formulaire abandonné ne laisse aucune trace.
- traiter_event(event) : appelée par le webhook Stripe central
  (billing_saas.webhook), reconnaît NOS sessions (metadata.portevoix),
  crée la fiche, lance la première mesure, prévient Jordan. Idempotent :
  Stripe peut rejouer l'évènement sans créer de doublon.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

SITE = "https://portevoix.triskell-studio.fr"

# Les offres du site (souscrire.html). Les prix vivent ici : la session
# Stripe est créée avec price_data, aucun produit à poser à la main.
OFFRES = {
    "presence":   {"label": "Présence",   "prix_euros": 149},
    "position":   {"label": "Position",   "prix_euros": 290},
    "territoire": {"label": "Territoire", "prix_euros": 449},
    "agences":    {"label": "Agences",    "prix_euros": 290},
}


def _texte(donnees: dict, cle: str) -> str:
    return str((donnees or {}).get(cle) or "").strip()


def valider(donnees: dict) -> dict:
    """Contrôle les réponses du formulaire AVANT tout appel Stripe.
    Renvoie les champs propres, lève ValueError en français sinon."""
    propres = {cle: _texte(donnees, cle)
               for cle in ("offre", "entreprise", "metier", "ville",
                           "site", "email")}
    if propres["offre"] not in OFFRES:
        raise ValueError("offre inconnue : choisir une formule sur la page")
    for cle, nom in (("entreprise", "le nom de l'entreprise"),
                     ("metier", "le métier"),
                     ("ville", "la ville"),
                     ("email", "l'adresse mail")):
        if not propres[cle]:
            raise ValueError(f"il manque {nom}")
    email = propres["email"].lower()
    if "@" not in email or " " in email or "." not in email.split("@")[-1]:
        raise ValueError(f"adresse mail invalide : « {propres['email']} »")
    propres["email"] = email
    return propres


def creer_session(donnees: dict) -> dict:
    """Crée la session de paiement Stripe (abonnement mensuel) et renvoie
    l'adresse vers laquelle le site redirige le visiteur."""
    propres = valider(donnees)
    offre = OFFRES[propres["offre"]]
    from ..billing_saas.checkout import _stripe
    stripe = _stripe()
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{
            "quantity": 1,
            "price_data": {
                "currency": "eur",
                "unit_amount": offre["prix_euros"] * 100,
                "recurring": {"interval": "month"},
                "product_data": {
                    "name": f"Porte-Voix · {offre['label']}",
                    "description": ("Suivi mensuel de part de voix dans "
                                    "les réponses des IA"),
                },
            },
        }],
        success_url=f"{SITE}/merci.html",
        cancel_url=f"{SITE}/souscrire.html",
        customer_email=propres["email"],
        metadata={"portevoix": "1", **propres},
        subscription_data={"metadata": {
            "portevoix": "1", "entreprise": propres["entreprise"]}},
        allow_promotion_codes=True,
        billing_address_collection="required",
    )
    return {"ok": True, "url": session.url}


# ------------------------------------------------------------- webhook

def traiter_event(event: dict) -> dict:
    """Branche Porte-Voix du webhook Stripe central. Ne regarde QUE nos
    sessions (metadata.portevoix). Un client déjà suivi n'est jamais
    recréé (rejeu Stripe, deuxième souscription du même cabinet…) : la
    souscription est alors signalée à Jordan au lieu d'écraser quoi que
    ce soit."""
    if event.get("type") != "checkout.session.completed":
        return {"processed": False}
    session = (event.get("data") or {}).get("object") or {}
    meta = session.get("metadata") or {}
    if meta.get("portevoix") != "1":
        return {"processed": False}

    email = (meta.get("email")
             or (session.get("customer_details") or {}).get("email")
             or session.get("customer_email") or "")
    offre = OFFRES.get(meta.get("offre") or "")
    palier = (f"{offre['label']} · {offre['prix_euros']} €/mois"
              if offre else (meta.get("offre") or ""))

    from . import clients as registre
    fiche, cree, souci = None, False, ""
    try:
        fiche = registre.ajouter_client(
            meta.get("entreprise") or "",
            meta.get("metier") or "",
            meta.get("ville") or "",
            palier=palier,
            email=email)
        cree = True
    except ValueError as exc:
        # Doublon (rejeu du webhook, client déjà suivi) ou donnée
        # invalide : le paiement est passé, on ne perd RIEN — Jordan est
        # prévenu et tranche depuis l'écran.
        souci = str(exc)
        logger.warning("souscription portevoix (%s) : %s",
                       meta.get("entreprise"), souci)
        try:
            fiche = registre.trouver_client(meta.get("entreprise") or "")
        except Exception:
            fiche = None

    if cree and fiche:
        _premiere_mesure(fiche)
    _prevenir(meta, palier, cree, souci)
    return {"processed": True, "cree": cree,
            "client_id": (fiche or {}).get("id") or "", "souci": souci}


def _premiere_mesure(fiche: dict) -> None:
    """Le point de référence part tout seul, en arrière-plan (le webhook
    doit répondre vite à Stripe)."""
    def _travail():
        try:
            from . import rapport
            rapport.mesurer_client(fiche, passes=3)
            donnees = rapport.generer_rapport(fiche)
            rapport.archiver_rapport(donnees)
        except Exception as exc:
            logger.warning("première mesure %s: %s", fiche.get("id"), exc)
    threading.Thread(target=_travail, daemon=True,
                     name=f"pdv-souscription-{fiche.get('id')}").start()


def _prevenir(meta: dict, palier: str, cree: bool, souci: str) -> None:
    """Notification à Jordan : un client vient de payer."""
    try:
        from ...web.push import send_push
        entreprise = meta.get("entreprise") or "?"
        if cree:
            titre = f"🎉 Nouveau client Porte-Voix : {entreprise}"
            corps = (f"{palier}. Fiche créée toute seule, première mesure "
                     f"en cours. Pense à ses 3 concurrents à suivre.")
            priorite = "normal"
        else:
            titre = f"⚠ Souscription Porte-Voix à vérifier : {entreprise}"
            corps = (f"Paiement reçu ({palier}) mais fiche non créée : "
                     f"{souci or 'raison inconnue'}.")
            priorite = "urgent"
        send_push(title=titre, body=corps, user_id="jordan",
                  url="/#portevoix", priority=priorite, tag_group="clients")
    except Exception as exc:  # la notification ne bloque jamais le webhook
        logger.warning("souscription push: %s", exc)
