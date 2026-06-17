"""Voix de Perceval — synthèse vocale neurale (voix Microsoft via edge-tts).

Texte → MP3. Les voix sont gratuites, sans clé API. C'est ce qui remplace la
voix « robot » du navigateur par une voix naturelle.

Mode dégradé garanti : si le paquet `edge-tts` est absent (ex. machine desktop)
ou si le service Microsoft est muet, `synthesize` lève une exception. La route
HTTP l'attrape et renvoie une erreur → le navigateur reprend alors avec sa
propre voix. Perceval n'est donc JAMAIS muet.
"""

from __future__ import annotations

import re
from collections import OrderedDict

# Voix proposées à Jordan (françaises, neurales). L'`id` est l'identifiant
# edge-tts ; le `label` est ce qu'il voit dans le menu. Doit rester aligné
# avec la liste côté navigateur (web/ui/scripts/perceval.js → VOICES).
VOICES: list[dict] = [
    {"id": "fr-FR-HenriNeural",                "label": "Henri (homme)"},
    {"id": "fr-FR-RemyMultilingualNeural",     "label": "Rémy (homme)"},
    {"id": "fr-FR-DeniseNeural",               "label": "Denise (femme)"},
    {"id": "fr-FR-VivienneMultilingualNeural", "label": "Vivienne (femme)"},
    {"id": "fr-FR-EloiseNeural",               "label": "Éloïse (femme)"},
]
DEFAULT_VOICE = "fr-FR-HenriNeural"
_VALID = {v["id"] for v in VOICES}

# Corrections de prononciation : mot écrit → mot soufflé à la voix.
# « Jordan » sonnerait « Jordan » (son « an ») ; on souffle « Jordane » pour
# obtenir le « ane » attendu. À l'écran, rien ne change : c'est uniquement
# le texte envoyé au moteur de voix qui est ajusté.
_PRON = {"jordan": "Jordane"}
_PRON_RE = (
    re.compile(r"\b(" + "|".join(map(re.escape, _PRON)) + r")\b", re.IGNORECASE)
    if _PRON else None
)

# Symboles décoratifs qui ne doivent pas être lus à voix haute.
_DECOR_RE = re.compile(r"[✓⚠👋🧭💬🔊🔇➤▾🛡🔥🎯↻•→✏🎙]")

# Petit cache mémoire borné : Perceval répète des phrases (« Je suis là. »,
# le bonjour du jour…). Évite de regénérer et d'appeler Microsoft à chaque fois.
_CACHE: "OrderedDict[tuple, bytes]" = OrderedDict()
_CACHE_MAX = 64


def normalize_voice(voice: str | None) -> str:
    """Renvoie une voix de la liste blanche, ou la voix par défaut."""
    v = (voice or "").strip()
    return v if v in _VALID else DEFAULT_VOICE


def prepare_text(text: str) -> str:
    """Nettoie le texte (symboles décoratifs) et applique les corrections
    de prononciation avant de l'envoyer au moteur de voix."""
    t = _DECOR_RE.sub(" ", str(text or ""))
    if _PRON_RE is not None:
        t = _PRON_RE.sub(lambda m: _PRON[m.group(0).lower()], t)
    return re.sub(r"\s+", " ", t).strip()


def list_voices() -> list[dict]:
    """Liste des voix proposées (copie défensive)."""
    return [dict(v) for v in VOICES]


async def synthesize(text: str, voice: str | None = None) -> bytes:
    """Fabrique le MP3 (octets) pour `text` dans la voix demandée.

    Lève une exception si edge-tts est indisponible ou en panne — l'appelant
    bascule alors sur la voix du navigateur.
    """
    voice = normalize_voice(voice)
    spoken = prepare_text(text)
    if not spoken:
        return b""

    key = (voice, spoken)
    cached = _CACHE.get(key)
    if cached is not None:
        _CACHE.move_to_end(key)
        return cached

    # Import tardif : sur la machine desktop, le paquet peut être absent — on
    # ne veut pas casser le démarrage, juste retomber sur la voix navigateur.
    import edge_tts

    comm = edge_tts.Communicate(spoken, voice)
    buf = bytearray()
    async for chunk in comm.stream():
        if chunk.get("type") == "audio":
            buf.extend(chunk.get("data") or b"")
    audio = bytes(buf)

    if audio:
        _CACHE[key] = audio
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return audio
