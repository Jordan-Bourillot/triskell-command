"""Voix de marque Triskell + filtre anti-slop pour les sorties LLM.

Tous les agents reçoivent ce préambule dans leur system prompt. Garantit la
cohérence éditoriale sur les 13+ sites de l'écosystème et empêche le LLM de
livrer du jargon ou du vocabulaire LLM-typique.
"""

from __future__ import annotations

import re

VOICE_TRISKELL = """Voix Triskell Studio :
- Français parlant, breton chaleureux mais professionnel
- Direct, sans flatterie, sans ouverture creuse
- Pas de jargon technique inutile, pas d'anglicismes gratuits
- Phrases de longueur variable, prose dense plutôt que listes à puces
- Concret avant tout : un détail, un chiffre, un nom propre valent mieux
  qu'une généralité abstraite
- Ton de marque : artisan numérique, sérieux et accessible

Vocabulaire bani (jamais utiliser) :
- delve, leverage, robust, comprehensive, seamless, cutting-edge
- game-changer, unlock, harness, foster, elevate, empower, unleash
- in today's fast-paced world, it's worth noting, moreover
- tapestry, realm, landscape, ever-evolving, paradigm shift

Structures bannies :
- "Not just X but Y" / "It's not about X, it's about Y"
- "More than X, it's Y" / "X isn't the answer, Y is"

Em-dashes : maximum 1 toutes les 5 phrases.

Ouvertures bannies : "Excellente question", "Bonne idée", "C'est intéressant",
"Je vais", "Voici", "Permettez-moi".

Conclusions bannies : "En résumé", "Pour conclure", "En conclusion" suivies
d'une reformulation. Si une vraie synthèse est utile, elle doit ajouter, pas
reformuler.
"""


# Mots/expressions à détecter avant publication
_BANNED_PATTERNS = [
    r"\bdelve\b",
    r"\bleverage\b",
    r"\brobust\b",
    r"\bcomprehensive\b",
    r"\bseamless\b",
    r"\bcutting[- ]edge\b",
    r"\bgame[- ]chang(?:er|ing)\b",
    r"\bunlock(?:ing)?\b",
    r"\bharness(?:ing)?\b",
    r"\bfoster(?:ing)?\b",
    r"\belevat(?:e|ing|es)\b",
    r"\bempower(?:ing|ed|s)?\b",
    r"\bunleash(?:ing)?\b",
    r"\btapestry\b",
    r"\brealm\b",
    r"\blandscape\b",
    r"\bever[- ]evolving\b",
    r"\bparadigm shift\b",
    r"in today's fast[- ]paced world",
    r"it's worth noting",
    r"\bmoreover\b",
]

_BANNED_OPENINGS = [
    r"^\s*(excellente?|bonne) (question|idée)\b",
    r"^\s*c'est (intéressant|une excellente?)",
    r"^\s*permett(ez|s)[- ]moi",
    r"^\s*je vais maintenant",
    r"^\s*voici (comment|ma|une)",
]

_BANNED_CONCLUSIONS = [
    r"\b(en résumé|pour conclure|en conclusion)\b\s*[:,]",
]


def system_preamble(extra: str = "") -> str:
    """Renvoie le bloc system prompt à préfixer pour chaque agent.

    `extra` permet d'ajouter une couche spécifique (rôle de l'agent).
    """
    base = VOICE_TRISKELL
    if extra:
        return f"{base}\n\n---\n\n{extra}"
    return base


def detect_slop(text: str) -> list[dict]:
    """Repère les violations anti-slop dans un texte.

    Renvoie une liste de dicts {kind, match, position} ; vide si tout est OK.
    """
    if not text:
        return []
    issues: list[dict] = []
    low = text.lower()
    for pat in _BANNED_PATTERNS:
        for m in re.finditer(pat, low, flags=re.IGNORECASE):
            issues.append({"kind": "banned_word", "match": m.group(0),
                           "position": m.start()})
    for pat in _BANNED_OPENINGS:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            issues.append({"kind": "banned_opening", "match": m.group(0),
                           "position": m.start()})
    for pat in _BANNED_CONCLUSIONS:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            issues.append({"kind": "banned_conclusion", "match": m.group(0),
                           "position": m.start()})
    em_dashes = text.count("—")
    sentences = max(1, len(re.findall(r"[.!?]+", text)))
    if em_dashes > sentences / 5 + 1:
        issues.append({"kind": "em_dash_overuse",
                       "match": f"{em_dashes} em-dashes / {sentences} phrases",
                       "position": 0})
    return issues


def is_clean(text: str) -> bool:
    """True si le texte ne contient aucune violation anti-slop."""
    return len(detect_slop(text)) == 0
