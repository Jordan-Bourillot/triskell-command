"""Génération de mails de prospection en direct.

Workflow :
1. L'utilisateur colle une URL + choisit une catégorie (celebrity / business)
2. On télécharge le HTML, on extrait le contenu pertinent
3. On liste les modèles d'emails existants
4. On envoie tout à Claude qui choisit le meilleur modèle et l'adapte
5. On renvoie {subject, body_html, target_name, used_template_name}

Toute la partie IA est synchrone (l'utilisateur attend), donc on garde le
prompt court et on limite le contexte du site à ~6 000 caractères.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def fetch_and_extract(url: str, timeout: int = 12) -> dict:
    """Télécharge l'URL et extrait les infos utiles. Renvoie un dict :
    {title, description, h1, body_text (~6000 chars), social_links, domain}.
    Lève en cas d'échec réseau ou de HTTP non-2xx.
    """
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "fr,en;q=0.8"}
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    html = resp.text

    soup = BeautifulSoup(html, "html.parser")
    # Retire les balises qui polluent
    for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
        tag.decompose()

    title = (soup.title.string.strip() if soup.title and soup.title.string else "")
    meta_desc = ""
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        meta_desc = md["content"].strip()
    og_desc = soup.find("meta", attrs={"property": "og:description"})
    if og_desc and og_desc.get("content") and not meta_desc:
        meta_desc = og_desc["content"].strip()

    og_title = soup.find("meta", attrs={"property": "og:title"})
    og_title_val = og_title["content"].strip() if og_title and og_title.get("content") else ""

    h1 = ""
    h1_tag = soup.find("h1")
    if h1_tag:
        h1 = h1_tag.get_text(" ", strip=True)[:200]

    # Body text condensé
    body_text = soup.get_text(" ", strip=True)
    body_text = re.sub(r"\s+", " ", body_text)[:6000]

    # Réseaux sociaux
    social_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"(instagram|tiktok|youtube|facebook|twitter|x\.com|linkedin|threads)\.com",
                     href, flags=re.I):
            if href not in social_links:
                social_links.append(href)
        if len(social_links) >= 8:
            break

    domain = urlparse(url).netloc.replace("www.", "")

    return {
        "title": title,
        "og_title": og_title_val,
        "description": meta_desc,
        "h1": h1,
        "body_text": body_text,
        "social_links": social_links,
        "domain": domain,
    }


SYSTEM_PROMPT_BASE = """Tu es l'assistant marketing personnel de Jordan Bourillot, fondateur de
Triskell Studio (Lagriffe Studio = sites web, RankUs Studio = SEO, Studio WoW = vidéo).

Ton job : rédiger un mail de prospection court, sincère, qui montre que Jordan a
vraiment regardé le site / le travail de la cible avant d'écrire. Pas de copier-coller
générique, pas de jargon, pas de "j'ai été impressionné par votre travail" creux.

Règles absolues :
- Tu reçois plusieurs MODÈLES de mails. Tu CHOISIS celui qui colle le mieux
  à la cible, ET tu l'adaptes (tu ne le sors pas brut). Si aucun modèle ne
  colle vraiment, tu pars d'une page blanche en gardant le style général.
- Tu cites 1 ou 2 éléments PRÉCIS du site (un projet, une page, une phrase
  qui t'a marqué, le nom d'un produit/service). Ça doit prouver que tu as
  ouvert le site.
- Ton court : 100-180 mots max corps du mail. Une accroche → un point précis
  → une proposition simple → une CTA douce.
- Pas de "Bonjour Madame/Monsieur" (impersonnel). Si tu trouves le prénom
  dans le site, utilise-le. Sinon "Bonjour" tout court.
- Ne signe PAS le mail (la signature sera ajoutée automatiquement).
- Pas d'invention d'éléments : si tu ne sais pas, ne dis rien.

Tu réponds OBLIGATOIREMENT au format JSON strict avec ces clés :
{
  "target_name": "Nom de la personne ou de l'entreprise (texte court)",
  "used_template": "Nom du modèle utilisé (ou 'aucun' si tu pars de zéro)",
  "subject": "Objet du mail (court, sans guillemets autour)",
  "body_html": "<p>...</p> HTML simple avec <p>, <br>, <strong>, <em>, <a href>."
}
"""

CATEGORY_HINTS = {
    "celebrity": (
        "CATÉGORIE : CÉLÉBRITÉ.\n"
        "- Ton respectueux et admiratif (sans flagornerie).\n"
        "- Pas d'arguments commerciaux frontaux. On propose plutôt une\n"
        "  collaboration, un échange, un cadeau pertinent.\n"
        "- Mentionne précisément un projet/œuvre/post récent qui t'a marqué.\n"
        "- Si la cible a déjà un site et une équipe, ne dis pas \"je peux te\n"
        "  refaire ton site\" — ça serait maladroit. Trouve un angle plus fin."
    ),
    "business": (
        "CATÉGORIE : ENTREPRISE / COMMERCE.\n"
        "- Ton commercial mais chaleureux, comme un voisin qui passe dire bonjour.\n"
        "- Identifie le secteur (boulangerie, cabinet, restaurant, garage…).\n"
        "- Mentionne 1 chose concrète vue sur leur site (un produit, un service,\n"
        "  une mention dans les actualités, un défaut visible).\n"
        "- Propose un service Triskell pertinent (site + Maps si commerce local,\n"
        "  SEO si déjà un site, vidéo si activité visuelle).\n"
        "- CTA douce type \"15 min en visio pour vous montrer ce que je vois\"."
    ),
}


def _model_first_provider(ai_keys: dict) -> tuple[str, str] | None:
    """Choisit le premier provider dispo + un modèle raisonnable."""
    if not ai_keys:
        return None
    if ai_keys.get("anthropic"):
        return ("anthropic", "claude-sonnet-4-5")
    if ai_keys.get("openai"):
        return ("openai", "gpt-4o-mini")
    if ai_keys.get("google"):
        return ("google", "gemini-1.5-flash")
    if ai_keys.get("mistral"):
        return ("mistral", "mistral-small-latest")
    return None


def generate(url: str, category: str, templates: list[dict],
             ai_keys: dict) -> dict:
    """Pipeline complet : fetch + prompt Claude + parse JSON.
    Renvoie {ok, subject, body_html, target_name, used_template, ...} ou
    {ok: False, error: ...}."""
    if not ai_keys or not ai_keys.get("anthropic"):
        return {"ok": False, "error": "Clé API Anthropic manquante (Réglages → Services IA)."}

    try:
        site = fetch_and_extract(url)
    except requests.HTTPError as exc:
        return {"ok": False, "error": f"Site inaccessible (HTTP {exc.response.status_code})."}
    except requests.RequestException as exc:
        return {"ok": False, "error": f"Impossible de joindre le site : {exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"Erreur d'analyse : {exc}"}

    # Construction du prompt utilisateur
    tpl_block = "AUCUN MODÈLE ENREGISTRÉ."
    if templates:
        lines = []
        for t in templates[:20]:
            name = (t.get("name") or "").strip()
            subj = (t.get("subject_default") or "").strip()
            # On garde un extrait du body (HTML stripped)
            raw_html = t.get("body_html") or ""
            body_clean = re.sub(r"<[^>]+>", " ", raw_html)
            body_clean = re.sub(r"\s+", " ", body_clean).strip()[:500]
            lines.append(f"- Nom : {name}\n  Objet par défaut : {subj}\n  Aperçu : {body_clean}")
        tpl_block = "\n".join(lines)

    user_prompt = (
        f"{CATEGORY_HINTS.get(category, '')}\n\n"
        f"MODÈLES DISPONIBLES (choisis-en un ou pars de zéro si rien ne colle) :\n"
        f"{tpl_block}\n\n"
        f"SITE CIBLE À ANALYSER :\n"
        f"URL : {url}\n"
        f"Domaine : {site['domain']}\n"
        f"Titre : {site['title']}\n"
        f"Titre OG : {site['og_title']}\n"
        f"H1 : {site['h1']}\n"
        f"Description : {site['description']}\n"
        f"Réseaux sociaux : {', '.join(site['social_links'][:5]) or '(non trouvés)'}\n"
        f"Contenu (extrait) :\n{site['body_text']}\n\n"
        f"Réponds maintenant au format JSON strict, rien d'autre."
    )

    try:
        from anthropic import Anthropic
    except ImportError:
        return {"ok": False, "error": "Le SDK Anthropic n'est pas installé côté serveur."}

    try:
        client = Anthropic(api_key=ai_keys["anthropic"])
        resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1200,
            system=SYSTEM_PROMPT_BASE,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        return {"ok": False, "error": f"Échec appel Claude : {exc}"}

    # Extraction du JSON
    text = ""
    try:
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text += block.text
    except Exception:
        text = str(resp)

    text = text.strip()
    # Au cas où Claude entoure le JSON de ```json … ```
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
    except Exception:
        return {"ok": False, "error": "Réponse Claude non parsable en JSON.",
                "raw": text[:500]}

    return {
        "ok": True,
        "target_name":    (data.get("target_name") or site["title"] or site["domain"])[:200],
        "used_template":  (data.get("used_template") or "aucun")[:120],
        "subject":        (data.get("subject") or "").strip(),
        "body_html":      (data.get("body_html") or "").strip(),
        "source_url":     url,
        "category":       category,
    }
