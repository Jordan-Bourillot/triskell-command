"""Runner Obelisk : lance les recherches en arrière-plan.

Quand l'utilisateur clique sur "Nouvelle recherche" dans la vue Obelisk de
Triskell Command :
  1. on crée un search job (table obelisk_search_jobs, status=pending)
  2. on spawn un thread daemon qui exécute la recherche :
     - plateformes natives (YouTube/Twitch/Reddit/Bluesky/Mastodon/
       Podcasts/Dailymotion/Kick/GitHub) → triskell_core.prospect
       .creators_pipeline.run_creators_pipeline
     - plateformes PhantomBuster (LinkedIn/Instagram/TikTok) →
       phantom_discovery.discover_profiles (un appel par plateforme,
       en séquence pour rester gentil avec les quotas)
  3. à chaque progression, on met à jour le job (status, progress, stats)
  4. le frontend poll get_search_job(job_id) toutes les 2 s

Les profils trouvés atterrissent dans la table partagée `public.prospects`,
peu importe la source.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from . import repo

logger = logging.getLogger(__name__)


# Plateformes qui passent par PhantomBuster (découverte). Toutes les autres
# sont gérées par run_creators_pipeline (sources natives : YouTube etc.).
PHANTOM_PLATFORMS = ("linkedin", "instagram", "tiktok")

# job_id → Thread (pour pouvoir savoir si une recherche tourne encore localement)
_RUNNING: dict[str, threading.Thread] = {}


def start_search(user_email: str, niche: str, platforms: list[str],
                 max_per_platform: int = 30,
                 config_overrides: Optional[dict] = None) -> dict:
    """Crée le job en base, le lance dans un thread daemon, renvoie le job_id.

    config_overrides : permet d'override la config user (utile pour les tests).
    """
    if not niche or not niche.strip():
        return {"ok": False, "error": "niche requise"}
    if not platforms:
        return {"ok": False, "error": "au moins une plateforme requise"}

    created = repo.create_search_job(user_email, niche.strip(), platforms, max_per_platform)
    if not created.get("ok"):
        return created
    job_id = created.get("job_id")
    if not job_id:
        return {"ok": False, "error": "job sans id"}

    t = threading.Thread(
        target=_run_thread,
        args=(job_id, user_email, niche, platforms, max_per_platform, config_overrides or {}),
        daemon=True,
        name=f"obelisk-search-{job_id[:8]}",
    )
    _RUNNING[job_id] = t
    t.start()
    return {"ok": True, "job_id": job_id}


def is_running(job_id: str) -> bool:
    t = _RUNNING.get(job_id)
    return bool(t and t.is_alive())


def _update_job(job_id: str, **fields) -> None:
    """Best-effort : met à jour le job (silencieux si erreur)."""
    sb = repo._sb()
    if sb is None:
        return
    try:
        sb.table("obelisk_search_jobs").update(fields).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning("obelisk._update_job(%s): %s", job_id, exc)


def _run_thread(job_id: str, user_email: str, niche: str, platforms: list[str],
                max_per_platform: int, overrides: dict) -> None:
    """Exécute le pipeline dans un thread. Toujours catch global pour
    ne jamais crash le worker."""
    progress_lines: list[str] = []

    def log(msg: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        progress_lines.append(line)
        # Tronque pour éviter d'écrire un blob jsonb géant
        trimmed = progress_lines[-200:]
        _update_job(job_id, progress=trimmed)

    _update_job(job_id, status="running",
                started_at=datetime.now(timezone.utc).isoformat())

    # Construit un dict de filtres exploitable (séparé d'AutopilotConfig pour
    # le pipeline natif). Ces filtres sont aussi appliqués en post-fetch côté
    # PhantomBuster.
    filters = _normalize_filters(overrides or {})

    try:
        # Charge la config user (fusionnée avec defaults) + applique overrides
        cfg_res = repo.get_user_config(user_email)
        ucfg = cfg_res.get("config") or {}
        ucfg.update(overrides)
        ucfg["niche"] = niche
        ucfg["platforms"] = platforms
        ucfg["max_per_platform"] = max_per_platform

        # ⚡ Auto-alimente ucfg["catalog"] depuis le catalogue principal
        # Triskell si l'utilisateur ne l'a pas explicitement rempli dans
        # Obelisk → Réglages. Comme ça, ajouter un produit dans la vue
        # Catalogue suffit pour qu'Obelisk le propose dans ses mails.
        if not (ucfg.get("catalog") or "").strip():
            try:
                from .. import catalog_repo
                items = catalog_repo.get_catalog() or []
                if items:
                    ucfg["catalog"] = _format_catalog_for_ai(items)
                    log(f"📚 Catalogue principal injecté dans le pipeline "
                        f"({len(items)} produit(s)).")
            except Exception as exc:
                log(f"⚠ Impossible de charger le catalogue principal : {exc}")

        # ⚡ CRITIQUE : sync les clés API stockées en Supabase vers le
        # fichier local ~/.ledenicheur/config.json que le pipeline natif
        # va lire. Sans ça, ce pipeline ne trouve aucune clé et toutes
        # les sources sont skippées avec "clé API manquante".
        # Inutile si le run ne contient QUE des plateformes PhantomBuster.
        if any(p not in PHANTOM_PLATFORMS for p in platforms):
            _sync_keys_to_ledenicheur(ucfg, log)
        # Aligne only_unmonetized avec le mode de monétisation choisi
        if filters.get("monetized_mode") == "unmonetized":
            ucfg["only_unmonetized"] = True
        elif filters.get("monetized_mode") == "monetized":
            ucfg["only_unmonetized"] = False
        # mode "all" : on laisse la valeur user existante

        # ⚡ Biais géographique : si l'utilisateur a coché « francophones »
        # (ou tout autre pays/langue), on dit à YouTube de prioriser cette
        # zone dès la recherche. Sans ça, les requêtes type « web » remontent
        # 95% de chaînes US — le post-filtre est trop tolérant pour rattraper.
        if filters.get("language"):
            ucfg["search_lang"] = filters["language"]
        if filters.get("country"):
            ucfg["search_region"] = filters["country"]
        # Cas fréquent : Jordan veut du français mais n'a coché que language=fr
        # → on infère region=FR pour resserrer encore.
        if filters.get("language") == "fr" and not filters.get("country"):
            ucfg["search_region"] = "FR"

        # Import paresseux pour ne pas alourdir le boot de Command
        try:
            from triskell_core.prospect.creators_pipeline import (
                AutopilotConfig, run_creators_pipeline,
            )
        except Exception as exc:
            log(f"⚠ triskell_core.prospect.creators_pipeline introuvable : {exc}")
            _update_job(job_id, status="failed", error=str(exc),
                        finished_at=datetime.now(timezone.utc).isoformat())
            return

        # Construit la dataclass AutopilotConfig depuis le dict, en ignorant
        # les clés qu'elle ne connaît pas.
        try:
            allowed = AutopilotConfig.__dataclass_fields__.keys()
        except Exception:
            allowed = set()
        cfg_kwargs = {k: v for k, v in ucfg.items() if k in allowed}
        try:
            cfg = AutopilotConfig(**cfg_kwargs)
        except Exception as exc:
            log(f"⚠ AutopilotConfig invalide : {exc}")
            cfg = AutopilotConfig()
            cfg.niche = niche
            cfg.platforms = platforms
            cfg.max_per_platform = max_per_platform

        # Sépare plateformes natives (creators_pipeline) vs PhantomBuster.
        native_platforms = [p for p in platforms if p not in PHANTOM_PLATFORMS]
        phantom_platforms = [p for p in platforms if p in PHANTOM_PLATFORMS]

        agg_stats: dict[str, Any] = {
            "found": 0, "enriched": 0, "drafts": 0,
            "phantom_inserted": 0, "phantom_skipped": 0,
            "per_platform": {},
            "niches_run": [],
        }

        # Support multi-niches : « entrepreneur, coaching, growth » →
        # ["entrepreneur", "coaching", "growth"]. Pour chacune on relance
        # le pipeline natif. La dédup côté Supabase (platform_url, handle+source)
        # évite les doublons cross-niches.
        niche_list = [n.strip() for n in (niche or "").split(",") if n.strip()]
        if not niche_list:
            niche_list = [niche or ""]

        # 1) Pipeline natif (YouTube, Twitch, Reddit, etc.)
        if native_platforms:
            cfg.platforms = native_platforms
            for idx, sub_niche in enumerate(niche_list, 1):
                if len(niche_list) > 1:
                    log(f"════════ NICHE {idx}/{len(niche_list)} : "
                        f"« {sub_niche} » ════════")
                cfg.niche = sub_niche
                log(f"Démarrage recherche natives '{sub_niche}' sur "
                    f"{', '.join(native_platforms)}…")
                # Snapshot des match_keys connues AVANT le run pour détecter
                # les nouveaux ensuite (le pipeline écrit dans un fichier local).
                before_keys = _read_local_prospects_keys()
                stats = run_creators_pipeline(cfg, progress=log) or {}
                agg_stats["found"]    += int(stats.get("found", 0) or 0)
                agg_stats["enriched"] += int(stats.get("enriched", 0) or 0)
                agg_stats["drafts"]   += int(stats.get("drafts", 0) or 0)
                agg_stats["niches_run"].append(sub_niche)
                key = f"_native_{sub_niche}" if len(niche_list) > 1 else "_native"
                agg_stats["per_platform"][key] = stats
                # ⚡ Upload les nouveaux prospects (qui ont été écrits localement
                # par le pipeline) vers Supabase, sinon l'UI Triskell ne les voit
                # JAMAIS — le pipeline natif vient de l'app standalone et
                # n'écrit pas dans Supabase de lui-même.
                _upload_new_locals_to_supabase(
                    before_keys=before_keys, niche=sub_niche, log=log,
                    agg_stats=agg_stats, filters=filters)

        # 2) Phantoms (LinkedIn / Instagram / TikTok)
        # Le multi-hashtag est déjà natif côté Phantom Instagram / TikTok
        # (séparateur « + »). Mon helper _ensure_two_hashtags transforme la
        # niche en hashtags. Pour LinkedIn, c'est un keyword unique → si
        # plusieurs niches, on relance le phantom une fois par niche.
        if phantom_platforms:
            for sub_niche in niche_list:
                if len(niche_list) > 1:
                    log(f"════════ NICHE « {sub_niche} » (PhantomBuster) ════════")
                _run_phantom_platforms(
                    niche=sub_niche,
                    platforms=phantom_platforms,
                    max_per_platform=max_per_platform,
                    log=log,
                    agg_stats=agg_stats,
                filters=filters,
            )

        log(f"Terminé : {agg_stats['found']} trouvés, "
            f"{agg_stats['enriched']} enrichis, "
            f"{agg_stats['drafts']} drafts, "
            f"{agg_stats['phantom_inserted']} via PhantomBuster.")
        _update_job(job_id, status="done", stats=agg_stats,
                    finished_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        logger.exception("obelisk._run_thread crashed: %s", exc)
        log(f"💥 Erreur : {exc}")
        _update_job(job_id, status="failed", error=str(exc),
                    finished_at=datetime.now(timezone.utc).isoformat())
    finally:
        _RUNNING.pop(job_id, None)


# ---------------------------------------------------------------------------
# Catalogue → format texte injecté dans le prompt IA
# ---------------------------------------------------------------------------
def _format_catalog_for_ai(items: list[dict]) -> str:
    """Transforme la liste plate du catalogue en texte structuré lisible
    par l'IA. Inclut les mots-clés et l'URL pour que l'IA sache à quel
    profil chaque produit s'adresse.

    Format produit par ligne :
        - <Nom> | pitch: <pitch> | pour: <keywords> | url: <url>
    """
    if not items:
        return ""
    lines: list[str] = []
    for it in items:
        name = (it.get("name") or "").strip()
        if not name:
            continue
        pitch = (it.get("pitch") or "").strip() or "(pas de pitch)"
        keywords = (it.get("keywords") or "").strip()
        url = (it.get("url") or "").strip()
        parts = [f"- {name}"]
        parts.append(f"pitch: {pitch}")
        if keywords:
            parts.append(f"pour: {keywords}")
        if url:
            parts.append(f"url: {url}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Upload des prospects locaux (écrits par le pipeline natif) vers Supabase
# ---------------------------------------------------------------------------
# Le pipeline natif écrit dans ~/.ledenicheur/prospects.json (PAS dans
# ~/.triskell-prospect/prospects.json — c'est l'app Le Dénicheur qui a
# créé ce dossier historiquement).
def _local_prospects_path():
    from pathlib import Path
    return Path.home() / ".ledenicheur" / "prospects.json"


def _read_local_prospects() -> list[dict]:
    import json
    p = _local_prospects_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _prospect_local_key(p: dict) -> str:
    """Même clé que le pipeline natif : platform|id."""
    return f"{p.get('platform', '')}|{p.get('id', '')}"


def _read_local_prospects_keys() -> set[str]:
    """Snapshot des (platform|id) actuellement connus dans le fichier local."""
    return {_prospect_local_key(p) for p in _read_local_prospects()
            if _prospect_local_key(p) != "|"}


def _platform_url_from_local(p: dict) -> str:
    """Construit l'URL profil depuis platform+id (heuristique par source)."""
    platform = (p.get("platform") or "").lower()
    pid = p.get("id") or ""
    handle = p.get("custom_url") or p.get("login") or p.get("username") or ""
    if not pid and not handle:
        return ""
    if platform == "youtube":
        if handle:
            return f"https://www.youtube.com/@{handle}"
        return f"https://www.youtube.com/channel/{pid}"
    if platform == "twitch":
        return f"https://www.twitch.tv/{handle or pid}"
    if platform == "reddit":
        return f"https://www.reddit.com/user/{handle or pid}"
    if platform == "bluesky":
        return f"https://bsky.app/profile/{handle or pid}"
    if platform == "github":
        return f"https://github.com/{handle or pid}"
    if platform == "dailymotion":
        return f"https://www.dailymotion.com/{handle or pid}"
    if platform == "kick":
        return f"https://kick.com/{handle or pid}"
    # Fallback : on prend l'URL stockée s'il y en a une
    return (p.get("url") or p.get("profile_url") or
            p.get("channel_url") or "")


def _local_prospect_to_supabase_row(p: dict, niche: str,
                                      now_iso: str) -> dict:
    """Convertit un dict prospect (format ~/.ledenicheur/prospects.json)
    en row Supabase prospects."""
    name = (p.get("name") or p.get("title") or p.get("login")
            or p.get("display_name") or p.get("username") or "")
    handle = (p.get("custom_url") or p.get("login") or p.get("username")
              or p.get("handle") or "")
    # YouTube stocke souvent custom_url avec un @ initial (ex: @entrepreneurdz).
    # On le strippe pour ne pas afficher @@xxx côté UI.
    if isinstance(handle, str) and handle.startswith("@"):
        handle = handle.lstrip("@")
    platform = (p.get("platform") or "").lower()
    pid = p.get("id") or ""
    platform_url = _platform_url_from_local(p)
    emails = p.get("emails") or []
    phones = p.get("phones") or []
    urls_in_bio = p.get("urls_in_bio") or []
    # 1er URL non-social comme website
    website = ""
    for u in urls_in_bio:
        if isinstance(u, str) and u and not any(
            s in u for s in ("youtube.com", "twitch.tv", "reddit.com",
                              "bsky.app", "github.com", "tiktok.com",
                              "instagram.com", "linkedin.com")
        ):
            website = u
            break
    subscribers = (p.get("subscribers") or p.get("subscriberCount")
                   or p.get("followers") or p.get("followers_count"))
    try:
        subscribers = int(subscribers) if subscribers not in (None, "") else None
    except Exception:
        subscribers = None
    description = (p.get("description") or p.get("bio") or
                   p.get("snippet") or "")[:1000]
    source_entry = {
        "name":      f"obelisk_{platform}" if platform else "obelisk",
        "source_id": pid,
        "url":       platform_url,
        "found_at":  p.get("found_at") or now_iso,
    }
    return {
        "name":          name,
        "handle":        handle,
        "legal_name":    "",
        "emails":        list(emails) if isinstance(emails, list) else [],
        "phones":        list(phones) if isinstance(phones, list) else [],
        "website":       website,
        "other_urls":    list(urls_in_bio) if isinstance(urls_in_bio, list) else [],
        "address":       "",
        "city":          "",
        "postal_code":   "",
        "country":       p.get("country") or "",
        "industry":      niche,
        "description":   description,
        "language":      p.get("language") or "",
        "monetized":     bool(p.get("monetized")),
        "monetization_reasons": list(p.get("monetization_reasons") or []),
        "has_legal_mentions":   False,
        "score":         int(p.get("score") or 0),
        "score_label":   p.get("score_label") or "",
        "subscribers":   subscribers,
        "platform_url":  platform_url,
        "status":        p.get("status") or "new",
        "tags":          [platform, niche] if platform else [niche],
        "notes":         "",
        "sources":       [source_entry],
        "match_keys":    [platform_url] if platform_url else [],
    }


def _upload_new_locals_to_supabase(*, before_keys: set[str], niche: str,
                                     log, agg_stats: dict,
                                     filters: dict | None = None) -> None:
    """Détecte les nouveaux prospects ajoutés par le pipeline natif dans
    ~/.ledenicheur/prospects.json et les uploade vers la table Supabase
    `prospects` avec workspace_id (sinon les RLS rejettent silencieusement).

    Applique aussi les filtres utilisateur (only_with_email, audience min/max,
    monétisation, pays, langue) AVANT l'insert — pour que la case « uniquement
    ceux avec un email » coche ne ramène pas les profils sans email.
    """
    after = _read_local_prospects()
    if not after:
        log("⚠ Fichier prospects local introuvable ou vide — rien à uploader.")
        return
    # Filtre les nouveaux : ceux dont la clé (platform|id) n'était pas avant
    new_rows: list[dict] = []
    for p in after:
        k = _prospect_local_key(p)
        if not k or k == "|":
            continue
        if k in before_keys:
            continue
        new_rows.append(p)
    if not new_rows:
        log("ℹ Aucun nouveau prospect détecté dans le fichier local "
            f"(total local = {len(after)}).")
        return
    # === ENRICHISSEMENT EMAIL ===
    # Avant le filtre, on tente de récupérer un email pour TOUS les
    # prospects qui n'en ont pas (bio, site web, /contact, /about, Linktree…).
    # Critique pour que le filtre `only_with_email` ne dégage pas 100 %
    # des trouvés (les plateformes sociales exposent rarement l'email).
    try:
        from .. import email_enricher
        email_enricher.enrich_batch(new_rows, log=log)
    except Exception as exc:
        log(f"⚠ Enrichisseur email indisponible ({exc}) — on continue sans.")
    # Applique les filtres user (only_with_email, audience, etc.) au format
    # Prospect "local". Comme la structure des rows est différente du format
    # Supabase, on construit un mini-row temporaire pour réutiliser
    # apply_filters().
    if filters:
        before_count = len(new_rows)
        kept: list[dict] = []
        for raw in new_rows:
            probe = {
                "emails":     raw.get("emails") or [],
                "subscribers": raw.get("subscribers") or raw.get("subscriberCount")
                              or raw.get("followers") or 0,
                "monetized":   bool(raw.get("monetized")),
                "country":     raw.get("country") or "",
                "language":    raw.get("language") or "",
                "tags":        raw.get("monetization_reasons") or [],
                # ⚡ Champs texte nécessaires à la mini-détection de langue
                # (sinon le filtre FR ne détecte rien et tout passe en silence).
                "name":        raw.get("name") or raw.get("title") or "",
                "description": raw.get("description") or raw.get("bio")
                               or raw.get("snippet") or "",
                "bio":         raw.get("bio") or "",
            }
            kept_one, _ = apply_filters([probe], filters)
            if kept_one:
                kept.append(raw)
        rejected = before_count - len(kept)
        if rejected:
            log(f"🔎 {rejected} profil(s) rejeté(s) par tes filtres "
                f"(audience / monétisation / pays / langue / email)")
        new_rows = kept
        if not new_rows:
            log("ℹ Aucun profil ne passe les filtres — rien à uploader.")
            return
    log(f"📤 Upload de {len(new_rows)} nouveau(x) prospect(s) vers Supabase…")
    sb = repo._sb()
    if sb is None:
        log("⚠ Supabase non joignable — les prospects restent locaux.")
        return
    # Workspace_id via le helper Triskell (le client wrapper)
    triskell_client = None
    try:
        from triskell_core.db import get_client as _gc, SupabaseNotConfigured
        try:
            tc = _gc()
            if tc.is_authenticated:
                triskell_client = tc
        except SupabaseNotConfigured:
            pass
    except Exception:
        pass

    try:
        from .. import multi_tenant
        with_workspace = multi_tenant.with_workspace
    except Exception:
        with_workspace = lambda _cli, row: row  # noqa: E731 (no-op fallback)

    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    inserted = 0
    skipped = 0
    errors = 0
    for raw in new_rows:
        row = _local_prospect_to_supabase_row(raw, niche, now_iso)
        if not row.get("name"):
            skipped += 1; continue
        purl = (row.get("platform_url") or "").rstrip("/").lower()
        handle = (row.get("handle") or "").strip().lower()
        sources = row.get("sources") or []
        src_name = (sources[0].get("name") if sources else "") or ""
        # Dédup côté Supabase :
        # 1) platform_url (normalisé : sans trailing slash, lowercase)
        # 2) sinon (handle, source name) — pour les sources sans URL fiable
        try:
            dup = False
            if purl:
                # On normalise aussi côté DB en comparant ilike pour
                # absorber http vs https et trailing slash.
                existing = (sb.table("prospects").select("id, platform_url")
                            .ilike("platform_url", f"%{purl[-40:]}%")
                            .limit(5).execute())
                for er in (existing.data or []):
                    if (er.get("platform_url") or "").rstrip("/").lower() == purl:
                        dup = True; break
            if not dup and handle and src_name:
                # Cherche un prospect existant avec le même handle ET la même
                # source (ex: youtube). Utilise le filtre JSON contains.
                try:
                    res = (sb.table("prospects").select("id, handle, sources")
                           .eq("handle", row["handle"]).limit(20).execute())
                    for er in (res.data or []):
                        for s in (er.get("sources") or []):
                            if isinstance(s, dict) and s.get("name") == src_name:
                                dup = True; break
                        if dup:
                            break
                except Exception:
                    pass
            if dup:
                skipped += 1; continue
            row = with_workspace(triskell_client, row)
            sb.table("prospects").insert(row).execute()
            inserted += 1
        except Exception as exc:
            logger.warning("upload prospect failed: %s", exc)
            errors += 1
    agg_stats["uploaded_to_supabase"] = inserted
    log(f"✅ {inserted} prospects uploadés (skip {skipped}, erreurs {errors})")


# ---------------------------------------------------------------------------
# Sync des clés API : Supabase → fichier ~/.ledenicheur/config.json
# ---------------------------------------------------------------------------
def _sync_keys_to_ledenicheur(ucfg: dict, log) -> None:
    """Recopie les clés API stockées en Supabase (via obelisk_user_config)
    vers le fichier local ~/.ledenicheur/config.json. C'est ce fichier
    que `triskell_core.prospect.creators_pipeline.run_creators_pipeline`
    lit pour trouver youtube_api_key, twitch_*, etc.

    Sans cette synchro, le pipeline natif skippe toutes les sources avec
    « clé API manquante » même si l'utilisateur a bien renseigné ses clés
    dans Triskell.
    """
    import json
    from pathlib import Path
    keys_to_sync = (
        "youtube_api_key", "youtube_api_keys",
        "twitch_client_id", "twitch_client_secret",
        "github_token",
        "mastodon_instances",
        "apple_podcasts_country", "apple_podcasts_lang",
    )
    payload: dict = {}
    for k in keys_to_sync:
        v = ucfg.get(k)
        if v not in (None, "", [], {}):
            payload[k] = v

    # ⚡ Clés IA (Anthropic/Google/OpenAI/…) — stockées dans le coffre
    # partagé Triskell (Réglages → Services IA), pas dans la config Obelisk.
    # Le pipeline natif les lit dans `denicheur_cfg["ai_api_keys"]` et skippe
    # l'étape IA si aucune n'est trouvée.
    try:
        from .. import shared_secrets
        from triskell_core.db import get_client, SupabaseNotConfigured
        sb = None
        try:
            sb = get_client()
            if not getattr(sb, "is_authenticated", False):
                try:
                    sb.restore_session()
                except Exception:
                    pass
            if not getattr(sb, "is_authenticated", False):
                sb = None
        except SupabaseNotConfigured:
            sb = None
        ai_keys = shared_secrets.get_ai_keys(client=sb) or {}
        ai_keys = {p: k for p, k in ai_keys.items() if k}
        if ai_keys:
            payload["ai_api_keys"] = ai_keys
            log(f"🧠 Clés IA récupérées : {', '.join(sorted(ai_keys.keys()))}")
        else:
            log(f"⚠ Aucune clé IA trouvée (Supabase auth={bool(sb)}). "
                f"Vérifie Réglages → Services IA.")
    except Exception as exc:
        log(f"⚠ Lecture des clés IA Triskell échouée : {exc}")

    if not payload:
        log("⚠ Aucune clé API trouvée dans la config Supabase à synchroniser.")
        return
    try:
        target_dir = Path.home() / ".ledenicheur"
        target_dir.mkdir(parents=True, exist_ok=True)
        cfg_file = target_dir / "config.json"
        existing: dict = {}
        if cfg_file.exists():
            try:
                existing = json.loads(cfg_file.read_text(encoding="utf-8"))
                if not isinstance(existing, dict):
                    existing = {}
            except Exception:
                existing = {}
        merged = {**existing, **payload}
        cfg_file.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log(f"🔑 {len(payload)} clé(s) API synchronisée(s) "
            f"vers ~/.ledenicheur/config.json "
            f"({', '.join(sorted(payload.keys()))})")
    except Exception as exc:
        log(f"⚠ Synchro des clés API échouée : {exc}")


# ---------------------------------------------------------------------------
# Filtres avancés (audience, monétisation, pays, langue, etc.)
# ---------------------------------------------------------------------------
def _normalize_filters(raw: dict) -> dict:
    """Extrait + normalise les filtres avancés depuis les overrides UI.
    Tolère les clés manquantes ou aux mauvais types.

    ⚠ FRANCOPHONES UNIQUEMENT — règle métier figée : Obelisk ne cherche
    QUE des créateurs francophones, point. La case "Langue" a été retirée
    de l'UI. Si language n'est pas fourni dans raw, on force "fr".
    """
    def _i(v, default=0):
        try: return int(v)
        except Exception: return default
    def _s(v):
        return (str(v or "").strip())
    mode = _s(raw.get("monetized_mode")).lower()
    if mode not in ("all", "unmonetized", "monetized"):
        mode = "all"
    # Langue : toujours "fr" sauf si quelqu'un override explicitement avec
    # une autre valeur valide (utile pour tests / clients SaaS futurs).
    lang_in = _s(raw.get("language")).lower()
    language = lang_in if lang_in else "fr"
    return {
        "monetized_mode":   mode,
        "min_subscribers":  max(0, _i(raw.get("min_subscribers"), 0)),
        "max_subscribers":  max(0, _i(raw.get("max_subscribers"), 0)),
        "country":          _s(raw.get("country")).upper(),
        "language":         language,
        "only_with_email":  bool(raw.get("only_with_email")),
        "only_uncontacted": bool(raw.get("only_uncontacted")),
    }


# Mots usuels propres à chaque langue. On compte les tokens marqueurs
# qu'on est ~sûr de ne pas trouver dans l'autre langue.
_FR_MARKERS = {
    # Articles / déterminants / petits mots
    "le", "la", "les", "des", "du", "de", "une", "un", "au", "aux", "et",
    "ou", "où", "ce", "cette", "ces", "son", "sa", "ses", "mon", "ma", "mes",
    "ton", "ta", "tes", "notre", "votre", "leur", "leurs", "à",
    # Verbes / pronoms courants
    "est", "sont", "ai", "as", "ont", "fait", "faire", "être", "avoir",
    "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles",
    "qui", "que", "quoi", "dont", "lequel",
    # Prépositions / adverbes courants
    "dans", "pour", "avec", "sur", "sous", "vers", "chez", "entre",
    "plus", "très", "aussi", "comme", "mais", "ne", "pas", "ni",
    "déjà", "encore", "toujours", "jamais", "bien", "mieux", "moins",
    # Vocabulaire créateur / YouTube FR
    "vidéo", "vidéos", "chaîne", "abonne", "abonnez", "abonné", "abonnés",
    "tutoriel", "tutoriels", "tuto", "ici", "découvrez", "bienvenue",
    "voici", "tout", "tous", "toute", "toutes", "présente", "partage",
    "français", "française", "francophone",
    # Politesse / formules courantes
    "merci", "salut", "bonjour", "coucou", "bisous",
    "semaine", "semaines", "jour", "jours", "mois", "année", "années",
    "ça", "moi", "toi", "lui", "soi",
}
_EN_MARKERS = {
    # Articles / petits mots
    "the", "and", "of", "to", "for", "with", "this", "that", "these",
    "those", "an", "or", "but", "not", "no", "yes",
    "a", "is", "are", "am", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had",
    # Pronoms
    "you", "your", "yours", "we", "our", "ours", "they", "their", "theirs",
    "i", "me", "my", "mine", "he", "she", "it", "its",
    # Prépositions / adverbes
    "from", "by", "at", "in", "on", "out", "up", "down", "over", "under",
    "more", "most", "less", "least", "very", "much", "many", "few",
    "also", "than", "then", "still", "always", "never", "ever",
    # Vocabulaire créateur / YouTube EN
    "video", "videos", "channel", "channels", "subscribe", "subscriber",
    "subscribers", "welcome", "here", "follow", "follower", "followers",
    "make", "made", "watch", "watching", "every", "week", "day", "month",
    "year", "join", "us", "about", "tutorial", "tutorials", "english",
    "content", "creator", "creators",
    # Questions
    "what", "how", "when", "where", "why", "who", "which",
}


def _detect_language(text: str) -> str:
    """Renvoie 'fr', 'en' ou '' selon la balance de marqueurs.
    Heuristique très grossière mais largement suffisante pour distinguer
    une bio FR d'une bio EN. Renvoie '' si pas assez de signal."""
    if not text or len(text) < 20:
        return ""
    import re as _re
    # Accepte les caractères accentués FR pour ne pas casser les mots
    tokens = _re.findall(r"[a-zàâäéèêëïîôöùûüçœæ]+", text.lower())
    if len(tokens) < 5:
        return ""
    fr_hits = sum(1 for t in tokens if t in _FR_MARKERS)
    en_hits = sum(1 for t in tokens if t in _EN_MARKERS)
    # Bonus FR : présence d'au moins une lettre accentuée (très rare en EN)
    has_accent = bool(_re.search(r"[àâäéèêëïîôöùûüçœæ]", text.lower()))
    if has_accent:
        fr_hits += 2
    # Décisions :
    # - FR clair : ≥ 2 hits FR et plus que l'EN
    # - EN clair : ≥ 2 hits EN et plus que le FR
    # - Sinon : inconnu
    if fr_hits >= 2 and fr_hits > en_hits:
        return "fr"
    if en_hits >= 2 and en_hits > fr_hits:
        return "en"
    return ""


def apply_filters(rows: list[dict], filters: dict) -> tuple[list[dict], int]:
    """Filtre une liste de Prospect-dicts selon les critères choisis.

    Les filtres sont TOLÉRANTS face aux infos manquantes : si on n'a pas
    l'info pour un champ (ex: subscribers=0 alors que le phantom ne fournit
    pas le nombre d'abonnés), on ne rejette PAS le profil — sinon on
    rejetterait tous les profils des plateformes qui ne donnent que
    le minimum (Instagram Hashtag Collector, etc.). À Jordan de retrier
    ensuite côté CRM s'il veut affiner.

    Renvoie (rows_gardés, nb_rejetés).
    """
    if not filters:
        return list(rows), 0
    kept, rejected = [], 0
    mn = filters.get("min_subscribers") or 0
    mx = filters.get("max_subscribers") or 0
    mode = filters.get("monetized_mode") or "all"
    country = (filters.get("country") or "").upper()
    language = (filters.get("language") or "").lower()
    with_email = filters.get("only_with_email")
    for r in rows:
        subs_raw = r.get("subscribers")
        subs_known = subs_raw not in (None, "", 0)
        subs = int(subs_raw or 0)
        # Si on a une vraie valeur > 0, on applique les bornes ; sinon
        # on laisse passer (info manquante = on garde).
        if mn and subs_known and subs < mn:
            rejected += 1; continue
        if mx and subs_known and subs > mx:
            rejected += 1; continue
        # Monétisation : on ne rejette que si l'info est explicitement
        # contraire (et présente). Pas d'info → on garde.
        monet_raw = r.get("monetized")
        monet_known = monet_raw is not None and monet_raw is not False or bool(monet_raw)
        # Plus simple : applique uniquement si tags ou metadata le confirment
        monetized = bool(monet_raw) or any(
            t in (r.get("tags") or [])
            for t in ("monetized", "business_account", "shop")
        )
        if mode == "unmonetized" and monetized:
            # Là c'est clair : il est marqué monétisé → on rejette
            rejected += 1; continue
        # mode "monetized" : trop restrictif si l'info n'est pas dans le
        # payload. On laisse passer tout (l'utilisateur triera ensuite par
        # nb d'abonnés / activité).
        if country and (r.get("country") or "").upper() != country:
            # country est rarement renseigné par les phantoms hashtag.
            # On rejette uniquement si on a une valeur explicite différente.
            if r.get("country"):
                rejected += 1; continue
        # ─── Filtre LANGUE — mode strict ────────────────────────────────
        # Quand l'utilisateur demande une langue, on vire tout ce qui n'est
        # PAS confirmé dans cette langue. Trois sources de confirmation :
        #   1. La langue déclarée par la plateforme (YouTube brandingSettings)
        #   2. Le pays déclaré (FR → on considère français)
        #   3. La détection sur description/nom (mots-marqueurs FR vs EN)
        # Si aucune source ne confirme la langue demandée → on rejette.
        if language:
            declared_lang = (r.get("language") or "").lower()
            declared_country = (r.get("country") or "").upper()
            text_blob = " ".join(filter(None, [
                str(r.get("description") or ""),
                str(r.get("bio") or ""),
                str(r.get("name") or ""),
                str(r.get("handle") or ""),
            ]))
            detected = _detect_language(text_blob)
            # Confirmations possibles
            ok_declared = declared_lang == language
            ok_country  = (language == "fr" and declared_country == "FR")
            ok_detected = detected == language
            # Conflits qui doivent virer même si une source dit OK :
            # (ex: lang=en déclaré mais on veut fr → rejette même si pays FR)
            conflict_declared = declared_lang and declared_lang != language
            conflict_detected = detected and detected != language
            if conflict_declared or conflict_detected:
                rejected += 1; continue
            if not (ok_declared or ok_country or ok_detected):
                # Aucune confirmation positive → rejette
                rejected += 1; continue
        if with_email and not (r.get("emails") or []):
            rejected += 1; continue
        kept.append(r)
    return kept, rejected


# ---------------------------------------------------------------------------
# Helpers PhantomBuster (discovery)
# ---------------------------------------------------------------------------
def _run_phantom_platforms(*, niche: str, platforms: list[str],
                            max_per_platform: int,
                            log,
                            agg_stats: dict,
                            filters: dict | None = None) -> None:
    """Exécute la découverte PhantomBuster pour chaque plateforme demandée,
    en séquence. Met à jour agg_stats en place.

    Les phantoms sont lents (10-30 min chacun) — on log régulièrement
    pour que l'UI affiche un signe de vie.
    """
    try:
        from .. import phantombuster_client, phantom_discovery
    except Exception as exc:
        log(f"⚠ PhantomBuster indisponible : {exc}")
        return

    sb = repo._sb()
    if sb is None:
        log("⚠ Supabase non joignable : impossible d'insérer les profils.")
        return

    triskell_client = None
    try:
        from triskell_core.db import get_client as _gc, SupabaseNotConfigured
        try:
            tc = _gc()
            if tc.is_authenticated:
                triskell_client = tc
        except SupabaseNotConfigured:
            pass
    except Exception:
        pass
    pb_cfg = phantombuster_client.load_config(triskell_client)
    api_key = (pb_cfg or {}).get("api_key") or ""
    phantoms = (pb_cfg or {}).get("discovery_phantoms") or {}
    if not api_key:
        log("⚠ Clé API PhantomBuster manquante (Réglages → Intégrations).")
        return

    for platform in platforms:
        phantom_id = (phantoms or {}).get(platform) or ""
        if not phantom_id:
            log(f"⚠ Phantom {platform} non configuré (Réglages → PhantomBuster).")
            continue
        log(f"════════ {platform.upper()} ════════")
        try:
            res = phantom_discovery.discover_profiles(
                sb=sb,
                api_key=api_key,
                platform=platform,
                phantom_id=phantom_id,
                niche=niche,
                max_results=max_per_platform,
                progress=log,
                client=triskell_client,
                filters=filters,
            )
        except Exception as exc:
            log(f"💥 {platform} : {exc}")
            continue
        if not res.get("ok"):
            log(f"⚠ {platform} : {res.get('error') or 'échec'}")
            continue
        agg_stats["phantom_inserted"] += int(res.get("inserted", 0) or 0)
        agg_stats["phantom_skipped"]  += int(res.get("skipped",  0) or 0)
        agg_stats["found"]            += int(res.get("profiles_found", 0) or 0)
        agg_stats["per_platform"][platform] = {
            "profiles_found": res.get("profiles_found", 0),
            "inserted":       res.get("inserted", 0),
            "skipped":        res.get("skipped", 0),
            "errors":         res.get("errors", 0),
        }
