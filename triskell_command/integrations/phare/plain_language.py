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

# Familles que le robot sait transformer en modification de code réelle
_CODE_FAMILIES = ("title", "meta", "canonical", "noindex", "h1",
                  "schema", "alt", "sitemap", "maillage")
# Familles traitées en relançant un outil interne (pas une modif de code)
_TOOL_FAMILIES = ("pagespeed",)
# Familles qui exigent un humain
_MANUAL_FAMILIES = ("gsc",)


def _families_of(action: dict) -> set[str]:
    text = f"{action.get('title') or ''}\n{action.get('detail_md') or ''}"
    return dedup.extract_fields(text)


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
    if agent == "veilleur" or "cluster" in title:
        return ("Des idées de nouvelles pages à créer autour d'un thème "
                "porteur. C'est un chantier de contenu : à lancer avec "
                "Claude, pas un clic.", "manual")
    if agent == "chasseur_backlinks" or "backlink" in title:
        return ("Des pistes de sites qui pourraient parler du tien. "
                "Ça se traite par prise de contact, pas par une modif du site.",
                "manual")
    return None


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
    # Fallback : début du détail technique, mieux que rien
    detail = (action.get("detail_md") or "").strip()
    if detail:
        first = detail.split("\n")[0].strip()
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

    fams = _families_of(action)
    if fams & set(_MANUAL_FAMILIES):
        return {"can": False, "mode": "manual", "why": _FAMILY_TEXTS["gsc"]}
    if fams & set(_TOOL_FAMILIES):
        return {"can": True, "mode": "tool",
                "why": "Le robot relance la mesure tout seul."}
    if fams & set(_CODE_FAMILIES):
        if not (site.get("repo_github") or "").strip():
            return {"can": False, "mode": "manual",
                    "why": ("Le site n'est pas encore relié à son code — "
                            "à brancher dans « Réglages du site ».")}
        return {"can": True, "mode": "code",
                "why": "Le robot prépare la modification, la vérifie et la publie."}
    # Famille inconnue : on laisse l'IA exécutrice regarder si le site est relié
    if (site.get("repo_github") or "").strip():
        return {"can": True, "mode": "code",
                "why": ("Le robot va regarder si cette proposition peut se "
                        "transformer en modification du site.")}
    return {"can": False, "mode": "manual",
            "why": ("Le site n'est pas encore relié à son code — "
                    "à brancher dans « Réglages du site ».")}
