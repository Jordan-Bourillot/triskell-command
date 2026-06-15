"""DAO Supabase pour Obelisk (prospection créateurs).

Lit/écrit dans la table partagée `public.prospects` (déjà alimentée par
l'app standalone Obelisk via son module RemoteCRM). Triskell Command
devient simplement un consommateur de plus de cette table.

Tables touchées :
  - public.prospects               (schéma : supabase/01_schema.sql)
  - public.obelisk_search_jobs     (créée par migration 21_obelisk_jobs.sql)
  - public.obelisk_user_config     (créée par migration 21_obelisk_jobs.sql)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SERVICE_CLIENT = None
_SERVICE_CLIENT_TRIED = False


# ---------------------------------------------------------------------------
# Connexion Supabase (même pattern que lagriffe/repo.py)
# ---------------------------------------------------------------------------
def _load_service_config() -> Optional[dict]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
    if url and key:
        return {"url": url, "service_role_key": key}
    p = Path.home() / ".triskell-command" / "settings.json"
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            sb = d.get("supabase") or {}
            url = sb.get("url") or ""
            key = sb.get("service_role_key") or sb.get("service_key") or ""
            if url and key:
                return {"url": url, "service_role_key": key}
        except Exception as exc:
            logger.debug("obelisk._load_service_config: %s", exc)
    return None


def _service_sb():
    global _SERVICE_CLIENT, _SERVICE_CLIENT_TRIED
    if _SERVICE_CLIENT is not None:
        return _SERVICE_CLIENT
    if _SERVICE_CLIENT_TRIED:
        return None
    _SERVICE_CLIENT_TRIED = True
    cfg = _load_service_config()
    if cfg is None:
        return None
    try:
        from supabase import create_client
    except ImportError:
        logger.warning("supabase-py introuvable — pip install supabase")
        return None
    try:
        _SERVICE_CLIENT = create_client(cfg["url"], cfg["service_role_key"])
    except Exception as exc:
        logger.warning("obelisk._service_sb: %s", exc)
        return None
    return _SERVICE_CLIENT


def _user_sb():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None
    try:
        c = get_client()
    except SupabaseNotConfigured:
        return None
    if not c.is_authenticated:
        return None
    # c.raw force l'init du SDK ; le getattr "_client" restait None en
    # mode service_role tant que rien d'autre n'avait touché le client.
    try:
        return c.raw
    except Exception:
        return None


def _sb():
    return _service_sb() or _user_sb()


# ---------------------------------------------------------------------------
# Liste des créateurs (lecture)
# ---------------------------------------------------------------------------
ALLOWED_STATUSES = ("new", "qualified", "contacted", "replied", "refused", "won", "lost")

# Colonnes lues pour la liste. Les 3 dernières (contact_channel,
# next_follow_up_at, demo_url) viennent de la migration 51 : si la base
# n'est pas encore migrée, le select les incluant échoue → on retombe
# automatiquement sur le jeu de base (cf. _select_columns / fallback dans
# list_creators). Le code reste donc fonctionnel sans la migration.
_LIST_COLUMNS_BASE = (
    "id, name, handle, legal_name, emails, phones, website, "
    "city, postal_code, country, industry, description, "
    "monetized, monetization_reasons, score, score_label, "
    "subscribers, platform_url, status, tags, notes, "
    "last_contact_at, exported_at, sources, created_at, updated_at"
)
_CREATOR_EXTRA_COLUMNS = "contact_channel, next_follow_up_at, demo_url"
_LIST_COLUMNS_FULL = _LIST_COLUMNS_BASE + ", " + _CREATOR_EXTRA_COLUMNS


def _shift_iso(iso_str: str, *, seconds: int) -> str:
    """Décale un timestamp ISO (de Supabase) de `seconds` secondes.
    Renvoie l'original si parsing impossible — best-effort."""
    from datetime import timedelta
    if not iso_str:
        return iso_str
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return (dt + timedelta(seconds=seconds)).isoformat()
    except Exception:
        return iso_str


PRO_PLATFORM_URL_PATTERNS = ("openstreetmap", "pubmed")

# Plateformes "créateur/influenceur" — pour distinguer côté UI les onglets
# « Créateurs » vs « Pros ». La règle est simple et robuste :
#   - creator = platform_url contient UN de ces patterns
#   - pro     = TOUT LE RESTE (y compris les prospects sans platform_url,
#               comme ceux poussés par Le Chasseur depuis SIRENE)
# Sinon les pros du Chasseur (commerces locaux, artisans, coiffeurs…) ne
# sont visibles ni dans « Créateurs » ni dans « Pros » alors qu'ils
# devraient être dans « Pros ».
CREATOR_PLATFORM_URL_PATTERNS = (
    "youtube.com", "twitch.tv", "reddit.com", "bsky.app", "github.com",
    "tiktok.com", "instagram.com", "linkedin.com", "mastodon",
    "dailymotion.com", "kick.com", "podcasts.apple.com", "pypi.org",
)


def list_creators(*,
                  platform: str = "",
                  status: str = "",
                  min_score: int = 0,
                  city: str = "",
                  q: str = "",
                  has_email: Optional[bool] = None,
                  country: str = "",
                  job_id: str = "",
                  exported: str = "",
                  contacted: str = "",
                  sort_by: str = "score",
                  audience: str = "",
                  contact_channel: str = "",
                  follow_up: bool = False,
                  follow_up_stale_days: int = 0,
                  limit: int = 100,
                  offset: int = 0) -> dict:
    """Retourne une page de prospects + le count total filtré.

    Filtres :
      - platform   : 'youtube', 'twitch', 'bluesky', etc. (matche dans
                     sources[*].name OU platform_url)
      - contact_channel : canal de contact exact ('instagram', 'tiktok',
                     'youtube', 'facebook', 'email', 'autre'). Sert à la
                     section « Créateurs » (démarchage réseaux sociaux).
      - follow_up  : True → ne renvoie QUE les créateurs « à relancer » :
                     next_follow_up_at <= maintenant, OU (si
                     follow_up_stale_days > 0) statut 'contacted' avec
                     last_contact_at plus vieux que ce nombre de jours et
                     aucune relance déjà programmée. Tri par date de
                     relance la plus ancienne d'abord.
      - status     : status CRM exact ('new', 'qualified', ...)
      - min_score  : score minimal (inclusif)
      - city       : préfixe ville (ilike)
      - q          : texte libre (matche name / handle / website / description)
      - has_email  : True → uniquement avec emails non vides ; False → uniquement sans ;
                     None (défaut) → tout
      - country    : "FR" → uniquement France ;
                     "OTHERS" → tous SAUF France (vide ou autre code) ;
                     "" → pas de filtre
      - job_id     : UUID d'un obelisk_search_jobs. Limite aux prospects créés
                     pendant la fenêtre d'exécution du job (started_at →
                     finished_at). Tolère 5 min de buffer pour absorber les
                     décalages d'horloge.
      - exported   : "yes" → uniquement ceux déjà sortis dans un export ;
                     "no" → ceux jamais exportés ;
                     "" (défaut) → tout
      - contacted  : "yes" → uniquement ceux déjà contactés par mail ;
                     "no" → ceux jamais contactés ;
                     "" (défaut) → tout
      - sort_by    : "score" (défaut, décroissant), "subs_desc", "subs_asc",
                     "created_desc" (les plus récents d'abord)
      - audience   : "creator" → uniquement les prospects dont platform_url
                     matche une plateforme créateur connue (YouTube, Twitch,
                     GitHub, LinkedIn, Instagram, TikTok…) ;
                     "pro" → tout le reste : OSM, PubMed, ET les pros sans
                     platform_url (entreprises poussées par Le Chasseur
                     depuis SIRENE n'ont qu'un site web, pas d'URL de
                     plateforme sociale) ;
                     "" (défaut) → tout, sans filtre d'audience.
    """
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré", "rows": [], "count": 0}

    chan = (contact_channel or "").strip().lower()
    follow_up_on = bool(follow_up)

    # Construit la requête. Isolée dans une closure pour pouvoir la rejouer
    # avec le jeu de colonnes de base si le jeu étendu (colonnes de la
    # migration 51) n'existe pas encore côté DB → aucun plantage sans la
    # migration, on perd juste le filtre canal / relance.
    def _build(columns: str, *, with_creator_cols: bool):
        qy = sb.table("prospects").select(columns, count="exact")
        if job_id:
            jres = get_search_job(job_id)
            if jres.get("ok"):
                job = jres.get("job") or {}
                start = job.get("started_at") or job.get("created_at")
                end = job.get("finished_at")
                if start:
                    qy = qy.gte("created_at",
                                _shift_iso(start, seconds=-300))
                if end:
                    qy = qy.lte("created_at",
                                _shift_iso(end, seconds=300))
        if status and status in ALLOWED_STATUSES:
            qy = qy.eq("status", status)
        if min_score and min_score > 0:
            qy = qy.gte("score", int(min_score))
        if city:
            qy = qy.ilike("city", f"{city}%")
        if q:
            # Recherche textuelle multi-colonnes (or_ supabase)
            term = q.replace("%", "")[:80]
            qy = qy.or_(
                f"name.ilike.%{term}%,"
                f"handle.ilike.%{term}%,"
                f"website.ilike.%{term}%,"
                f"description.ilike.%{term}%,"
                f"legal_name.ilike.%{term}%"
            )
        if has_email is True:
            qy = qy.neq("emails", "[]")
        elif has_email is False:
            qy = qy.eq("emails", "[]")
        if platform:
            # platform_url contient youtube.com / twitch.tv / etc. selon source
            p = platform.lower()
            qy = qy.ilike("platform_url", f"%{p}%")
        # Filtre par audience (créateurs vs pros/entreprises).
        # Règle : un prospect est "creator" si son platform_url matche un
        # pattern de plateforme créateur (YouTube, Twitch, GitHub…). Tout
        # le reste est "pro" — y compris les prospects sans platform_url
        # (typique des entreprises poussées par Le Chasseur depuis SIRENE)
        # ou avec un platform_url type openstreetmap.org / pubmed.
        aud = (audience or "").strip().lower()
        if aud == "creator":
            qy = qy.or_(",".join(
                f"platform_url.ilike.%{pat}%"
                for pat in CREATOR_PLATFORM_URL_PATTERNS
            ))
        elif aud == "pro":
            for pat in CREATOR_PLATFORM_URL_PATTERNS:
                qy = qy.filter("platform_url", "not.ilike", f"%{pat}%")
        if country:
            cu = country.strip().upper()
            if cu == "FR":
                qy = qy.eq("country", "FR")
            elif cu == "OTHERS":
                qy = qy.neq("country", "FR")
            else:
                # Pays explicite : on filtre dessus
                qy = qy.eq("country", cu)
        # Déjà exporté dans une liste ?
        if exported == "yes":
            qy = qy.not_.is_("exported_at", "null")
        elif exported == "no":
            qy = qy.is_("exported_at", "null")
        # Déjà contacté par mail ?
        if contacted == "yes":
            qy = qy.not_.is_("last_contact_at", "null")
        elif contacted == "no":
            qy = qy.is_("last_contact_at", "null")
        # Filtres « créateurs » (colonnes migration 51) — seulement si le
        # jeu de colonnes étendu est disponible, sinon on les ignore
        # silencieusement (la requête de base reste valide).
        if with_creator_cols:
            if chan:
                qy = qy.eq("contact_channel", chan)
            if follow_up_on:
                now_iso = datetime.now(timezone.utc).isoformat()
                clauses = [f"next_follow_up_at.lte.{now_iso}"]
                if follow_up_stale_days and follow_up_stale_days > 0:
                    from datetime import timedelta
                    cutoff = (datetime.now(timezone.utc)
                              - timedelta(days=int(follow_up_stale_days))).isoformat()
                    # Contactés depuis longtemps, sans relance programmée.
                    clauses.append(
                        "and(status.eq.contacted,"
                        f"last_contact_at.lte.{cutoff},"
                        "next_follow_up_at.is.null)")
                qy = qy.or_(",".join(clauses))
        # Ordre. En mode « à relancer » : la relance la plus en retard
        # d'abord (next_follow_up_at croissant). Sinon : score (défaut),
        # abonnés desc/asc, arrivée récente.
        sb_sort = (sort_by or "").strip().lower()
        if follow_up_on and with_creator_cols:
            qy = qy.order("next_follow_up_at", desc=False, nullsfirst=False)
        elif sb_sort == "subs_desc":
            qy = qy.order("subscribers", desc=True, nullsfirst=False).order("score", desc=True)
        elif sb_sort == "subs_asc":
            qy = qy.order("subscribers", desc=False, nullsfirst=False).order("score", desc=True)
        elif sb_sort == "created_desc":
            qy = qy.order("created_at", desc=True).order("score", desc=True)
        else:
            qy = qy.order("score", desc=True).order("updated_at", desc=True)
        qy = qy.range(offset, offset + max(0, limit - 1))
        return qy

    # 1re tentative avec les colonnes étendues (canal/relance/démo). Si la
    # base n'est pas migrée, Postgres renvoie une erreur « column does not
    # exist » → on rejoue avec le jeu de base (sans les filtres créateurs).
    want_creator_cols = True
    try:
        res = _build(_LIST_COLUMNS_FULL, with_creator_cols=True).execute()
        return {"ok": True, "rows": res.data or [],
                "count": getattr(res, "count", None) or len(res.data or [])}
    except Exception as exc:
        msg = str(exc).lower()
        col_missing = ("contact_channel" in msg or "next_follow_up_at" in msg
                       or "demo_url" in msg or "does not exist" in msg
                       or "column" in msg)
        if not col_missing:
            logger.warning("obelisk.list_creators: %s", exc)
            return {"ok": False, "error": str(exc), "rows": [], "count": 0}
        want_creator_cols = False
    if not want_creator_cols:
        # Migration 51 pas encore appliquée : on sert quand même la liste,
        # sans les colonnes/filtres créateurs (dégradé propre).
        if follow_up_on or chan:
            logger.info("obelisk.list_creators : colonnes créateurs absentes "
                        "(migration 51 non appliquée) — filtre relance/canal ignoré")
        try:
            res = _build(_LIST_COLUMNS_BASE, with_creator_cols=False).execute()
            return {"ok": True, "rows": res.data or [],
                    "count": getattr(res, "count", None) or len(res.data or [])}
        except Exception as exc:
            logger.warning("obelisk.list_creators (fallback): %s", exc)
            return {"ok": False, "error": str(exc), "rows": [], "count": 0}


def mark_exported(prospect_ids: list[str]) -> dict:
    """Marque une liste de prospects comme "exportés à l'instant" en
    posant `exported_at = now()`. Utilisé par l'API d'export pour qu'on
    puisse ensuite filtrer "déjà exporté dans une liste" depuis Obelisk."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    ids = [str(x) for x in (prospect_ids or []) if x]
    if not ids:
        return {"ok": True, "updated": 0}
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        res = (sb.table("prospects")
                 .update({"exported_at": now_iso})
                 .in_("id", ids)
                 .execute())
        return {"ok": True, "updated": len(res.data or [])}
    except Exception as exc:
        logger.warning("obelisk.mark_exported: %s", exc)
        return {"ok": False, "error": str(exc), "updated": 0}


def list_creators_for_export(*, limit_max: int = 5000, **filters) -> dict:
    """Récupère TOUTES les lignes qui matchent les filtres, sans pagination
    (cap à limit_max pour ne pas exploser la mémoire). Réutilise list_creators
    par pages de 500. Renvoie {"ok": True, "rows": [...]}.

    Les paramètres acceptés sont les mêmes que list_creators sauf limit/offset.
    """
    page_size = 500
    all_rows: list[dict] = []
    offset = 0
    while True:
        res = list_creators(limit=page_size, offset=offset, **filters)
        if not res.get("ok"):
            return res
        chunk = res.get("rows") or []
        all_rows.extend(chunk)
        if len(chunk) < page_size or len(all_rows) >= limit_max:
            break
        offset += page_size
    return {"ok": True, "rows": all_rows[:limit_max], "count": len(all_rows[:limit_max])}


def get_creator(prospect_id: str) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        rows = (sb.table("prospects").select("*")
                  .eq("id", prospect_id).limit(1).execute().data or [])
        if not rows:
            return {"ok": False, "error": "introuvable"}
        return {"ok": True, "prospect": rows[0]}
    except Exception as exc:
        logger.warning("obelisk.get_creator: %s", exc)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Audit + purge des prospects non-francophones
# ---------------------------------------------------------------------------
def _is_likely_francophone(row: dict) -> tuple[bool, str]:
    """Renvoie (True, raison) si le prospect est probablement francophone,
    (False, raison) sinon. La logique reflète apply_filters en mode strict :
    il faut au moins une source de confirmation FR et aucun conflit.
    """
    from .runner import _detect_language
    declared_lang = (row.get("language") or "").lower()
    declared_country = (row.get("country") or "").upper()
    text_blob = " ".join(filter(None, [
        str(row.get("description") or ""),
        str(row.get("name") or ""),
        str(row.get("handle") or ""),
    ]))
    detected = _detect_language(text_blob)
    # Conflit fort : langue déclarée ≠ fr, ou détection ≠ fr
    if declared_lang and declared_lang != "fr":
        return False, f"langue déclarée = {declared_lang}"
    if detected == "en":
        return False, "anglais détecté dans la description"
    # Confirmation positive ?
    if declared_lang == "fr":
        return True, "langue déclarée = fr"
    if declared_country == "FR":
        return True, "pays = FR"
    if detected == "fr":
        return True, "français détecté dans la description"
    # Rien ne confirme FR → on considère pas francophone
    return False, "aucun signal FR (pas de description / pas de pays / pas de langue déclarée)"


def audit_non_francophones(*, limit_scan: int = 5000) -> dict:
    """Parcourt jusqu'à `limit_scan` prospects et renvoie ceux qui ne
    sont PAS confirmés francophones. Pour preview avant suppression.

    Renvoie {ok, total_scanned, non_fr_count, ids, examples}.
    examples = jusqu'à 10 prospects (id + name + reason) pour affichage UI.
    """
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        page = 500
        offset = 0
        scanned = 0
        non_fr_ids: list[str] = []
        examples: list[dict] = []
        while scanned < limit_scan:
            res = (sb.table("prospects")
                     .select("id, name, handle, language, country, description")
                     .range(offset, offset + page - 1)
                     .execute())
            rows = res.data or []
            if not rows:
                break
            for r in rows:
                scanned += 1
                is_fr, reason = _is_likely_francophone(r)
                if not is_fr:
                    non_fr_ids.append(r["id"])
                    if len(examples) < 10:
                        examples.append({
                            "id":     r.get("id"),
                            "name":   r.get("name") or r.get("handle") or "?",
                            "country": r.get("country") or "",
                            "language": r.get("language") or "",
                            "reason": reason,
                        })
            if len(rows) < page:
                break
            offset += page
        return {
            "ok": True,
            "total_scanned": scanned,
            "non_fr_count":  len(non_fr_ids),
            "ids":           non_fr_ids,
            "examples":      examples,
        }
    except Exception as exc:
        logger.exception("obelisk.audit_non_francophones")
        return {"ok": False, "error": str(exc),
                "total_scanned": 0, "non_fr_count": 0, "ids": [], "examples": []}


def purge_below_subscribers(*, threshold: int, confirm: str = "") -> dict:
    """Supprime les prospects qui ont MOINS de `threshold` abonnés
    (prospects sans valeur d'abonnés ne sont PAS supprimés — on ne sait pas
    s'ils sont petits ou juste pas mesurés).
    Exige confirm = 'PURGE_BELOW_SUBS' pour passer à l'action.
    Sans confirm, renvoie un preview (count + 5 exemples)."""
    try:
        threshold = int(threshold)
    except (TypeError, ValueError):
        return {"ok": False, "error": "threshold invalide"}
    if threshold <= 0:
        return {"ok": False, "error": "threshold doit être > 0"}
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        # Récupère les prospects à supprimer (count + exemples + ids)
        page_size = 500
        all_rows: list[dict] = []
        offset = 0
        while True:
            res = (sb.table("prospects")
                     .select("id, name, handle, subscribers, platform_url")
                     .not_.is_("subscribers", "null")
                     .lt("subscribers", threshold)
                     .range(offset, offset + page_size - 1)
                     .execute())
            chunk = res.data or []
            all_rows.extend(chunk)
            if len(chunk) < page_size:
                break
            offset += page_size
        ids = [r["id"] for r in all_rows if r.get("id")]
        examples = []
        for r in all_rows[:5]:
            examples.append({
                "name": r.get("name") or r.get("handle") or "(sans nom)",
                "subscribers": r.get("subscribers"),
            })
        if confirm != "PURGE_BELOW_SUBS":
            return {
                "ok": True,
                "preview": True,
                "threshold": threshold,
                "count": len(ids),
                "examples": examples,
            }
        if not ids:
            return {"ok": True, "deleted": 0, "examples": []}
        deleted = 0
        for i in range(0, len(ids), 200):
            batch = ids[i:i + 200]
            try:
                sb.table("prospects").delete().in_("id", batch).execute()
                deleted += len(batch)
            except Exception as exc:
                logger.warning("obelisk.purge_below_subs batch: %s", exc)
        return {"ok": True, "deleted": deleted, "examples": examples}
    except Exception as exc:
        logger.warning("obelisk.purge_below_subscribers: %s", exc)
        return {"ok": False, "error": str(exc)}


def audit_guessed_emails(*, limit_scan: int = 10000) -> dict:
    """Scan la base et renvoie les prospects dont TOUS les emails sont
    des local-parts génériques (contact@, info@, hello@, ...), donc
    devinés à partir du domaine et jamais lus en vrai sur une page.

    Renvoie {ok, total_scanned, count, ids, examples}.
    examples = jusqu'à 10 prospects (id + name + email) pour preview UI.
    """
    from .export import _row_confidence
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        page = 500
        offset = 0
        scanned = 0
        guessed_ids: list[str] = []
        examples: list[dict] = []
        while scanned < limit_scan:
            res = (sb.table("prospects")
                     .select("id, name, handle, emails")
                     .neq("emails", "[]")
                     .range(offset, offset + page - 1)
                     .execute())
            rows = res.data or []
            if not rows:
                break
            for r in rows:
                scanned += 1
                if _row_confidence(r) == "devine":
                    guessed_ids.append(r["id"])
                    if len(examples) < 10:
                        ems = r.get("emails") or []
                        first = str(ems[0]) if ems else ""
                        examples.append({
                            "id":    r.get("id"),
                            "name":  r.get("name") or r.get("handle") or "?",
                            "email": first,
                        })
            if len(rows) < page:
                break
            offset += page
        return {
            "ok":            True,
            "total_scanned": scanned,
            "count":         len(guessed_ids),
            "ids":           guessed_ids,
            "examples":      examples,
        }
    except Exception as exc:
        logger.exception("obelisk.audit_guessed_emails")
        return {"ok": False, "error": str(exc),
                "total_scanned": 0, "count": 0, "ids": [], "examples": []}


def purge_guessed_emails(*, confirm: str = "") -> dict:
    """Supprime tous les prospects dont les emails sont uniquement
    génériques (contact@, info@, ...). Exige confirm = 'PURGE_GUESSED'
    pour passer à l'action. Sinon renvoie un preview."""
    audit = audit_guessed_emails()
    if not audit.get("ok"):
        return audit
    if confirm != "PURGE_GUESSED":
        return {
            "ok":            True,
            "preview":       True,
            "count":         audit["count"],
            "total_scanned": audit["total_scanned"],
            "examples":      audit["examples"],
        }
    ids = audit.get("ids") or []
    if not ids:
        return {"ok": True, "deleted": 0, "examples": []}
    sb = _sb()
    deleted = 0
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        try:
            sb.table("prospects").delete().in_("id", batch).execute()
            deleted += len(batch)
        except Exception as exc:
            logger.warning("obelisk.purge_guessed_emails batch failed: %s", exc)
    return {"ok": True, "deleted": deleted, "examples": audit["examples"]}


def purge_non_francophones(*, confirm: str = "") -> dict:
    """Supprime tous les prospects non-confirmés francophones.
    Exige confirm = 'PURGE_NON_FR' pour passer à l'action (sécurité).
    Sinon, renvoie juste un preview (count + examples).
    """
    audit = audit_non_francophones()
    if not audit.get("ok"):
        return audit
    if confirm != "PURGE_NON_FR":
        return {
            "ok": True,
            "preview": True,
            "non_fr_count": audit["non_fr_count"],
            "total_scanned": audit["total_scanned"],
            "examples": audit["examples"],
        }
    ids = audit.get("ids") or []
    if not ids:
        return {"ok": True, "deleted": 0, "examples": []}
    # Supprime par batches de 200 (Supabase a une limite sur les "in" filters)
    sb = _sb()
    deleted = 0
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        try:
            sb.table("prospects").delete().in_("id", batch).execute()
            deleted += len(batch)
        except Exception as exc:
            logger.warning("obelisk.purge_non_francophones batch failed: %s", exc)
    return {"ok": True, "deleted": deleted, "examples": audit["examples"]}


# ---------------------------------------------------------------------------
# Stats globales pour le bandeau du haut
# ---------------------------------------------------------------------------
def stats() -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        out: dict[str, int] = {"total": 0, "with_email": 0, "qualified": 0,
                                "contacted": 0, "replied": 0, "won": 0}
        # total
        r = sb.table("prospects").select("id", count="exact").limit(1).execute()
        out["total"] = getattr(r, "count", None) or 0
        # with_email (emails != '[]')
        r = sb.table("prospects").select("id", count="exact").neq("emails", "[]").limit(1).execute()
        out["with_email"] = getattr(r, "count", None) or 0
        for s in ("qualified", "contacted", "replied", "won"):
            r = sb.table("prospects").select("id", count="exact").eq("status", s).limit(1).execute()
            out[s] = getattr(r, "count", None) or 0
        return {"ok": True, "stats": out}
    except Exception as exc:
        logger.warning("obelisk.stats: %s", exc)
        return {"ok": False, "error": str(exc), "stats": {}}


# ---------------------------------------------------------------------------
# Update CRM (statut, tags, notes)
# ---------------------------------------------------------------------------
def update_creator(prospect_id: str, fields: dict) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    # contact_channel / next_follow_up_at / demo_url = colonnes migration 51.
    ALLOWED = ("status", "tags", "notes", "last_contact_at",
               "contact_channel", "next_follow_up_at", "demo_url")
    # Colonnes susceptibles d'être absentes si la base n'est pas migrée.
    CREATOR_COLS = ("contact_channel", "next_follow_up_at", "demo_url")
    payload: dict = {}
    for k in ALLOWED:
        if k in fields:
            payload[k] = fields[k]
    if "status" in payload and payload["status"] not in ALLOWED_STATUSES:
        return {"ok": False, "error": "status invalide"}
    if "notes" in payload and isinstance(payload["notes"], str):
        payload["notes"] = payload["notes"][:10_000]
    if "demo_url" in payload and isinstance(payload["demo_url"], str):
        payload["demo_url"] = payload["demo_url"].strip()[:2_000]
    if "contact_channel" in payload and isinstance(payload["contact_channel"], str):
        payload["contact_channel"] = payload["contact_channel"].strip().lower()[:40]
    # next_follow_up_at : "" ou None → on remet la colonne à NULL (relance
    # annulée) ; sinon on passe la valeur telle quelle (ISO attendu).
    if "next_follow_up_at" in payload:
        v = payload["next_follow_up_at"]
        payload["next_follow_up_at"] = (v or None) if not isinstance(v, str) else (v.strip() or None)
    if not payload:
        return {"ok": False, "error": "aucun champ à mettre à jour"}
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("prospects").update(payload).eq("id", prospect_id).execute()
        return {"ok": True, "prospect_id": prospect_id}
    except Exception as exc:
        msg = str(exc).lower()
        # Base pas encore migrée (colonnes créateurs absentes) : on réessaie
        # sans elles plutôt que d'échouer, pour ne pas bloquer la mise à
        # jour des champs CRM classiques (statut, notes…).
        if any(c in payload for c in CREATOR_COLS) and (
                "does not exist" in msg or "column" in msg
                or any(c in msg for c in CREATOR_COLS)):
            safe = {k: v for k, v in payload.items() if k not in CREATOR_COLS}
            if len(safe) <= 1:  # ne reste que updated_at
                return {"ok": False,
                        "error": "Colonnes créateurs absentes — applique la migration 51."}
            try:
                sb.table("prospects").update(safe).eq("id", prospect_id).execute()
                return {"ok": True, "prospect_id": prospect_id,
                        "warning": "Champs créateurs ignorés (migration 51 non appliquée)."}
            except Exception as exc2:
                logger.warning("obelisk.update_creator (fallback): %s", exc2)
                return {"ok": False, "error": str(exc2)}
        logger.warning("obelisk.update_creator: %s", exc)
        return {"ok": False, "error": str(exc)}


def create_creator(fields: dict, *, workspace_id: str = "") -> dict:
    """Crée un créateur de prospection dans la table `prospects`.

    Pensé pour la saisie manuelle depuis la section « Créateurs » (un
    YouTubeur/Instagrameur qu'on démarche par réseaux sociaux). Champs
    acceptés : name (requis), handle, platform_url, subscribers, status,
    contact_channel, next_follow_up_at, demo_url, notes, tags, emails.

    Dédoublonnage léger : si un platform_url est fourni et qu'un prospect
    a déjà EXACTEMENT ce platform_url, on renvoie celui-là (action
    'exists') au lieu d'en créer un doublon. Pas d'email exigé (le cœur du
    besoin : ces créateurs se démarchent SANS mail).

    Renvoie {ok, prospect_id, action}. Défensif vis-à-vis de la migration
    51 : si les colonnes créateurs manquent, on insère sans elles.
    """
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    f = fields or {}
    name = (f.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name requis"}
    status = (f.get("status") or "new").strip() or "new"
    if status not in ALLOWED_STATUSES:
        status = "new"
    platform_url = (f.get("platform_url") or "").strip()

    # Dédoublonnage : platform_url identique → on ne recrée pas.
    if platform_url:
        try:
            dup = (sb.table("prospects").select("id")
                   .eq("platform_url", platform_url).limit(1).execute().data or [])
            if dup:
                return {"ok": True, "prospect_id": dup[0]["id"], "action": "exists"}
        except Exception as exc:
            logger.debug("create_creator dedup lookup KO: %s", exc)

    emails = f.get("emails") or []
    if not isinstance(emails, list):
        emails = []
    tags = f.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    subs = f.get("subscribers")
    try:
        subs = int(subs) if subs not in (None, "", []) else None
    except (TypeError, ValueError):
        subs = None

    row: dict = {
        "name": name,
        "handle": (f.get("handle") or "").strip(),
        "platform_url": platform_url,
        "emails": [str(e).strip() for e in emails if str(e).strip()],
        "subscribers": subs,
        "status": status,
        "notes": (f.get("notes") or "").strip()[:10_000],
        "tags": tags,
    }
    if workspace_id:
        row["workspace_id"] = workspace_id
    # Champs CRM « créateurs » (migration 51).
    creator_extra = {
        "contact_channel": (f.get("contact_channel") or "").strip().lower()[:40],
        "demo_url": (f.get("demo_url") or "").strip()[:2_000],
    }
    nfu = f.get("next_follow_up_at")
    if isinstance(nfu, str) and nfu.strip():
        creator_extra["next_follow_up_at"] = nfu.strip()
    # last_contact_at : si on saisit une date de contact, on la pose ; sinon
    # on laisse vide (la création seule ne vaut pas « contacté »).
    lca = f.get("last_contact_at")
    if isinstance(lca, str) and lca.strip():
        row["last_contact_at"] = lca.strip()

    def _insert(full: bool) -> dict:
        body = dict(row)
        if full:
            body.update({k: v for k, v in creator_extra.items() if v not in (None, "")})
        res = sb.table("prospects").insert(body).execute()
        new_id = ""
        if res.data:
            new_id = (res.data[0] or {}).get("id", "")
        return {"ok": True, "prospect_id": new_id, "action": "created"}

    try:
        return _insert(full=True)
    except Exception as exc:
        msg = str(exc).lower()
        if ("does not exist" in msg or "column" in msg
                or any(c in msg for c in ("contact_channel", "next_follow_up_at", "demo_url"))):
            try:
                out = _insert(full=False)
                out["warning"] = "Champs créateurs ignorés (migration 51 non appliquée)."
                return out
            except Exception as exc2:
                logger.warning("obelisk.create_creator (fallback): %s", exc2)
                return {"ok": False, "error": str(exc2)}
        logger.warning("obelisk.create_creator: %s", exc)
        return {"ok": False, "error": str(exc)}


def mark_contacted(prospect_id: str) -> dict:
    """Passe le statut d'un prospect à « contacted » s'il était en
    new/qualified, et met à jour last_contact_at. Idempotent : on ne
    régresse jamais un statut plus avancé (replied/won/lost/refused)."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        from datetime import datetime, timezone
        cur = (sb.table("prospects").select("status")
               .eq("id", prospect_id).limit(1).execute().data or [])
        status_now = (cur[0].get("status") if cur else "") or ""
        # On bascule seulement si on est en amont de la pipeline
        if status_now in ("", "new", "qualified"):
            sb.table("prospects").update({
                "status":          "contacted",
                "last_contact_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }).eq("id", prospect_id).execute()
            return {"ok": True, "changed": True, "from": status_now}
        # Sinon on met juste à jour last_contact_at (utile pour drips)
        sb.table("prospects").update({
            "last_contact_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }).eq("id", prospect_id).execute()
        return {"ok": True, "changed": False, "from": status_now}
    except Exception as exc:
        logger.warning("obelisk.mark_contacted: %s", exc)
        return {"ok": False, "error": str(exc)}


def delete_creator(prospect_id: str) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        sb.table("prospects").delete().eq("id", prospect_id).execute()
        return {"ok": True}
    except Exception as exc:
        logger.warning("obelisk.delete_creator: %s", exc)
        return {"ok": False, "error": str(exc)}


def delete_creators_bulk(prospect_ids: list[str]) -> dict:
    """Supprime plusieurs créateurs d'un coup. Renvoie le nombre supprimé."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré", "deleted": 0}
    ids = [str(i).strip() for i in (prospect_ids or []) if i]
    if not ids:
        return {"ok": True, "deleted": 0}
    try:
        # Le client Supabase Python ne supporte pas always le batch in_().
        # On chunke par 50 pour rester sous la limite d'URL.
        deleted = 0
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            sb.table("prospects").delete().in_("id", chunk).execute()
            deleted += len(chunk)
        return {"ok": True, "deleted": deleted}
    except Exception as exc:
        logger.warning("obelisk.delete_creators_bulk: %s", exc)
        return {"ok": False, "error": str(exc), "deleted": 0}


def delete_creators_filtered(*,
                              platform: str = "",
                              status: str = "",
                              min_score: int = 0,
                              city: str = "",
                              q: str = "",
                              has_email: Optional[bool] = None,
                              audience: str = "",
                              country: str = "",
                              job_id: str = "",
                              exported: str = "",
                              contacted: str = "") -> dict:
    """Supprime tous les créateurs qui matchent les filtres donnés.
    Réutilise list_creators pour récupérer les IDs, puis delete_bulk.
    Honore TOUS les filtres de la vue (sinon « supprimer les résultats
    filtrés » pourrait toucher bien plus large que ce qui est affiché).

    Renvoie {ok, deleted, matched}.
    """
    # On récupère par paquets jusqu'à épuisement
    ids_total: list[str] = []
    offset = 0
    page_size = 200
    while True:
        page = list_creators(platform=platform, status=status,
                              min_score=min_score, city=city, q=q,
                              has_email=has_email, audience=audience,
                              country=country, job_id=job_id,
                              exported=exported, contacted=contacted,
                              limit=page_size, offset=offset)
        rows = (page or {}).get("rows") or []
        if not rows:
            break
        ids_total.extend(r["id"] for r in rows if r.get("id"))
        if len(rows) < page_size:
            break
        offset += page_size
        if offset > 10_000:   # garde-fou
            break
    if not ids_total:
        return {"ok": True, "deleted": 0, "matched": 0}
    res = delete_creators_bulk(ids_total)
    return {"ok": res.get("ok", False),
            "deleted": res.get("deleted", 0),
            "matched": len(ids_total),
            "error":   res.get("error", "")}


def delete_all_creators() -> dict:
    """Supprime TOUS les créateurs (table prospects). Garde-fou côté API :
    cette méthode doit être appelée seulement après double confirmation
    utilisateur. La table est purgée intégralement (workspace-scoped via
    les RLS Supabase normalement)."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré", "deleted": 0}
    try:
        # Count avant pour les stats
        c = sb.table("prospects").select("id", count="exact").limit(1).execute()
        before = int(c.count or 0)
        # Delete all avec un filtre toujours vrai (id n'est jamais vide)
        sb.table("prospects").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        return {"ok": True, "deleted": before}
    except Exception as exc:
        logger.warning("obelisk.delete_all_creators: %s", exc)
        return {"ok": False, "error": str(exc), "deleted": 0}


# ---------------------------------------------------------------------------
# Config Obelisk par user (clés API, IA, préférences, catalogue d'offres)
# Stockée dans une table dédiée pour rester user-scoped propre.
# ---------------------------------------------------------------------------
def get_user_config(user_email: str = "") -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": True, "config": _default_config(), "fallback": True}
    try:
        q = sb.table("obelisk_user_config").select("*").limit(1)
        if user_email:
            q = q.eq("user_email", user_email)
        rows = q.execute().data or []
        if not rows:
            return {"ok": True, "config": _default_config()}
        row = rows[0]
        cfg = row.get("config") or {}
        # Fusionne avec les défauts pour ne jamais renvoyer d'objet incomplet
        merged = {**_default_config(), **(cfg if isinstance(cfg, dict) else {})}
        return {"ok": True, "config": merged, "updated_at": row.get("updated_at")}
    except Exception as exc:
        logger.warning("obelisk.get_user_config: %s", exc)
        return {"ok": True, "config": _default_config(), "error": str(exc), "fallback": True}


def save_user_config(user_email: str, config: dict) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    if not isinstance(config, dict):
        return {"ok": False, "error": "config doit être un objet"}
    # Filtre les clés sensibles pour ne pas écrire n'importe quoi
    ALLOWED = (
        "niche", "platforms", "max_per_platform", "only_unmonetized",
        "enrich_web", "daily_cap",
        "ai_provider", "ai_model", "ai_mega_prompts",
        "catalog", "product_override",
        # API keys (chiffrement géré côté Supabase par RLS, pas de chiffrement
        # local supplémentaire à ce stade — TODO sécurité niveau 2 si besoin)
        "youtube_api_key", "twitch_client_id", "twitch_client_secret",
        "github_token", "mastodon_instances",
        "apple_podcasts_country", "apple_podcasts_lang",
        "ai_api_keys",
    )
    clean = {k: v for k, v in config.items() if k in ALLOWED}
    try:
        sb.table("obelisk_user_config").upsert({
            "user_email": user_email or "_default_",
            "config": clean,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="user_email").execute()
        return {"ok": True}
    except Exception as exc:
        logger.warning("obelisk.save_user_config: %s", exc)
        return {"ok": False, "error": str(exc)}


def list_pending(job_id: str = "") -> dict:
    """File d'attente « relire avant d'ajouter » : créateurs trouvés en mode
    validation, pas encore versés en base. Lecture seule."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "base indisponible", "rows": [], "count": 0}
    try:
        q = sb.table("obelisk_pending").select("id,job_id,prospect,created_at")
        if job_id:
            q = q.eq("job_id", job_id)
        rows = (q.order("created_at", desc=True).limit(1000).execute()).data or []
        return {"ok": True,
                "rows": [r.get("prospect") or {} for r in rows],
                "count": len(rows)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "rows": [], "count": 0}


def approve_pending(job_id: str = "") -> dict:
    """Verse les créateurs en attente dans la base, puis vide la file.
    Les fiches sont prêtes (workspace déjà appliqué) ; les contraintes SQL
    (mail unique, etc.) écartent d'elles-mêmes un éventuel doublon."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "base indisponible", "approved": 0}
    try:
        q = sb.table("obelisk_pending").select("id,prospect")
        if job_id:
            q = q.eq("job_id", job_id)
        rows = (q.limit(5000).execute()).data or []
        approved = 0
        for r in rows:
            row = r.get("prospect") or {}
            if row.get("name"):
                try:
                    sb.table("prospects").insert(row).execute()
                    approved += 1
                except Exception:
                    pass  # déjà en base / contrainte → on ignore (pas de doublon)
            try:
                sb.table("obelisk_pending").delete().eq("id", r.get("id")).execute()
            except Exception:
                pass
        return {"ok": True, "approved": approved}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "approved": 0}


def discard_pending(job_id: str = "") -> dict:
    """Vide la file d'attente sans rien verser (on ignore ces créateurs)."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "base indisponible", "discarded": 0}
    try:
        q = sb.table("obelisk_pending").select("id")
        if job_id:
            q = q.eq("job_id", job_id)
        rows = (q.limit(5000).execute()).data or []
        n = 0
        for r in rows:
            try:
                sb.table("obelisk_pending").delete().eq("id", r.get("id")).execute()
                n += 1
            except Exception:
                pass
        return {"ok": True, "discarded": n}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "discarded": 0}


def _default_config() -> dict:
    return {
        "niche": "",
        "platforms": ["youtube", "reddit"],
        "max_per_platform": 30,
        "only_unmonetized": True,
        "enrich_web": True,
        "daily_cap": 20,
        "ai_provider": "google",
        "ai_model": "gemini-2.5-flash",
        "ai_mega_prompts": ["16", "06", "07"],
        "catalog": "",
        "product_override": "",
        "youtube_api_key": "",
        "twitch_client_id": "",
        "twitch_client_secret": "",
        "github_token": "",
        "mastodon_instances": [],
        "apple_podcasts_country": "fr",
        "apple_podcasts_lang": "fr_fr",
        "ai_api_keys": {},
    }


# ---------------------------------------------------------------------------
# Search jobs : queue partagée pour lancer une recherche depuis Triskell
# Command alors qu'Obelisk standalone tourne (à terme : le runner web prend
# la main directement).
# ---------------------------------------------------------------------------
def create_search_job(user_email: str, niche: str, platforms: list[str],
                      max_per_platform: int = 30) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    if not niche:
        return {"ok": False, "error": "niche requise"}
    try:
        row = {
            "user_email": user_email or "_default_",
            "niche": niche[:200],
            "platforms": platforms or ["youtube"],
            "max_per_platform": int(max_per_platform or 30),
            "status": "pending",  # pending → running → done | failed
            "progress": [],
            "stats": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        res = sb.table("obelisk_search_jobs").insert(row).select("id").execute()
        data = res.data or []
        job_id = data[0].get("id") if data else None
        return {"ok": True, "job_id": job_id}
    except Exception as exc:
        logger.warning("obelisk.create_search_job: %s", exc)
        return {"ok": False, "error": str(exc)}


# Une vraie recherche Obélisk dure quelques minutes. Au-delà de ce délai
# sans s'être terminée, le job est considéré mort (serveur redémarré /
# planté pendant la recherche) — comme les « chasses zombies » des autres
# outils, qu'Obélisk ne gérait pas (d'où des recherches affichées « en
# cours » pendant des jours). Réglable via OBELISK_STALE_JOB_MINUTES.
def _stale_job_minutes() -> int:
    try:
        return max(15, int(os.environ.get("OBELISK_STALE_JOB_MINUTES", "90")))
    except (TypeError, ValueError):
        return 90


_ZOMBIE_JOB_MSG = ("Recherche interrompue (redémarrage du serveur ou "
                   "plantage). Relance-la pour repartir.")


def _job_is_stale(job: dict) -> bool:
    status = (job.get("status") or "").strip().lower()
    if status not in ("pending", "running") or job.get("finished_at"):
        return False
    ts = job.get("started_at") or job.get("created_at") or ""
    if not ts:
        return False
    # Sécurité : si le job tourne VRAIMENT dans ce process, on n'y touche pas.
    try:
        from .runner import _RUNNING
        if job.get("id") in _RUNNING:
            return False
    except Exception:
        pass
    from datetime import datetime, timezone, timedelta
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt) > timedelta(
            minutes=_stale_job_minutes())
    except Exception:
        return False


def _requalify_stale_jobs(jobs: list[dict]) -> list[dict]:
    """Marque « failed » les jobs visiblement morts et persiste la
    correction. Best-effort : ne lève jamais. Renvoie la liste corrigée."""
    out: list[dict] = []
    sb = None
    for job in (jobs or []):
        if isinstance(job, dict) and _job_is_stale(job):
            from datetime import datetime, timezone
            patch = {"status": "failed", "error": _ZOMBIE_JOB_MSG,
                     "finished_at": datetime.now(timezone.utc).isoformat()}
            try:
                sb = sb if sb is not None else _sb()
                if sb is not None:
                    (sb.table("obelisk_search_jobs").update(patch)
                       .eq("id", job.get("id")).execute())
                    logger.info("Recherche Obélisk zombie requalifiée : %s",
                                job.get("id"))
            except Exception as exc:
                logger.debug("requalify stale job %s : %s", job.get("id"), exc)
            job = {**job, **patch}
        out.append(job)
    return out


def get_search_job(job_id: str) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        rows = (sb.table("obelisk_search_jobs").select("*")
                  .eq("id", job_id).limit(1).execute().data or [])
        if not rows:
            return {"ok": False, "error": "introuvable"}
        job = _requalify_stale_jobs([rows[0]])[0]
        return {"ok": True, "job": job}
    except Exception as exc:
        logger.warning("obelisk.get_search_job: %s", exc)
        return {"ok": False, "error": str(exc)}


def list_recent_jobs(user_email: str = "", limit: int = 10) -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": True, "jobs": [], "fallback": True}
    try:
        q = (sb.table("obelisk_search_jobs")
               .select("id, niche, platforms, status, stats, created_at, "
                       "started_at, finished_at")
               .order("created_at", desc=True).limit(limit))
        if user_email:
            q = q.eq("user_email", user_email)
        jobs = _requalify_stale_jobs(q.execute().data or [])
        return {"ok": True, "jobs": jobs}
    except Exception as exc:
        logger.warning("obelisk.list_recent_jobs: %s", exc)
        return {"ok": True, "jobs": [], "error": str(exc)}
