"""Post-sale runner — génère J+30 cross-sell + J+90 NPS sur les clients livrés.

Conception alignée sur reply_responder / drip_runner :
- Worker thread daemon, cycle toutes les heures.
- Pour chaque client_projects.status='delivered' (ou 'closed') :
    - si paid_at + 30j atteint et cross_sell_sent_at NULL → génère un draft
      cross-sell (mail) → mode toggle (manual / delay_30m / instant)
    - si paid_at + 90j atteint et nps_sent_at NULL → génère un mail NPS
- Le mode est par étape, configurable via shared_settings 'post_sale'.
- Tous les drafts auto sont posés en prospect_drafts (vue Drafts à valider)
  pour rester cohérent avec les autres flows.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


STAGES = ("welcome_at_paid", "cross_sell_30d", "nps_90d")
# Follow-ups dynamiques issus du kit du produit : tag = "delivery_followup_<idx>"
DELIVERY_FOLLOWUP_PREFIX = "delivery_followup_"
MODES = ("manual", "delay_30m", "instant")
DELAY_SECONDS = {"manual": None, "delay_30m": 30 * 60, "instant": 0}

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "stages": {
        # Livraison initiale : déclenchée dès que paid_at est rempli (days=0)
        # Mode 'instant' par défaut → envoi auto au moment du paiement
        "welcome_at_paid": {"days": 0, "mode": "instant"},
        "cross_sell_30d":  {"days": 30, "mode": "manual"},
        "nps_90d":         {"days": 90, "mode": "manual"},
    },
    "templates": {
        "cross_sell_30d": (
            "Bonjour {client_name},\n\n"
            "1 mois après {product_name} : tout se passe comme prévu ?\n\n"
            "Si vous avez aimé, j'ai un autre outil qui pourrait "
            "vous intéresser : {next_product_name}.\n"
            "{next_product_link}\n\n"
            "Si une question, répondez à ce mail.\n\n"
            "{signature}"
        ),
        "nps_90d": (
            "Bonjour {client_name},\n\n"
            "3 mois après {product_name}, j'aimerais avoir votre avis. "
            "Sur une échelle de 0 à 10, quelle est la probabilité "
            "que vous recommandiez Triskell Studio à un confrère ?\n\n"
            "Une seule note + 1 phrase suffisent. Merci d'avance.\n\n"
            "{signature}"
        ),
    },
    "subject_templates": {
        "cross_sell_30d": "Un mois après {product_name}",
        "nps_90d": "3 mois après {product_name} — votre avis ?",
    },
    "next_product_default": {
        "name": "La Suite des Héros",
        "link": "https://productivite.triskell-studio.fr",
    },
}


CYCLE_INTERVAL_SECONDS = 60 * 60
INITIAL_DELAY_SECONDS = 120

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


def start_worker(app_state) -> bool:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _WORKER_STOP.clear()
        t = threading.Thread(target=_loop, args=(app_state,),
                              name="PostSaleRunnerWorker", daemon=True)
        t.start()
        _WORKER_THREAD = t
    return True


def stop_worker() -> None:
    _WORKER_STOP.set()


def get_status() -> dict:
    return {
        "running": _WORKER_THREAD is not None and _WORKER_THREAD.is_alive(),
        "last_run_at": _LAST_RUN_AT,
        "last_run_result": dict(_LAST_RUN_RESULT),
    }


def load_config(client) -> dict:
    raw = client.get_shared_setting("post_sale", {}) or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    return _deep_merge(_deep_copy(DEFAULT_CONFIG), raw)


def save_config(client, config: dict) -> None:
    client.set_shared_setting("post_sale", config)


def run_now(app_state) -> dict:
    return _do_one_cycle(app_state)


# ---------------------------------------------------------------------------
def _loop(app_state) -> None:
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        try:
            result = _do_one_cycle(app_state)
            try:
                from . import pulse_bus
                drafts = result.get("drafts", 0) if isinstance(result, dict) else 0
                sent = result.get("auto_sent", 0) if isinstance(result, dict) else 0
                err = result.get("error") if isinstance(result, dict) else None
                total = drafts + sent
                if total > 0:
                    parts = []
                    if drafts:
                        parts.append(f"{drafts} cross-sell prêt{'s' if drafts > 1 else ''}")
                    if sent:
                        parts.append(f"{sent} envoi{'s' if sent > 1 else ''}")
                    pulse_bus.report(
                        "postsale", "active",
                        text=" + ".join(parts),
                        relative_time="à l'instant",
                    )
                elif err and err != "supabase_unavailable":
                    pulse_bus.report("postsale", "error", error=str(err))
            except Exception:
                pass
        except Exception as exc:
            logger.warning("PostSale cycle: %s", exc)
            try:
                from . import pulse_bus
                pulse_bus.report("postsale", "error", error=str(exc))
            except Exception:
                pass
        for _ in range(CYCLE_INTERVAL_SECONDS // 5):
            if _WORKER_STOP.is_set():
                return
            time.sleep(5)


def _do_one_cycle(app_state) -> dict:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    counters = {"scanned": 0, "drafts": 0, "auto_sent": 0,
                "skipped": 0, "errors": 0}

    client = _get_client()
    if client is None:
        counters["error"] = "supabase_unavailable"
        _set_run(counters)
        return counters

    config = load_config(client)
    if not config.get("enabled", True):
        _set_run(counters)
        return counters

    sb = client.raw
    try:
        # On scanne les projets payés (paid_at non null), peu importe leur statut.
        # Pour la livraison initiale on cible justement les nouveaux paiements.
        res = (sb.table("client_projects").select("*")
               .not_.is_("paid_at", "null")
               .limit(1000).execute())
        projects = res.data or []
    except Exception:
        # Fallback : ancienne logique (statuts delivered/closed) si la requête
        # avec not_.is_ n'est pas supportée par la version du client.
        try:
            res = (sb.table("client_projects").select("*")
                   .in_("status", ["delivered", "closed", "paid"])
                   .limit(1000).execute())
            projects = res.data or []
        except Exception as exc:
            counters["error"] = f"fetch: {exc}"
            _set_run(counters)
            return counters

    # Charge les déjà-envoyés depuis email_history (un seul fetch global,
    # plutôt que 1 par projet) — perf + cohérence
    sent_stages = _load_sent_stages(sb, [p.get("id") for p in projects])

    # Verrou doux : skip les projets actuellement traités par un autre user
    from . import task_lock
    me_uid = client.user_id or ""

    now = datetime.now()
    for proj in projects:
        counters["scanned"] += 1
        # Si quelqu'un d'autre a verrouillé ce projet → SKIP
        if task_lock.is_locked_by_other(client, "client_projects",
                                          proj.get("id"), user_id=me_uid):
            counters["skipped"] += 1
            continue
        # On pose le verrou pour éviter qu'un autre worker le traite
        # pendant qu'on est dessus (TTL 5 min)
        if not task_lock.try_acquire_lock(client, "client_projects",
                                            proj.get("id"), user_id=me_uid):
            counters["skipped"] += 1
            continue
        try:
            paid_at = _parse_dt(proj.get("paid_at"))
            if paid_at is None:
                counters["skipped"] += 1
                continue

            # 1) Stages fixes (welcome / cross-sell / nps)
            for stage in STAGES:
                stage_cfg = (config.get("stages") or {}).get(stage) or {}
                days = int(stage_cfg.get("days") or 0)
                target = paid_at + timedelta(days=days)
                if now < target:
                    continue
                if _already_done(proj, stage, sent_stages):
                    continue
                drafted = _create_post_sale_draft(
                    client, app_state, proj, stage, config)
                _tally(counters, drafted)

            # 2) Stages dynamiques : follow-ups du kit produit
            product_key = proj.get("product_key") or ""
            if product_key:
                try:
                    from . import delivery_kits
                    fus = delivery_kits.list_follow_ups(
                        product_key, client=client)
                except Exception:
                    fus = []
                for idx, fu in enumerate(fus):
                    days = int(fu.get("days") or 0)
                    if days <= 0:
                        continue
                    target = paid_at + timedelta(days=days)
                    if now < target:
                        continue
                    stage = f"{DELIVERY_FOLLOWUP_PREFIX}{idx}"
                    if _already_done(proj, stage, sent_stages):
                        continue
                    drafted = _create_post_sale_draft(
                        client, app_state, proj, stage, config,
                        kit_follow_up_index=idx)
                    _tally(counters, drafted)

        except Exception as exc:
            logger.warning("post_sale project %s: %s",
                            proj.get("id"), exc)
            counters["errors"] += 1
        finally:
            # Libère le verrou (succès ou échec)
            task_lock.release_lock(client, "client_projects",
                                    proj.get("id"), user_id=me_uid)

    _set_run(counters)
    return counters


def _tally(counters: dict, drafted: dict) -> None:
    if drafted.get("auto_sent"):
        counters["auto_sent"] += 1
    elif drafted.get("created"):
        counters["drafts"] += 1
    elif drafted.get("error"):
        counters["errors"] += 1


def _load_sent_stages(sb, project_ids: list) -> dict[str, set[str]]:
    """Renvoie {client_project_id → set(post_sale_stage envoyés)} depuis
    email_history, pour éviter de re-envoyer la même stage."""
    out: dict[str, set[str]] = {}
    pids = [p for p in project_ids if p]
    if not pids:
        return out
    try:
        # On filtre sur kind='email_sent' avec extra contenant
        # post_sale_stage. Pas de filtre JSONB côté Postgres = on filtre
        # en mémoire, plus simple et compatible.
        res = (sb.table("email_history").select("extra")
               .eq("kind", "email_sent")
               .limit(5000).execute())
        rows = res.data or []
        import json as _json
        for r in rows:
            extra = r.get("extra") or {}
            if isinstance(extra, str):
                try: extra = _json.loads(extra)
                except Exception: continue
            cpid = extra.get("client_project_id")
            stage = extra.get("post_sale_stage")
            if cpid and stage:
                out.setdefault(str(cpid), set()).add(str(stage))
    except Exception as exc:
        logger.debug("_load_sent_stages: %s", exc)
    return out


def _already_done(proj: dict, stage: str,
                  sent_stages: dict[str, set[str]] | None = None) -> bool:
    """Vrai si la stage a déjà été envoyée pour ce projet.

    Vérifie en priorité les colonnes legacy (cross_sell_sent_at, nps_sent_at)
    puis la trace dans email_history.extra.post_sale_stage."""
    if stage == "cross_sell_30d" and proj.get("cross_sell_sent_at"):
        return True
    if stage == "nps_90d" and proj.get("nps_sent_at"):
        return True
    if sent_stages is not None:
        cpid = str(proj.get("id") or "")
        if cpid and stage in sent_stages.get(cpid, set()):
            return True
    return False


def _create_post_sale_draft(client, app_state, proj: dict,
                              stage: str, config: dict,
                              kit_follow_up_index: int | None = None) -> dict:
    out = {"created": False, "auto_sent": False, "error": ""}
    sb = client.raw

    # Stages dynamiques (delivery_followup_<idx>) : pas de config.stages
    # dédiée, on hérite du mode global "delivery_followup_default" sinon manual
    if stage.startswith(DELIVERY_FOLLOWUP_PREFIX):
        stage_cfg = (config.get("stages") or {}).get(
            "delivery_followup_default", {"mode": "manual"})
    else:
        stage_cfg = (config.get("stages") or {}).get(stage) or {}
    mode = stage_cfg.get("mode", "manual")

    client_name = (proj.get("client_name") or "").strip() or "vous"
    client_email = (proj.get("client_email") or "").strip()
    if not client_email:
        out["error"] = "no_email"
        return out
    product_key = proj.get("product_key") or ""
    product_name = (proj.get("product_name") or product_key or "votre projet")
    signature = config.get("signature") or app_state.get(
        "outreach", "from_name", default="") or ""

    # ---- Routage du contenu selon la stage ----
    subject = ""
    body = ""

    if stage == "welcome_at_paid":
        # Mail de bienvenue : utilise le kit du produit
        try:
            from . import delivery_kits
            rendered = delivery_kits.render_welcome(
                product_key,
                client_name=client_name,
                signature=signature,
                client=client,
            )
            subject = rendered.get("subject", "")
            body    = rendered.get("body", "")
        except Exception as exc:
            out["error"] = f"render_welcome: {exc}"
            return out

    elif stage.startswith(DELIVERY_FOLLOWUP_PREFIX) and kit_follow_up_index is not None:
        # Suivi spécifique au kit du produit
        try:
            from . import delivery_kits
            rendered = delivery_kits.render_follow_up(
                product_key, kit_follow_up_index,
                client_name=client_name, signature=signature, client=client,
            )
            if not rendered:
                out["error"] = "kit_followup_missing"
                return out
            subject = rendered.get("subject", "")
            body    = rendered.get("body", "")
        except Exception as exc:
            out["error"] = f"render_followup: {exc}"
            return out

    else:
        # Stages legacy (cross_sell_30d, nps_90d) : templates dans la config
        next_default = config.get("next_product_default") or {}
        body_tmpl = (config.get("templates") or {}).get(stage, "")
        subj_tmpl = (config.get("subject_templates") or {}).get(stage, "")
        body = body_tmpl.format(
            client_name=client_name,
            product_name=product_name,
            next_product_name=next_default.get("name", "un autre outil Triskell"),
            next_product_link=next_default.get("link", ""),
            signature=signature,
        )
        subject = subj_tmpl.format(product_name=product_name)

    if not subject and not body:
        out["error"] = "empty_template"
        return out

    # On crée un draft dans prospect_drafts pour cohérence avec la vue
    # "Drafts à valider". prospect_id peut être null (client_projects ne
    # l'exige pas), dans ce cas on log juste l'envoi en email_history sans
    # prospect lié.
    prospect_id = proj.get("prospect_id")

    if prospect_id:
        try:
            sb.table("prospect_drafts").insert({
                "prospect_id": prospect_id,
                "subject": subject[:200],
                "body": body[:8000],
                "kind": stage,
                "status": "pending",
                "created_by": client.user_id,
            }).execute()
            out["created"] = True
        except Exception as exc:
            out["error"] = f"insert_draft: {exc}"
            return out

    # Envoi auto si mode != manual
    if mode != "manual":
        smtp_cfg = _resolve_smtp_config(app_state, client)
        if not smtp_cfg:
            return out
        try:
            from triskell_core.prospect.outreach.smtp_sender import send_email
            msg_id = send_email(smtp_cfg, to=client_email,
                                 subject=subject, body=body)
            now_iso = datetime.now().isoformat(timespec="seconds")
            # Marque la stage envoyée sur le projet (colonnes legacy
            # uniquement pour les stages historiques). Les nouvelles stages
            # (welcome_at_paid, delivery_followup_*) sont tracées via
            # email_history.extra.post_sale_stage (cf. _load_sent_stages).
            stage_field = None
            if stage == "cross_sell_30d":
                stage_field = "cross_sell_sent_at"
            elif stage == "nps_90d":
                stage_field = "nps_sent_at"
            if stage_field:
                try:
                    sb.table("client_projects").update({
                        stage_field: now_iso,
                        "updated_by": client.user_id,
                    }).eq("id", proj.get("id")).execute()
                except Exception:
                    pass  # colonne legacy peut ne plus exister
            # Log envoi
            try:
                sb.table("email_history").insert({
                    "prospect_id": prospect_id,
                    "kind": "email_sent",
                    "ts": now_iso,
                    "subject": subject[:200],
                    "body": body[:2000],
                    "message_id": msg_id,
                    "extra": {"post_sale_stage": stage,
                                "client_project_id": proj.get("id")},
                    "created_by": client.user_id,
                }).execute()
            except Exception:
                pass
            out["auto_sent"] = True
        except Exception as exc:
            out["error"] = f"smtp: {exc}"

    return out


# ---------------------------------------------------------------------------
def _get_client():
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
    return c


def _resolve_smtp_config(app_state, client) -> Optional[dict]:
    """Délègue à shared_secrets (source de vérité partagée)."""
    from . import shared_secrets
    return shared_secrets.resolve_smtp_for_send(client=client, app_state=app_state)


def _parse_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            # supporte "2026-05-06T10:00:00" et "2026-05-06T10:00:00+00:00"
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception:
            try:
                return datetime.strptime(v[:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                return None
    return None


def _set_run(counters: dict) -> None:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
    _LAST_RUN_RESULT = counters


def _deep_copy(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: _deep_copy(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_deep_copy(x) for x in d]
    return d


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
