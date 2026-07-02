"""Résolveur central des modèles de mails TRANSACTIONNELS.

Point d'entrée unique pour que les expéditeurs (Pixel Pros, relances J+7/J+30,
après-vente…) lisent leur modèle depuis la table éditable
`triskell_email_templates` (category='transactionnel'), la MÊME que Jordan
édite dans l'écran « Modèles mails ». But : un seul endroit pour gérer tous
les mails, au lieu d'un tiroir séparé par produit.

🔒 RÈGLE DE SÉCURITÉ ABSOLUE (mails clients en production) : on ne renvoie un
modèle QUE s'il est complet et activé (sujet + au moins un corps). Le moindre
doute ou la moindre panne → None, et l'appelant GARDE son comportement actuel
(repli sur son modèle par défaut). Conséquence : tant qu'aucun modèle central
n'a été créé/édité, RIEN ne change pour personne.

L'appelant applique SES PROPRES placeholders sur le texte renvoyé (chaque
expéditeur a ses variables : {firstname}/{business} pour Pixel Pros,
{name}/{signature} pour les relances…). Le résolveur ne rend rien lui-même.
"""
from __future__ import annotations

import html as _html
import logging
import re as _re

logger = logging.getLogger(__name__)


def html_to_text(html_body: str) -> str:
    """Convertit un corps HTML en texte propre pour un mail texte.

    L'éditeur « Modèles mails » met le contenu principal dans le champ HTML.
    Quand un expéditeur envoie en TEXTE (relances, après-vente), il faut donc
    aplatir ce HTML : sauts de ligne pour <br>/</p>, balises retirées, PUIS
    décodage de TOUTES les entités (accents &eacute;, guillemets &laquo;,
    codes &#233;…) via html.unescape — jamais un décodage maison partiel qui
    laisserait « R&eacute;serv&eacute; » chez le client.
    """
    h = html_body or ""
    h = _re.sub(r"(?i)<br\s*/?>", "\n", h)
    h = _re.sub(r"(?i)</p\s*>", "\n\n", h)
    h = _re.sub(r"<[^>]+>", "", h)
    # unescape décode TOUTES les entités (accents, guillemets, codes &#233;…) ;
    # l'espace insécable (&nbsp; → \xa0) redevient une espace normale, plus
    # propre dans un mail texte.
    return _html.unescape(h).replace("\xa0", " ").strip()


def safe_format(template: str, values: dict) -> str:
    """Remplace les placeholders {clef} un par un, sans str.format().

    str.format() plante dès qu'une accolade littérale ({, }, emoji, JSON) ou un
    placeholder mal orthographié traîne dans un modèle édité par Jordan. On fait
    donc un simple remplacement clef par clef : un modèle central s'affiche
    TOUJOURS (accolades littérales gardées), aucune exception, comportement
    identique au moteur Pixel Pros (_safe_format). Un placeholder inconnu reste
    visible tel quel — signal lisible d'une faute de frappe, jamais un crash.
    """
    out = template or ""
    for k, v in (values or {}).items():
        out = out.replace("{" + str(k) + "}", str(v))
    return out


def _sb():
    # La table vit sur la base partagée ; on réutilise le client déjà utilisé
    # par l'éditeur (lagriffe/repo), par convention historique.
    try:
        from .lagriffe.repo import _sb as lagriffe_sb
        return lagriffe_sb()
    except Exception as exc:
        logger.debug("mail_templates_resolver._sb: %s", exc)
        return None


def get_transactional(product: str, key: str) -> dict | None:
    """Modèle central (product, key, category='transactionnel') s'il est
    COMPLET et ACTIVÉ, sinon None (l'appelant garde son repli).

    Renvoie {subject, body_text, body_html, from_address} — chaînes prêtes à
    recevoir les placeholders de l'appelant.
    """
    product = (product or "").strip()
    key = (key or "").strip()
    if not product or not key:
        return None
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("triskell_email_templates")
                  .select("subject, body_text, body_html, from_address, "
                          "enabled, category")
                  .eq("product", product)
                  .eq("key", key)
                  .limit(1)
                  .execute().data) or []
    except Exception as exc:
        logger.debug("mail_templates_resolver(%s,%s): %s", product, key, exc)
        return None
    if not rows:
        return None
    r = rows[0]
    # Désactivé, ou pas transactionnel → on ne s'en sert pas.
    if r.get("enabled") is False:
        return None
    if (r.get("category") or "transactionnel") != "transactionnel":
        return None
    subject = (r.get("subject") or "").strip()
    body_text = (r.get("body_text") or "").strip()
    body_html = (r.get("body_html") or "").strip()
    # Incomplet → repli (jamais un mail au sujet vide chez un client).
    if not subject or not (body_text or body_html):
        return None
    return {
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
        "from_address": (r.get("from_address") or "").strip(),
    }
