"""« L'œil » — robot serveur qui passe la base au crible VISUEL.

Tourne sur le serveur (Playwright + clés IA y sont déjà — cf. apercu_site).
À chaque cycle, prend un petit paquet de prospects à domaine propre AVEC
mail PAS encore jugés, les fait regarder par l'œil (site_vision) et tague :
  - « sûr » (confiance ≥ 90)   → site_a_refaire + redo_visuel
  - « à vérifier » (75-89)     → a_verifier_look (à confirmer par Jordan)
  - TOUS (même « ok »)         → oeil_vu  (pour ne JAMAIS rejuger)

Garde-fous :
  - interrupteur shared_settings « oeil_visuel » (défaut ON — Jordan a dit
    « on fonce » le 16/06/2026, après validation sur 50 sites) ;
  - cède au serveur (anti-double-traitement desktop, comme les autres robots) ;
  - petit paquet par cycle + pause entre sites (cadence Mistral) ;
  - quand toute la base est passée, le robot se met en veille longue et se
    réveille de temps en temps pour juger les NOUVEAUX prospects.

Voir site_vision.py (l'œil) et site_quality.py (signaux texte gratuits).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

CYCLE_INTERVAL_SECONDS = 180        # paquet toutes les 3 min quand il y a du travail
IDLE_INTERVAL_SECONDS = 30 * 60     # base finie → on checke les nouveaux toutes les 30 min
INITIAL_DELAY_SECONDS = 120         # laisse le serveur finir son boot
BATCH_PER_CYCLE = 15                # sites jugés par cycle (cadence Mistral)
PAUSE_BETWEEN = 2.0                 # s entre deux sites

SETTING_ENABLED = "oeil_visuel"
SEEN_TAG = "oeil_vu"

_worker_thread: threading.Thread | None = None
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}
_TOTALS = {"sure": 0, "verif": 0, "ok": 0, "judged": 0}


def _get_client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured  # noqa
    except ImportError:
        return None
    try:
        c = get_client()
    except Exception:
        return None
    return c if getattr(c, "is_authenticated", False) else None


def is_enabled() -> bool:
    """True si l'œil est activé (défaut : True — Jordan a validé le 16/06)."""
    c = _get_client()
    if c is None:
        return False
    try:
        return bool(c.get_shared_setting(SETTING_ENABLED, default=True))
    except Exception:
        return True


def set_enabled(value: bool) -> tuple[bool, str]:
    c = _get_client()
    if c is None:
        return False, "Base partagée non connectée."
    try:
        c.set_shared_setting(SETTING_ENABLED, bool(value))
        real = bool(c.get_shared_setting(SETTING_ENABLED, default=True))
        if real != bool(value):
            return False, "Le réglage n'a pas pu être enregistré."
        return True, "Mode mis à jour."
    except Exception as exc:
        return False, str(exc)


# Colonnes utiles à l'œil : pas besoin de l'historique, des brouillons, des
# sources… juste de quoi juger le site. On ne lit donc JAMAIS « * ».
_LIGHT_COLS = "id,name,website,emails,tags,notes,industry"

# Mémoire légère anti-egress : une fois toute la base jugée, on ne la relit
# plus en boucle. On garde le dernier total connu ; tant qu'aucun prospect
# n'a été ajouté, un simple comptage (qui ne transfère pas les lignes) suffit
# à savoir qu'il n'y a rien de neuf à juger.
_LAST_TOTAL: int | None = None
_BACKLOG_CLEARED: bool = False


def _judgeable(row: dict) -> bool:
    """Fiche à juger : domaine propre, avec mail, pas déjà vue ni flaguée."""
    from .site_quality import classify_url, REDO_TAG
    from .site_vision import VERIFY_CATEGORY
    tags = row.get("tags") or []
    if SEEN_TAG in tags or REDO_TAG in tags or VERIFY_CATEGORY in tags:
        return False
    if not row.get("emails"):
        return False
    if classify_url((row.get("website") or "")) != "normal":
        return False
    return True


def _count_prospects(c) -> int | None:
    """Nombre total de prospects, sans ramener les lignes (egress ~nul)."""
    try:
        res = (c.raw.table("prospects")
               .select("id", count="exact", head=True).execute())
        return int(res.count or 0)
    except Exception:
        return None


def _load_judgeable(c) -> list[dict]:
    """Lit léger (6 colonnes) tous les prospects et renvoie les fiches à
    juger. Pagine par 1000. Ne charge NI l'historique NI les brouillons
    (contrairement à crm.all()), donc beaucoup moins lourd."""
    out: list[dict] = []
    page = 0
    PAGE = 1000
    while True:
        res = (c.raw.table("prospects").select(_LIGHT_COLS)
               .order("id").range(page * PAGE, page * PAGE + PAGE - 1)
               .execute())
        batch = res.data or []
        for row in batch:
            if _judgeable(row):
                out.append(row)
        if len(batch) < PAGE:
            break
        page += 1
        if page > 200:   # garde-fou dur
            break
    return out


def _tag_and_save_row(c, row: dict, extra_tags, note) -> None:
    """Écrit tags/notes UNIQUEMENT sur cette fiche (update ciblé par id).
    Ne recharge JAMAIS toute la base — l'ancien crm.upsert le faisait à
    chaque fiche (des dizaines de relectures complètes par cycle)."""
    row_id = row.get("id")
    if not row_id:
        return
    tags = list(row.get("tags") or [])
    for t in extra_tags:
        if t not in tags:
            tags.append(t)
    patch: dict = {"tags": tags}
    if note:
        old = (row.get("notes") or "").strip()
        patch["notes"] = (old + "\n" + note).strip() if old else note
    try:
        patch["updated_by"] = c.user_id
    except Exception:
        pass
    try:
        c.raw.table("prospects").update(patch).eq("id", row_id).execute()
        row["tags"] = tags   # reflète localement
    except Exception as exc:
        logger.warning("oeil: tag %s échoué : %s", row.get("name", "?"), exc)


def tick() -> dict:
    """Un passage : juge un petit paquet de prospects pas encore vus.

    Anti-egress : si toute la base est déjà jugée et qu'aucun prospect n'a
    été ajouté depuis, on se contente d'un comptage (qui ne transfère pas
    les lignes) au lieu de retélécharger toute la base. Sinon on lit léger
    (6 colonnes) et on écrit en ciblé, fiche par fiche.
    """
    global _LAST_TOTAL, _BACKLOG_CLEARED
    from .site_quality import REDO_TAG
    from . import site_vision

    c = _get_client()
    if c is None:
        return {"skipped_reason": "supabase_indispo"}
    if not is_enabled():
        return {"skipped_reason": "disabled"}

    # Cède au serveur : si le serveur bat, le desktop ne fait rien (et
    # inversement le serveur ne défère pas à lui-même).
    try:
        from .server_presence import should_defer_to_server
        if should_defer_to_server(c):
            return {"skipped_reason": "server_active"}
    except Exception:
        pass

    # Garde-fou egress : base déjà nettoyée + aucun nouveau prospect → on ne
    # relit RIEN (le comptage ne transfère pas les lignes).
    total = _count_prospects(c)
    if (_BACKLOG_CLEARED and total is not None and _LAST_TOTAL is not None
            and total <= _LAST_TOTAL):
        return {"done": True, "remaining": 0, "skipped_reason": "rien_de_neuf"}

    targets = _load_judgeable(c)
    remaining = len(targets)
    if total is not None:
        _LAST_TOTAL = total
    if not targets:
        _BACKLOG_CLEARED = True
        return {"done": True, "remaining": 0}
    _BACKLOG_CLEARED = False

    keys = {}
    try:
        from . import shared_secrets
        keys = shared_secrets.get_ai_keys() or {}
    except Exception:
        pass

    out = {"judged": 0, "sure": 0, "verif": 0, "ok": 0, "ia_skipped": 0,
           "remaining": remaining}
    batch = targets[:BATCH_PER_CYCLE]
    for row in batch:
        if not is_enabled():
            out["stopped"] = "disabled_mid_cycle"
            break
        url = (row.get("website") or "").strip()
        v = site_vision.assess_visually(
            url, row.get("name") or "", row.get("industry") or "", keys)
        # Souci IA temporaire (quota / aucune IA) : on NE marque PAS vu, on
        # réessaiera au prochain cycle (ne pas perdre le site).
        if not v["ok"] and ("IA" in (v["error"] or "") or
                            "aucune" in (v["error"] or "")):
            out["ia_skipped"] += 1
            continue
        note = ""
        extra = [SEEN_TAG]
        if v["to_redo"]:
            extra += [REDO_TAG, site_vision.VISION_CATEGORY]
            note = (f"🔴 Site à refaire (look) — {v['style']} : "
                    f"{v['reasons'][0] if v['reasons'] else ''} "
                    f"[IA visuelle, confiance {v['confidence']}]")
            out["sure"] += 1
        elif v["to_verify"]:
            extra += [site_vision.VERIFY_CATEGORY]
            note = (f"🟠 À vérifier (look) — {v['style']} : "
                    f"{v['reasons'][0] if v['reasons'] else ''} "
                    f"[IA visuelle, confiance {v['confidence']}]")
            out["verif"] += 1
        else:
            out["ok"] += 1
        _tag_and_save_row(c, row, extra, note)
        out["judged"] += 1
        _TOTALS["judged"] += 1
        time.sleep(PAUSE_BETWEEN)
    _TOTALS["sure"] += out["sure"]
    _TOTALS["verif"] += out["verif"]
    _TOTALS["ok"] += out["ok"]
    out["remaining"] = max(0, remaining - out["judged"])
    if out["remaining"] <= 0:
        _BACKLOG_CLEARED = True
    return out


def start_worker(app_state=None) -> bool:
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return True

    def loop():
        global _LAST_RUN_AT, _LAST_RUN_RESULT
        logger.info("site_vision_worker: thread démarré")
        time.sleep(INITIAL_DELAY_SECONDS)
        while True:
            try:
                _LAST_RUN_RESULT = tick()
                _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
            except Exception as exc:
                logger.exception("site_vision_worker tick: %s", exc)
                _LAST_RUN_RESULT = {"error": str(exc)}
            # File vide / désactivé → veille longue ; sinon cadence normale.
            r = _LAST_RUN_RESULT or {}
            idle = (r.get("done") or r.get("skipped_reason") in
                    ("disabled", "server_active"))
            time.sleep(IDLE_INTERVAL_SECONDS if idle else CYCLE_INTERVAL_SECONDS)

    _worker_thread = threading.Thread(
        target=loop, name="site_vision_worker", daemon=True)
    _worker_thread.start()
    return True


def stop_worker() -> None:
    pass  # thread daemon ; l'interrupteur shared_settings suffit à le museler


def run_now() -> dict:
    return tick()


def get_status() -> dict:
    return {
        "running": _worker_thread is not None and _worker_thread.is_alive(),
        "enabled": is_enabled(),
        "last_run_at": _LAST_RUN_AT,
        "last_run_result": dict(_LAST_RUN_RESULT),
        "totals": dict(_TOTALS),
    }


__all__ = ["start_worker", "stop_worker", "run_now", "get_status",
           "is_enabled", "set_enabled", "tick"]
