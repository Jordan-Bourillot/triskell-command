"""Découverte de créateurs / influenceurs via PhantomBuster.

Étend Obelisk pour couvrir Instagram, TikTok et LinkedIn — plateformes
que le pipeline natif `creators_pipeline` ne scrappe pas (Google ne
fournit pas d'API publique pour les indexer en masse).

Principe :
1. Jordan configure dans PhantomBuster un Phantom de découverte par
   plateforme (LinkedIn Search Export, Instagram Hashtag Collector,
   TikTok Hashtag Scraper). Il colle l'ID de chacun dans les Réglages
   → Intégrations → PhantomBuster.
2. Quand on lance une recherche pour une plateforme PhantomBuster,
   `discover_profiles()` :
   - Lance le Phantom avec les arguments adaptés à la niche
   - Poll l'état du container jusqu'à completion (timeout 30 min)
   - Récupère le résultat (CSV ou JSON suivant le Phantom)
   - Mappe chaque profil au format Prospect Triskell
   - Insère/upsert dans la table partagée `public.prospects`
3. L'enrichissement email se fait après, via le `enrichers/footprint`
   existant (visite le site web du créateur s'il est connu).

Phantoms recommandés côté PhantomBuster (à configurer une fois) :
- LinkedIn : https://phantombuster.com/automations/linkedin/4147/linkedin-search-export
- Instagram : https://phantombuster.com/automations/instagram/3489/instagram-hashtag-collector
- TikTok : https://phantombuster.com/automations/tiktok/13070/tiktok-hashtag-scraper
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import phantombuster_client as pb
from .multi_tenant import with_workspace

logger = logging.getLogger(__name__)


SUPPORTED_PLATFORMS = ("linkedin", "instagram", "tiktok")


# Statuts terminaux d'un container PhantomBuster
_TERMINAL_STATUSES = ("finished", "completed", "success", "error", "failed",
                       "stopped", "canceled", "cancelled")


# ---------------------------------------------------------------------------
# Construction des arguments par plateforme
# ---------------------------------------------------------------------------
def _linkedin_search_url(niche: str) -> str:
    """Construit une URL de recherche LinkedIn pour le Phantom Search Export.

    On recherche dans les personnes (PEOPLE) avec le mot-clé donné, en
    pondérant légèrement vers les profils francophones (langue de l'UI).
    """
    from urllib.parse import quote_plus
    return ("https://www.linkedin.com/search/results/people/?"
            f"keywords={quote_plus(niche)}")


# Compagnons génériques utilisés quand l'utilisateur ne fournit qu'un seul
# hashtag : on en ajoute un de la même famille pour satisfaire les Phantoms
# qui exigent ≥ 2 termes. L'ordre est tenté dans l'ordre, on prend le 1er
# qui n'est pas identique au hashtag user.
_HASHTAG_COMPANIONS = (
    "business", "entrepreneur", "marketing", "growth", "coaching",
    "formation", "mindset", "success", "startup", "freelance",
)


def _ensure_two_hashtags(niche: str) -> list[str]:
    """Renvoie une liste d'au moins 2 hashtags distincts depuis la niche.

    Accepte une virgule comme séparateur explicite. Si l'utilisateur n'en
    fournit qu'un, on tente d'abord de découper un mot composé en deux
    parties (ex: "coachingbusiness" → ["coaching", "business"]), sinon on
    appose un compagnon générique de la liste ci-dessus.
    """
    parts = [h.strip().lstrip("#").replace(" ", "").lower()
             for h in (niche or "").split(",") if h.strip()]
    parts = [p for p in parts if p]
    if not parts:
        parts = ["entrepreneur"]
    if len(parts) >= 2:
        # Déduplique tout en gardant l'ordre
        seen, out = set(), []
        for p in parts:
            if p not in seen:
                seen.add(p)
                out.append(p)
        if len(out) >= 2:
            return out
        parts = out

    base = parts[0]
    # Essai 1 : couper un mot composé long en deux moitiés sémantiques
    # (heuristique très simple : sépare avant un mot connu).
    for word in _HASHTAG_COMPANIONS + (
        "pro", "tips", "life", "studio", "academy", "official", "fr", "world",
    ):
        if len(base) > len(word) + 3 and base.endswith(word):
            head = base[: -len(word)]
            if head != word:
                return [head, word]
        if len(base) > len(word) + 3 and base.startswith(word):
            tail = base[len(word):]
            if tail != word:
                return [word, tail]
    # Essai 2 : ajoute un compagnon générique différent du hashtag user
    for comp in _HASHTAG_COMPANIONS:
        if comp != base:
            return [base, comp]
    # Fallback ultime
    return [base, "business"]


def _build_args(platform: str, niche: str, max_results: int) -> dict[str, Any]:
    """Renvoie le dict d'arguments à passer au Phantom selon la plateforme.

    Format calqué sur les Phantoms recommandés. Si Jordan utilise un
    autre Phantom, il peut ajuster (PhantomBuster ignore les clés
    inconnues).
    """
    n = max(1, min(max_results, 500))
    if platform == "linkedin":
        return {
            "searches":          _linkedin_search_url(niche),
            "numberOfProfiles":  n,
            "numberOfLinesPerLaunch": n,
            "csvName":           f"triskell_linkedin_{int(time.time())}",
        }
    if platform == "instagram":
        # « Instagram Multiple Hashtag Collector » exige AU MOINS DEUX
        # termes différents, séparés par « + », chacun préfixé par #.
        # Si l'utilisateur n'en fournit qu'un, on en génère un compagnon
        # plausible pour satisfaire le phantom.
        hashtags = _ensure_two_hashtags(niche)
        formatted = " + ".join(f"#{h}" for h in hashtags)
        return {
            "spreadsheetUrl":           formatted,
            "hashtags":                 formatted,
            "searchTerms":              formatted,
            "keywords":                 formatted,
            "queries":                  hashtags,
            "numberOfPostsPerHashtag":  n,
            "numberOfPostsPerLaunch":   n,
            "numberOfProfilesPerLaunch": n,
            "numberOfLinesPerLaunch":   n,
            "csvName":                  f"triskell_instagram_{int(time.time())}",
        }
    if platform == "tiktok":
        # Format similaire côté TikTok Hashtag Scraper — par sécurité on
        # garantit aussi 2 termes au cas où le phantom TikTok ait la même
        # contrainte.
        hashtags = _ensure_two_hashtags(niche)
        formatted = " + ".join(f"#{h}" for h in hashtags)
        return {
            "spreadsheetUrl":            formatted,
            "hashtags":                  formatted,
            "searchTerms":               formatted,
            "keywords":                  formatted,
            "queries":                   hashtags,
            "numberOfVideosPerHashtag":  n,
            "numberOfVideosPerLaunch":   n,
            "numberOfLinesPerLaunch":    n,
            "csvName":                   f"triskell_tiktok_{int(time.time())}",
        }
    raise ValueError(f"Plateforme non supportée : {platform}")


# ---------------------------------------------------------------------------
# Mapping résultat brut Phantom → format Prospect Triskell
# ---------------------------------------------------------------------------
def _first_nonempty(d: dict, keys: list[str]) -> str:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _to_int(v: Any) -> int:
    try:
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).strip().lower().replace(",", "").replace(" ", "")
        if s.endswith("k"):
            return int(float(s[:-1]) * 1_000)
        if s.endswith("m"):
            return int(float(s[:-1]) * 1_000_000)
        return int(float(s))
    except Exception:
        return 0


def map_raw_to_prospect(raw: dict, platform: str, niche: str) -> Optional[dict]:
    """Transforme un dict brut Phantom en row Prospect prêt à insérer.

    Clés écrites :
      name, handle, website, emails, phones,
      industry, language, country, status,
      monetized, score, score_label,
      subscribers, platform_url, sources, notes
    """
    profile_url = _first_nonempty(raw, [
        "profileUrl", "profile_url", "url", "link",
        "ownerProfileUrl", "userUrl", "channelUrl",
    ])
    if not profile_url:
        return None

    name = _first_nonempty(raw, [
        "fullName", "name", "displayName", "nickname",
        "title", "fullname", "full_name",
    ])
    handle = _first_nonempty(raw, [
        "username", "handle", "uniqueId", "vanityName", "screenName",
        "profileSlug",
    ])
    if not name and handle:
        name = handle
    if not name:
        return None

    description = _first_nonempty(raw, [
        "biography", "bio", "summary", "headline", "signature",
        "description", "about",
    ])
    website = _first_nonempty(raw, [
        "externalUrl", "external_url", "website", "websiteUrl",
        "personalWebsite",
    ])
    email = _first_nonempty(raw, [
        "email", "publicEmail", "businessEmail", "contactEmail",
    ])

    subscribers = _to_int(_first_nonempty(raw, [
        "followers", "followerCount", "subscribers", "subscriberCount",
        "fanCount", "connectionCount", "connections", "audienceSize",
    ]))

    verified = bool(raw.get("isVerified") or raw.get("verified") or
                    raw.get("blueVerified"))
    monetized = bool(raw.get("hasShop") or raw.get("isBusinessAccount") or
                     raw.get("merchant") or raw.get("creatorMonetization"))

    city = _first_nonempty(raw, [
        "city", "location", "geoLocation", "geo", "locationName",
    ])

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Provenance du mail : PhantomBuster lit le champ "email" exposé par le
    # profil social (Instagram, LinkedIn, TikTok…). On marque la source en
    # ce sens — si l'enricheur web rajoute des emails par la suite, il
    # taggera lui-même avec sa propre source ("web", "linktree"…).
    emails_meta_list = ([
        {
            "email":     email,
            "source":    f"phantombuster_{platform}" if platform else "phantombuster",
            "source_id": "",
            "url":       profile_url,
            "context":   (f"profil {platform} (champ email public)" if platform
                          else "profil social (champ email public)"),
            "found_at":  now_iso,
        }
    ] if email else [])
    return {
        "name":          name,
        "handle":        handle,
        "legal_name":    "",
        "emails":        [email] if email else [],
        "emails_meta":   emails_meta_list,
        "phones":        [],
        "website":       website,
        "other_urls":    [],
        "address":       "",
        "city":          city,
        "industry":      niche,
        "description":   description[:1000],
        "language":      "",
        "country":       "",
        "monetized":     monetized,
        "monetization_reasons": [],
        "has_legal_mentions": False,
        "score":         (50 if verified else 0) + min(50, subscribers // 1000),
        "score_label":   "verified" if verified else "",
        "subscribers":   subscribers or None,
        "platform_url":  profile_url,
        "status":        "new",
        "tags":          [platform, "phantombuster", niche],
        "notes":         "",
        "sources":       [{
            "name":      f"phantombuster_{platform}",
            "source_id": handle or profile_url,
            "url":       profile_url,
            "found_at":  now_iso,
        }],
        "match_keys":    [profile_url],
    }


# ---------------------------------------------------------------------------
# Polling de l'exécution du Phantom
# ---------------------------------------------------------------------------
def _wait_for_completion(
    api_key: str,
    container_id: str,
    *,
    timeout_sec: int = 30 * 60,
    poll_every_sec: int = 30,
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """Bloque jusqu'à ce que le container atteigne un statut terminal
    ou que le timeout soit dépassé. Renvoie le dernier état."""
    start = time.time()
    last_status = {}
    while time.time() - start < timeout_sec:
        try:
            last_status = pb.fetch_container_status(api_key, container_id)
        except Exception as exc:
            if progress:
                progress(f"⚠ erreur de polling : {exc}")
            time.sleep(poll_every_sec)
            continue
        status_str = (last_status.get("status") or
                       last_status.get("lastEndStatus") or "").lower()
        running = bool(last_status.get("running"))
        end_at = last_status.get("endedAt") or last_status.get("endDate")
        if (status_str in _TERMINAL_STATUSES) or (not running and end_at):
            if progress:
                # On expose le lastEndStatus séparément : il indique
                # success / error / etc. côté PhantomBuster, alors que
                # `status` peut juste dire "finished" même si le job a planté.
                end_status = (last_status.get("lastEndStatus") or "").lower()
                exit_code = last_status.get("exitCode")
                msg = f"Container terminé (status={status_str or 'finished'}"
                if end_status and end_status != status_str:
                    msg += f", lastEndStatus={end_status}"
                if exit_code not in (None, 0):
                    msg += f", exitCode={exit_code}"
                msg += ")"
                progress(msg)
            return last_status
        if progress:
            elapsed = int(time.time() - start)
            progress(f"⏳ phantom en cours… ({elapsed}s écoulées)")
        time.sleep(poll_every_sec)
    if progress:
        progress(f"⚠ timeout atteint après {timeout_sec}s — on prend ce qu'on a")
    return last_status


# ---------------------------------------------------------------------------
# Insertion dans la base prospects
# ---------------------------------------------------------------------------
def _upsert_prospects(sb, rows: list[dict],
                       progress: Optional[Callable[[str], None]] = None,
                       client=None) -> dict:
    """Insère les prospects en évitant les doublons sur platform_url.
    Renvoie {inserted, skipped, errors}.

    Si `client` (wrapper Supabase) est fourni, on injecte automatiquement
    workspace_id dans chaque insert (requis depuis migration 20)."""
    inserted = 0
    skipped = 0
    errors = 0
    for row in rows:
        purl = row.get("platform_url") or ""
        if not purl:
            skipped += 1
            continue
        try:
            existing = (sb.table("prospects").select("id")
                        .eq("platform_url", purl).limit(1).execute())
            if existing.data:
                skipped += 1
                continue
            sb.table("prospects").insert(with_workspace(client, row)).execute()
            inserted += 1
        except Exception as exc:
            logger.warning("upsert prospect failed: %s", exc)
            errors += 1
    if progress:
        progress(f"📥 {inserted} ajoutés, {skipped} déjà connus, {errors} erreurs")
    return {"inserted": inserted, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def discover_profiles(
    *,
    sb,                          # client Supabase (raw)
    api_key: str,
    platform: str,
    phantom_id: str,
    niche: str,
    max_results: int = 50,
    progress: Optional[Callable[[str], None]] = None,
    poll_timeout_sec: int = 30 * 60,
    client=None,                 # wrapper Supabase (pour workspace_id)
    filters: Optional[dict] = None,  # filtres audience / monétisation / pays…
) -> dict:
    """Lance une recherche PhantomBuster et insère les profils trouvés.

    Renvoie {ok, container_id, profiles_found, inserted, skipped, errors}.
    """
    log = progress or (lambda _msg: None)

    if platform not in SUPPORTED_PLATFORMS:
        return {"ok": False, "error": f"plateforme non supportée : {platform}"}
    if not api_key:
        return {"ok": False, "error": "Clé API PhantomBuster manquante"}
    if not phantom_id:
        return {"ok": False, "error": f"Phantom ID manquant pour {platform}"}
    if not (niche or "").strip():
        return {"ok": False, "error": "niche requise"}

    log(f"🚀 Lancement Phantom {platform} pour « {niche} » (max {max_results})…")
    try:
        args = _build_args(platform, niche, max_results)
        launch = pb.launch_agent(api_key, phantom_id, args)
    except Exception as exc:
        return {"ok": False, "error": f"launch_agent: {exc}"}

    container_id = (launch.get("containerId") or launch.get("container_id")
                    or launch.get("id") or "")
    if not container_id:
        return {"ok": False, "error": f"pas de containerId dans la réponse: {launch}"}
    log(f"   container_id={container_id}")

    status = _wait_for_completion(api_key, container_id,
                                    timeout_sec=poll_timeout_sec,
                                    progress=log)

    try:
        result = pb.fetch_container_result(api_key, container_id)
    except Exception as exc:
        return {"ok": False, "error": f"fetch_result: {exc}",
                "container_id": container_id}

    # Le résultat peut être inline (resultObject = liste) ou via URL S3
    raw_rows: list[dict] = []
    inline = result.get("resultObject") if isinstance(result, dict) else None
    source_kind = ""
    download_url = ""
    if isinstance(inline, list):
        raw_rows = [d for d in inline if isinstance(d, dict)]
        source_kind = "resultObject (liste inline)"
    elif isinstance(inline, str):
        raw_rows = pb.parse_result_payload(inline.encode("utf-8"))
        source_kind = "resultObject (string inline)"
    else:
        for key in ("csvUrl", "jsonUrl", "resultUrl", "outputUrl", "url"):
            if isinstance(result, dict) and result.get(key):
                download_url = str(result[key])
                source_kind = f"téléchargement {key}"
                break
        if download_url:
            log(f"📄 téléchargement résultat : {download_url[:80]}…")
            try:
                blob = pb.download_result_file(download_url)
                raw_rows = pb.parse_result_payload(blob)
            except Exception as exc:
                return {"ok": False, "error": f"download_result: {exc}",
                        "container_id": container_id}

    if not raw_rows:
        # Diagnostic : on ne sait pas si c'est PhantomBuster qui a renvoyé
        # vide, ou si on a pas su lire la forme de sa réponse. On expose
        # les clés top-level + un extrait du resultObject pour que Jordan
        # voie d'un coup d'œil ce qui se passe.
        if isinstance(result, dict):
            top_keys = sorted(result.keys())
            log(f"🔬 résultat vide — clés disponibles côté PhantomBuster : "
                f"{', '.join(top_keys) or '(aucune)'}")
            if isinstance(inline, str) and inline.strip():
                snippet = inline.strip()[:200].replace("\n", " ")
                log(f"   resultObject (texte) : {snippet}…")
            elif inline is None and not download_url:
                log("   → ni resultObject ni URL CSV/JSON : le Phantom n'a "
                    "rien produit (vérifie côté PhantomBuster : "
                    "exécution réussie ? hashtags valides ? cookie de "
                    "session encore frais ?)")
    log(f"🔎 {len(raw_rows)} profils bruts récupérés"
        + (f" (source : {source_kind})" if raw_rows and source_kind else ""))

    prospects = []
    for raw in raw_rows:
        p = map_raw_to_prospect(raw, platform, niche)
        if p is not None:
            prospects.append(p)
    log(f"✔ {len(prospects)} profils valides après mapping")
    if raw_rows and not prospects:
        # On a reçu des lignes mais aucune n'est mappable : presque toujours
        # un Phantom qui renvoie des colonnes inattendues. On affiche les
        # clés du premier brut pour qu'on puisse ajouter le mapping.
        sample_keys = sorted(raw_rows[0].keys())[:20]
        log(f"⚠ Aucun profil mappable. Clés du 1er brut : "
            f"{', '.join(sample_keys)}")

    # === ENRICHISSEMENT EMAIL ===
    # PhantomBuster ne donne quasi jamais d'email côté hashtag/keyword
    # collectors — on tente de récupérer une adresse via bio, site web,
    # /contact, etc. AVANT le filtre, sinon `only_with_email` vide tout.
    try:
        from . import email_enricher
        email_enricher.enrich_batch(prospects, log=log)
    except Exception as exc:
        log(f"⚠ Enrichisseur email indisponible ({exc}) — on continue sans.")

    # Filtrage post-fetch (audience, monétisation, pays, etc.)
    if filters:
        try:
            from .obelisk.runner import apply_filters as _apply
            prospects, rejected = _apply(prospects, filters)
            if rejected:
                log(f"🔎 {rejected} profils rejetés par les filtres "
                    f"(audience / monétisation / pays / langue / email)")
        except Exception as exc:
            log(f"⚠ application des filtres ignorée : {exc}")

    upsert = _upsert_prospects(sb, prospects, progress=log, client=client)

    return {
        "ok":             True,
        "container_id":   container_id,
        "profiles_found": len(prospects),
        "inserted":       upsert["inserted"],
        "skipped":        upsert["skipped"],
        "errors":         upsert["errors"],
        "status":         status,
    }
