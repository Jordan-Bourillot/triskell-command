"""Explications en français normal pour les actions Le Phare.

Demande de Jordan (12/06/2026) : chaque carte doit dire clairement, sans
jargon, ce qui est proposé et ce que ça change — et l'écran doit savoir si
le robot peut le faire tout seul (bouton « OK, fais-le ») ou si c'est un
conseil à lire.

Deux niveaux :
  - `explain(action)`  → phrase « ce que ça change » affichée sur la carte.
    Si l'action porte déjà une explication écrite par un agent (simple_md),
    elle gagne. Sinon, gabarits déterministes par famille (title, canonical,
    noindex…) — testables hors ligne, zéro coût IA.
  - `classify_for_apply(action, site)` → le robot peut-il s'en charger ?
    {can, mode 'code'|'tool'|'info'|'manual', why}.

Un nouveau motif mal expliqué → enrichir CE fichier (pas de texte en dur
dans l'UI).
"""

from __future__ import annotations

import re
from typing import Optional

from . import dedup

# ---------------------------------------------------------------------------
# Gabarits par famille de balise / d'outil (familles de dedup._FIELD_HINTS)
# ---------------------------------------------------------------------------
_FAMILY_TEXTS: dict[str, str] = {
    "title": ("Changer le titre de la page tel qu'il s'affiche dans Google, "
              "pour sortir sur ce que les gens tapent vraiment."),
    "meta": ("Réécrire le petit texte qui s'affiche sous le titre dans les "
             "résultats Google, pour donner envie de cliquer."),
    "canonical": ("Quand plusieurs adresses montrent la même page, Google croit "
                  "voir des copies. On lui indique la page principale pour "
                  "arrêter de brouiller le site."),
    "noindex": ("Cacher des résultats Google les pages sans intérêt pour la "
                "recherche (mentions légales, CGV…) pour concentrer son "
                "attention sur les pages qui comptent."),
    "h1": "Changer le grand titre affiché en haut de la page.",
    "schema": ("Ajouter une étiquette invisible qui aide Google à comprendre "
               "la page (prix, activité…). Peut enrichir l'affichage dans "
               "les résultats."),
    "sitemap": ("Donner à Google le plan du site pour qu'il trouve toutes "
                "les pages sans en oublier."),
    "pagespeed": ("Mesurer la vitesse du site sur téléphone — un site lent "
                  "perd des places dans Google. Le robot lance la mesure en "
                  "relançant un audit."),
    "alt": ("Ajouter un petit descriptif sur les images : Google ne « voit » "
            "pas les images, il lit ces descriptifs."),
    "gsc": ("Une vérification à faire dans l'outil Google Search Console. "
            "Il faut être connecté au compte Google — le robot n'y a pas accès."),
    "maillage": ("Ajouter des liens entre les pages du site pour aider Google "
                 "(et les visiteurs) à circuler vers les pages importantes."),
}

# Familles que le robot sait transformer en modification de code réelle.
# « alt » (texte des images) en fait partie depuis le 17/06/2026 — avant, le
# bouton vert s'affichait dessus mais l'Exécuteur ne savait pas le faire.
_CODE_FAMILIES = ("title", "meta", "canonical", "noindex", "h1",
                  "schema", "alt", "sitemap")
# Familles traitées en relançant un outil interne (pas une modif de code)
_TOOL_FAMILIES = ("pagespeed",)
# Familles qui exigent un humain (l'Exécuteur ne sait pas les faire seul) :
#   - gsc      : compte Google Search Console requis
#   - maillage : ajouter des liens DANS le corps d'une page — l'Exécuteur ne
#                touche que <head>/title/meta/h1, jamais le contenu de la page
_MANUAL_FAMILIES = ("gsc", "maillage")
_MANUAL_TEXTS: dict[str, str] = {
    "gsc": _FAMILY_TEXTS["gsc"],
    "maillage": ("Ajouter des liens entre tes pages, ça se décide dans le "
                 "contenu — à préparer avec Claude, pas en un clic."),
}


_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_URL_IN_TEXT_RE = re.compile(r"https?://\S+")


def _clean_text_for_fields(text: str) -> str:
    """Retire blocs de code et URLs avant de repérer la famille de balise.

    Sinon l'adresse interne du sitemap (« …sitemaps.org/schemas/… ») contient
    le mot « schemas » et fait croire à tort à des « données structurées » :
    la carte « plan du site » s'affichait avec le texte des données
    structurées (constaté par Jordan le 17/06/2026)."""
    text = _CODE_BLOCK_RE.sub(" ", text or "")
    text = _URL_IN_TEXT_RE.sub(" ", text)
    return text


def _families_of(action: dict) -> set[str]:
    text = f"{action.get('title') or ''}\n{action.get('detail_md') or ''}"
    return dedup.extract_fields(_clean_text_for_fields(text))


def _agent_special(action: dict) -> Optional[tuple[str, str]]:
    """Cas par agent : (texte, mode). Mode 'info' = à lire, rien à publier."""
    agent = (action.get("agent") or "").lower()
    title = (action.get("title") or "").lower()
    if agent == "chef_orchestre" or title.startswith("plan du mois"):
        return ("Le programme de travail du mois proposé par le chef "
                "d'orchestre. À lire — rien à publier sur le site.", "info")
    if agent == "analyste" or title.startswith("bulletin"):
        return ("Le point sur les chiffres du site. À lire — rien à publier.",
                "info")
    if agent == "geo_surveillant" or title.startswith("geo check"):
        return ("Le point sur ta visibilité dans les IA (ChatGPT, Perplexity…). "
                "C'est une mesure à lire — rien à publier sur le site.", "info")
    if agent == "veilleur" or "cluster" in title:
        return ("Des idées de nouvelles pages à créer autour d'un thème "
                "porteur. C'est un chantier de contenu : à lancer avec "
                "Claude, pas un clic.", "manual")
    if agent == "chasseur_backlinks" or "backlink" in title:
        return ("Des pistes de sites qui pourraient parler du tien. "
                "Ça se traite par prise de contact, pas par une modif du site.",
                "manual")
    return None


# Filet anti-jargon : Jordan ne doit JAMAIS voir de mot technique (règle
# « parler normal »). Quand un texte écrit par une IA en contient malgré tout,
# on le remplace par un message neutre plutôt que de lui infliger le charabia.
_JARGON_RE = re.compile(
    r"(faqpage|json-?ld|schema\.?org|données structurées|donnees structurees|"
    r"fetchpriority|canonical|noindex|méta-?description|meta-?description|"
    r"\bmeta\b|\bbalise|\battribut|<\s*/?\s*(head|img|title|meta|link|script|h[1-6])|"
    r"\bjsonld\b|\bcrawl|\bsrcset|\bloading=|\balt=|microdonnées|microdonnees|"
    r"breadcrumb|localbusiness|\borganization\b|sitemap\.xml|head_insert|"
    r"\bhtml\b|\bcss\b|\brepo\b|\bh1\b|\bh2\b)",
    re.IGNORECASE)

CLEAN_MANUAL_FALLBACK = (
    "celle-ci, c'est mieux qu'on la fasse ensemble — le robot préfère ne pas y "
    "toucher tout seul. Tu peux la mettre de côté pour l'instant.")


def has_jargon(text: str) -> bool:
    """Le texte contient-il un mot technique interdit pour Jordan ?"""
    return bool(_JARGON_RE.search(text or ""))


# Le robot a déjà BUTÉ sur un blocage CONCRET qu'aucune capacité ne lèvera :
# page absente de son scan, titre actuel inconnu, page introuvable… Re-proposer
# un bouton vert « OK, fais-le » sur ces cartes, c'est mentir — ça échouerait
# exactement pareil (vécu le 18/06 : « Enrichir les titles de /demo-wedding-
# planner & /demo-coach » re-proposé alors que ces pages ne sont pas dans le
# scan → clic → échec en boucle).
_HARD_BLOCKER_RE = re.compile(
    r"(ne figure|n['’ ]?existe|introuvable|dernier scan|"
    r"pas dans (le |les |son )?(scan|données|donnees|crawl)|"
    r"je ne connais pas|ne connais pas|je ne peux pas modifier|"
    r"relanc\w* (le scan|un scan|l['’ ]?analyse)|page absente|"
    r"pas trouvé|pas trouvee|pas trouvée|sous les yeux)",
    re.IGNORECASE)


def _is_hard_blocker(text: str) -> bool:
    """Le robot a buté sur un blocage CONCRET (donnée manquante) qu'aucune
    capacité ne lèvera. Sur ces cartes : pas de bouton vert, on respecte le
    verdict du robot et on affiche sa raison."""
    return bool(_HARD_BLOCKER_RE.search(text or ""))


def explain(action: dict) -> str:
    """Phrase « ce que ça change », sans jargon. Jamais vide."""
    simple = (action.get("simple_md") or "").strip()
    if simple:
        return simple
    special = _agent_special(action)
    if special:
        return special[0]
    fams = _families_of(action)
    # Ordre stable : la famille la plus « parlante » d'abord
    for fam in ("title", "canonical", "noindex", "meta", "schema", "h1",
                "sitemap", "pagespeed", "alt", "maillage", "gsc"):
        if fam in fams:
            return _FAMILY_TEXTS[fam]
    # Fallback : début du détail — mais JAMAIS une 1re ligne pleine de jargon
    # (texte d'un agent technique). Mieux vaut une phrase neutre qu'un charabia.
    detail = (action.get("detail_md") or "").strip()
    if detail:
        first = detail.split("\n")[0].strip()
        if first and not has_jargon(first):
            return first[:220] + ("…" if len(first) > 220 else "")
    return "Proposition des robots — ouvre le détail pour en savoir plus."


def classify_for_apply(action: dict, site: Optional[dict]) -> dict:
    """Le bouton « OK, fais-le » a-t-il un sens sur cette carte ?

    Renvoie {can: bool, mode: 'code'|'tool'|'info'|'manual', why: str}.
    `why` est montré à Jordan quand can=False — en français normal.
    """
    site = site or {}
    status = (action.get("status") or "").lower()
    kind = (action.get("kind") or "").lower()
    if kind == "pr_modif" or (action.get("github_pr_url") or "").strip():
        # Modif déjà préparée : le bouton « Publier sur le site » existant suffit
        return {"can": False, "mode": "code",
                "why": "La modification est déjà préparée — utilise « Publier sur le site »."}
    if status not in ("draft", "pending_review"):
        return {"can": False, "mode": "manual",
                "why": "Cette carte n'est plus en attente."}

    special = _agent_special(action)
    if special:
        return {"can": False, "mode": special[1], "why": special[0]}

    # Le robot a DÉJÀ tenté cette carte et a buté sur un blocage CONCRET (page
    # absente de son scan, titre actuel inconnu…) qu'aucune capacité ne lève.
    # On le détecte AVANT les familles de balises : sinon une carte « titre »
    # garderait son bouton vert alors que le robot vient de dire qu'il ne peut
    # pas (clic → échec en boucle). On respecte son verdict et on montre sa
    # raison (vu par Jordan le 18/06 sur « Enrichir les titles de /demo-* »).
    _err = action.get("apply_error") or ""
    if ((action.get("apply_state") or "").lower() in ("manual", "failed")
            and _is_hard_blocker(_err)):
        return {"can": False, "mode": "manual",
                "why": _err.strip() if not has_jargon(_err) else CLEAN_MANUAL_FALLBACK}

    # Capacités apprises au robot le 17/06 (il lit la page en direct) : FAQ
    # structurée + préchargement de l'image principale → faisables tout seul.
    title_low = (action.get("title") or "").lower()
    if ("faq" in title_low
            or any(k in title_low for k in ("précharg", "precharg", "preload"))):
        if (site.get("repo_github") or "").strip():
            return {"can": True, "mode": "code",
                    "why": "Le robot lit ta page et s'en charge."}

    # Changer la PRIORITÉ ou le mode de chargement d'une image (fetchpriority,
    # lazy-load) : le robot ne sait pas encore toucher aux attributs d'une
    # image. Sans ce garde-fou, ces cartes citent « PageSpeed » dans leur détail
    # et tombaient en mode « outil » (« le robot relance la mesure ») → un faux
    # bouton vert qui ne pose JAMAIS le fetchpriority promis (constaté le
    # 17/06 sur la home Pixel Pros, dont l'image principale est un fond CSS).
    if any(k in title_low for k in ("fetchpriority", "fetch-priority",
                                    "lazy-load", "lazyload", "lazy load")):
        return {"can": False, "mode": "manual",
                "why": ("Changer la priorité de chargement des images, le robot "
                        "ne sait pas encore le faire tout seul — à voir ensemble.")}

    # Créer/dupliquer une PAGE entière ou écrire le CONTENU d'une page : hors de
    # portée de l'Exécuteur (il ne retouche que des balises — title, méta, h1… —
    # sur des pages qui existent DÉJÀ ; il n'invente jamais de contenu). On le
    # détecte AVANT les familles : sinon un détail qui cite « Title cible : … »
    # ou « + H1 ciblé » allume à tort la famille title/h1 et décroche un faux
    # bouton vert (vu le 18/06 : « Dupliquer /carreleur en /electricien »,
    # « Publier un contenu minimal sur la home », « Rédiger et déployer le
    # contenu de … »). Volontairement des expressions MULTI-MOTS, pour ne jamais
    # frapper un légitime « réécrire le title/la méta ».
    _PAGE_CONTENT_SIGNS = (
        "dupliquer", "créer une page", "creer une page", "créer un brouillon",
        "creer un brouillon", "publier un contenu", "publier du contenu",
        "rédiger une page", "rediger une page", "rédiger et déployer le contenu",
        "rediger et deployer le contenu", "rédiger le contenu", "rediger le contenu")
    if any(k in title_low for k in _PAGE_CONTENT_SIGNS):
        return {"can": False, "mode": "manual",
                "why": ("Écrire ou dupliquer une page entière, c'est du contenu à "
                        "préparer ensemble — le robot ne retouche que des pages "
                        "qui existent déjà, il n'invente jamais de texte.")}

    fams = _families_of(action)
    code_fams = fams & set(_CODE_FAMILIES)
    tool_fams = fams & set(_TOOL_FAMILIES)
    manual_fams = fams & set(_MANUAL_FAMILIES)
    # Une mention « à vérifier dans Search Console » n'empêche PAS le robot
    # de faire la modification principale (vécu : la carte canonical classée
    # « à toi de le faire » parce que son détail citait GSC pour la
    # vérification d'après). Le manuel ne gagne que s'il est SEUL en jeu.
    if manual_fams and not code_fams and not tool_fams:
        fam = sorted(manual_fams)[0]
        return {"can": False, "mode": "manual",
                "why": _MANUAL_TEXTS.get(fam, _FAMILY_TEXTS["gsc"])}
    if tool_fams and not code_fams:
        return {"can": True, "mode": "tool",
                "why": "Le robot relance la mesure tout seul."}
    if code_fams:
        if not (site.get("repo_github") or "").strip():
            return {"can": False, "mode": "manual",
                    "why": ("Le site n'est pas encore relié à son code — "
                            "à brancher dans « Réglages du site ».")}
        return {"can": True, "mode": "code",
                "why": "Le robot prépare la modification, la vérifie et la publie."}
    # Famille inconnue MAIS travail clairement humain (écrire du contenu,
    # alléger le poids des images, compte Google, backlinks) → pas de faux
    # bouton vert. (Les cartes faisables ont une famille et ne passent pas ici.)
    if any(k in title_low for k in
           ("rédiger", "rediger", "rédige", "rédaction", "redaction", "écrire",
            "ecrire", "créer une page", "creer une page", "contenu", "webp",
            "avif", "convertir les image", "compresser", "search console",
            "backlink")):
        return {"can": False, "mode": "manual",
                "why": ("Celle-ci, c'est un travail à faire ensemble — le robot "
                        "ne peut pas s'en charger tout seul.")}
    # Le robot a DÉJÀ regardé cette carte et tranché « à la main »
    # (apply_state 'manual', sa raison est affichée juste en dessous). Les
    # vraies capacités (FAQ, préchargement, familles de balises) sont testées
    # PLUS HAUT et priment — si on arrive ICI, aucune capacité sûre ne couvre
    # la carte. On n'invente donc pas un bouton vert optimiste qui
    # contredirait le verdict déjà rendu (bug vu par Jordan le 18/06 : pastille
    # verte « le robot peut le faire » posée AU-DESSUS de « le robot préfère ne
    # pas y toucher tout seul »).
    if (action.get("apply_state") or "").lower() == "manual":
        return {"can": False, "mode": "manual", "why": CLEAN_MANUAL_FALLBACK}
    # Sinon : on laisse l'IA exécutrice regarder si le site est relié.
    if (site.get("repo_github") or "").strip():
        return {"can": True, "mode": "code",
                "why": ("Le robot va regarder si cette proposition peut se "
                        "transformer en modification du site.")}
    return {"can": False, "mode": "manual",
            "why": ("Le site n'est pas encore relié à son code — "
                    "à brancher dans « Réglages du site ».")}
