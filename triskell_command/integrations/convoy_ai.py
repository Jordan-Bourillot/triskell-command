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
# ---------------------------------------------------------------------------
# Détection produit "à vendre" vs démo métier "à montrer comme exemple"
# ---------------------------------------------------------------------------
def _is_demo(offer: dict) -> bool:
    """Renvoie True si l'entrée est une DÉMO métier (exemple à montrer)
    plutôt qu'un produit vendable.

    Conventions reconnues (l'utilisateur peut en utiliser une) :
    - kind == "demo" ou "démo" ou "example" ou "exemple"
    - name commence par « Démo », « Demo », « Exemple », « Template »,
      « Site exemple »
    """
    kind = (offer.get("kind") or "").strip().lower()
    if kind in ("demo", "démo", "example", "exemple"):
        return True
    name_lc = (offer.get("name") or "").strip().lower()
    for prefix in ("démo ", "demo ", "exemple ", "template ",
                    "site exemple ", "exemple de site "):
        if name_lc.startswith(prefix):
            return True
    return False


def _score_sector_match(sector_lc: str, keywords_str: str) -> int:
    """Score de match entre un secteur prospect et une chaîne de keywords.
    Utilisé à la fois pour le matching produit ET démo. Voir
    pick_offer_for_sector pour les règles."""
    if not sector_lc or not keywords_str:
        return 0
    kws = keywords_str.lower()
    score = 0
    for kw in re.split(r"[,\n;]+", kws):
        kw = kw.strip()
        if not kw:
            continue
        if kw in sector_lc:
            score += 3
            continue
        root = re.sub(r"(?:s|es|ier|iere|iste|ique|isme|age|aire)$", "", kw)
        if len(root) >= 4 and root in sector_lc:
            score += 2
            continue
        for tok in re.split(r"\s+", sector_lc):
            if len(tok) >= 4 and tok in kw:
                score += 1
                break
    return score


def pick_demo_for_sector(sector: str,
                          catalog: list[dict[str, str]]) -> dict[str, str]:
    """Sélectionne la démo métier la plus pertinente pour le secteur du
    prospect. Renvoie {} si aucune démo métier n'est dans le catalogue
    OU si aucune ne matche le secteur (= on n'inclut pas de démo dans
    le mail, plutôt qu'en mettre une hors-sujet)."""
    demos = [o for o in (catalog or []) if isinstance(o, dict) and _is_demo(o)]
    if not demos:
        return {}
    sector_lc = (sector or "").lower().strip()
    if not sector_lc:
        return {}
    best: dict[str, str] = {}
    best_score = 0
    for demo in demos:
        s = _score_sector_match(sector_lc, demo.get("keywords") or "")
        if s > best_score:
            best_score = s
            best = demo
    if best_score == 0:
        return {}
    return best


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
    # On exclut les démos métier — elles ne sont pas vendables, on les
    # gère séparément via pick_demo_for_sector().
    sellable = [o for o in (catalog or [])
                if isinstance(o, dict) and not _is_demo(o)]
    if not sellable:
        return {}
    sector_lc = (sector or "").lower().strip()

    # Choix du fallback générique = produit avec le plus de keywords variés
    # (= le plus "couvrant"). Si plusieurs ex-aequo, on prend le 1er.
    def _generic_fallback() -> dict[str, str]:
        best_count = -1
        chosen = sellable[0]
        for offer in sellable:
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
    for offer in sellable:
        s = _score_sector_match(sector_lc, offer.get("keywords") or "")
        if s > best_score:
            best_score = s
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

{demo_block}CONSIGNES STRICTES (à respecter SANS exception) :
- VOUVOIEMENT OBLIGATOIRE : tu vouvoies TOUJOURS le prospect, même si tu
  connais son prénom. JAMAIS de tutoiement, même pour les métiers
  « cools » (coiffeur, tatoueur, restaurateur…). C'est une prospection
  professionnelle, le respect du vouvoiement est non négociable.
- Adresse : si tu as un prénom + nom → « Bonjour <Prénom> » ou
  « Bonjour Monsieur/Madame <Nom> ». Si tu n'as que la raison sociale
  → « Bonjour, » ou « Bonjour l'équipe de <raison sociale>, ».
- Ton : direct, chaleureux mais pro, jamais commercial agressif.
- Longueur : 5 à 10 lignes max.
- Pas de « J'espère que vous allez bien » ni autre formule creuse.
- Mentionne UNE raison spécifique pour laquelle votre offre colle à
  leur métier (tirée du Secteur d'activité ci-dessus).
- Cohérence : reste sur UN seul secteur, UN seul produit, UN seul ton.
  Pas de phrases qui partent dans tous les sens. Pas d'invention de
  fonctionnalités absentes du pitch officiel ci-dessus.
- Termine par un CTA simple (réponse à ce mail, ou lien à cliquer).
- Signature : « {sender_name} » sur la dernière ligne, rien après.

INSTRUCTIONS LIBRES DE L'UTILISATEUR (à respecter en priorité si elles entrent en conflit) :
{user_brief}

RÉPONDS AU FORMAT JSON STRICT (pas de markdown, pas de texte autour) :
{{"subject": "<objet du mail, 4-8 mots>", "body": "<corps complet du mail>"}}
"""


# ---------------------------------------------------------------------------
# Mode "pioche dans templates" — l'IA choisit un template existant et l'adapte
# ---------------------------------------------------------------------------
TEMPLATE_PICK_PROMPT = """Ton SEUL boulot : choisir, parmi les templates ci-dessous, celui qui
correspond le MIEUX à ce prospect précis. Tu ne réécris RIEN, tu ne
modifies RIEN. Tu donnes juste la clé du meilleur template.

CONTEXTE DU PROSPECT :
- Raison sociale : {raison_sociale}
- Contact : {prenom} {nom}
- Email : {email}
- Ville : {ville} ({code_postal})
- Secteur d'activité / type de chantier : {secteur}
- Notes : {notes}

TEMPLATES DISPONIBLES (produit : {template_product}) :
{templates_block}

CRITÈRES DE CHOIX :
- Regarde la description et le sujet de chaque template.
- Privilégie le template dont la description colle le mieux au profil du
  prospect (son secteur, sa taille, son type d'activité).
- S'il n'y a aucun match parfait, prends le moins pire — tu DOIS choisir
  un template, tu n'as JAMAIS le droit de refuser.

INSTRUCTIONS LIBRES DE L'UTILISATEUR (à respecter dans ton choix) :
{user_brief}

RÉPONDS AU FORMAT JSON STRICT (pas de markdown, pas de texte autour) :
{{"template_key": "<clé du template choisi>"}}

Note : sender_name = {sender_name} (juste pour info, ne sert pas dans la
réponse).
"""


def _format_templates_for_prompt(templates: list[dict]) -> str:
    """Formate la liste des templates pour l'injecter dans le prompt IA.
    Limite la longueur de chaque template pour ne pas exploser le token count."""
    if not templates:
        return "(aucun template — fallback génération libre attendu)"
    lines: list[str] = []
    for t in templates:
        key = (t.get("key") or "").strip() or "(sans clé)"
        label = (t.get("label") or "").strip()
        desc = (t.get("description") or "").strip()
        subj = (t.get("subject") or "").strip()
        body = (t.get("body_text") or "").strip()
        # Trim corps à 1500 chars max pour rester raisonnable
        if len(body) > 1500:
            body = body[:1500] + "\n[...tronqué...]"
        head = f"=== TEMPLATE clé=« {key} »"
        if label:
            head += f" — {label}"
        head += " ==="
        lines.append(head)
        if desc:
            lines.append(f"Description / quand l'utiliser : {desc}")
        lines.append(f"Sujet : {subj}")
        lines.append("Corps :")
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


def generate_message_from_templates(
    prospect: dict[str, str],
    *,
    templates: list[dict],
    template_product: str,
    sender_name: str,
    user_brief: str,
    provider: str,
    model: str,
    api_keys: dict[str, str],
) -> dict[str, str]:
    """Pioche dans `templates` et renvoie {subject, body, body_html,
    template_key, offer_name}. Si la liste est vide, retombe sur le fallback
    classique (génération libre via generate_message)."""
    if not templates:
        # Pas de templates → on ne peut rien piocher, on laisse l'appelant
        # gérer le fallback (généralement vers generate_message classique).
        return {"subject": "", "body": "", "body_html": "",
                "template_key": "", "offer_name": "",
                "offer_mail_account_id": "", "html_is_custom": False}
    # Court-circuit : si l'appelant nous passe deja UN seul template, il a
    # deja fait son choix (round-robin pipeline par exemple). Inutile de
    # demander a l'IA de "choisir" parmi 1 option -> on saute l'appel IA
    # et on enchaine direct sur la substitution des placeholders.
    if len(templates) == 1:
        chosen = templates[0]
        template_key = chosen.get("key") or ""
        # Saut au bloc substitution en court-circuitant les variables
        # intermediaires (data, response). On reutilise le bloc en aval.
        template_subject = (chosen.get("subject") or "").strip()
        template_body_txt = (chosen.get("body_text") or "").strip()
        template_body_html = (chosen.get("body_html") or "").strip()
        subj = _apply_placeholders(template_subject, prospect, sender_name)
        body_txt = _apply_placeholders(template_body_txt, prospect, sender_name)
        body_txt = _strip_unfilled_sentences(body_txt)
        if template_body_html:
            body_html = _apply_placeholders(template_body_html, prospect, sender_name)
            body_html = _strip_unfilled_sentences(body_html)
        else:
            primary_url = _first_url_in(template_body_txt)
            body_html = text_to_email_html(
                body_txt, sender_name=sender_name,
                primary_url=primary_url,
                primary_label="En savoir plus",
            )
        return {
            "subject":               subj,
            "body":                  body_txt,
            "body_html":             body_html,
            "template_key":          template_key,
            "offer_name":            template_product or "",
            "offer_mail_account_id": "",
            # True = le HTML vient du modele ecrit a la main (on n'y
            # retouche plus) ; False = HTML auto-genere depuis le texte
            # (l'appelant peut le regenerer apres ajout de la signature).
            "html_is_custom":        bool(template_body_html),
        }
    prompt = TEMPLATE_PICK_PROMPT.format(
        raison_sociale=prospect.get("raison_sociale", "") or "(non précisé)",
        prenom=prospect.get("prenom", ""),
        nom=prospect.get("nom", ""),
        email=prospect.get("email", ""),
        ville=prospect.get("ville", "") or "—",
        code_postal=prospect.get("code_postal", ""),
        secteur=prospect.get("secteur", "") or "(non précisé)",
        notes=prospect.get("notes", "") or "(aucune)",
        template_product=template_product or "(produit)",
        templates_block=_format_templates_for_prompt(templates),
        sender_name=sender_name or "L'équipe",
        user_brief=user_brief.strip() or "(aucune)",
    )
    response = _call_ai(prompt, provider=provider, model=model, api_keys=api_keys)
    data = _parse_json_lenient(response)
    template_key = ""
    if isinstance(data, dict):
        template_key = _stringify(data.get("template_key", "")).strip()
    # On retrouve le template choisi par l'IA. Si l'IA a renvoye autre chose
    # qu'une cle valide -> on prend le premier (filet anti-erreur).
    chosen = next((t for t in templates
                   if (t.get("key") or "") == template_key), templates[0])

    # === SUBSTITUTION PURE, ZERO REECRITURE IA ===
    # Jordan a explicitement demande que ses templates soient utilises tels
    # quels, avec juste les placeholders remplis. L'IA n'invente rien, ne
    # reformule rien, ne change pas le texte. Elle a juste choisi le template.
    template_subject = (chosen.get("subject") or "").strip()
    template_body_txt = (chosen.get("body_text") or "").strip()
    template_body_html = (chosen.get("body_html") or "").strip()

    subj = _apply_placeholders(template_subject, prospect, sender_name)
    body_txt = _apply_placeholders(template_body_txt, prospect, sender_name)
    body_txt = _strip_unfilled_sentences(body_txt)
    if template_body_html:
        body_html = _apply_placeholders(template_body_html, prospect, sender_name)
        body_html = _strip_unfilled_sentences(body_html)
    else:
        # Pas de HTML custom -> on enrobe le texte dans le wrapper Triskell
        primary_url = _first_url_in(template_body_txt)
        body_html = text_to_email_html(
            body_txt, sender_name=sender_name,
            primary_url=primary_url,
            primary_label="En savoir plus",
        )
    return {
        "subject":               subj,
        "body":                  body_txt,
        "body_html":             body_html,
        "template_key":          template_key or (chosen.get("key") or ""),
        "offer_name":            template_product or "",
        "offer_mail_account_id": "",
        "html_is_custom":        bool(template_body_html),
    }


def _strip_unfilled_sentences(text: str) -> str:
    """Nettoie un texte apres substitution de placeholders : supprime les
    artefacts comme " . " ou "  " causes par des placeholders contextuels
    qu'on a vides ({{example_pain}}, {{competitor_example}}, ...).

    Si une phrase finit par "votre . " ou contient "  " (double espace),
    on nettoie ; si la phrase devient vide, on la retire entierement.
    """
    if not text:
        return ""
    import re as _re
    # Suppression des artefacts apres vide-placeholder
    out = text
    # "votre . " -> "" (la phrase fait juste reference a un truc vide)
    out = _re.sub(r"[A-Za-zÀ-ÿ']+\s+\.\s*", "", out)
    # Doubles/triples espaces -> un seul
    out = _re.sub(r"[ \t]{2,}", " ", out)
    # Espace avant point/virgule : "  ." -> "." — UNIQUEMENT ces deux-la.
    # En typographie francaise, l'espace avant : ; ! ? est legitime ;
    # l'enlever abimait les modeles ecrits a la main ("approche :" devenait
    # "approche:").
    out = _re.sub(r"\s+([,.])", r"\1", out)
    # Lignes vides multiples -> max une ligne vide
    out = _re.sub(r"\n{3,}", "\n\n", out)
    # Si une <p>...</p> ne contient plus que des espaces -> on la vire
    out = _re.sub(r"<p[^>]*>\s*</p>", "", out, flags=_re.IGNORECASE)
    return out


def _apply_placeholders(text: str, prospect: dict, sender_name: str) -> str:
    """Remplit les placeholders dans un template.

    Accepte 2 syntaxes en parallele (les anciens templates Triskell ET les
    nouveaux templates Pixel Pros style Mailchimp/CRM) :
      - syntaxe FR a 1 accolade : {prenom} {ville} {secteur} ...
      - syntaxe EN a 2 accolades : {{first_name}} {{city}} {{business_type}} ...
    Toutes pointent vers les memes champs du dict prospect, donc l'auteur
    du template peut utiliser celle qu'il prefere sans se prendre la tete.

    Variables speciales {page_metier} / {page_demo} : URLs des pages de
    pub metier de pixel-pros.fr, choisies selon le secteur du prospect
    (coiffeuse -> /beaute + /demo-beaute). Toujours remplies : secteur
    inconnu -> accueil + demo generique, jamais un trou dans le mail.
    """
    if not text:
        return ""

    prenom    = prospect.get("prenom", "") or ""
    nom       = prospect.get("nom", "") or ""
    raison    = prospect.get("raison_sociale", "") or ""
    ville     = prospect.get("ville", "") or ""
    secteur   = prospect.get("secteur", "") or ""
    email     = prospect.get("email", "") or ""
    website   = prospect.get("website", "") or ""
    sender    = sender_name or "L'équipe"
    # Fallback "name" = prenom si dispo, sinon raison sociale, sinon ""
    name_any  = prenom or raison

    # Pages de pub metier Pixel Pros ciblees sur le secteur du prospect.
    # Best-effort : si le module manque, on retombe sur l'accueil pour ne
    # jamais laisser {{page_metier}} en clair dans un mail envoye.
    try:
        from .pixelpros_pages import pages_for_sector
        page_metier_url, page_demo_url = pages_for_sector(secteur)
    except Exception:
        page_metier_url = "https://pixel-pros.fr"
        page_demo_url = "https://pixel-pros.fr/demo"

    replacements = {
        # === Syntaxe FR a 1 accolade (historique) ===
        "{prenom}":         prenom,
        "{nom}":            nom,
        "{raison_sociale}": raison,
        "{ville}":          ville,
        "{secteur}":        secteur,
        "{email}":          email,
        "{sender_name}":    sender,
        "{page_metier}":    page_metier_url,
        "{page_demo}":      page_demo_url,
        # === Syntaxe EN a 2 accolades (templates Pixel Pros) ===
        "{{first_name}}":    prenom,
        "{{last_name}}":     nom,
        "{{name}}":          name_any,
        "{{company_name}}":  raison,
        "{{company}}":       raison,
        "{{city}}":          ville,
        "{{business_type}}": secteur,
        "{{industry}}":      secteur,
        "{{sector}}":        secteur,
        "{{email}}":         email,
        "{{website}}":       website,
        "{{domain}}":        website,
        "{{signature}}":     sender,
        "{{sender_name}}":   sender,
        "{{page_metier}}":   page_metier_url,
        "{{page_demo}}":     page_demo_url,
        # Placeholders contextuels qu'on ne peut pas auto-remplir : on les
        # vide pour eviter d'envoyer "{{price}}" en clair au prospect.
        # IMPORTANT : tous les placeholders presents dans les templates Pixel
        # Pros qui ne peuvent pas etre devines doivent figurer ici, sinon ils
        # apparaissent en clair dans le mail envoye.
        "{{price}}":             "",
        "{{link}}":              "",
        "{{example_content}}":   "",
        "{{example_pain}}":      "",
        "{{competitor_example}}": "",
    }
    out = text
    for ph, val in replacements.items():
        out = out.replace(ph, val)
    # Nettoie "Bonjour ," qui apparaît quand le prénom est vide
    out = (out
           .replace("Bonjour ,", "Bonjour,")
           .replace("Bonjour , ", "Bonjour, ")
           .replace("Salut ,", "Bonjour,")
           .replace("Salut , ", "Bonjour, "))
    return out


def _first_url_in(text: str) -> str:
    """Trouve la première URL http(s) dans un texte (sert au CTA)."""
    if not text:
        return ""
    m = _URL_RE.search(text)
    return m.group(1) if m else ""


def _fallback_first_template(template: dict, prospect: dict, sender_name: str,
                              template_product: str) -> dict[str, str]:
    """Si l'IA renvoie n'importe quoi, on prend le 1er template, on remplit
    les placeholders de base et on l'envoie tel quel. Mieux qu'un mail vide.

    Respecte le body_html du template s'il existe (mise en forme écrite à
    la main par l'utilisateur)."""
    subj = _apply_placeholders((template.get("subject") or "").strip(),
                                prospect, sender_name)
    body = _apply_placeholders((template.get("body_text") or "").strip(),
                                prospect, sender_name)
    template_body_html = (template.get("body_html") or "").strip()
    if template_body_html:
        # Respecte la mise en forme HTML écrite à la main
        body_html = _apply_placeholders(template_body_html, prospect, sender_name)
    else:
        # Pas de HTML custom — regénère un HTML auto avec bouton CTA
        primary_url = _first_url_in(template.get("body_text", ""))
        body_html = text_to_email_html(
            body, sender_name=sender_name,
            primary_url=primary_url,
            primary_label="En savoir plus",
        )
    return {
        "subject":               subj or "Une idée pour vous",
        "body":                  body or "(template vide)",
        "body_html":             body_html,
        "template_key":          template.get("key") or "",
        "offer_name":            template_product or "",
        "offer_mail_account_id": "",
        "html_is_custom":        bool(template_body_html),
    }


# ---------------------------------------------------------------------------
# Mise en forme HTML — joli mais sobre, pas de gros visuels qui font fuir
# ---------------------------------------------------------------------------
import html as _html_mod
import re as _re_mod

_URL_RE = _re_mod.compile(r'(https?://[^\s<>"\')\]]+)')


def text_to_email_html(body_text: str, *,
                        sender_name: str = "",
                        primary_url: str = "",
                        primary_label: str = "Découvrir",
                        secondary_url: str = "",
                        secondary_label: str = "Voir l'exemple") -> str:
    """Transforme un body texte (généré par l'IA) en HTML mail propre.

    - Paragraphes séparés par double saut de ligne
    - URLs inline détectées et soulignées (clic = ouvre la page)
    - 1 ou 2 boutons CTA en bas du mail si fournis (offre principale +
      démo métier en seconde)
    - Wrapper sobre : font Inter/system, couleur de marque légère
    """
    if not body_text:
        return ""
    accent = "#6366F1"   # cohérent avec Triskell (indigo)
    text_color = "#1f2937"
    muted_color = "#6b7280"
    bg_color = "#f9fafb"

    # 1) Échappe le HTML, applique le markdown léger (**gras** et __souligné__),
    # puis détecte les URLs inline et les transforme en petits boutons pilule
    # (plus engageant qu'un simple lien souligné).
    safe = _html_mod.escape(body_text)
    # Markdown leger : **gras** et __soulignement__. Limite a 1-2 lignes
    # par marqueur pour eviter qu'une etoile orpheline ne ruine la mise
    # en forme du reste du mail.
    import re as _re_md
    safe = _re_md.sub(
        r"\*\*([^*\n]{1,120}?)\*\*",
        r'<strong>\1</strong>',
        safe,
    )
    safe = _re_md.sub(
        r"__([^_\n]{1,120}?)__",
        r'<u>\1</u>',
        safe,
    )
    def _linkify(m):
        u = m.group(1)
        # Affichage compact : retire le protocole et le slash final
        display = u
        for proto in ("https://", "http://"):
            if display.startswith(proto):
                display = display[len(proto):]
                break
        display = display.rstrip("/")
        if len(display) > 36:
            display = display[:33] + "..."
        return (
            f'<a href="{u}" style="display:inline-block;'
            f'background:{accent};color:white;padding:6px 14px;'
            f'border-radius:999px;text-decoration:none;font-weight:600;'
            f'font-size:13.5px;margin:3px 2px;line-height:1.2;'
            f'white-space:nowrap;">'
            f'{_html_mod.escape(display)} &rarr;</a>'
        )
    safe = _URL_RE.sub(_linkify, safe)

    # 2) Découpe en paragraphes (double saut de ligne) puis en lignes
    paragraphs = []
    for chunk in safe.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        lines = chunk.split("\n")
        paragraphs.append("<br>".join(lines))
    body_html_inner = "".join(
        f'<p style="margin:0 0 14px;line-height:1.55;color:{text_color};font-size:15px;">{p}</p>'
        for p in paragraphs
    )

    # 3) Boutons CTA (max 2 : offre principale + démo métier)
    ctas: list[str] = []
    if primary_url:
        ctas.append(
            f'<a href="{_html_mod.escape(primary_url)}" '
            f'style="display:inline-block;background:{accent};color:white;'
            f'padding:12px 24px;border-radius:8px;text-decoration:none;'
            f'font-weight:600;font-size:14.5px;margin:6px;">'
            f'{_html_mod.escape(primary_label)} →</a>'
        )
    if secondary_url and secondary_url != primary_url:
        ctas.append(
            f'<a href="{_html_mod.escape(secondary_url)}" '
            f'style="display:inline-block;background:white;color:{accent};'
            f'padding:11px 23px;border-radius:8px;text-decoration:none;'
            f'font-weight:600;font-size:14.5px;margin:6px;'
            f'border:1.5px solid {accent};">'
            f'🖼️ {_html_mod.escape(secondary_label)}</a>'
        )
    ctas_block = ""
    if ctas:
        ctas_block = (
            '<div style="text-align:center;margin:22px 0 8px;">'
            + "".join(ctas) +
            '</div>'
        )

    # 4) Wrapper plus chaleureux : bordure colorée en haut, kicker discret
    # avec le nom de l'expéditeur, fond doux, ombre marquée, padding aere.
    sender_safe = _html_mod.escape(sender_name or "").upper()
    kicker_block = ""
    if sender_safe:
        kicker_block = (
            f'<div style="font-size:11px;font-weight:700;letter-spacing:0.18em;'
            f'color:{accent};margin:0 0 22px 0;padding-bottom:14px;'
            f'border-bottom:2px solid #e0e7ff;">'
            f'{sender_safe}'
            f'</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:{bg_color};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:{bg_color};">
    <tr><td align="center" style="padding:32px 12px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" style="max-width:600px;background:white;border-radius:14px;box-shadow:0 2px 6px rgba(15,23,42,0.06),0 8px 24px rgba(15,23,42,0.08);border-top:4px solid {accent};">
        <tr><td style="padding:32px 36px 24px;">
          {kicker_block}
          {body_html_inner}
          {ctas_block}
        </td></tr>
      </table>
      <div style="margin-top:18px;font-size:11px;color:{muted_color};">Ce message vous a ete envoye personnellement.</div>
    </td></tr>
  </table>
</body></html>"""


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
    """Renvoie {'subject': '...', 'body': '...', 'body_html': '...',
    'offer_name': '...'}."""
    offer = pick_offer_for_sector(prospect.get("secteur", ""), catalog)
    demo = pick_demo_for_sector(prospect.get("secteur", ""), catalog)
    demo_block = ""
    if demo:
        demo_block = (
            "EXEMPLE CONCRET À INCLURE OBLIGATOIREMENT DANS LE MAIL "
            "(démo métier qui correspond pile au prospect) :\n"
            f"- Nom de la démo : {demo.get('name', '')}\n"
            f"- URL exacte à coller dans le corps du mail : {demo.get('url', '')}\n"
            "\n"
            "INSTRUCTION OBLIGATOIRE — tu DOIS inclure cette URL DANS LE "
            "CORPS DU MAIL (pas dans la signature, pas en P.S., mais dans "
            "le texte). Phrase modèle (à adapter au ton mais avec vouvoiement) :\n"
            "  « Pour vous faire une idée concrète, voici un exemple de "
            "site que nous avons préparé pour votre métier : <URL> ».\n"
            "Tu peux varier la formulation, mais l'URL DOIT apparaître "
            "telle quelle dans le mail (pas raccourcie, pas masquée).\n"
            "\n"
            "Cette démo n'est PAS le produit à vendre — l'offre à pitcher "
            "reste celle indiquée plus haut. La démo sert juste de PREUVE "
            "VISUELLE adaptée à leur métier. Mentionne les 2 dans le mail : "
            "l'offre (pour la vente) + la démo (pour la preuve).\n\n"
        )
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
        demo_block=demo_block,
        sender_name=sender_name or "L'équipe",
        user_brief=user_brief.strip() or "(aucune instruction supplémentaire)",
    )
    response = _call_ai(prompt, provider=provider, model=model, api_keys=api_keys)
    data = _parse_json_lenient(response)
    if not isinstance(data, dict):
        body_txt = response.strip() or "(génération vide)"
        body_html = text_to_email_html(
            body_txt, sender_name=sender_name,
            primary_url=offer.get("url", ""),
            primary_label=offer.get("name", "") or "Découvrir",
            secondary_url=(demo or {}).get("url", ""),
            secondary_label="Voir un exemple pour votre métier",
        )
        return {
            "subject":               _fallback_subject(prospect, offer),
            "body":                  body_txt,
            "body_html":             body_html,
            "offer_name":            offer.get("name", ""),
            "offer_mail_account_id": (offer.get("mail_account_id") or "").strip(),
        }
    body_txt = _stringify(data.get("body", "")) or "(génération vide)"
    body_html = text_to_email_html(
        body_txt, sender_name=sender_name,
        primary_url=offer.get("url", ""),
        primary_label=offer.get("name", "") or "Découvrir",
        secondary_url=(demo or {}).get("url", ""),
        secondary_label="Voir un exemple pour votre métier",
    )
    return {
        "subject":               _stringify(data.get("subject", "")) or _fallback_subject(prospect, offer),
        "body":                  body_txt,
        "body_html":             body_html,
        "offer_name":            offer.get("name", ""),
        "offer_mail_account_id": (offer.get("mail_account_id") or "").strip(),
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
