"""Enrichisseur d'emails pour les prospects découverts par Obelisk.

Objectif : maximiser le taux de prospects avec email AVANT le filtre
`only_with_email`, sinon ce filtre dégage 80-100 % des trouvés (les
plateformes sociales exposent rarement l'email dans leur API).

Sources scannées, dans l'ordre :
  1. Description / bio du profil (regex)
  2. Liens `mailto:` ou texte d'email dans la page d'accueil du site
  3. Pages /contact, /contact-us, /about, /a-propos, /mentions-legales
  4. URLs en bio (Linktree, Beacons, Carrd…) — quand pas de site direct

Tolérant aux erreurs : tout échec (timeout, DNS, 404…) est silencieux,
on passe à la stratégie suivante. Concurrence par défaut = 10 prospects
en parallèle pour qu'un batch de 100 prospects prenne ~30s au lieu de
plusieurs minutes.

Utilisation :
    from triskell_command.integrations import email_enricher
    found = email_enricher.enrich_emails(prospect_dict)
    # ou en batch :
    email_enricher.enrich_batch(prospects, log=print)
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex et listes de filtrage
# ---------------------------------------------------------------------------
# Match basique mais robuste — on accepte les TLD de 2 à 24 chars
EMAIL_RX = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}"
)
MAILTO_RX = re.compile(
    r'mailto:([^"?\s\'<>]+)', re.IGNORECASE
)

# Faux positifs courants : noreply, images @2x, exemples de doc, fichiers
# d'image Wix/Shopify qui contiennent souvent "@" dans le nom.
SKIP_SUBSTRINGS = [
    "noreply@", "no-reply@", "donotreply@", "do-not-reply@",
    "@example.", "@yourdomain.", "@domain.com", "@email.com",
    "user@", "name@", "your@",
    "@2x.", "@3x.", "@4x.",
    ".png@", ".jpg@", ".jpeg@", ".gif@", ".svg@", ".webp@",
    "@x-default",
]
# Domaines de services tiers (sponsors, analytics, plateformes) qu'on ne veut
# JAMAIS pitcher : leur email apparaît souvent dans la bio/description ou
# dans le code des sites qu'on crawle, mais ce n'est pas le bon contact.
# Match en suffixe : couvre aussi les sous-domaines (o1.ingest.sentry.io).
SKIP_DOMAIN_SUFFIXES = (
    "sentry.io", "wixpress.com", "wix.com",
    "epidemicsound.com", "soundstripe.com", "artlist.io",
    "patreon.com", "kofi.com", "ko-fi.com", "buymeacoffee.com",
    "linktr.ee", "beacons.ai", "bio.link",
    "googlemail.com", "gmail-noreply.google.com",
    "shopify.com", "myshopify.com",
    "stripe.com", "paypal.com",
    "fb.com", "facebookmail.com",
    "twitter.com", "x.com",
    "youtube.com", "googleusercontent.com",
    "discord.com", "discord.gg",
    "expressvpn.com", "nordvpn.com", "surfshark.com",
    "squarespace.com", "godaddy.com",
)
SKIP_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".eot",
)

# Pages courantes à scanner après la home (priorité : où on trouve le
# plus souvent un email pro). Limité à 4 pour rester sous ~20s par site.
CONTACT_PATHS = [
    "/contact",
    "/contact-us",
    "/mentions-legales",
    "/about",
]

TIMEOUT_S = 4  # par requête HTTP (avant : 6s — trop long en cascade)
MAX_BYTES = 500_000  # 500 Ko : suffisant pour les pages textuelles
DEFAULT_WORKERS = 10
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 "
    "TriskellEmailEnricher/1.0"
)

# Hôtes à NE PAS gratter (pas la peine — pas d'email perso côté plateforme)
SKIP_HOSTS = {
    "youtube.com", "youtu.be", "www.youtube.com",
    "twitter.com", "x.com", "www.twitter.com", "www.x.com",
    "instagram.com", "www.instagram.com",
    "tiktok.com", "www.tiktok.com",
    "facebook.com", "www.facebook.com", "fb.com",
    "linkedin.com", "www.linkedin.com",
    "reddit.com", "www.reddit.com",
    "twitch.tv", "www.twitch.tv",
    "github.com", "www.github.com",
    "bsky.app",
    "discord.com", "discord.gg",
    "t.me", "telegram.me",
    "spotify.com", "open.spotify.com",
    "apple.com", "music.apple.com",
    "soundcloud.com",
    "amazon.com", "amazon.fr",
    "dailymotion.com", "www.dailymotion.com",
    "kick.com",
    "pinterest.com", "fr.pinterest.com",
    "snapchat.com",
}

# Bio-URLs qu'on accepte de gratter (sites de regroupement de liens)
LINK_AGGREGATORS = {
    "linktr.ee", "linktree.com", "beacons.ai", "carrd.co",
    "lnk.bio", "bio.link", "lnkfi.re", "campsite.bio",
    "msha.ke", "flowcode.com", "linkpop.com", "stan.store",
    "many.link", "milkshake.app", "shor.by", "withkoji.com",
    "snipfeed.co", "komi.io", "later.com",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_valid_email(email: str) -> bool:
    """Filtre les faux positifs (images, exemples, noreply, sponsors…)."""
    if not email or "@" not in email:
        return False
    e = email.lower().strip().strip(".,;:")
    if len(e) < 6 or len(e) > 254:
        return False
    if e.endswith(SKIP_SUFFIXES):
        return False
    for bad in SKIP_SUBSTRINGS:
        if bad in e:
            return False
    # Match strict
    if not EMAIL_RX.fullmatch(e):
        return False
    # Domaine blacklisté ? (couvre sous-domaines : o1.ingest.sentry.io)
    domain = e.split("@", 1)[1]
    for bad in SKIP_DOMAIN_SUFFIXES:
        if domain == bad or domain.endswith("." + bad):
            return False
    return True


def _clean_email(raw: str) -> str:
    """Normalise un email (lowercase, strip ponctuation)."""
    return raw.lower().strip().strip(".,;:()<>[]\"'")


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _is_skipped_host(url: str) -> bool:
    h = _host_of(url)
    return any(h == bad or h.endswith("." + bad) for bad in SKIP_HOSTS)


def _is_link_aggregator(url: str) -> bool:
    h = _host_of(url)
    return any(h == agg or h.endswith("." + agg) for agg in LINK_AGGREGATORS)


def _normalize_url(url: str) -> str:
    """Ajoute https:// si absent, valide grossièrement."""
    if not url or not isinstance(url, str):
        return ""
    u = url.strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    try:
        parsed = urlparse(u)
        if not parsed.netloc or "." not in parsed.netloc:
            return ""
    except Exception:
        return ""
    return u


def _deobfuscate(text: str) -> str:
    """Remet en forme les emails masqués (anti-bots) pour que le regex
    standard les attrape. Couvre les cas les plus fréquents :

      - HTML entities :  contact&#64;brand.com  → contact@brand.com
      - (at) / [at] :    contact (at) brand (dot) com
      - " at " / " AT ": contact at brand dot com
      - JS string split: "contact" + "@" + "brand.com" (rare, ignoré)
    """
    if not text:
        return text
    # 1) Entités HTML (&#64; = @, &#46; = .)
    out = (
        text.replace("&#64;", "@").replace("&#x40;", "@")
        .replace("&commat;", "@")
        .replace("&#46;", ".").replace("&period;", ".")
    )
    # 1bis) Escapes Unicode littéraux (sources JSON inline non-décodées) :
    # > = > , < = < , & = & , . = . — sinon "u003eemail@x"
    # ou "&amp;guidelines@x" deviennent des faux positifs collés.
    out = (
        out.replace("\\u003e", " ").replace("\\u003c", " ")
        .replace("\\u0026", " ").replace("\\u002e", ".")
        .replace("\\n", " ").replace("\\r", " ").replace("\\t", " ")
        .replace("&gt;", " ").replace("&lt;", " ").replace("&amp;", " ")
    )
    # 2) (at) / [at] / {at} avec ou sans espaces autour
    out = re.sub(
        r"\s*[\(\[\{]\s*(?:at|arobase|AT)\s*[\)\]\}]\s*",
        "@", out, flags=re.IGNORECASE,
    )
    out = re.sub(
        r"\s*[\(\[\{]\s*(?:dot|point|DOT)\s*[\)\]\}]\s*",
        ".", out, flags=re.IGNORECASE,
    )
    # 3) " at " / " arobase " (entouré d'espaces, sinon on casse "matter", "fat")
    out = re.sub(
        r"(?<=\w)\s+(?:at|arobase)\s+(?=\w)",
        "@", out, flags=re.IGNORECASE,
    )
    out = re.sub(
        r"(?<=\w)\s+(?:dot|point)\s+(?=\w)",
        ".", out, flags=re.IGNORECASE,
    )
    # 4) Compactage final : "contact @ brand.com" → "contact@brand.com"
    #    (les remplacements ci-dessus peuvent laisser des espaces autour
    #    du @ quand l'entité HTML était écrite avec espaces : " &#64; ")
    out = re.sub(r"(\w)\s*@\s*(\w)", r"\1@\2", out)
    return out


def _extract_emails_from_text(text: str) -> set[str]:
    """Extrait + valide tous les emails d'un blob de texte.
    Inclut un passage de désobfuscation pour rattraper les emails
    écrits "contact (at) brand (dot) com"."""
    if not text:
        return set()
    out: set[str] = set()
    # mailto: d'abord (plus fiables)
    for m in MAILTO_RX.findall(text):
        e = _clean_email(m.split("?")[0])  # vire ?subject=...
        if _is_valid_email(e):
            out.add(e)
    # Désobfuscation + regex plein texte
    deobfuscated = _deobfuscate(text)
    for m in EMAIL_RX.findall(deobfuscated):
        e = _clean_email(m)
        if _is_valid_email(e):
            out.add(e)
    return out


def _fetch(url: str, timeout: float = TIMEOUT_S) -> str:
    """GET tolérant : renvoie le texte ou '' en cas d'erreur. Tronque à MAX_BYTES."""
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "fr,en;q=0.7"},
            allow_redirects=True,
            stream=True,
        )
        if r.status_code >= 400:
            return ""
        # Lit max 800 Ko pour éviter d'avaler des PDF/vidéo
        content = b""
        for chunk in r.iter_content(chunk_size=16_384):
            content += chunk
            if len(content) >= MAX_BYTES:
                break
        # Détection encoding tolérante
        try:
            return content.decode(r.encoding or "utf-8", errors="ignore")
        except Exception:
            return content.decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.debug("fetch failed for %s : %s", url, exc)
        return ""


def _scrape_website(website: str) -> set[str]:
    """Tente homepage + pages contact courantes. S'arrête dès qu'on trouve."""
    base = _normalize_url(website)
    if not base or _is_skipped_host(base):
        return set()
    found: set[str] = set()
    # Homepage d'abord
    html = _fetch(base)
    found |= _extract_emails_from_text(html)
    if found:
        return found
    # Pages contact / about / mentions-légales
    parsed = urlparse(base)
    root = f"{parsed.scheme}://{parsed.netloc}"
    for path in CONTACT_PATHS:
        url = urljoin(root, path)
        html = _fetch(url)
        if html:
            found |= _extract_emails_from_text(html)
            if found:
                break
    return found


def _scrape_bio_urls(urls: Iterable[str]) -> set[str]:
    """Scanne les URLs en bio. Priorise les agrégateurs (Linktree…)
    car ils centralisent souvent un mail pro.

    Pour les sites « normaux » (non-aggregators), on ne s'arrête pas à la home :
    on tape aussi /contact, /about, /mentions-legales. Indispensable pour
    YouTube où les liens sponsors (Sentry, ExpressVPN) apparaissent souvent
    AVANT le site perso : si on s'arrête à la home sans email, on ne teste
    jamais le vrai site perso plus loin dans la liste.
    """
    if not urls:
        return set()
    # Trie : agrégateurs en premier, sites perso ensuite
    sorted_urls = sorted(urls, key=lambda u: 0 if _is_link_aggregator(u) else 1)
    found: set[str] = set()
    for url in sorted_urls[:6]:  # max 6 URLs par prospect
        clean = _normalize_url(url)
        if not clean or _is_skipped_host(clean):
            continue
        if _is_link_aggregator(clean):
            # Linktree & co : la home suffit, tout y est listé
            html = _fetch(clean)
            if html:
                found |= _extract_emails_from_text(html)
        else:
            # Site perso : on tente home + pages contact/about
            found |= _scrape_website(clean)
        if found:
            break
    return found


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def enrich_emails(prospect: dict) -> list[str]:
    """Renvoie la liste fusionnée des emails déjà connus + ceux qu'on trouve.

    Modifie PAS le dict source. Renvoie [] si rien trouvé.
    """
    known = set(
        _clean_email(e) for e in (prospect.get("emails") or [])
        if isinstance(e, str) and _is_valid_email(_clean_email(e))
    )
    if known:
        # Déjà au moins un email valide → on garde et on s'arrête
        # (on pourrait toujours essayer d'en trouver d'autres mais ça
        # coûte du temps réseau pour peu de valeur)
        return sorted(known)

    # 1) Bio / description : instantané, pas de réseau
    bio_text = " ".join(filter(None, [
        prospect.get("description") or "",
        prospect.get("bio") or "",
        prospect.get("summary") or "",
        prospect.get("about") or "",
        prospect.get("headline") or "",
    ]))
    found = _extract_emails_from_text(bio_text)
    if found:
        return sorted(found)

    # 2) Site web officiel
    website = prospect.get("website") or ""
    if website:
        found = _scrape_website(website)
        if found:
            return sorted(found)

    # 3) URLs en bio (Linktree, Beacons, site perso annexe…)
    bio_urls = (
        prospect.get("urls_in_bio")
        or prospect.get("other_urls")
        or []
    )
    if bio_urls:
        found = _scrape_bio_urls(bio_urls)
        if found:
            return sorted(found)

    return []


def enrich_batch(
    prospects: list[dict],
    *,
    log: Callable[[str], None] | None = None,
    max_workers: int = DEFAULT_WORKERS,
    skip_if_has_email: bool = True,
) -> dict:
    """Enrichit une liste de prospects EN PLACE.

    Pour chaque prospect, met à jour `prospect["emails"]` avec ce qu'on
    trouve. Concurrent : `max_workers` prospects scannés en parallèle.

    Renvoie un dict de stats : { "scanned": int, "enriched": int,
                                   "already_had_email": int }.
    """
    log = log or (lambda _msg: None)
    stats = {"scanned": 0, "enriched": 0, "already_had_email": 0}

    todo: list[tuple[int, dict]] = []
    for idx, p in enumerate(prospects):
        if skip_if_has_email and (p.get("emails") or []):
            stats["already_had_email"] += 1
            continue
        todo.append((idx, p))

    if not todo:
        return stats

    log(f"📧 Enrichissement email : scan de {len(todo)} prospect(s) "
        f"sans adresse connue (concurrence {max_workers})…")

    def _work(item: tuple[int, dict]) -> tuple[int, list[str]]:
        idx, p = item
        try:
            emails = enrich_emails(p)
        except Exception as exc:
            logger.debug("enrich_emails crashed for %s : %s",
                         p.get("name") or p.get("handle") or "?", exc)
            emails = []
        return idx, emails

    enriched_examples: list[str] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for fut in as_completed([pool.submit(_work, it) for it in todo]):
            try:
                idx, emails = fut.result()
            except Exception:
                continue
            stats["scanned"] += 1
            if emails:
                prospects[idx]["emails"] = emails
                stats["enriched"] += 1
                if len(enriched_examples) < 3:
                    name = (prospects[idx].get("name")
                            or prospects[idx].get("handle") or "?")
                    enriched_examples.append(f"{name} → {emails[0]}")

    if stats["enriched"]:
        log(f"✅ {stats['enriched']}/{stats['scanned']} prospect(s) enrichis "
            f"avec un email. Ex : " + " · ".join(enriched_examples))
    else:
        log(f"ℹ Aucun email trouvé sur les {stats['scanned']} prospect(s) "
            f"scannés (bio/site/liens).")
    return stats
