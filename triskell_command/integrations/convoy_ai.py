"""Le Convoi — couche IA : structuration des prospects + génération de mails.

Deux fonctions principales :

1. `extract_prospects(text, ...)` :
   transforme un texte brut (issu d'un PDF / Word / Excel / Image) en une
   liste de dicts structurés (nom, email, téléphone, secteur, ville, etc.)
   en demandant à l'IA configurée dans Triskell Command de retourner du JSON.

2. `generate_message(prospect, template, catalog, ...)` :
   pour 1 prospect donné, choisit dans le catalogue l'offre la plus adaptée
   à son secteur, injecte les variables du template, demande à l'IA d'écrire
   le mail final personnalisé.

L'IA est appelée via `triskell_core.ai.providers.send_to_provider`, qui sait
parler à Anthropic / OpenAI / Google / Mistral / xAI.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Champs canoniques d'un prospect Convoi
# ---------------------------------------------------------------------------
PROSPECT_FIELDS = [
    "raison_sociale",   # nom de l'entreprise / structure
    "prenom",           # contact
    "nom",              # contact
    "email",
    "telephone",
    "site_web",
    "adresse",
    "ville",
    "code_postal",
    "secteur",          # secteur d'activité / type de chantier
    "notes",            # autre info pertinente détectée
]


REQUIRED_FOR_SEND = ["email"]   # un prospect doit au minimum avoir un email pour partir
RECOMMENDED = ["raison_sociale", "secteur"]   # signalées si manquantes (≠ bloquantes)


# ---------------------------------------------------------------------------
# Extraction structurée via IA
# ---------------------------------------------------------------------------
EXTRACTION_PROMPT = """Tu es un assistant qui transforme un texte brut (issu d'un fichier PDF, Word, Excel, image OCR ou listing texte) en une liste structurée de prospects.

VOICI LE TEXTE BRUT À ANALYSER :
<<<
{raw_text}
>>>

Indices déjà extraits par regex (peuvent être incomplets ou bruités) :
- Emails détectés : {emails}
- Téléphones détectés : {phones}
- URLs détectées : {urls}

INSTRUCTIONS :
1. Identifie chaque prospect distinct dans le texte.
2. Pour chaque prospect, extrais ces champs (vide si non disponible) :
   - raison_sociale : nom de l'entreprise / structure
   - prenom : prénom du contact si visible
   - nom : nom de famille du contact si visible
   - email : 1 seul, prioritaire celui qui correspond au prospect
   - telephone : 1 seul, format brut tel qu'écrit
   - site_web : URL du site officiel si visible
   - adresse : rue + numéro
   - ville
   - code_postal
   - secteur : secteur d'activité ou type de chantier (ex: "électricité", "plomberie", "rénovation cuisine", "agence digitale", "boulangerie")
   - notes : autre info utile (taille, spécialité, contexte précisé)

3. RÉPONDS UNIQUEMENT AVEC UN JSON VALIDE, sans texte autour, sans markdown, sans bloc ```.
   Format strict :
   {{"prospects": [{{"raison_sociale": "...", "prenom": "...", ...}}, ...]}}

4. Si tu n'es pas sûr d'un champ, laisse-le vide ("") plutôt que d'inventer.
5. Si le texte ne contient aucun prospect identifiable, renvoie {{"prospects": []}}.
"""


def extract_prospects(
    raw_text: str,
    *,
    emails_hint: list[str] | None = None,
    phones_hint: list[str] | None = None,
    urls_hint: list[str] | None = None,
    provider: str,
    model: str,
    api_keys: dict[str, str],
    max_chars: int = 24_000,
) -> list[dict[str, str]]:
    """Demande à l'IA de structurer le texte en liste de prospects.

    `max_chars` : on tronque si le fichier est gigantesque pour éviter de
    dépasser le contexte du modèle. L'utilisateur sera averti si tronqué.
    """
    text = raw_text or ""
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[…texte tronqué pour rester dans le contexte du modèle…]"

    prompt = EXTRACTION_PROMPT.format(
        raw_text=text,
        emails=", ".join(emails_hint or []) or "(aucun)",
        phones=", ".join(phones_hint or []) or "(aucun)",
        urls=", ".join(urls_hint or []) or "(aucune)",
    )

    response = _call_ai(prompt, provider=provider, model=model, api_keys=api_keys)
    data = _parse_json_lenient(response)
    if not isinstance(data, dict):
        logger.warning("Réponse IA non-dict : %r", response[:200])
        return []
    items = data.get("prospects", [])
    if not isinstance(items, list):
        return []
    out: list[dict[str, str]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        cleaned = {k: _stringify(raw.get(k, "")) for k in PROSPECT_FIELDS}
        if any(cleaned.values()):
            out.append(cleaned)
    return out


# ---------------------------------------------------------------------------
# Catalogue d'offres + matching secteur → offre
# ---------------------------------------------------------------------------
def pick_offer_for_sector(sector: str, catalog: list[dict[str, str]]) -> dict[str, str]:
    """Sélectionne dans le catalogue l'offre dont les mots-clés matchent
    le mieux le secteur du prospect.

    Stratégie :
    1. Match parfait : keyword exact dans le secteur (« électricien » dans
       « Électricien tous corps de métier ») → score le plus haut
    2. Match partiel : racine du keyword (≥ 4 lettres) dans le secteur
       (« électric » dans « électricité générale ») → score moyen
    3. Match inverse : secteur dans un keyword (« plombier » dans
       « plombier-chauffagiste ») → score faible
    4. Fallback : si vraiment 0 match, on choisit le produit le plus
       GÉNÉRIQUE du catalogue (celui avec le plus de keywords variés)
       au lieu du 1er.

    Format attendu d'une entrée catalogue :
        {
            "name": "Pack Électricien Pro",
            "pitch": "Site + outils pour électriciens",
            "keywords": "électricien, électricité, artisan bâtiment, BTP",
            "url": "https://pack-elec.triskell-studio.fr",
        }
    """
    if not catalog:
        return {}
    sector_lc = (sector or "").lower().strip()

    # Choix du fallback générique = produit avec le plus de keywords variés
    # (= le plus "couvrant"). Si plusieurs ex-aequo, on prend le 1er.
    def _generic_fallback() -> dict[str, str]:
        best_count = -1
        chosen = catalog[0]
        for offer in catalog:
            if not isinstance(offer, dict):
                continue
            kws = offer.get("keywords") or ""
            count = len([k for k in re.split(r"[,\n;]+", kws) if k.strip()])
            if count > best_count:
                best_count = count
                chosen = offer
        return chosen

    if not sector_lc:
        return _generic_fallback()

    best: dict[str, str] = {}
    best_score = 0
    for offer in catalog:
        if not isinstance(offer, dict):
            continue
        kws = (offer.get("keywords") or "").lower()
        if not kws:
            continue
        score = 0
        for kw in re.split(r"[,\n;]+", kws):
            kw = kw.strip()
            if not kw:
                continue
            # 1. Match parfait : keyword tel quel dans le secteur
            if kw in sector_lc:
                score += 3
                continue
            # 2. Match partiel : racine du keyword (sans suffixes courants)
            #    si ≥ 4 lettres pour éviter les faux positifs ("le", "un"...)
            root = re.sub(r"(?:s|es|ier|iere|iste|ique|isme|age|aire)$",
                           "", kw)
            if len(root) >= 4 and root in sector_lc:
                score += 2
                continue
            # 3. Match inverse : le secteur (ou un mot du secteur) apparaît
            #    dans le keyword
            for tok in re.split(r"\s+", sector_lc):
                if len(tok) >= 4 and tok in kw:
                    score += 1
                    break
        if score > best_score:
            best_score = score
            best = offer
    if not best or best_score == 0:
        return _generic_fallback()
    return best


# ---------------------------------------------------------------------------
# Génération du message personnalisé
# ---------------------------------------------------------------------------
GENERATION_PROMPT = """Tu es {sender_name}, et tu écris un email de prospection court et naturel.

CONTEXTE DU PROSPECT :
- Raison sociale : {raison_sociale}
- Contact : {prenom} {nom}
- Email : {email}
- Ville : {ville} ({code_postal})
- Secteur d'activité / type de chantier : {secteur}
- Notes : {notes}

OFFRE QUE TU PROPOSES (adaptée à son secteur) :
- Nom : {offer_name}
- Pitch : {offer_pitch}
- Lien : {offer_url}

CONSIGNES STRICTES :
- Ton : direct, chaleureux, pro, jamais commercial agressif.
- Longueur : 5 à 10 lignes max.
- Pas de "J'espère que vous allez bien" ni autre formule creuse.
- Si tu connais le prénom : tu tutoies ou vouvoies selon ce qui est plus naturel pour le secteur.
- Si tu ne connais que la raison sociale : adresse-toi à l'entreprise.
- Mentionne UNE raison spécifique pour laquelle ton offre colle à leur métier.
- Termine par un CTA simple (réponse à ce mail, ou lien à cliquer).
- Signature : "{sender_name}" sur la dernière ligne, rien après.

INSTRUCTIONS LIBRES DE L'UTILISATEUR (à respecter en priorité si elles entrent en conflit) :
{user_brief}

RÉPONDS AU FORMAT JSON STRICT (pas de markdown, pas de texte autour) :
{{"subject": "<objet du mail, 4-8 mots>", "body": "<corps complet du mail>"}}
"""


def generate_message(
    prospect: dict[str, str],
    *,
    catalog: list[dict[str, str]],
    sender_name: str,
    user_brief: str,
    provider: str,
    model: str,
    api_keys: dict[str, str],
) -> dict[str, str]:
    """Renvoie {'subject': '...', 'body': '...', 'offer_name': '...'}."""
    offer = pick_offer_for_sector(prospect.get("secteur", ""), catalog)
    prompt = GENERATION_PROMPT.format(
        raison_sociale=prospect.get("raison_sociale", "") or "(non précisé)",
        prenom=prospect.get("prenom", ""),
        nom=prospect.get("nom", ""),
        email=prospect.get("email", ""),
        ville=prospect.get("ville", "") or "—",
        code_postal=prospect.get("code_postal", ""),
        secteur=prospect.get("secteur", "") or "(non précisé)",
        notes=prospect.get("notes", "") or "(aucune)",
        offer_name=offer.get("name", "") or "(catalogue vide)",
        offer_pitch=offer.get("pitch", ""),
        offer_url=offer.get("url", ""),
        sender_name=sender_name or "L'équipe",
        user_brief=user_brief.strip() or "(aucune instruction supplémentaire)",
    )
    response = _call_ai(prompt, provider=provider, model=model, api_keys=api_keys)
    data = _parse_json_lenient(response)
    if not isinstance(data, dict):
        # Fallback : on récupère un objet plausible si l'IA a parlé en clair
        return {
            "subject": _fallback_subject(prospect, offer),
            "body": response.strip() or "(génération vide)",
            "offer_name": offer.get("name", ""),
        }
    return {
        "subject": _stringify(data.get("subject", "")) or _fallback_subject(prospect, offer),
        "body": _stringify(data.get("body", "")) or "(génération vide)",
        "offer_name": offer.get("name", ""),
    }


def _fallback_subject(prospect: dict[str, str], offer: dict[str, str]) -> str:
    raison = prospect.get("raison_sociale", "")
    if raison:
        return f"Une idée pour {raison}"
    if offer.get("name"):
        return offer["name"]
    return "Bonjour"


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------
def _stringify(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _call_ai(
    prompt: str, *, provider: str, model: str, api_keys: dict[str, str]
) -> str:
    """Appelle le bon provider via Triskell Core."""
    from triskell_core.ai.providers import send_to_provider, ProviderError
    try:
        return send_to_provider(provider, model, prompt, api_keys)
    except ProviderError as exc:
        raise RuntimeError(f"IA indisponible : {exc}") from exc


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json_lenient(s: str) -> Any:
    """Essaie json.loads direct, sinon attrape la 1re paire {…} dans la réponse.

    Les LLM ajoutent parfois des ```json ... ``` ou un préambule narratif.
    """
    if not s:
        return None
    s = s.strip()
    # Strip markdown code fences
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = _JSON_BLOCK_RE.search(s)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


# ---------------------------------------------------------------------------
# Validation d'un prospect (signalement des lignes douteuses)
# ---------------------------------------------------------------------------
def validate_prospect(p: dict[str, str]) -> dict[str, Any]:
    """Renvoie {'ok': bool, 'severity': 'error'|'warning'|'ok', 'reasons': [...]}.

    - error  : email manquant / invalide → ne peut pas être envoyé.
    - warning: champs recommandés manquants → l'IA aura moins de contexte.
    - ok     : toutes les cases utiles sont là.
    """
    reasons: list[str] = []
    email = (p.get("email") or "").strip()
    if not email:
        reasons.append("email manquant")
    elif "@" not in email or "." not in email.split("@")[-1]:
        reasons.append("email mal formé")

    if not p.get("raison_sociale") and not (p.get("prenom") or p.get("nom")):
        reasons.append("aucun nom (ni raison sociale, ni contact)")
    if not p.get("secteur"):
        reasons.append("secteur d'activité absent (offre par défaut sera utilisée)")

    severity = "ok"
    if any(r in reasons for r in ("email manquant", "email mal formé")):
        severity = "error"
    elif reasons:
        severity = "warning"
    return {
        "ok": severity != "error",
        "severity": severity,
        "reasons": reasons,
    }
