"""Génération de mails de prospection en direct.

Workflow :
- Jordan a réalisé un site web POUR une célébrité ou une entreprise (par
  exemple un site de démo / portfolio sur un sous-domaine Triskell).
- Il veut envoyer un mail à cette célébrité/entreprise pour leur
  présenter ce site et les inviter à le découvrir.
- L'utilisateur colle l'URL du site qu'il a réalisé + choisit la catégorie.
- On télécharge le HTML pour comprendre la cible (qui est-ce, secteur,
  style du site fait).
- On capture une image du site via Microlink (best-effort).
- On liste les modèles d'emails existants.
- Claude choisit le meilleur modèle, l'adapte, rédige un mail qui PRÉSENTE
  ce site à la cible.
- On renvoie {subject, body_html, screenshot_b64?, ...} ; le frontend
  ouvre le composer pré-rempli avec le mail + l'image en pièce jointe
  inline (CID) référencée dans le HTML.

Toute la partie IA est synchrone (l'utilisateur attend), donc on garde le
prompt court et on limite le contexte du site à ~6 000 caractères.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse, quote_plus

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


def grab_screenshot(url: str, timeout: int = 25) -> Optional[dict]:
    """Capture une image du site via l'API publique Microlink (gratuite,
    limite raisonnable sans clé). Renvoie {b64, content_type, size} ou
    None en cas d'échec (best-effort, on continue sans).
    """
    try:
        api = (
            "https://api.microlink.io/?url=" + quote_plus(url)
            + "&screenshot=true&meta=false&waitForTimeout=1800"
            + "&viewport.width=1280&viewport.height=720&fullPage=false"
        )
        r = requests.get(api, timeout=timeout)
        if not r.ok:
            logger.info("microlink HTTP %s for %s", r.status_code, url)
            return None
        data = r.json()
        if data.get("status") != "success":
            return None
        sh_url = (data.get("data") or {}).get("screenshot", {}).get("url")
        if not sh_url:
            return None
        img = requests.get(sh_url, timeout=timeout)
        if not img.ok:
            return None
        b = img.content
        return {
            "b64": base64.b64encode(b).decode("ascii"),
            "content_type": img.headers.get("Content-Type", "image/png"),
            "size": len(b),
        }
    except Exception as exc:
        logger.info("microlink screenshot failed for %s: %s", url, exc)
        return None


SYSTEM_PROMPT_BASE = """Tu es l'assistant marketing personnel de Jordan Bourillot, fondateur de
Triskell Studio (Lagriffe Studio = sites web, RankUs Studio = SEO, Studio WoW = vidéo).

CONTEXTE — LIS BIEN :
L'URL que tu reçois est un SITE WEB QUE JORDAN A DÉJÀ CRÉÉ pour la cible
(célébrité, créateur, entreprise locale, etc.) — sur un sous-domaine Triskell
ou un domaine de test, pas encore en production officielle. Jordan veut
envoyer un mail à cette cible pour leur PRÉSENTER ce site qu'il a réalisé
spécifiquement pour eux, leur donner envie de l'ouvrir, et idéalement
qu'ils l'adoptent (le rachètent / déploient sur leur vrai domaine).

Ton job : rédiger un mail court, sincère, qui leur fait découvrir CE site
qu'il a fait pour eux, en mettant l'accent sur le soin apporté et sur ce
qu'il leur apporte concrètement.

LES MODÈLES ENREGISTRÉS SONT EN HTML COMPLET (avec styles inline,
couleurs, blocs structurés, mises en forme). Tu DOIS :
- Choisir le modèle qui correspond le mieux à la cible.
- RÉUTILISER son HTML complet : tu conserves la structure (divs, tables,
  styles inline, couleurs, polices, boutons, séparateurs, padding,
  background-color, etc.) telle quelle.
- Tu remplaces UNIQUEMENT le contenu textuel par du contenu personnalisé
  pour cette cible précise. Le rendu visuel du mail doit rester celui
  du modèle.
- Si le modèle contient un bouton CTA, tu remplaces son texte et son href
  par les bons éléments. Si plusieurs CTA, tu choisis celui qui sert le
  mieux le message ; tu peux retirer les autres en gardant la structure
  cohérente.
- Si le modèle contient une zone "aperçu du site", tu y mets
  <img src="cid:prospect_preview" alt="..." style="...">. Sinon, tu
  insères ce <img> à un endroit pertinent (juste après l'accroche ou
  avant la CTA).
- Si AUCUN modèle ne colle vraiment, tu pars d'une page blanche en
  HTML simple (<p>, <strong>, <a href>, <img>).

Règles de contenu :
- Le mail DOIT inclure le lien cliquable vers le site. Utilise
  EXACTEMENT l'URL fournie dans le <a href="URL">.
- Cite 1 ou 2 éléments PRÉCIS de la cible (projet, page, produit, ligne
  éditoriale) — ça doit prouver que tu as vraiment regardé qui ils sont.
- Ton : 110-200 mots max corps du mail. Accroche → ce que tu as fait pour
  eux → preview + lien → bénéfice → CTA douce.
- Pas de "Bonjour Madame/Monsieur". Si tu trouves le prénom dans le site,
  utilise-le. Sinon "Bonjour" tout court.
- Ne signe PAS le mail (signature ajoutée automatiquement par le composer).
- Pas d'invention : si tu ne sais pas, ne dis rien.

Tu réponds OBLIGATOIREMENT au format JSON strict avec ces clés :
{
  "target_name": "Nom de la personne ou de l'entreprise (texte court)",
  "used_template": "Nom du modèle utilisé (ou 'aucun')",
  "subject": "Objet du mail (court, sans guillemets autour)",
  "body_html": "Le HTML complet du mail, fidèle au modèle (styles inline conservés)."
}
"""

CATEGORY_HINTS = {
    # Conservé pour rétrocompatibilité (sans sous-type célébrité)
    "celebrity": (
        "CATÉGORIE : CÉLÉBRITÉ.\n"
        "- Ton respectueux, posé, jamais flagorneur.\n"
        "- Insiste sur l'idée que le site a été pensé SPÉCIALEMENT pour eux.\n"
        "- CTA douce type \"Ouvrez quand vous avez 30 secondes\"."
    ),
    "celebrity_sport": (
        "CATÉGORIE : CÉLÉBRITÉ — SPORTIF / SPORTIVE.\n"
        "Cible : boxeur, footballeur, MMA, cycliste, athlète, basketteur, etc.\n"
        "- Ton respectueux et concret, comme un fan qui connaît leur carrière.\n"
        "- Mentionne 1 ou 2 éléments PRÉCIS : un combat / match / record / titre\n"
        "  / palmarès / prochain événement vu sur le site, dans leurs interviews\n"
        "  ou leurs réseaux. Ça doit prouver que tu suis leur actu.\n"
        "- Insiste sur le fait que le site reflète leur identité de compétiteur :\n"
        "  palmarès mis en avant, calendrier des prochains événements, espace\n"
        "  sponsors / partenaires, presse, fan-zone.\n"
        "- Pas de jargon commercial. Pas de \"pack visibilité\" ou \"booster\n"
        "  votre présence\". Parle plutôt de \"un outil au service de votre\n"
        "  carrière\".\n"
        "- CTA douce : \"Ouvrez quand vous avez 30 secondes entre deux séances,\n"
        "  dites-moi ce que vous en pensez.\""
    ),
    "celebrity_influencer": (
        "CATÉGORIE : CÉLÉBRITÉ — INFLUENCEUR / CRÉATEUR.\n"
        "Cible : YouTubeur, TikTokeur, Instagrameur, podcaster, streamer Twitch,\n"
        "créateur de contenu en général.\n"
        "- Ton décontracté, comme entre créateurs. Vouvoiement OK mais sans\n"
        "  raideur, ou tutoiement si le ton du site / des posts est clairement\n"
        "  tu (tutoiement adapté à la plateforme).\n"
        "- Mentionne 1 ou 2 éléments PRÉCIS : une vidéo récente, une série de\n"
        "  contenus, un format signature, un partenariat visible, une mention\n"
        "  d'audience / abonnés vue sur le site.\n"
        "- Insiste sur le fait que le site reflète leur univers de contenu :\n"
        "  vitrine des derniers projets, lien vers les plateformes, espace\n"
        "  partenariats / brand deals, fan-mail / newsletter, shop éventuel.\n"
        "- Parle de \"univers\", \"communauté\", \"identité visuelle\" plutôt\n"
        "  que \"prospects\" et \"conversion\".\n"
        "- CTA douce : \"Ouvrez le entre deux montages, dites-moi ce que vous\n"
        "  en pensez.\""
    ),
    "business_template": (
        "CATÉGORIE : ENTREPRISE / COMMERCE — SITE MODÈLE GÉNÉRIQUE.\n"
        "Contexte précis : ce que Jordan a réalisé est un site MODÈLE générique\n"
        "adapté au métier de la cible (ex : un site type pour une boulangerie,\n"
        "envoyé à toutes les boulangeries que Jordan prospecte). Il n'est PAS\n"
        "encore personnalisé avec leurs vraies infos.\n"
        "- Le mail doit être honnête : présenter le site comme une démo / vitrine\n"
        "  de style pour leur métier, pas comme un site déjà adapté à eux.\n"
        "- Inviter à imaginer la version personnalisée : \"voici à quoi pourrait\n"
        "  ressembler votre site dans ce style, je peux le personnaliser avec\n"
        "  vos infos, vos photos, votre carte/services en 1 à 2 jours\".\n"
        "- Pas de \"votre prise de RDV est déjà en ligne\" — ça serait faux.\n"
        "- Mentionne le secteur (boulangerie, cabinet, restaurant…) mais ne\n"
        "  prétends pas avoir adapté à leur nom / leur ville / leurs produits.\n"
        "- CTA : \"15 min pour vous montrer la version personnalisée que je\n"
        "  ferais pour vous\" ou \"si l'idée vous plaît, je l'adapte à vos\n"
        "  vraies infos\"."
    ),
    "business_personalized": (
        "CATÉGORIE : ENTREPRISE / COMMERCE — 1ʳᵉ PERSONNALISATION (basée sur\n"
        "infos publiques uniquement).\n"
        "\n"
        "Contexte précis : Jordan a commencé à personnaliser le site avec ce\n"
        "qu'il a trouvé en PUBLIC (sur leur site existant, leurs réseaux, leur\n"
        "fiche Google) : nom, ville, secteur, principaux services / produits,\n"
        "ambiance générale. Ce N'EST PAS un site finalisé : il manque des\n"
        "détails (photos pros, textes définitifs, services exhaustifs, infos\n"
        "internes) qui nécessiteront un brief avec le client pour être finalisés.\n"
        "\n"
        "Règles de rédaction :\n"
        "- Présenter le site comme une PREMIÈRE VERSION, pas comme un produit\n"
        "  fini. Sois honnête : \"j'ai commencé à le personnaliser avec ce que\n"
        "  j'ai trouvé\", \"première ébauche\", \"point de départ\".\n"
        "- Ne PAS dire \"votre site est prêt à être déployé\" ni \"taillé\n"
        "  exactement pour vous\" — ce serait mensonger à ce stade.\n"
        "- Cite 1-2 éléments concrets que tu as identifiés (un service vu sur\n"
        "  leur fiche Google, leur ville, leur secteur, un produit phare). Ça\n"
        "  prouve que la personnalisation n'est pas vide, mais ça reste basé\n"
        "  sur du public.\n"
        "- Propose explicitement un brief court pour finaliser : photos pros,\n"
        "  formulations, services exhaustifs, identité finale.\n"
        "- CTA claire : \"15 min en visio pour qu'on affine ensemble — vous\n"
        "  voyez ce que ça donne avec vos vraies infos, et si ça vous plaît\n"
        "  on bascule sur votre vrai domaine\". Pas de promesse \"en 1 jour\n"
        "  c'est fini\" — il y a une étape brief obligatoire."
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
             ai_keys: dict, subtype: str = "personalized") -> dict:
    """Pipeline complet : fetch + prompt Claude + parse JSON.
    Renvoie {ok, subject, body_html, target_name, used_template, ...} ou
    {ok: False, error: ...}.

    subtype : 'template' = site modèle générique pour le métier,
              'personalized' = site déjà adapté à la cible (défaut).
              Pour celebrity, c'est toujours 'personalized'.
    """
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

    # Construction du prompt utilisateur — on envoie le HTML BRUT des modèles
    # pour que Claude réutilise la structure (styles inline, couleurs, blocs).
    # Limite : ~3500 chars de HTML par modèle, ~8 modèles max (sinon le prompt
    # explose). Si un modèle est trop long, on tronque proprement.
    tpl_block = "AUCUN MODÈLE ENREGISTRÉ."
    if templates:
        MAX_HTML_PER_TPL = 3500
        MAX_TPLS = 8
        chunks = []
        for i, t in enumerate(templates[:MAX_TPLS]):
            name = (t.get("name") or "").strip() or f"Modèle {i+1}"
            subj = (t.get("subject_default") or "").strip()
            raw_html = (t.get("body_html") or "").strip()
            if len(raw_html) > MAX_HTML_PER_TPL:
                raw_html = raw_html[:MAX_HTML_PER_TPL] + "\n<!-- [tronqué - HTML complet trop long] -->"
            chunks.append(
                f"--- MODÈLE #{i+1} ---\n"
                f"Nom : {name}\n"
                f"Objet par défaut : {subj or '(aucun)'}\n"
                f"HTML complet :\n{raw_html}"
            )
        tpl_block = "\n\n".join(chunks)

    # Choisit le bon prompt selon catégorie + subtype
    hint_key = category
    if category == "business":
        hint_key = f"business_{subtype}" if subtype in ("template", "personalized") else "business_personalized"
    elif category == "celebrity":
        hint_key = f"celebrity_{subtype}" if subtype in ("sport", "influencer") else "celebrity"
    category_hint = CATEGORY_HINTS.get(hint_key) or CATEGORY_HINTS.get("celebrity", "")

    user_prompt = (
        f"{category_hint}\n\n"
        f"MODÈLES DISPONIBLES (choisis-en un ou pars de zéro si rien ne colle) :\n"
        f"{tpl_block}\n\n"
        f"SITE DÉJÀ RÉALISÉ POUR LA CIBLE (à présenter dans le mail) :\n"
        f"URL : {url}\n"
        f"Domaine : {site['domain']}\n"
        f"Titre : {site['title']}\n"
        f"Titre OG : {site['og_title']}\n"
        f"H1 : {site['h1']}\n"
        f"Description : {site['description']}\n"
        f"Réseaux sociaux trouvés sur le site : {', '.join(site['social_links'][:5]) or '(aucun)'}\n"
        f"Contenu (extrait) :\n{site['body_text']}\n\n"
        f"Pour rappel : ce site a été créé par Jordan pour cette cible. Tu rédiges\n"
        f"un mail qui le leur présente et leur donne envie de cliquer pour le voir.\n"
        f"Lien à utiliser tel quel dans le mail : {url}\n\n"
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
            max_tokens=4000,
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

    body_html = (data.get("body_html") or "").strip()

    # Capture d'écran du site (best-effort). Si OK, on s'attend à ce que
    # Claude ait déjà inséré <img src="cid:prospect_preview"> dans body_html.
    # Sinon, on injecte l'image en haut du body. Si on n'a pas réussi à
    # capturer, on retire l'éventuelle balise placeholder.
    screenshot = grab_screenshot(url)
    if screenshot:
        if "cid:prospect_preview" not in body_html:
            # Claude a oublié de placer le placeholder : on l'ajoute en haut
            preview_img = ('<p style="margin:0 0 1em 0"><img src="cid:prospect_preview" '
                           'alt="Aperçu du site" style="max-width:100%;height:auto;'
                           'display:block;border-radius:8px;border:1px solid #e5e7eb;"></p>')
            body_html = preview_img + body_html
    else:
        # Pas de screenshot : on retire les balises placeholder vides
        body_html = re.sub(
            r'<img[^>]*src=["\']cid:prospect_preview["\'][^>]*>',
            "", body_html
        )

    return {
        "ok": True,
        "target_name":    (data.get("target_name") or site["title"] or site["domain"])[:200],
        "used_template":  (data.get("used_template") or "aucun")[:120],
        "subject":        (data.get("subject") or "").strip(),
        "body_html":      body_html,
        "source_url":     url,
        "category":       category,
        "subtype":        subtype,
        "screenshot_b64": (screenshot or {}).get("b64") or "",
        "screenshot_content_type": (screenshot or {}).get("content_type") or "",
    }
