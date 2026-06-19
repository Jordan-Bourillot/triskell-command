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

    # Le robot a DÉJÀ tranché « à la main » sur cette carte (apply_state='manual')
    # → on RESPECTE son verdict : plus JAMAIS de bouton vert qui re-promet ce
    # qu'il vient de refuser. C'était LA cause de la boucle « clic vert → fais-le
    # toi-même → clic vert → … » (Jordan, 19/06 : « ça fait 10 fois qu'on
    # recommence »). AVANT, on ne gelait QUE les refus « durs » (page absente…)
    # et on laissait une 2e chance « optimiste » aux autres → d'où la boucle sur
    # les refus « doux » (accueil, FAQ à écrire…). Un échec TECHNIQUE ('failed')
    # garde, lui, son bouton Réessayer : ce n'est pas un refus, juste un raté.
    _err = action.get("apply_error") or ""
    _state = (action.get("apply_state") or "").lower()
    if _state == "manual" or (_state == "failed" and _is_hard_blocker(_err)):
        return {"can": False, "mode": "manual",
                "why": (_err.strip() if (_err.strip() and not has_jargon(_err))
                        else CLEAN_MANUAL_FALLBACK)}

    # La page d'ACCUEIL (la vitrine) : le robot n'en RÉÉCRIT jamais le contenu
    # visible tout seul (le titre, le grand titre, le descriptif) — règle de fond
    # depuis qu'il avait viré le nom du site d'une home. Donc PAS de bouton vert
    # sur ces cartes : c'est une décision à prendre ensemble. (Les ajouts
    # INVISIBLES — plan du site, données structurées… — restent permis.)
    try:
        from . import orchestrator
        if orchestrator._targets_home(action) and (
                _families_of(action) & {"title", "h1", "meta"}):
            return {"can": False, "mode": "manual",
                    "why": ("La page d'accueil, c'est ta vitrine — le robot n'en "
                            "change pas le texte tout seul. Si tu veux la "
                            "retoucher, on le fait ensemble.")}
    except Exception:
        pass

    # Agents DÉTERMINISTES : l'Exécuteur a un traitement dédié SANS IA (plan du
    # site régénéré, texte des images recopié, lien rendu direct). Le robot SAIT
    # les faire → bouton vert, même si le titre ne cite aucune balise (« Lien
    # direct » n'a aucune « famille »). Sans ça, ces cartes tombaient dans le
    # repli « à voir ensemble » quand on a coupé l'optimisme (régression 19/06).
    agent_low = (action.get("agent") or "").lower()
    if agent_low in ("sitemap_builder", "image_seo", "redirect_fixer"):
        if (site.get("repo_github") or "").strip():
            return {"can": True, "mode": "code",
                    "why": "Le robot prépare la modification, la vérifie et la publie."}
        return {"can": False, "mode": "manual",
                "why": ("Le site n'est pas encore relié à son code — "
                        "à brancher dans « Réglages du site ».")}

    title_low = (action.get("title") or "").lower()
    # FAQ : le robot sait RECOPIER en données structurées une FAQ DÉJÀ écrite sur
    # la page — il n'en INVENTE jamais (sinon pénalité Google). Une carte qui
    # propose d'ÉCRIRE / d'étoffer une FAQ (« étoffer… avec une mini-FAQ »,
    # « rédiger 3 questions ») est donc du CONTENU à préparer ensemble, pas un
    # clic (vécu le 19/06 : « Étoffer /demande-site avec une mini-FAQ » montrait
    # le bouton vert puis « il faudrait d'abord en écrire une ensemble »).
    if "faq" in title_low and any(
            k in title_low for k in ("étoffer", "etoffer", "mini-faq", "mini faq",
                                     "rédiger", "rediger", "écrire", "ecrire",
                                     "créer", "creer")):
        return {"can": False, "mode": "manual",
                "why": ("Écrire une FAQ — les questions et leurs réponses —, "
                        "c'est du contenu à préparer ensemble. Le robot ne sait "
                        "que recopier une FAQ déjà présente sur ta page.")}

    # Capacités apprises au robot le 17/06 (il lit la page en direct) : FAQ
    # structurée (recopie) + préchargement de l'image principale → faisables seul.
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
    # Si on arrive ICI : aucune capacité SÛRE ne couvre la carte (pas de famille
    # de balise reconnue, pas un cas spécial). On ne PROMET PLUS un bouton vert
    # « optimiste » qui se dégonflait au clic — la cause des « 10 fois qu'on
    # recommence » (Jordan, 19/06 : un « je peux » DOIT savoir faire). Le robot
    # ne se déclare capable QUE de ce qu'il sait vraiment faire (testé plus haut).
    # Le reste → honnêtement « à voir ensemble » (volet Idées, silencieux), jamais
    # une fausse promesse. (Un refus passé, apply_state='manual', est déjà géré
    # tout en haut : il n'est jamais re-proposé.)
    if not (site.get("repo_github") or "").strip():
        return {"can": False, "mode": "manual",
                "why": ("Le site n'est pas encore relié à son code — "
                        "à brancher dans « Réglages du site ».")}
    return {"can": False, "mode": "manual",
            "why": ("Celle-ci, le robot n'est pas sûr de savoir la faire tout "
                    "seul — on la regarde ensemble quand tu veux.")}
