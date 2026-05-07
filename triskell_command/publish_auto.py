"""Auto-publish hook : déclenche des drafts AlphaCast à partir de la prospection.

Quand tu envoies des propositions de site dans Campagnes, on incrémente un
compteur par plateforme. Au seuil, on génère un draft via AlphaCast en
intégrant : un thème (parmi 6), un angle rotatif (parmi 5) et le métier +
région du dernier prospect démarché en 1er contact.

Architecture multi-utilisateur (Jordan + Thomas sur le même compte LinkedIn
de Triskell Studio) :
- Compteurs et état partagés via `triskell_core.db` (Supabase, table
  `shared_settings`, clé `publish_auto_state`).
- Plafond quotidien calculé en interrogeant AlphaCast (qui sait qui a
  publié quoi aujourd'hui, sans qu'on duplique l'info).
- Les **préférences locales** (auto_publish toggle, master enabled) restent
  dans le settings.json local — c'est OK que chacun configure son client
  comme il veut.

Public API :
- THEMES, ANGLES               — listes utilisées par la vue Publier
- record_first_contact(...)    — appelée après une vague de Campagnes
- trigger_for_platform(...)    — déclenche manuellement un draft (bouton)
- daily_cap_remaining(...)     — combien il reste pour aujourd'hui
- counter_status(...)          — (count, threshold) pour l'UI
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

import requests

from .integrations import alphacast
from .integrations.alphacast import AlphaCastError, Draft

logger = logging.getLogger(__name__)


PLATFORMS = ("linkedin", "x", "bluesky")
SHARED_KEY = "publish_auto_state"

# Squelette du blob partagé. Si Supabase est offline, on retombe sur les
# clés équivalentes du settings.json local (mode dégradé mono-utilisateur).
_DEFAULT_SHARED: dict[str, Any] = {
    "counters": {"linkedin": 0, "x": 0, "bluesky": 0},
    "next_theme": "",
    "angle_index": 0,
    "last_prospect": {"metier": "", "region": ""},
}


THEMES: list[tuple[str, str, str]] = [
    # (key, label affiché, brief envoyé à l'IA)
    ("avant_apres", "Avant/Après",
     "raconte la refonte d'un site obsolète vers un site moderne, contraste visuel"),
    ("temoignage", "Témoignage client",
     "présente le retour d'un client content sans utiliser de citation fabriquée"),
    ("pourquoi_site", "Pourquoi un site",
     "explique pourquoi ce métier précis a besoin d'un site web aujourd'hui"),
    ("process", "Mon process",
     "décris ta façon de bosser de manière transparente et concrète"),
    ("tarif", "Tarif transparent",
     "démystifie le prix d'un site web pro, parle franchement du budget"),
    ("coulisses", "Coulisses",
     "partage une anecdote ou un détail des coulisses du métier de freelance"),
]


ANGLES: list[tuple[str, str]] = [
    # (key, hint envoyé à l'IA)
    ("anecdote",     "ouvre par une mini-histoire vécue (2-3 phrases) qui accroche"),
    ("question",     "ouvre par une question franche qui interpelle le lecteur"),
    ("stat",         "ouvre par un chiffre ou une stat qui surprend"),
    ("hot_take",     "ouvre par un avis tranché, presque polémique"),
    ("coulisses",    "ouvre par 'ce que les clients ne voient pas' — angle dévoilement"),
]


def theme_keys() -> list[str]:
    return [k for k, _, _ in THEMES]


def theme_label(key: str) -> str:
    for k, label, _ in THEMES:
        if k == key:
            return label
    return key


# ─── State partagé (AlphaCast /publish-state) ────────────────────────


def _alphacast_creds(app_state) -> tuple[str, str]:
    url = (app_state.get("social", "reseaux_api_url", default="") or "").rstrip("/")
    token = app_state.get("social", "reseaux_jwt", default="") or ""
    return url, token


def _normalize_blob(blob: dict) -> dict:
    """Garantit la structure attendue (defaults + sub-structure counters)."""
    out = dict(_DEFAULT_SHARED)
    out.update(blob if isinstance(blob, dict) else {})
    counters = blob.get("counters") if isinstance(blob, dict) else None
    if isinstance(counters, dict):
        out["counters"] = {**_DEFAULT_SHARED["counters"], **counters}
    else:
        out["counters"] = dict(_DEFAULT_SHARED["counters"])
    last = blob.get("last_prospect") if isinstance(blob, dict) else None
    if isinstance(last, dict):
        out["last_prospect"] = {
            "metier": str(last.get("metier") or ""),
            "region": str(last.get("region") or ""),
        }
    else:
        out["last_prospect"] = dict(_DEFAULT_SHARED["last_prospect"])
    return out


def _read_shared(app_state) -> dict:
    """GET /api/v1/publish-state. Fallback local si AlphaCast injoignable."""
    url, token = _alphacast_creds(app_state)
    if url and token:
        try:
            r = requests.get(
                f"{url}/api/v1/publish-state",
                headers={"Authorization": f"Bearer {token}"},
                timeout=8,
            )
            r.raise_for_status()
            return _normalize_blob(r.json() or {})
        except Exception as exc:
            logger.warning("read_shared(AlphaCast) a échoué : %s — fallback local", exc)
    # Fallback : on lit le settings.json local (mono-utilisateur dégradé)
    return _normalize_blob({
        "counters": {p: int(app_state.get("publish_auto", "counters", p, default=0) or 0)
                     for p in PLATFORMS},
        "next_theme": app_state.get("publish_auto", "next_theme", default="") or "",
        "angle_index": int(app_state.get("publish_auto", "angle_index", default=0) or 0),
        "last_prospect": app_state.get("publish_auto", "last_prospect", default={}) or {},
    })


def _write_shared(app_state, state: dict) -> None:
    """PUT /api/v1/publish-state (partial upsert). Fallback local si offline."""
    url, token = _alphacast_creds(app_state)
    if url and token:
        try:
            body = {
                "counters": state.get("counters") or {},
                "next_theme": state.get("next_theme", "") or "",
                "angle_index": int(state.get("angle_index", 0) or 0),
                "last_prospect": state.get("last_prospect") or {"metier": "", "region": ""},
            }
            r = requests.put(
                f"{url}/api/v1/publish-state",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json=body, timeout=8,
            )
            r.raise_for_status()
            return
        except Exception as exc:
            logger.warning("write_shared(AlphaCast) a échoué : %s — fallback local", exc)
    # Fallback local
    counters = state.get("counters") or {}
    for p in PLATFORMS:
        app_state.set("publish_auto", "counters", p, value=int(counters.get(p, 0) or 0))
    app_state.set("publish_auto", "next_theme", value=state.get("next_theme", "") or "")
    app_state.set("publish_auto", "angle_index",
                  value=int(state.get("angle_index", 0) or 0))
    app_state.set("publish_auto", "last_prospect",
                  value=state.get("last_prospect", {}) or {})
    try:
        app_state.save()
    except Exception:
        pass


def _atomic_increment(app_state, n: int,
                      last_prospect: dict | None = None) -> dict:
    """POST /publish-state/increment — incrément atomique côté serveur.

    Renvoie le state mis à jour. Fallback local en cas d'offline.
    """
    url, token = _alphacast_creds(app_state)
    if url and token:
        try:
            body: dict[str, Any] = {"n": n}
            if last_prospect:
                body["last_prospect"] = last_prospect
            r = requests.post(
                f"{url}/api/v1/publish-state/increment",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json=body, timeout=8,
            )
            r.raise_for_status()
            return _normalize_blob(r.json() or {})
        except Exception as exc:
            logger.warning("increment(AlphaCast) a échoué : %s — fallback local", exc)
    # Fallback : read+modify+write local
    cur = _read_shared(app_state)
    new = _increment_counters_in(cur, n=n)
    if last_prospect:
        new["last_prospect"] = last_prospect
    _write_shared(app_state, new)
    return new


def _atomic_reset(app_state, platform: str) -> dict:
    """POST /publish-state/reset — reset atomique d'une plateforme."""
    url, token = _alphacast_creds(app_state)
    if url and token:
        try:
            r = requests.post(
                f"{url}/api/v1/publish-state/reset",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json={"platform": platform}, timeout=8,
            )
            r.raise_for_status()
            return _normalize_blob(r.json() or {})
        except Exception as exc:
            logger.warning("reset(AlphaCast) a échoué : %s — fallback local", exc)
    cur = _read_shared(app_state)
    new = _reset_counter_in(cur, platform)
    _write_shared(app_state, new)
    return new


# ─── Compteurs & garde-fous ──────────────────────────────────────────


def _today_iso() -> str:
    return date.today().isoformat()


def daily_cap_remaining(app_state, platform: str) -> int:
    """Plafond restant aujourd'hui = cap - posts publiés aujourd'hui via AlphaCast.

    On interroge AlphaCast pour savoir combien de drafts ont été publiés
    aujourd'hui sur cette plateforme. Évite la divergence entre Jordan/Thomas
    qui auraient chacun un compteur local.
    """
    cap = int(app_state.get("publish_auto", "daily_cap", platform, default=0) or 0)
    if cap <= 0:
        return 0
    used = _published_today_via_alphacast(app_state, platform)
    return max(0, cap - used)


def _published_today_via_alphacast(app_state, platform: str) -> int:
    """Compte les drafts published aujourd'hui sur AlphaCast pour cette plateforme.

    Échec silencieux → renvoie 0 (n'empêche pas la génération si AlphaCast
    est temporairement HS).
    """
    url = (app_state.get("social", "reseaux_api_url", default="") or "").rstrip("/")
    token = app_state.get("social", "reseaux_jwt", default="") or ""
    if not url or not token:
        return 0
    try:
        r = requests.get(
            f"{url}/api/v1/generated-posts",
            headers={"Authorization": f"Bearer {token}"},
            params={"platform": platform, "status": "published", "limit": 50},
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        today_prefix = _today_iso()
        count = 0
        for p in items or []:
            ts = str(p.get("createdAt") or p.get("created_at") or "")
            # Tolère les timezone : on regarde si le préfixe ISO matche
            if ts.startswith(today_prefix):
                count += 1
                continue
            # Sinon, parse et compare en UTC
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.astimezone(timezone.utc).date() == date.today():
                    count += 1
            except Exception:
                pass
        return count
    except Exception as exc:
        logger.debug("daily_cap query AlphaCast échec : %s", exc)
        return 0


def counter_status(app_state, platform: str) -> tuple[int, int]:
    """Renvoie (count_actuel_partagé, seuil_local) pour l'affichage 'X/N envois'."""
    shared = _read_shared(app_state)
    count = int(shared.get("counters", {}).get(platform, 0) or 0)
    threshold = int(app_state.get("publish_auto", "cadence", platform, default=0) or 0)
    return count, threshold


def _reset_counter_in(state: dict, platform: str) -> dict:
    state = dict(state)
    counters = dict(state.get("counters") or {})
    counters[platform] = 0
    state["counters"] = counters
    return state


def _increment_counters_in(state: dict, n: int = 1) -> dict:
    state = dict(state)
    counters = dict(state.get("counters") or {})
    for p in PLATFORMS:
        counters[p] = int(counters.get(p, 0) or 0) + n
    state["counters"] = counters
    return state


# ─── Thème & angle ───────────────────────────────────────────────────


def pick_theme(app_state, *, override: str | None = None,
               consume: bool = True) -> tuple[str, str, str]:
    """Renvoie (key, label, brief). Consomme le next_theme s'il existe.

    Lit/écrit dans le state partagé : un thème sélectionné par Jordan
    s'applique aussi au prochain draft généré côté Thomas.
    """
    import random
    shared = _read_shared(app_state)
    next_t = (shared.get("next_theme") or "").strip()
    chosen_key = override or next_t or random.choice(theme_keys())

    if consume and next_t and override is None:
        new_state = dict(shared)
        new_state["next_theme"] = ""
        _write_shared(app_state, new_state)

    for k, label, brief in THEMES:
        if k == chosen_key:
            return k, label, brief
    k, label, brief = THEMES[0]
    return k, label, brief


def set_next_theme(app_state, key: str) -> None:
    """Sélection du thème pour le prochain draft (partagée Jordan/Thomas)."""
    shared = _read_shared(app_state)
    new_state = dict(shared)
    new_state["next_theme"] = key or ""
    _write_shared(app_state, new_state)


def get_next_theme(app_state) -> str:
    return (_read_shared(app_state).get("next_theme") or "")


def pick_angle(app_state, *, advance: bool = True) -> tuple[str, str]:
    """Tourne dans la liste des angles. Index partagé."""
    shared = _read_shared(app_state)
    idx = int(shared.get("angle_index", 0) or 0) % len(ANGLES)
    if advance:
        new_state = dict(shared)
        new_state["angle_index"] = (idx + 1) % len(ANGLES)
        _write_shared(app_state, new_state)
    return ANGLES[idx]


# ─── Construction du brief envoyé à AlphaCast ────────────────────────


def build_brief(*, theme_brief: str, angle_hint: str,
                metier: str, region: str) -> str:
    """Compose le `content` brut passé à /api/v1/generate côté Réseaux.

    AlphaCast a un voice profile et un slop detector — on lui laisse de la
    marge créative. On donne juste les ingrédients, pas un template figé.
    """
    metier = (metier or "").strip() or "un artisan"
    region = (region or "").strip()
    where = f" en {region}" if region else ""

    return (
        f"Contexte : je viens de proposer un site web à {metier}{where} "
        f"(prospect anonymisé, ne mentionne ni nom ni adresse précise).\n"
        f"\n"
        f"Thème du post : {theme_brief}.\n"
        f"\n"
        f"Angle d'attaque : {angle_hint}.\n"
        f"\n"
        f"Écris le post complet, prêt à publier. Pas de titre, pas de "
        f"métadonnées, juste le texte. Voix naturelle, pas de marketing-speak."
    )


# ─── 1er contact : détection ─────────────────────────────────────────


@dataclass
class FirstContact:
    prospect_id: str
    metier: str
    region: str


def detect_first_contacts(crm_before: dict[str, int], crm_after: list) -> list[FirstContact]:
    """Compare un snapshot AVANT (id → nb d'email_sent) à l'état APRÈS du CRM.

    Un 1er contact = prospect qui n'avait aucun email_sent avant et en a >= 1
    après.
    """
    out: list[FirstContact] = []
    for p in crm_after:
        pid = getattr(p, "id", None) or getattr(p, "uid", None) or str(id(p))
        before_count = crm_before.get(pid, 0)
        after_count = sum(1 for h in (p.history or [])
                          if h.get("kind") == "email_sent")
        if before_count == 0 and after_count >= 1:
            metier = (p.industry or "").strip() or "un artisan"
            region = _region_of(p)
            out.append(FirstContact(prospect_id=pid, metier=metier, region=region))
    return out


def snapshot_email_sent_counts() -> dict[str, int]:
    """Snapshot AVANT campagne : pour chaque prospect, son nombre d'email_sent.

    Renvoie {} si Triskell Core n'est pas dispo (mode dégradé).
    """
    try:
        from triskell_core.prospect.core.crm import CRM
    except Exception:
        return {}
    try:
        crm = CRM()
        out: dict[str, int] = {}
        for p in crm.all():
            pid = getattr(p, "id", None) or getattr(p, "uid", None) or str(id(p))
            out[pid] = sum(1 for h in (p.history or [])
                           if h.get("kind") == "email_sent")
        return out
    except Exception as exc:
        logger.warning("snapshot_email_sent_counts a échoué : %s", exc)
        return {}


def fresh_first_contacts(snapshot: dict[str, int]) -> list[FirstContact]:
    """Compare le snapshot avec l'état actuel du CRM."""
    try:
        from triskell_core.prospect.core.crm import CRM
        return detect_first_contacts(snapshot, CRM().all())
    except Exception as exc:
        logger.warning("fresh_first_contacts a échoué : %s", exc)
        return []


def _region_of(prospect) -> str:
    """Extrait une région lisible : ville, département, ou code postal."""
    city = (prospect.city or "").strip()
    if city:
        return city
    cp = (getattr(prospect, "postal_code", "") or "").strip()
    if cp and len(cp) >= 2:
        return f"département {cp[:2]}"
    return ""


# ─── Génération + publication ────────────────────────────────────────


def _settings_url_token(app_state) -> tuple[str, str]:
    url = (app_state.get("social", "reseaux_api_url",
                         default="http://localhost:3001") or "").rstrip("/")
    token = app_state.get("social", "reseaux_jwt", default="") or ""
    return url, token


def _generate_one(app_state, *, platform: str,
                  metier: str, region: str,
                  theme_override: str | None = None) -> tuple[bool, str]:
    """Génère (et publie si auto-publish ON) un draft pour `platform`.

    Renvoie (succès, message_court).
    """
    url, token = _settings_url_token(app_state)
    if not token:
        return False, "JWT manquant — Réglages > Service Réseaux."

    if daily_cap_remaining(app_state, platform) <= 0:
        return False, f"Plafond {platform} atteint pour aujourd'hui."

    theme_key, theme_label_, theme_brief = pick_theme(app_state, override=theme_override)
    angle_key, angle_hint = pick_angle(app_state)

    brief = build_brief(theme_brief=theme_brief, angle_hint=angle_hint,
                        metier=metier, region=region)

    auto_publish = bool(app_state.get("publish_auto", "auto_publish", platform,
                                      default=False))

    try:
        if auto_publish:
            alphacast.generate_and_publish(url, token, platform=platform,
                                            content=brief)
            msg = f"✓ {platform} publié ({theme_label_}/{angle_key})."
        else:
            draft = alphacast.generate_draft(url, token, platform=platform,
                                              content=brief)
            msg = (f"✓ {platform} : draft {draft.id[:8]} créé "
                   f"({theme_label_}/{angle_key}).")
        # Reset atomique du compteur partagé pour cette plateforme.
        _atomic_reset(app_state, platform)
        return True, msg
    except AlphaCastError as e:
        return False, f"✗ {platform} : {e}"
    except Exception as e:  # noqa: BLE001
        logger.exception("_generate_one")
        return False, f"✗ {platform} : {e}"


def trigger_for_platform(app_state, platform: str, *,
                         theme_override: str | None = None,
                         on_done: Callable[[bool, str], None] | None = None) -> None:
    """Déclenchement manuel (bouton 'Générer maintenant').

    Utilise le dernier prospect démarché s'il existe ; sinon, tente une
    génération sur thème pur (sans métier/région).
    """
    last = _read_shared(app_state).get("last_prospect") or {}
    metier = last.get("metier") or ""
    region = last.get("region") or ""

    def worker():
        ok, msg = _generate_one(app_state, platform=platform,
                                metier=metier, region=region,
                                theme_override=theme_override)
        if on_done:
            on_done(ok, msg)

    threading.Thread(target=worker, daemon=True).start()


def record_first_contact(app_state, *, contacts: list[FirstContact],
                         on_draft: Callable[[str, bool, str], None] | None = None) -> None:
    """À appeler APRÈS une vague de campagne, avec la liste des 1ers contacts.

    - Met à jour last_prospect avec le dernier contact (pour les drafts à venir).
    - Incrémente les compteurs des 3 plateformes de N (= len(contacts)).
    - Pour chaque plateforme dont le compteur a franchi le seuil ET qui a
      encore du quota daily_cap, génère un draft (en thread, async).

    `on_draft(platform, ok, message)` est rappelé après chaque tentative.
    """
    if not contacts:
        return
    if not bool(app_state.get("publish_auto", "enabled", default=True)):
        return

    last = contacts[-1]
    # Incrément atomique côté serveur — pas de race condition entre Jordan
    # et Thomas qui prospecteraient en parallèle.
    _atomic_increment(
        app_state, n=len(contacts),
        last_prospect={"metier": last.metier, "region": last.region},
    )

    to_fire: list[str] = []
    for platform in PLATFORMS:
        count, threshold = counter_status(app_state, platform)
        if threshold <= 0:
            continue
        if count < threshold:
            continue
        if daily_cap_remaining(app_state, platform) <= 0:
            continue
        to_fire.append(platform)

    if not to_fire:
        return

    def worker():
        for platform in to_fire:
            ok, msg = _generate_one(app_state, platform=platform,
                                    metier=last.metier, region=last.region)
            if on_draft:
                try:
                    on_draft(platform, ok, msg)
                except Exception:
                    logger.exception("on_draft callback")

    threading.Thread(target=worker, daemon=True).start()
