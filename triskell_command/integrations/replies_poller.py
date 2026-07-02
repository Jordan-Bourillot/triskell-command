"""Poller IMAP des réponses prospects + classification IA + persistance Supabase.

Conception :
- Tourne en thread daemon, poll IMAP toutes les 5 min (configurable).
- Pour chaque mail nouveau :
    1. Match au prospect (par Message-ID référencé OU par From)
    2. Classification IA en 5 catégories : interested / not_now / no /
       unsubscribe / unknown
    3. Écrit un row email_history avec kind='reply_received' + extra =
       {classification, body_excerpt, from, in_reply_to, handled: false}
    4. Met à jour prospects.status → 'replied' (si pas déjà won/lost)
- Idempotent : last_uid IMAP stocké dans shared_settings ("imap_last_uid").
- Pas de Supabase configuré ou pas de config IMAP → no-op silencieux.

Pourquoi un poller dédié à Triskell Command et pas l'imap_listener de Triskell
Core : Core écrit dans le CRM JSON local et n'a pas de classification IA.
Ici on veut Supabase + classification dès la 1re détection pour que la vue
"Réponses" soit utile sans pré-traitement humain.
"""

from __future__ import annotations

import email
import imaplib
import json
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any, Optional

from .multi_tenant import with_workspace

logger = logging.getLogger(__name__)


# Catégories de classification — alignées avec ce que l'UI attendra
CATEGORIES = ("interested", "not_now", "no", "unsubscribe", "unknown")

POLL_INTERVAL_SECONDS = 300  # 5 min
INITIAL_DELAY_SECONDS = 30   # laisse l'app finir son boot


_POLLER_THREAD: Optional[threading.Thread] = None
_POLLER_STOP = threading.Event()
_POLLER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}
# Poll manuel (bouton « Vérifier maintenant ») : lancé en arrière-plan pour ne
# JAMAIS faire attendre l'appel HTTP (le tour des comptes prend ~45 s → la
# connexion du navigateur couperait avant la fin). _POLL_GUARD sérialise les
# cycles (auto + manuel) : jamais deux scans des mêmes boîtes en parallèle.
_MANUAL_THREAD: Optional[threading.Thread] = None
_POLL_GUARD = threading.Lock()
# Fix 3 — compteur d'erreurs consecutives par compte pour declencher une
# alerte si le polling echoue plusieurs cycles d'affilee
_CONSECUTIVE_ERRORS: dict[str, int] = {}
_LAST_SUCCESSFUL_POLL: dict[str, str] = {}
_LAST_ERROR_PER_ACCOUNT: dict[str, str] = {}
HEALTH_ALERT_THRESHOLD = 2  # >= N cycles consecutifs en erreur => alerte

# Index prospects (email->id, msgid->id) mis en cache au niveau module.
# Avant : reconstruit a CHAQUE cycle (toutes les 5 min) en relisant TOUTE la
# base prospects + tout l'historique des envois -> des Go d'egress Supabase
# par mois pour rien (la plupart des cycles n'ont aucun nouveau mail).
# Maintenant : construit A LA DEMANDE (seulement si un cycle a du courrier)
# et reutilise pendant _INDEX_TTL_SEC.
_INDEX_CACHE: dict = {"at": 0.0, "msgid": None, "from": None}
_INDEX_TTL_SEC = 600  # 10 min


def start_poller(app_state) -> bool:
    """Lance le poller en background. Idempotent."""
    global _POLLER_THREAD
    with _POLLER_LOCK:
        if _POLLER_THREAD is not None and _POLLER_THREAD.is_alive():
            return True
        _POLLER_STOP.clear()
        t = threading.Thread(
            target=_poller_loop, args=(app_state,),
            name="RepliesPoller", daemon=True,
        )
        t.start()
        _POLLER_THREAD = t
    return True


def stop_poller() -> None:
    _POLLER_STOP.set()


def get_status() -> dict:
    # Fix 3 : expose la sante du polling (erreurs consecutives par compte)
    health: dict = {}
    alerts: list = []
    for aid, count in _CONSECUTIVE_ERRORS.items():
        health[aid] = {
            "consecutive_errors": count,
            "last_success_at": _LAST_SUCCESSFUL_POLL.get(aid, ""),
            "last_error": _LAST_ERROR_PER_ACCOUNT.get(aid, ""),
            "alert": count >= HEALTH_ALERT_THRESHOLD,
        }
        if count >= HEALTH_ALERT_THRESHOLD:
            alerts.append({
                "account_id": aid,
                "consecutive_errors": count,
                "last_error": _LAST_ERROR_PER_ACCOUNT.get(aid, ""),
                "last_success_at": _LAST_SUCCESSFUL_POLL.get(aid, ""),
            })
    return {
        "running": _POLLER_THREAD is not None and _POLLER_THREAD.is_alive(),
        "last_run_at": _LAST_RUN_AT,
        "last_run_result": dict(_LAST_RUN_RESULT),
        "health": health,
        "alerts": alerts,
    }


def poll_now(app_state) -> dict:
    """Force un cycle de poll synchrone et renvoie le résultat."""
    return _do_one_poll(app_state)


def poll_now_async(app_state) -> dict:
    """Lance un cycle de poll en arrière-plan et REND LA MAIN tout de suite.

    Le bouton « Vérifier maintenant » fait le tour de tous les comptes IMAP
    (~45 s). Attendre la fin côté HTTP garantissait une coupure (timeout
    navigateur/proxy) → le bouton affichait une erreur alors que le scan se
    terminait. On démarre donc le tour dans un thread ; l'appelant lit le
    résultat ensuite via get_status() (last_run_at / last_run_result),
    exactement comme pour le poll automatique.
    """
    global _MANUAL_THREAD
    if _MANUAL_THREAD is not None and _MANUAL_THREAD.is_alive():
        return {"ok": True, "started": False, "already_running": True,
                "since": _LAST_RUN_AT}

    def _run() -> None:
        try:
            _do_one_poll(app_state)
        except Exception as exc:
            logger.warning("poll manuel: %s", exc)

    t = threading.Thread(target=_run, name="replies-poll-manual", daemon=True)
    _MANUAL_THREAD = t
    t.start()
    return {"ok": True, "started": True, "since": _LAST_RUN_AT}


# ---------------------------------------------------------------------------
# Boucle interne
# ---------------------------------------------------------------------------
def _poller_loop(app_state) -> None:
    # Délai initial pour ne pas bloquer le boot UI
    if _POLLER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _POLLER_STOP.is_set():
        try:
            result = _do_one_poll(app_state)
            # Pulse worker : on ne reporte que si quelque chose de notable
            # (nouvelle réponse écrite ou erreur). Pas de pulse si scan vide.
            try:
                from . import pulse_bus
                written = result.get("written", 0) if isinstance(result, dict) else 0
                err = result.get("error") if isinstance(result, dict) else None
                if written > 0:
                    pulse_bus.report(
                        "replies", "active",
                        text=(f"{written} nouvelle réponse"
                              if written == 1
                              else f"{written} nouvelles réponses"),
                        relative_time="à l'instant",
                    )
                elif err:
                    pulse_bus.report(
                        "replies", "error",
                        error=str(err),
                    )
            except Exception:
                pass
        except Exception as exc:
            logger.warning("RepliesPoller cycle: %s", exc)
            try:
                from . import pulse_bus
                pulse_bus.report("replies", "error", error=str(exc))
            except Exception:
                pass
        # Sleep par tranches de 5s pour permettre stop rapide
        for _ in range(POLL_INTERVAL_SECONDS // 5):
            if _POLLER_STOP.is_set():
                return
            time.sleep(5)


def _do_one_poll(app_state) -> dict:
    """Un cycle de poll, SÉRIALISÉ : si un scan (auto ou manuel) tourne déjà,
    on rend la main sans rien faire — deux lecteurs en parallèle se
    disputeraient le curseur last_uid de chaque compte."""
    if not _POLL_GUARD.acquire(blocking=False):
        return {"scanned": 0, "matched": 0, "classified": 0, "written": 0,
                "errors": 0, "skipped": 0, "accounts_scanned": 0,
                "per_account": {}, "skipped_reason": "poll_already_running"}
    try:
        return _do_one_poll_inner(app_state)
    finally:
        _POLL_GUARD.release()


def _do_one_poll_inner(app_state) -> dict:
    """Un cycle complet : IMAP fetch → classify → write Supabase.

    Depuis la phase 2 multi-comptes : itère sur tous les comptes mail
    configurés (compte principal + comptes secondaires via shared_secrets).
    Chaque compte a son propre last_uid pour ne pas mélanger les UIDs.
    """
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    counters = {"scanned": 0, "matched": 0, "classified": 0,
                "written": 0, "errors": 0, "skipped": 0, "notified": 0,
                "warmup": 0, "accounts_scanned": 0, "per_account": {}}

    client = _get_supabase_client()
    if client is None:
        counters["error"] = "supabase_unavailable"
        _LAST_RUN_RESULT = counters
        _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
        return counters

    # Anti-double-traitement : deux lecteurs IMAP en parallèle (serveur +
    # desktop) se disputent le curseur last_uid → on s'efface si le serveur
    # bat encore. Relais automatique si le serveur meurt (>15 min).
    from .server_presence import should_defer_to_server
    if should_defer_to_server(client):
        counters["skipped_reason"] = "server_active"
        _LAST_RUN_RESULT = counters
        _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
        return counters

    accounts = _list_imap_accounts_to_scan(app_state, client)
    if not accounts:
        counters["error"] = "no_imap_account_configured"
        _LAST_RUN_RESULT = counters
        _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
        return counters

    # AI settings — commun à tous les comptes. L'index prospects, lui, n'est
    # PLUS construit ici : il l'est à la demande dans _poll_one_account, et
    # seulement si un compte a effectivement du courrier à traiter (sinon on
    # relisait toute la base pour rien à chaque cycle, à vide).
    ai_settings = _resolve_ai_settings(app_state, client)
    # Réglages de tri/alerte des mails entrants (analyse des inconnus +
    # notifications téléphone). Lus une seule fois par cycle. Ne bloque
    # jamais la lecture des mails — repli sur les valeurs par défaut.
    from . import inbox_triage
    try:
        triage_cfg = inbox_triage.load_config(client)
    except Exception:
        triage_cfg = dict(inbox_triage.DEFAULT_CONFIG)

    for acc in accounts:
        aid = acc.get("id", "primary")
        try:
            sub = _poll_one_account(
                client, app_state, acc, ai_settings, triage_cfg,
            )
        except Exception as exc:
            logger.warning("poll account %s failed: %s", aid, exc)
            sub = {"error": str(exc)}
        # --- Fix 3 : suivi sante par compte ---
        sub_err = sub.get("error") if isinstance(sub, dict) else None
        if sub_err:
            _CONSECUTIVE_ERRORS[aid] = _CONSECUTIVE_ERRORS.get(aid, 0) + 1
            _LAST_ERROR_PER_ACCOUNT[aid] = str(sub_err)[:300]
            if _CONSECUTIVE_ERRORS[aid] == HEALTH_ALERT_THRESHOLD:
                # Premiere fois qu'on franchit le seuil : pulse + persiste
                try:
                    from . import pulse_bus
                    pulse_bus.report(
                        "replies", "error",
                        error=(f"IMAP {aid}: {_CONSECUTIVE_ERRORS[aid]} erreurs"
                               f" consecutives. Verifier les identifiants."),
                    )
                except Exception:
                    pass
        else:
            _CONSECUTIVE_ERRORS[aid] = 0
            _LAST_SUCCESSFUL_POLL[aid] = datetime.now().isoformat(timespec="seconds")
            _LAST_ERROR_PER_ACCOUNT.pop(aid, None)
        counters["per_account"][aid] = sub
        counters["accounts_scanned"] += 1
        for k in ("scanned", "matched", "classified", "written", "errors",
                  "skipped", "notified", "warmup"):
            counters[k] = counters.get(k, 0) + sub.get(k, 0)

    _LAST_RUN_RESULT = counters
    _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
    return counters


def _log_inbox_mail(client, account_id: str, *, from_addr: str, subject: str,
                     body: str, in_reply_to: str, body_html: str = "",
                     extra_fields: Optional[dict] = None) -> str:
    """Loggue dans email_history un mail entrant qui n'est pas une réponse
    prospect (kind='inbox_received'). Anti-doublon : si un mail avec même
    sujet + même from + même in_reply_to existe déjà sur ce compte, on saute.

    Renvoie l'id de la ligne créée, ou '' si doublon écarté / échec d'insert.
    extra_fields (optionnel) est fusionné dans extra — sert à y déposer le
    résultat du tri IA ('triage') du mail d'inconnu.
    """
    sb = client.raw
    try:
        # Anti-doublon léger — le in_reply_to fait partie de la clé : les DSN
        # (rebonds) partagent tous le même sujet générique et le même
        # mailer-daemon, seul le fil référencé les distingue (4 rebonds de
        # juin avalés par un doublon de mai avant ce critère).
        check = (sb.table("email_history")
                 .select("id").eq("kind", "inbox_received")
                 .eq("subject", subject[:200])
                 .eq("extra->>account_id", account_id)
                 .eq("extra->>from", from_addr)
                 .eq("extra->>in_reply_to", in_reply_to or "")
                 .limit(1).execute())
        if check.data:
            return ""
    except Exception:
        pass  # si le check fail, on continue, l'insert peut échouer mais best-effort
    extra = {
        "account_id": account_id,
        "from": from_addr,
        "in_reply_to": in_reply_to,
        "body_excerpt": (body or "")[:1500],
        "body_html": (body_html or "")[:80_000],
    }
    if extra_fields:
        extra.update(extra_fields)
    row = {
        "kind": "inbox_received",
        "ts": datetime.now().isoformat(timespec="seconds"),
        "subject": subject[:200],
        "body": "",
        "extra": extra,
        "created_by": client.user_id,
    }
    try:
        ins = sb.table("email_history").insert(
            with_workspace(client, row)).execute()
        return ((ins.data or [{}])[0].get("id") or "")
    except Exception as exc:
        logger.warning("log inbox mail insert KO: %s", exc)
        return ""


def _notify_inbox_attention(client, history_row_id: str, triage_cfg: dict, *,
                             title: str, body: str, priority: str,
                             view: str, tag_group: str) -> bool:
    """Envoie l'alerte téléphone pour un mail qui mérite l'attention, puis
    marque la fiche (extra.notified_at) pour ne JAMAIS alerter deux fois.

    Relit l'extra à jour avant d'écrire (pour ne pas écraser le brouillon de
    réponse déposé entre-temps). Renvoie True si une alerte a été délivrée.
    Ne lève jamais.
    """
    if not history_row_id:
        return False
    from . import inbox_triage
    sb = client.raw
    try:
        res = (sb.table("email_history").select("extra")
               .eq("id", history_row_id).limit(1).execute())
        extra = (res.data or [{}])[0].get("extra") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
    except Exception:
        extra = {}
    if extra.get("notified_at"):
        return False   # déjà alerté pour ce mail

    sent = 0
    try:
        from ..web.push import send_push
        target = (triage_cfg.get("notify_user_id") or "").strip()
        user_id = target if (target and target.lower() != "all") else None
        result = send_push(
            title, body,
            user_id=user_id,
            tag_group=tag_group,
            url=f"/?view={view}",
            priority=inbox_triage.push_priority(priority),
            extra_data={"history_id": history_row_id, "view": view},
        ) or {}
        sent = int(result.get("sent") or 0)
    except Exception as exc:
        logger.debug("send_push KO: %s", exc)

    # On marque la fiche quel que soit le résultat d'envoi : si le téléphone
    # n'était pas joignable, on ne ré-alerte pas en boucle au cycle suivant.
    try:
        extra["notified_at"] = datetime.now().isoformat(timespec="seconds")
        extra["notify_sent"] = sent
        sb.table("email_history").update({"extra": extra}).eq(
            "id", history_row_id).execute()
    except Exception as exc:
        logger.debug("mark notified KO: %s", exc)

    return sent > 0


def _list_imap_accounts_to_scan(app_state, client) -> list[dict]:
    """Renvoie tous les comptes IMAP à scanner.

    Format renvoyé : [{id, host, port, user, password, last_uid_key}, ...].
    Le compte principal a id='primary' et utilise la clé legacy 'imap_last_uid'
    (pour ne pas perdre l'historique des UIDs déjà scannés). Les comptes
    secondaires utilisent 'imap_last_uid_{id}'.
    """
    out: list[dict] = []

    # 1) Compte principal — réutilise _resolve_imap_config (compat)
    primary = _resolve_imap_config(app_state, client)
    if primary:
        out.append({
            "id": "primary",
            "host": primary["host"], "port": primary["port"],
            "user": primary["user"], "password": primary["password"],
            "last_uid_key": "imap_last_uid",   # legacy
        })

    # 2) Comptes secondaires depuis shared_secrets
    try:
        from . import shared_secrets
        for a in shared_secrets.list_secondary_accounts(client=client):
            host = (a.get("imap_host") or "").strip()
            user = (a.get("imap_user") or "").strip()
            pwd  = a.get("imap_password") or ""
            if not (host and user and pwd):
                continue   # pas encore complètement configuré
            aid = a.get("id")
            if not aid:
                continue
            out.append({
                "id": aid,
                "host": host, "port": int(a.get("imap_port") or 993),
                "user": user, "password": pwd,
                "last_uid_key": f"imap_last_uid_{aid}",
            })
    except Exception as exc:
        logger.warning("list secondary mail accounts: %s", exc)

    return out


def _poll_one_account(client, app_state, account: dict, ai_settings: dict,
                       triage_cfg: dict | None = None) -> dict:
    """Scanne UNE boîte IMAP. Renvoie les compteurs locaux.

    Ne lève pas — toute erreur est capturée et renvoyée dans counters['error'].
    Le account_id est tracé dans email_history.extra.account_id pour le filtre
    par compte côté UI.
    """
    from . import inbox_triage
    if triage_cfg is None:
        triage_cfg = dict(inbox_triage.DEFAULT_CONFIG)
    counters = {"scanned": 0, "matched": 0, "classified": 0,
                "written": 0, "errors": 0, "skipped": 0, "notified": 0,
                "warmup": 0}
    last_uid_key = account["last_uid_key"]
    account_id = account.get("id", "primary")
    last_uid = int(client.get_shared_setting(last_uid_key, 0) or 0)

    try:
        M = imaplib.IMAP4_SSL(account["host"], account["port"])
        try:
            M.login(account["user"], account["password"])
            M.select("INBOX", readonly=True)

            criteria = f"UID {last_uid + 1}:*" if last_uid else "ALL"
            typ, data = M.uid("search", None, criteria)
            if typ != "OK":
                counters["error"] = f"imap_search_{typ}"
                return counters
            uids = data[0].split() if data and data[0] else []
            # Quirk IMAP : pour une plage "N:*" sans nouveau mail, beaucoup de
            # serveurs renvoient quand meme le DERNIER UID existant (le "*"
            # accroche le plus haut). On ecarte donc tout UID deja traite
            # (<= last_uid) : sinon on refait un fetch ET on reconstruit
            # l'index prospects (toute la base) a CHAQUE cycle pour un mail
            # deja vu. C'est la cause n1 de l'egress du poller.
            if last_uid:
                uids = [u for u in uids if int(u) > last_uid]
            if not uids:
                return counters

            # Il y a du VRAI courrier nouveau -> on a (enfin) besoin de
            # l'index prospects. Construit a la demande + mis en cache (voir
            # _get_prospect_index) pour ne plus relire toute la base a vide.
            msgid_to_prospect, from_to_prospect = _get_prospect_index(client)

            max_uid_seen = last_uid
            # Premier UID dont le traitement a échoué : le curseur ne doit
            # jamais le dépasser, sinon ce mail ne sera plus jamais relu
            # (4 rebonds de juin perdus comme ça).
            first_error_uid = 0

            for uid in uids:
                uid_int = int(uid)
                max_uid_seen = max(max_uid_seen, uid_int)
                counters["scanned"] += 1
                try:
                    typ, msg_data = M.uid("fetch", uid, "(BODY.PEEK[])")
                    if typ != "OK" or not msg_data:
                        counters["errors"] += 1
                        if not first_error_uid:
                            first_error_uid = uid_int
                        continue
                    headers, body, body_html = _parse_fetch_response(msg_data)
                    in_reply_to = _extract_msg_id(headers.get("In-Reply-To", ""))
                    references = headers.get("References", "") or ""
                    from_addr = _from_address(headers.get("From", ""))
                    subject = (headers.get("Subject") or "").strip()

                    # --- Mails de CHAUFFE (warm-up) ---
                    # Ce sont NOS propres mails, envoyés entre nos boîtes pour
                    # bâtir la réputation d'envoi. Ils portent l'en-tête caché
                    # X-TS-Warmup. On les ignore TOTALEMENT : ni prospect, ni
                    # tri IA, ni alerte téléphone, ni log — sinon ils sont vus
                    # comme des « mails d'inconnus à regarder » (faux positif).
                    # warmup_tick.py les lit et les nettoie de son côté.
                    if headers.get("X-TS-Warmup"):
                        counters["warmup"] += 1
                        continue

                    # --- Fix 2 : detection precoce des bounces (DSN) ---
                    # Un avis de non-delivrance arrive depuis mailer-daemon,
                    # postmaster, etc. avec un sujet typique. On extrait
                    # l'adresse en bounce et on marque le prospect.
                    from . import prospect_status as PS
                    if PS.looks_like_bounce(from_addr, subject):
                        bounced_addr = PS.extract_bounced_address(
                            body, exclude=account["user"])
                        target_pid = None
                        if bounced_addr:
                            target_pid = from_to_prospect.get(bounced_addr.lower())
                        if target_pid:
                            # account_id = la boîte d'ENVOI (le DSN revient
                            # chez l'expéditeur) → la rampe de montée auto
                            # sait quelle boîte freiner. On extrait AUSSI la
                            # raison lisible (adresse inexistante, boîte
                            # pleine, bloqué…) pour la garder sur la fiche.
                            reason_human = PS.extract_bounce_reason(body)
                            PS.mark_bounced(client, target_pid,
                                            bounced_address=bounced_addr,
                                            reason=(reason_human
                                                    or f"Rebond (avis de {from_addr})"),
                                            account_id=account_id)
                            counters["matched"] += 1
                            counters["written"] += 1
                        else:
                            # On loggue le bounce orphelin pour audit
                            try:
                                _log_inbox_mail(client, account_id,
                                                 from_addr=from_addr,
                                                 subject=f"[BOUNCE] {subject}",
                                                 body=body,
                                                 in_reply_to=in_reply_to,
                                                 body_html=body_html)
                            except Exception:
                                pass
                            counters["skipped"] += 1
                        continue

                    # --- Filtre : mails automatiques (newsletters, notifs,
                    # no-reply, security alerts, accuses de reception...).
                    # On les loggue en inbox_received pour audit, mais on ne
                    # tente JAMAIS de les matcher a un prospect ni de les
                    # classifier — ils ne doivent pas polluer la vue Reponses.
                    if PS.looks_like_automated(headers, from_addr, subject):
                        try:
                            _log_inbox_mail(client, account_id,
                                             from_addr=from_addr,
                                             subject=f"[AUTO] {subject}",
                                             body=body,
                                             in_reply_to=in_reply_to,
                                             body_html=body_html)
                        except Exception as exc:
                            logger.debug("log_inbox_mail (auto) KO: %s", exc)
                        counters["skipped"] += 1
                        continue

                    # Match précis puis flou
                    prospect_id = None
                    for cand in [in_reply_to] + [
                        _extract_msg_id(r) for r in references.split()
                    ]:
                        if cand and cand in msgid_to_prospect:
                            prospect_id = msgid_to_prospect[cand]
                            break
                    if prospect_id is None and from_addr:
                        prospect_id = from_to_prospect.get(from_addr.lower())
                    if prospect_id is None:
                        # Mail d'un INCONNU (pas encore dans la base prospects).
                        # Avant : simplement rangé, sans analyse → on pouvait
                        # passer à côté d'un mail important. Maintenant : l'IA
                        # juge s'il mérite l'attention de Jordan, on garde son
                        # verdict sur la fiche, et on alerte le téléphone si oui.
                        if from_addr and (subject or body):
                            try:
                                if triage_cfg.get("analyze_strangers_with_ai", True):
                                    triage = inbox_triage.triage_stranger_mail(
                                        ai_settings, from_addr=from_addr,
                                        subject=subject, body=body)
                                else:
                                    triage = inbox_triage._fallback_triage(
                                        subject, body)
                                row_id = _log_inbox_mail(
                                    client, account_id, from_addr=from_addr,
                                    subject=subject, body=body,
                                    in_reply_to=in_reply_to,
                                    body_html=body_html,
                                    extra_fields={"triage": triage})
                                if row_id and inbox_triage.should_notify(
                                        triage_cfg, is_stranger=True,
                                        attention=triage.get("attention"),
                                        priority=triage.get("priority")):
                                    title, pbody = inbox_triage.build_stranger_push(
                                        from_addr=from_addr, triage=triage)
                                    if _notify_inbox_attention(
                                            client, row_id, triage_cfg,
                                            title=title, body=pbody,
                                            priority=triage.get("priority"),
                                            view="mails", tag_group="contact"):
                                        counters["notified"] += 1
                            except Exception as exc:
                                logger.debug("triage inconnu KO: %s", exc)
                        counters["skipped"] += 1
                        continue
                    counters["matched"] += 1

                    if _already_logged(client, prospect_id, in_reply_to,
                                        from_addr, subject):
                        counters["skipped"] += 1
                        continue

                    classification = _classify_reply(
                        ai_settings, subject=subject, body=body, from_addr=from_addr,
                    )
                    counters["classified"] += 1

                    # Attention déterministe (zéro coût IA) : un « intéressé »
                    # mérite une alerte, un « non merci » / désinscription est
                    # géré tout seul → pas d'alerte.
                    attention = inbox_triage.attention_for_reply(
                        (classification or {}).get("category", ""),
                        (classification or {}).get("confidence", 0.0))

                    # Fiche prospect (nom + mails) lue UNE seule fois : sert au
                    # brouillon de réponse ET à l'alerte (évite 2 lectures).
                    try:
                        pres = (client.raw.table("prospects")
                                .select("name,legal_name,emails")
                                .eq("id", prospect_id).limit(1).execute())
                        prospect = (pres.data or [{}])[0]
                    except Exception:
                        prospect = {}

                    extra = {
                        "classification": classification,
                        "attention": attention,
                        "body_excerpt": (body or "")[:1500],
                        "body_html": (body_html or "")[:80_000],
                        "from": from_addr,
                        "in_reply_to": in_reply_to,
                        "handled": False,
                        "account_id": account_id,        # phase 2 : trace l'origine
                    }
                    row = {
                        "prospect_id": prospect_id,
                        "kind": "reply_received",
                        "ts": datetime.now().isoformat(timespec="seconds"),
                        "subject": subject[:200],
                        "body": "",
                        "extra": extra,
                        "created_by": client.user_id,
                    }
                    try:
                        ins = client.raw.table("email_history").insert(
                            with_workspace(client, row)
                        ).execute()
                        counters["written"] += 1
                        history_row_id = (ins.data or [{}])[0].get("id", "")
                    except Exception as exc:
                        logger.warning("insert email_history KO: %s", exc)
                        counters["errors"] += 1
                        continue

                    if history_row_id:
                        try:
                            from . import reply_responder
                            reply_responder.ensure_suggested_reply(
                                client, history_row_id,
                                classification=classification,
                                prospect=prospect,
                                reply_subject=subject,
                                reply_body=body,
                                in_reply_to=in_reply_to,
                                app_state=app_state,
                            )
                        except Exception as exc:
                            logger.debug("ensure_suggested_reply: %s", exc)

                    # --- Fix 1 : maj statut selon classification ---
                    # unsubscribe -> 'unsubscribed' definitif (RGPD)
                    # no          -> 'refused' definitif (cycle business clos)
                    # autres      -> 'replied' soft (humain doit traiter)
                    # On ne descend JAMAIS un statut deja "no_contact" vers
                    # un statut plus permissif.
                    try:
                        cat = (classification or {}).get("category", "").lower()
                        cur_status = PS.get_status(client, prospect_id)
                        if PS.is_no_contact(cur_status):
                            # Deja en no-contact (won/lost/refused/unsubscribed/
                            # bounced) -> ne rien changer
                            pass
                        elif cat == "unsubscribe":
                            PS.mark_unsubscribed(
                                client, prospect_id,
                                reason=f"reply classified unsubscribe: {subject[:120]}")
                        elif cat == "no":
                            PS.mark_refused(
                                client, prospect_id,
                                reason=f"reply classified no: {subject[:120]}")
                        elif cur_status != "replied":
                            client.raw.table("prospects").update({
                                "status": "replied",
                                "last_contact_at": datetime.now().isoformat(timespec="seconds"),
                                "updated_by": client.user_id,
                            }).eq("id", prospect_id).execute()
                    except Exception as exc:
                        logger.debug("update status KO: %s", exc)

                    # --- Alerte téléphone si la réponse mérite l'attention ---
                    # (intéressé surtout). Les refus / désinscriptions sont
                    # traités tout seuls → pas d'alerte (attention=False).
                    try:
                        if history_row_id and inbox_triage.should_notify(
                                triage_cfg, is_stranger=False,
                                attention=attention.get("attention"),
                                priority=attention.get("priority")):
                            disp = (prospect.get("name")
                                    or prospect.get("legal_name") or "")
                            title, pbody = inbox_triage.build_reply_push(
                                display_name=disp,
                                category=(classification or {}).get("category", ""),
                                subject=subject)
                            if _notify_inbox_attention(
                                    client, history_row_id, triage_cfg,
                                    title=title, body=pbody,
                                    priority=attention.get("priority"),
                                    view="replies", tag_group="replies"):
                                counters["notified"] += 1
                    except Exception as exc:
                        logger.debug("notify reply KO: %s", exc)

                except Exception as exc:
                    logger.warning("UID %s [%s]: %s", uid_int, account_id, exc)
                    counters["errors"] += 1
                    if not first_error_uid:
                        first_error_uid = uid_int

            # Persiste le dernier UID vu pour ce compte — sans jamais dépasser
            # un mail en échec : il sera rejoué au prochain cycle (les logs
            # réponse/inbox ont chacun leur anti-doublon, rejouer est sûr).
            if first_error_uid:
                max_uid_seen = max(last_uid, first_error_uid - 1)
            if max_uid_seen > last_uid:
                try:
                    client.set_shared_setting(last_uid_key, max_uid_seen)
                except Exception as exc:
                    logger.debug("save %s KO: %s", last_uid_key, exc)
        finally:
            try:
                M.logout()
            except Exception:
                pass
    except imaplib.IMAP4.error as exc:
        counters["error"] = f"imap_login_{exc}"
    except Exception as exc:
        counters["error"] = str(exc)

    return counters


# ---------------------------------------------------------------------------
# Helpers IMAP / parsing
# ---------------------------------------------------------------------------
def _mime_decode(s: str) -> str:
    """Décode une string MIME (RFC 2047) du genre =?UTF-8?Q?...?=
    Renvoie la string décodée propre. Robuste aux entrées vides/None.
    """
    if not s:
        return ""
    try:
        from email.header import decode_header
        out = []
        for chunk, enc in decode_header(s):
            if isinstance(chunk, bytes):
                out.append(chunk.decode(enc or "utf-8", errors="replace"))
            else:
                out.append(chunk)
        return "".join(out).strip()
    except Exception:
        return s


def _extract_plain_body(raw: str) -> str:
    """Extrait le texte plain d'un body MIME multipart.
    Si pas de structure multipart détectable, renvoie le raw nettoyé.
    """
    if not raw:
        return ""
    try:
        msg = email.message_from_string(raw)
        if msg.is_multipart():
            for part in msg.walk():
                ctype = (part.get_content_type() or "").lower()
                if ctype == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace").strip()
            # Fallback : prendre la première partie text/* trouvée
            for part in msg.walk():
                ctype = (part.get_content_type() or "").lower()
                if ctype.startswith("text/"):
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        text = payload.decode(charset, errors="replace")
                        # Si HTML, strip les balises grossièrement
                        text = re.sub(r"<[^>]+>", " ", text)
                        return text.strip()
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
                text = re.sub(r"<[^>]+>", " ", text)
                return text.strip()
    except Exception:
        pass
    # Fallback ultime : nettoyer le raw (HTML grossier + boundaries)
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"^------=_Part_.*$", "", text, flags=re.M)
    text = re.sub(r"^Content-(Type|Transfer-Encoding|Disposition):.*$", "", text, flags=re.M | re.I)
    text = re.sub(r"^boundary=.*$", "", text, flags=re.M)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text


def _parse_fetch_response(msg_data) -> tuple[dict, str, str]:
    """Parse une réponse IMAP `BODY.PEEK[]` (message complet : headers + body).
    Renvoie (dict_headers, str_body_text, str_body_html).

    Les en-têtes (Subject, From) sont décodés depuis le MIME (RFC 2047).
    - body_text : version texte brut (text/plain de préférence, fallback HTML
      strippé). Sert à la classification IA et au snippet d'aperçu.
    - body_html : version HTML d'origine si le mail en a une, sinon "".
      Sert à afficher le mail avec sa mise en page dans l'iframe sandbox.
    """
    # Concatène tous les chunks de la réponse IMAP en une seule string
    raw_full = ""
    for part in msg_data:
        if not isinstance(part, tuple):
            continue
        chunk = part[1]
        if isinstance(chunk, bytes):
            raw_full += chunk.decode("utf-8", errors="ignore")
        elif chunk:
            raw_full += str(chunk)
    if not raw_full:
        return {}, "", ""

    headers: dict = {}
    try:
        msg = email.message_from_string(raw_full)
        # Headers fonctionnels (threading + identification)
        for k in ("From", "In-Reply-To", "References", "Subject", "Date"):
            v = msg.get(k)
            if v:
                headers[k] = _mime_decode(v) if k in ("Subject", "From") else v
        # Headers de detection "envoi automatique" — utilises par
        # prospect_status.looks_like_automated() pour ecarter newsletters,
        # notifs de plateformes, accuses de reception, etc.
        for k in ("List-Unsubscribe", "List-Id", "Auto-Submitted",
                  "Precedence", "X-Auto-Response-Suppress", "Feedback-ID",
                  "X-TS-Warmup"):
            v = msg.get(k)
            if v:
                headers[k] = v
    except Exception:
        pass

    # Body : extraction text/plain + text/html en parallèle
    try:
        msg = email.message_from_string(raw_full)
        body_text = ""
        body_html = ""
        if msg.is_multipart():
            for sub in msg.walk():
                ctype = (sub.get_content_type() or "").lower()
                if not body_text and ctype == "text/plain":
                    payload = sub.get_payload(decode=True)
                    if payload:
                        charset = sub.get_content_charset() or "utf-8"
                        body_text = payload.decode(charset, errors="replace").strip()
                elif not body_html and ctype == "text/html":
                    payload = sub.get_payload(decode=True)
                    if payload:
                        charset = sub.get_content_charset() or "utf-8"
                        body_html = payload.decode(charset, errors="replace").strip()
                if body_text and body_html:
                    break
            # Si pas de text/plain trouvé mais HTML dispo, on dérive le texte du HTML
            if not body_text and body_html:
                body_text = re.sub(r"<[^>]+>", " ", body_html).strip()
            # Fallback ultime : premier text/* trouvé
            if not body_text:
                for sub in msg.walk():
                    ctype = (sub.get_content_type() or "").lower()
                    if ctype.startswith("text/"):
                        payload = sub.get_payload(decode=True)
                        if payload:
                            charset = sub.get_content_charset() or "utf-8"
                            text = payload.decode(charset, errors="replace")
                            text = re.sub(r"<[^>]+>", " ", text)
                            body_text = text.strip()
                            break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
                ctype = (msg.get_content_type() or "").lower()
                if ctype == "text/html":
                    body_html = text.strip()
                    body_text = re.sub(r"<[^>]+>", " ", text).strip()
                else:
                    body_text = text.strip()
        # Compact whitespace sur le texte (pas sur le HTML, qu'on garde tel quel)
        body_text = re.sub(r"\n{3,}", "\n\n", body_text)
        body_text = re.sub(r"[ \t]+", " ", body_text).strip()
        return headers, body_text, body_html
    except Exception as exc:
        logger.debug("parse body failed: %s", exc)
        return headers, "", ""


def _extract_msg_id(raw: str) -> str:
    if not raw:
        return ""
    m = re.search(r"<([^>]+)>", raw)
    return m.group(1).strip() if m else raw.strip()


def _from_address(raw: str) -> str:
    if not raw:
        return ""
    addr = email.utils.parseaddr(raw)
    return (addr[1] or "").lower().strip()


# ---------------------------------------------------------------------------
# Helpers Supabase
# ---------------------------------------------------------------------------
def _get_supabase_client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None
    try:
        client = get_client()
    except SupabaseNotConfigured:
        return None
    if not client.is_authenticated:
        return None
    return client


def _resolve_imap_config(app_state, client) -> Optional[dict]:
    """Cherche IMAP config : shared_settings d'abord, settings.json local sinon."""
    sb = client.get_shared_setting("imap_config", None)
    if sb and isinstance(sb, dict):
        host = (sb.get("imap_host") or "").strip()
        user = (sb.get("imap_user") or "").strip()
        password = sb.get("imap_password") or ""
        port = int(sb.get("imap_port") or 993)
        if host and user and password:
            return {"host": host, "port": port, "user": user, "password": password}
    # Fallback : settings.json local
    out = app_state.get("outreach", default={}) or {}
    host = (out.get("imap_host") or "").strip()
    user = (out.get("imap_user") or "").strip()
    password = out.get("imap_password") or ""
    port = int(out.get("imap_port") or 993)
    if host and user and password:
        return {"host": host, "port": port, "user": user, "password": password}
    return None


def _resolve_ai_settings(app_state, client) -> dict:
    """Provider + clé pour la classification. Préfère shared_settings."""
    out: dict = {"provider": "", "model": "", "api_key": ""}
    sb = client.get_shared_setting("ai", None)
    if sb and isinstance(sb, dict):
        out["provider"] = sb.get("selected_provider", "") or ""
        out["model"] = sb.get("selected_model", "") or ""
        keys = sb.get("api_keys") or {}
        if out["provider"]:
            out["api_key"] = keys.get(out["provider"], "") or ""
    if not out["provider"] or not out["api_key"]:
        ai = app_state.get("ai", default={}) or {}
        out["provider"] = ai.get("selected_provider", "") or out["provider"]
        out["model"] = ai.get("selected_model", "") or out["model"]
        keys = ai.get("api_keys") or {}
        if out["provider"]:
            out["api_key"] = keys.get(out["provider"], "") or out["api_key"]
    return out


def _build_prospect_index(client) -> tuple[dict, dict]:
    """Renvoie (msgid → prospect_id, from_email → prospect_id) en lisant
    prospects + email_history (kind=email_sent).

    Lecture PAGINÉE : PostgREST plafonne toute réponse à 1000 lignes, or la
    base dépasse 11 000 prospects — sans pagination l'index ignorait en
    silence tout prospect au-delà des 1000 premiers (rebond/réponse non
    reconnus). Lève RuntimeError si la lecture échoue : un index vide mis en
    cache ferait traiter tout le courrier en « inconnu » pendant 10 minutes
    (c'est comme ça que 4 rebonds ont été perdus mi-juin)."""
    msgid_to: dict = {}
    from_to: dict = {}
    sb = client.raw
    page = 1000
    try:
        # Tous les prospects (id + emails), par pages
        start = 0
        while True:
            res = (sb.table("prospects").select("id,emails")
                   .order("id").range(start, start + page - 1).execute())
            rows = res.data or []
            for row in rows:
                pid = row.get("id")
                emails = row.get("emails") or []
                for em in emails:
                    if em:
                        from_to[str(em).lower().strip()] = pid
            if len(rows) < page:
                break
            start += page
        # Tous les message_id envoyés, par pages
        start = 0
        while True:
            res2 = (sb.table("email_history").select("prospect_id,message_id")
                    .eq("kind", "email_sent")
                    .order("id").range(start, start + page - 1).execute())
            rows2 = res2.data or []
            for row in rows2:
                mid = (row.get("message_id") or "").strip()
                pid = row.get("prospect_id")
                if mid and pid:
                    clean = _extract_msg_id(mid)
                    if clean:
                        msgid_to[clean] = pid
            if len(rows2) < page:
                break
            start += page
    except Exception as exc:
        logger.warning("build_prospect_index: %s", exc)
        raise RuntimeError(f"index prospects indisponible: {exc}") from exc
    return msgid_to, from_to


def _get_prospect_index(client) -> tuple[dict, dict]:
    """Renvoie l'index (msgid->id, email->id) en le construisant A LA DEMANDE
    et en le gardant en cache _INDEX_TTL_SEC. Appele uniquement quand un
    compte a du courrier -> on ne relit plus toute la base a vide."""
    now = time.time()
    if (_INDEX_CACHE.get("from") is not None
            and (now - _INDEX_CACHE.get("at", 0.0)) < _INDEX_TTL_SEC):
        return _INDEX_CACHE["msgid"], _INDEX_CACHE["from"]
    msgid_to, from_to = _build_prospect_index(client)
    _INDEX_CACHE["at"] = now
    _INDEX_CACHE["msgid"] = msgid_to
    _INDEX_CACHE["from"] = from_to
    return msgid_to, from_to


def _already_logged(client, prospect_id: str, in_reply_to: str,
                     from_addr: str, subject: str) -> bool:
    """Évite d'écrire 2x la même réponse si le poller refait un cycle après crash."""
    try:
        sb = client.raw
        # Check par message_id (in_reply_to stocké dans extra) — limite aux 50
        # derniers reply_received pour ce prospect.
        res = (sb.table("email_history")
               .select("subject,extra")
               .eq("prospect_id", prospect_id)
               .eq("kind", "reply_received")
               .order("ts", desc=True).limit(50).execute())
        for row in res.data or []:
            extra = row.get("extra") or {}
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except Exception:
                    extra = {}
            same_thread = (in_reply_to and
                            extra.get("in_reply_to") == in_reply_to)
            same_subject_from = (
                subject and from_addr
                and (row.get("subject") or "").strip()[:200] == subject[:200]
                and (extra.get("from") or "").lower() == from_addr.lower()
            )
            if same_thread or same_subject_from:
                return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Classification IA
# ---------------------------------------------------------------------------
CLASSIFY_PROMPT = (
    "Classe ce mail entrant en UNE catégorie parmi : "
    "interested, not_now, no, unsubscribe, unknown.\n"
    "- interested = montre un intérêt clair (veut en savoir plus, demande RDV, "
    "  prix, démo, échange).\n"
    "- not_now = poli mais reporte (pas le bon moment, recontactez plus tard, "
    "  en vacances, en réunion, etc).\n"
    "- no = refus net (pas intéressé, pas pour nous, on a déjà, merci non).\n"
    "- unsubscribe = demande explicite de désinscription / arrêter les mails / "
    "  RGPD / spam.\n"
    "- unknown = auto-réponse, hors-sujet, contenu vide, ou impossible à classer.\n"
    "\n"
    "RÉPONDS UNIQUEMENT par un JSON valide : "
    '{\"category\": \"interested\", \"confidence\": 0.85, \"reason\": "..."}\n'
    "Aucun autre texte avant ou après le JSON."
)


def _classify_reply(ai: dict, *, subject: str, body: str,
                     from_addr: str) -> dict:
    """Renvoie {category, confidence, reason}. Fallback unknown si pas d'IA."""
    out = {"category": "unknown", "confidence": 0.0, "reason": "no_ai_configured"}
    provider = (ai.get("provider") or "").strip()
    api_key = (ai.get("api_key") or "").strip()
    model = (ai.get("model") or "").strip()
    if not provider or not api_key:
        return out
    try:
        from triskell_core.ai.providers import send_to_provider, ProviderError
    except ImportError:
        return out
    user_msg = (
        f"De : {from_addr}\nObjet : {subject}\n\n"
        f"Corps :\n{(body or '')[:4000]}"
    )
    try:
        prompt = CLASSIFY_PROMPT + "\n\n---\n\n" + user_msg
        api_keys = {provider: api_key}
        text = send_to_provider(provider, model or "", prompt, api_keys)
        text = (text or "").strip()
        # Extrait le 1er JSON
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
                cat = (data.get("category") or "").strip().lower()
                if cat in CATEGORIES:
                    return {
                        "category": cat,
                        "confidence": float(data.get("confidence", 0.0) or 0.0),
                        "reason": (data.get("reason") or "")[:300],
                    }
            except Exception:
                pass
        # Fallback : essaye keyword match sur la réponse brute
        low = text.lower()
        for cat in CATEGORIES:
            if cat in low:
                return {"category": cat, "confidence": 0.4,
                        "reason": "keyword_fallback"}
    except ProviderError as exc:
        return {"category": "unknown", "confidence": 0.0,
                "reason": f"ai_error: {exc}"[:300]}
    except Exception as exc:
        return {"category": "unknown", "confidence": 0.0,
                "reason": f"ai_exc: {exc}"[:300]}
    return out
