"""Moteur de mesure La Part de Voix.

Pose des questions d'intention d'achat aux IA branchées au web
(ChatGPT via l'API de recherche OpenAI, Perplexity, Gemini avec
Google Search), extrait les noms d'entreprises cités, et calcule
la part de voix de chacun sur l'ensemble des passages.

Règle d'honnêteté gravée : une réponse isolée ne prouve rien, seule
la tendance multi-passages est fiable. Tout résultat rendu par ce
module porte le nombre de passages et la date.
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Le même esprit que la surveillance GEO : on veut la réponse qu'aurait
# un internaute normal, pas une réponse flatteuse.
PROMPT_CONSOMMATEUR = (
    "Tu es une IA grand public que des utilisateurs interrogent tous les "
    "jours. Réponds à la question ci-dessous comme tu le ferais "
    "normalement : librement, objectivement, en citant des noms précis "
    "si c'est pertinent. Ne triche pas, ne flatte personne, sois utile.\n\n"
    "Question : {question}\n\nTa réponse :"
)

# Plateformes et annuaires : jamais comptés comme « concurrents cités ».
_PLATEFORMES = {
    "pagesjaunes", "pages jaunes", "google", "google maps", "yelp",
    "tripadvisor", "leboncoin", "linkedin", "facebook", "instagram",
    "meilleurtaux comparateur", "trustpilot", "doctolib", "yellowpages",
    "seloger", "leboncoin immobilier", "bienici", "logic-immo",
    "justifit", "avocat.fr", "conseil national des barreaux",
    "chatgpt", "perplexity", "gemini", "wikipedia",
}

# Mots trop génériques pour identifier une entreprise à eux seuls.
_MOTS_GENERIQUES = {
    "cabinet", "agence", "courtier", "courtiers", "assurance",
    "assurances", "credit", "immobilier", "immobiliere", "avocat",
    "avocats", "expert", "experts", "comptable", "comptables",
    "expertise", "conseil", "conseils", "societe", "groupe", "france",
    "sarl", "sas", "eurl", "selarl", "notaire", "maitre", "gestion",
    "patrimoine", "finance", "et", "les", "des", "sud", "nord", "ouest",
}


# ------------------------------------------------------------------ clés

def recuperer_cles(client=None, app_state=None) -> dict:
    """Renvoie {provider: cle} en réutilisant la chaîne shared_secrets,
    complétée par les providers hors coeur (Perplexity, Groq, DeepSeek)
    lus dans l'environnement, comme le fait l'écran GEO."""
    try:
        from ..shared_secrets import get_ai_keys
        cles = dict(get_ai_keys(client=client, app_state=app_state) or {})
    except Exception as exc:  # pragma: no cover - dépend de l'environnement
        logger.info("partdevoix cles: %s", exc)
        cles = {}
    extras = {
        "perplexity": "PERPLEXITY_API_KEY",
        "groq": "GROQ_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }
    for prov, env_name in extras.items():
        if not cles.get(prov):
            valeur = os.environ.get(env_name, "")
            if valeur:
                cles[prov] = valeur
    return cles


def providers_web(cles: dict) -> list[dict]:
    """Les IA « branchées au web », les seules qui comptent pour la
    part de voix (les IA à mémoire pure ne connaissent pas les TPE)."""
    catalogue = [
        ("openai", "ChatGPT (OpenAI, mode recherche)", "gpt-4o-mini-search-preview"),
        ("perplexity", "Perplexity (mode web)", "sonar"),
        ("google", "Gemini (Google, mode web)", "gemini-2.5-flash"),
    ]
    provs = []
    for pid, label, model in catalogue:
        if cles.get(pid):
            provs.append({"id": pid, "label": label, "model": model,
                          "key": cles[pid]})
    return provs


# ------------------------------------------------------------- interroger

def poser(provider: dict, question: str) -> str:
    """Pose une question à un provider web, renvoie le texte (vide si échec)."""
    prompt = PROMPT_CONSOMMATEUR.format(question=question.strip())
    pid = provider.get("id")
    if pid == "openai":
        return _ask_openai_recherche(provider, prompt)
    if pid == "perplexity":
        return _ask_openai_compatible(
            provider, prompt, "https://api.perplexity.ai/chat/completions",
            defaut="sonar")
    if pid == "google":
        return _ask_gemini_recherche(provider, prompt)
    return ""


def _ask_openai_recherche(provider: dict, prompt: str) -> str:
    """ChatGPT avec recherche web (modèle *-search-preview*). C'est le plus
    proche de ce que voit un utilisateur de ChatGPT ; si le modèle de
    recherche est refusé, repli sur le modèle classique (sans web),
    marqué côté appelant par une réponse plus pauvre mais jamais fausse."""
    texte = _ask_openai_compatible(
        provider, prompt, "https://api.openai.com/v1/chat/completions",
        defaut="gpt-4o-mini-search-preview", sans_temperature=True)
    if texte:
        return texte
    repli = dict(provider)
    repli["model"] = "gpt-4o-mini"
    return _ask_openai_compatible(
        repli, prompt, "https://api.openai.com/v1/chat/completions",
        defaut="gpt-4o-mini")


def _ask_openai_compatible(provider: dict, prompt: str, url: str,
                           defaut: str, sans_temperature: bool = False) -> str:
    """Appel générique au format OpenAI (OpenAI, Perplexity)."""
    try:
        import requests
        corps = {
            "model": provider.get("model") or defaut,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1200,
        }
        if not sans_temperature:
            corps["temperature"] = 0.4
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {provider['key']}",
                     "Content-Type": "application/json"},
            json=corps, timeout=60,
        )
        if r.status_code >= 400:
            logger.info("partdevoix %s HTTP %s: %s", provider.get("id"),
                        r.status_code, r.text[:200])
            return ""
        data = r.json()
        return (data.get("choices", [{}])[0]
                .get("message", {}).get("content", "")) or ""
    except Exception as exc:
        logger.info("partdevoix %s exception: %s", provider.get("id"), exc)
        return ""


def _ask_gemini_recherche(provider: dict, prompt: str) -> str:
    """Gemini avec la recherche Google activée (même appel que le GEO)."""
    try:
        import requests
        model = provider.get("model") or "gemini-2.5-flash"
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent",
            params={"key": provider["key"]},
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}], "role": "user"}],
                "tools": [{"google_search": {}}],
                "generationConfig": {"temperature": 0.4,
                                     "maxOutputTokens": 1500},
            },
            timeout=60,
        )
        if r.status_code >= 400:
            logger.info("partdevoix gemini HTTP %s: %s",
                        r.status_code, r.text[:200])
            return ""
        cands = (r.json().get("candidates") or [])
        if not cands:
            return ""
        parts = (cands[0].get("content") or {}).get("parts") or []
        return "".join((p.get("text") or "") for p in parts) or ""
    except Exception as exc:
        logger.info("partdevoix gemini exception: %s", exc)
        return ""


# ----------------------------------------------------------- extraction

def extraire_noms(question: str, reponse: str, cles: dict) -> list[str]:
    """Extrait les noms d'entreprises locales cités dans une réponse d'IA.

    L'extraction passe par Claude (haiku) parce que les réponses sont du
    texte libre. En cas d'échec, renvoie une liste vide plutôt qu'un
    résultat deviné : une mesure absente vaut mieux qu'une mesure fausse.
    """
    if not (reponse or "").strip():
        return []
    if not cles.get("anthropic"):
        logger.info("partdevoix extraction: pas de cle anthropic")
        return []
    prompt = (
        "Voici la réponse d'une IA grand public à la question suivante.\n"
        f"Question : {question}\n"
        f"Réponse :\n{reponse[:6000]}\n\n"
        "Liste les noms PROPRES d'entreprises, cabinets ou professionnels "
        "locaux que cette réponse recommande ou cite. Ignore les annuaires, "
        "plateformes et sites génériques (Pages Jaunes, Google, SeLoger, "
        "Doctolib...). Ignore les conseils généraux sans nom. Réponds "
        "UNIQUEMENT par un tableau JSON de chaînes, sans commentaire. "
        "Exemple : [\"Cabinet Durand\", \"Assurances Le Goff\"]. "
        "S'il n'y a aucun nom, réponds []."
    )
    try:
        from triskell_core.ai.providers import send_to_provider
        brut = send_to_provider("anthropic", "claude-haiku-4-5", prompt,
                                {"anthropic": cles["anthropic"]}) or ""
    except Exception as exc:
        logger.info("partdevoix extraction: %s", exc)
        return []
    m = re.search(r"\[.*\]", brut, re.DOTALL)
    if not m:
        return []
    try:
        noms = json.loads(m.group(0))
    except Exception:
        return []
    propres = []
    for nom in noms:
        if not isinstance(nom, str):
            continue
        nom = nom.strip()
        if not nom or normaliser(nom) in {normaliser(p) for p in _PLATEFORMES}:
            continue
        propres.append(nom)
    return propres


# ---------------------------------------------------------- correspondance

def normaliser(texte: str) -> str:
    """Minuscules, sans accents, sans ponctuation, espaces simples."""
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = re.sub(r"[^a-z0-9 ]", " ", texte.lower())
    return re.sub(r"\s+", " ", texte).strip()


def _jetons_significatifs(nom: str) -> set:
    return {t for t in normaliser(nom).split()
            if len(t) >= 3 and t not in _MOTS_GENERIQUES}


def correspond(nom_a: str, nom_b: str) -> bool:
    """Deux libellés désignent-ils la même entreprise ?
    Inclusion après normalisation, ou partage d'un jeton distinctif."""
    na, nb = normaliser(nom_a), normaliser(nom_b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    ja, jb = _jetons_significatifs(nom_a), _jetons_significatifs(nom_b)
    commun = ja & jb
    if not commun:
        return False
    # Un seul jeton commun suffit s'il est vraiment distinctif (4 lettres
    # et plus, les noms de famille bretons comme « Goff » en font 4),
    # sinon il en faut deux (évite « Cabinet X » = « Cabinet Y »).
    return len(commun) >= 2 or any(len(t) >= 4 for t in commun)


# ------------------------------------------------------------- mesurer

def mesurer(questions: list[str], passes: int, cles: dict,
            providers: list[dict] | None = None) -> dict:
    """Pose chaque question `passes` fois à chaque IA web.

    Renvoie {"runs": [...], "ts": iso, "nb_reponses": N} où chaque run
    contient la question, le provider, la réponse brute et les noms cités.
    """
    provs = providers if providers is not None else providers_web(cles)
    runs = []
    for question in questions:
        for _ in range(max(1, passes)):
            for prov in provs:
                reponse = poser(prov, question)
                cites = extraire_noms(question, reponse, cles) if reponse else []
                runs.append({
                    "question": question,
                    "provider": prov["id"],
                    "reponse": reponse,
                    "cites": cites,
                    "ok": bool(reponse),
                })
    return {
        "runs": runs,
        "ts": datetime.now(timezone.utc).isoformat(),
        "nb_reponses": sum(1 for r in runs if r["ok"]),
    }


def agreger(mesure: dict) -> list[dict]:
    """Part de voix par entreprise citée, toutes réponses confondues.

    Renvoie une liste triée [{nom, occurrences, part}] où `part` est le
    pourcentage de réponses valides qui citent ce nom. Les libellés
    voisins (« Cabinet Durand » / « Durand Assurances ») fusionnent.
    """
    reponses_ok = [r for r in (mesure.get("runs") or []) if r.get("ok")]
    total = len(reponses_ok)
    if not total:
        return []
    groupes: list[dict] = []
    for run in reponses_ok:
        vus_dans_cette_reponse: set = set()
        for nom in run.get("cites") or []:
            groupe = next((g for g in groupes
                           if correspond(g["nom"], nom)), None)
            if groupe is None:
                groupe = {"nom": nom, "occurrences": 0}
                groupes.append(groupe)
            cle_groupe = id(groupe)
            if cle_groupe in vus_dans_cette_reponse:
                continue  # cité deux fois dans la même réponse = une fois
            vus_dans_cette_reponse.add(cle_groupe)
            groupe["occurrences"] += 1
    for g in groupes:
        g["part"] = round(100.0 * g["occurrences"] / total, 1)
    groupes.sort(key=lambda g: -g["occurrences"])
    return groupes


def part_de(nom_entreprise: str, agregat: list[dict]) -> float:
    """La part de voix d'une entreprise donnée dans un agrégat (0 si absente)."""
    for g in agregat:
        if correspond(nom_entreprise, g["nom"]):
            return float(g.get("part") or 0.0)
    return 0.0
