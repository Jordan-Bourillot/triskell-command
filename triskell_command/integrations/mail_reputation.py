"""Réputation & chauffe RÉELLE des boîtes d'envoi — zéro affirmation non vérifiée.

Pourquoi ce module existe
-------------------------
Avant, une boîte était dite « déjà chaude » uniquement parce que son nom de
domaine n'était pas dans une petite liste codée en dur (warmup_tick._role).
C'était une SUPPOSITION : une boîte d'un mois qui n'a jamais envoyé un mail
était affichée « chaude » alors qu'elle n'a aucune réputation.

Ici, on ne suppose rien. Chaque information produite est un FAIT mesuré, avec
sa source et sa date. Si une donnée n'a pas pu être vérifiée (réseau coupé,
aucun historique), elle est étiquetée « non vérifié » — jamais déguisée en
certitude.

Les sources de vérité (toutes gratuites, toutes vérifiables)
------------------------------------------------------------
1. **Authentification du domaine** (SPF / DKIM / DMARC / MX) — interrogation DNS
   publique via ``mail_dns_doctor.check_domain`` (résolveurs injectables, donc
   testable sans réseau). Sans ces « tampons », les mails partent en spam quoi
   qu'il arrive.
2. **Historique d'envoi RÉEL** — table ``email_history`` : combien de mails
   cette boîte a réellement envoyés, depuis quand, combien ont rebondi, combien
   de désinscriptions, combien de réponses. Attribué à la boîte par son adresse
   expéditrice (``extra.from``) puis par son identifiant (``extra.account_id``).
3. **Chauffe interne** — état ``warmup_state`` écrit par ``scripts/warmup_tick``
   (depuis combien de jours le trafic d'amorçage tourne entre tes boîtes).
4. **Connexion live** (optionnelle) — test réel SMTP/IMAP des identifiants.

Le verdict de chauffe est DÉRIVÉ de ces faits (ancienneté du 1er envoi réel +
volume + rebonds + chauffe interne), jamais du nom de domaine.

Architecture testable
----------------------
La collecte réseau (``_read_history``, ``domain_age_days``, le DNS) est isolée.
Les fonctions de calcul (``aggregate_for_accounts``, ``classify``) sont PURES :
on leur injecte des données et elles rendent un résultat déterministe — c'est
ce que vérifie ``scripts/smoke_mail_reputation.py`` sans aucun réseau.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Seuils — alignés sur les règles Google/Yahoo 2024 (SPF+DKIM+DMARC exigés,
# montée en volume sur 3-4 semaines) et sur le barème de rampe déjà en place
# (sender_pool_tracker.RAMP_STEPS). Un seul endroit pour les régler.
# ---------------------------------------------------------------------------
WARMUP_GOAL_DAYS = 28              # durée d'une chauffe complète (= sender pool)
ESTABLISHED_MIN_DAYS = 28          # envoie réellement depuis au moins 4 semaines…
ESTABLISHED_MIN_SENT_30D = 100     # … ET garde un volume réel sur 30 jours
COLD_MAX_SENT = 0                  # 0 envoi réel observé = jamais utilisée
BOUNCE_RATE_WARN = 0.05            # > 5 % de rebonds sur 30 j = réputation à risque
BOUNCE_MIN_FOR_ALERT = 3           # …mais pas d'alerte sous 3 rebonds (bruit)
HISTORY_WINDOW_DAYS = 90           # fenêtre de lecture de l'historique réel

# Les lignes d'historique qui nous renseignent sur une boîte d'envoi.
KINDS = ("email_sent", "status_bounced", "status_unsubscribed", "reply_received")


# ---------------------------------------------------------------------------
# Petits utilitaires purs
# ---------------------------------------------------------------------------
def _domain_of(email: str) -> str:
    return (email or "").split("@")[-1].strip().lower().lstrip("@")


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Parse un timestamp ISO. Les ts naïfs (heure locale serveur, écrits par
    email_history_log) sont considérés UTC — léger biais d'1-2 h sans effet sur
    des seuils exprimés en jours/volumes. Même convention que sender_pool_tracker.
    """
    try:
        dt = datetime.fromisoformat((ts_str or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Agrégation PURE de l'historique par boîte (testable sans réseau)
# ---------------------------------------------------------------------------
def aggregate_for_accounts(rows: Iterable[dict], accounts: list[dict],
                           now: Optional[datetime] = None) -> dict[str, dict]:
    """Compte, pour chaque boîte, ses envois/rebonds/désinscriptions/réponses
    réels par fenêtre de temps.

    rows : lignes brutes [{ts, kind, account_id, from_email}].
    accounts : [{id, from_email}, ...].
    Chaque ligne est attribuée à AU PLUS une boîte (priorité à l'adresse
    expéditrice exacte, puis à l'identifiant, sinon au compte principal) →
    jamais de double comptage entre boîtes.
    Renvoie {account_id: {sent_24h, sent_7d, sent_30d, sent_window,
             bounces_30d, unsub_30d, replies_30d, first_seen, active_days_30d}}.
    """
    now = now or _now_utc()
    c24 = now - timedelta(hours=24)
    c7 = now - timedelta(days=7)
    c30 = now - timedelta(days=30)

    by_addr: dict[str, str] = {}
    by_id: dict[str, str] = {}
    for a in accounts:
        aid = str(a.get("id") or "").strip()
        if not aid:
            continue
        addr = (a.get("from_email") or "").strip().lower()
        if addr:
            by_addr[addr] = aid
        by_id[aid] = aid

    def _blank() -> dict:
        return {"sent_24h": 0, "sent_7d": 0, "sent_30d": 0, "sent_window": 0,
                "bounces_30d": 0, "unsub_30d": 0, "replies_30d": 0,
                "first_seen": None, "active_days_30d": set()}

    agg: dict[str, dict] = {aid: _blank() for aid in by_id}

    for r in rows:
        addr = (r.get("from_email") or "").strip().lower()
        rid = str(r.get("account_id") or "").strip()
        # Attribution STRICTE : par adresse expéditrice exacte, sinon par
        # identifiant de boîte exact. Une ligne sans étiquette reconnue n'est
        # JAMAIS collée d'office sur la principale — sinon cette boîte ramasse
        # les rebonds de tout le monde et affiche un faux taux catastrophique
        # (vécu : 62 rebonds d'une seule adresse morte gonflaient primary à 38 %).
        owner = by_addr.get(addr) or by_id.get(rid)
        if owner is None or owner not in agg:
            continue
        ts = _parse_ts(r.get("ts") or "")
        if ts is None:
            continue
        kind = r.get("kind") or ""
        a = agg[owner]
        if kind == "email_sent":
            a["sent_window"] += 1
            if a["first_seen"] is None or ts < a["first_seen"]:
                a["first_seen"] = ts
            if ts >= c30:
                a["sent_30d"] += 1
                a["active_days_30d"].add(ts.date().isoformat())
            if ts >= c7:
                a["sent_7d"] += 1
            if ts >= c24:
                a["sent_24h"] += 1
        elif kind == "status_bounced" and ts >= c30:
            a["bounces_30d"] += 1
        elif kind == "status_unsubscribed" and ts >= c30:
            a["unsub_30d"] += 1
        elif kind == "reply_received" and ts >= c30:
            a["replies_30d"] += 1

    # Fige les sets de jours actifs en nombre (sérialisable).
    for a in agg.values():
        a["active_days_30d"] = len(a["active_days_30d"])
    return agg


# ---------------------------------------------------------------------------
# Verdict PUR — la vérité, faits à l'appui (testable sans réseau)
# ---------------------------------------------------------------------------
def classify(facts: dict, *, auth: Optional[dict] = None,
             warmup_age_days: Optional[int] = None,
             history_ok: bool = True,
             now: Optional[datetime] = None) -> dict:
    """Transforme les faits mesurés d'une boîte en verdict honnête.

    facts : sortie d'aggregate_for_accounts pour cette boîte.
    auth  : résultat de mail_dns_doctor.check_domain (ou None = non vérifié).
    warmup_age_days : âge de la chauffe interne en jours (ou None = pas en chauffe).
    history_ok : False si la lecture de l'historique a échoué (→ « non vérifié »,
                 surtout pas « froide »).
    """
    now = now or _now_utc()
    sent_30d = int(facts.get("sent_30d", 0))
    sent_window = int(facts.get("sent_window", 0))
    bounces_30d = int(facts.get("bounces_30d", 0))
    replies_30d = int(facts.get("replies_30d", 0))
    unsub_30d = int(facts.get("unsub_30d", 0))
    active_days = int(facts.get("active_days_30d", 0))
    first_seen = facts.get("first_seen")

    first_days = None
    if isinstance(first_seen, datetime):
        first_days = max(0, (now - first_seen).days)

    bounce_rate = (bounces_30d / sent_30d) if sent_30d > 0 else 0.0
    bounce_alert = (bounces_30d >= BOUNCE_MIN_FOR_ALERT
                    and bounce_rate >= BOUNCE_RATE_WARN)

    # --- Axe authentification (tampons DNS) ---
    auth_state = "inconnu"          # inconnu / ok / incomplet
    auth_missing: list[str] = []
    if isinstance(auth, dict) and auth.get("ok") and auth.get("checks"):
        auth_missing = [c.get("label") or c.get("id")
                        for c in auth["checks"] if not c.get("ok")]
        auth_state = "ok" if not auth_missing else "incomplet"

    # --- Axe chauffe (basé sur les faits, jamais sur le domaine) ---
    warmed_up = warmup_age_days is not None and warmup_age_days >= WARMUP_GOAL_DAYS
    real_track_record = (first_days is not None
                         and first_days >= ESTABLISHED_MIN_DAYS
                         and sent_30d >= ESTABLISHED_MIN_SENT_30D)

    if not history_ok:
        warmth = "inconnu"
    elif sent_window <= COLD_MAX_SENT and not warmup_age_days:
        # 0 envoi réel ET pas en chauffe interne → jamais utilisée. Mais une
        # boîte qu'on chauffe (même au jour 1) n'est PAS « jamais utilisée » :
        # elle tombe dans « en chauffe » plus bas.
        warmth = "froide"
    elif warmed_up or real_track_record:
        warmth = "etablie"
    else:
        # soit quelques envois réels, soit chauffe interne en cours (même J1).
        warmth = "en_chauffe"

    # --- Statut global affiché (le plus prudent l'emporte) ---
    if bounce_alert:
        status, label, tone = "risque", "À risque", "danger"
    elif auth_state == "incomplet":
        status, label, tone = "a_corriger", "À corriger", "danger"
    elif warmth == "inconnu":
        status, label, tone = "inconnu", "Non vérifié", "muted"
    elif warmth == "froide":
        status, label, tone = "froide", "Jamais utilisée", "muted"
    elif warmth == "en_chauffe":
        status, label, tone = "en_chauffe", "En chauffe", "warning"
    else:
        # « Rodée » et non « Établie » : on décrit un état d'ENVOI (la boîte
        # envoie vraiment, régulièrement, proprement), PAS une réputation
        # prouvée. La vraie réputation reste la note Gmail (Postmaster).
        status, label, tone = "etablie", "Rodée", "success"

    # --- Phrase de vérité + conseil (français normal, pas de jargon) ---
    summary, advice = _phrase(
        status=status, warmth=warmth, sent_30d=sent_30d, sent_window=sent_window,
        first_days=first_days, warmup_age_days=warmup_age_days,
        bounce_rate=bounce_rate, bounces_30d=bounces_30d,
        auth_missing=auth_missing, auth_state=auth_state, history_ok=history_ok)

    return {
        "status": status, "label": label, "tone": tone,
        "warmth": warmth, "summary": summary, "advice": advice,
        "auth_state": auth_state, "auth_missing": auth_missing,
        "bounce_alert": bounce_alert,
        "metrics": {
            "sent_24h": int(facts.get("sent_24h", 0)),
            "sent_7d": int(facts.get("sent_7d", 0)),
            "sent_30d": sent_30d, "sent_window": sent_window,
            "bounces_30d": bounces_30d, "bounce_rate_pct": round(bounce_rate * 100, 1),
            "unsub_30d": unsub_30d, "replies_30d": replies_30d,
            "active_days_30d": active_days, "first_send_days_ago": first_days,
            "warmup_age_days": warmup_age_days, "warmup_goal_days": WARMUP_GOAL_DAYS,
        },
    }


def _phrase(*, status, warmth, sent_30d, sent_window, first_days,
            warmup_age_days, bounce_rate, bounces_30d, auth_missing,
            auth_state, history_ok) -> tuple[str, str]:
    """Construit la phrase de vérité et le conseil, sans jargon."""
    if not history_ok:
        return ("Impossible de mesurer son activité pour le moment "
                "(base injoignable).",
                "Réessaie dans un instant.")

    chauffe_txt = ""
    if warmup_age_days is not None:
        if warmup_age_days >= WARMUP_GOAL_DAYS:
            chauffe_txt = f"chauffe interne terminée ({warmup_age_days} j)"
        else:
            chauffe_txt = (f"chauffe interne en cours : {warmup_age_days} j "
                           f"sur {WARMUP_GOAL_DAYS}")

    envois_txt = (f"{sent_30d} envoi(s) réel(s) sur 30 jours"
                  if sent_30d else "aucun envoi réel sur 30 jours")
    if first_days is not None and sent_window:
        envois_txt += f", elle envoie depuis {first_days} j"

    parts = [envois_txt]
    if chauffe_txt:
        parts.append(chauffe_txt)

    if status == "risque":
        summary = (f"Réputation en danger : {bounces_30d} rebond(s) "
                   f"({round(bounce_rate*100)} % des envois). " + " · ".join(parts))
        advice = ("Mets cette boîte en pause et nettoie les adresses mortes "
                  "avant de continuer — un fort taux de rebond grille la "
                  "réputation.")
    elif status == "a_corriger":
        manque = ", ".join(auth_missing) if auth_missing else "des tampons"
        summary = (f"Authentification incomplète ({manque} manquant). "
                   + " · ".join(parts))
        advice = ("Pose les tampons manquants sur le domaine (voir le détail "
                  "ci-dessous) : sans eux, les mails partent en indésirable.")
    elif warmth == "froide":
        summary = ("Jamais utilisée pour envoyer : aucune réputation. "
                   + " · ".join(parts))
        advice = ("À chauffer avant tout envoi en volume. Ne lui confie pas de "
                  "prospection tout de suite.")
    elif warmth == "en_chauffe":
        summary = "En chauffe, pas encore prête pour le volume. " + " · ".join(parts)
        advice = ("Laisse la chauffe finir et monte le volume progressivement. "
                  "Évite les gros envois d'un coup.")
    elif warmth == "etablie":
        summary = ("Rodée à l'envoi : " + " · ".join(parts)
                   + ". Sa réputation réelle = la note Gmail ci-dessous.")
        advice = ("Bonne base d'envoi. Mais ne te fie pas au seul nombre "
                  "d'envois : la vraie réputation vient de la note Gmail "
                  "(elle se remplira quand le volume de prospection montera).")
    else:
        summary = " · ".join(parts)
        advice = ""
    return summary, advice


# ---------------------------------------------------------------------------
# Collecte réseau — isolée (non testée hors-ligne, faillible proprement)
# ---------------------------------------------------------------------------
def _read_history(client, *, days: int = HISTORY_WINDOW_DAYS,
                  now: Optional[datetime] = None) -> Optional[list[dict]]:
    """Lit email_history sur N jours pour les KINDS utiles. Renvoie une liste
    [{ts, kind, account_id, from_email}], ou None si la lecture est IMPOSSIBLE
    (panne) — à distinguer de [] (rien trouvé, ce qui est une info valable)."""
    if client is None:
        return None
    try:
        sb = client.raw
    except Exception:
        return None
    now = now or _now_utc()
    since = (now - timedelta(days=days)).isoformat()

    def _base(cols: str):
        # `.select()` DOIT venir en premier : le SDK supabase-py n'expose les
        # filtres (.in_, .gte…) que sur l'objet rendu par .select(). Les poser
        # avant plantait à chaque appel ('SyncRequestBuilder' has no attribute
        # 'in_') → toutes les boîtes affichées « Non vérifié » et le robot de
        # chauffe traitait les boîtes rodées comme neuves.
        return (sb.table("email_history")
                  .select(cols)
                  .in_("kind", list(KINDS))
                  .gte("ts", since)
                  .order("ts", desc=False)
                  .limit(50000))

    try:
        # On ne lit QUE les deux clés utiles de `extra` (account_id, from) via
        # la projection JSONB de PostgREST, au lieu de rapatrier toute la
        # colonne (elle peut contenir de gros contenus). Divise l'egress de
        # ce passage — appelé plusieurs fois par jour par la chauffe.
        # Repli automatique sur la lecture complète si la syntaxe projetée
        # n'est pas acceptée : jamais de régression.
        try:
            res = _base("ts, kind, account_id:extra->>account_id, "
                        "from_email:extra->>from").execute()
            rows = res.data or []
            narrow = True
        except Exception as exc_narrow:
            logger.debug("mail_reputation: projection JSONB refusée (%s) — "
                         "repli lecture complète", exc_narrow)
            res = _base("ts, kind, extra").execute()
            rows = res.data or []
            narrow = False

        out: list[dict] = []
        for r in rows:
            if narrow:
                account_id = str(r.get("account_id") or "").strip()
                from_email = str(r.get("from_email") or "").strip().lower()
            else:
                extra = r.get("extra") or {}
                if isinstance(extra, str):
                    try:
                        import json as _json
                        extra = _json.loads(extra)
                    except Exception:
                        extra = {}
                if not isinstance(extra, dict):
                    extra = {}
                account_id = str(extra.get("account_id") or "").strip()
                from_email = str(extra.get("from") or "").strip().lower()
            out.append({
                "ts": r.get("ts") or "",
                "kind": r.get("kind") or "",
                "account_id": account_id,
                "from_email": from_email,
            })
        return out
    except Exception as exc:
        logger.warning("mail_reputation._read_history: %s", exc)
        return None


def _warmup_age_days(client, now: Optional[datetime] = None) -> tuple[Optional[int], set]:
    """Âge de la chauffe interne (jours depuis warmup_state.start) + ensemble
    des identifiants de boîtes présentes dans warmup_state. (None, set()) si
    aucune chauffe enregistrée."""
    if client is None:
        return None, set()
    try:
        state = client.get_shared_setting("warmup_state", {}) or {}
        if isinstance(state, str):
            import json as _json
            state = _json.loads(state)
        if not isinstance(state, dict):
            return None, set()
        accts = set((state.get("accounts") or {}).keys())
        start = state.get("start")
        if not start:
            return None, accts
        now = now or _now_utc()
        d0 = _parse_ts(start) or _parse_ts(start + "T00:00:00")
        if d0 is None:
            return None, accts
        return max(1, (now - d0).days + 1), accts
    except Exception as exc:
        logger.debug("mail_reputation._warmup_age_days: %s", exc)
        return None, set()


def domain_age_days(domain: str, *, timeout: float = 5.0) -> Optional[int]:
    """Âge réel du nom de domaine via RDAP (date d'enregistrement publique).
    Renvoie le nombre de jours, ou None si non vérifiable. C'est l'âge du
    DOMAINE — un indice, pas une preuve de réputation d'envoi."""
    domain = _domain_of("x@" + (domain or "")) if "@" not in (domain or "") else _domain_of(domain)
    if not domain or "." not in domain:
        return None
    try:
        import requests
        for url in (f"https://rdap.org/domain/{domain}",
                    f"https://www.rdap.net/domain/{domain}"):
            try:
                r = requests.get(url, timeout=timeout,
                                 headers={"accept": "application/rdap+json"})
                if r.status_code != 200:
                    continue
                data = r.json() or {}
                for ev in data.get("events") or []:
                    if (ev.get("eventAction") or "").lower() == "registration":
                        reg = _parse_ts(ev.get("eventDate") or "")
                        if reg:
                            return max(0, (_now_utc() - reg).days)
            except Exception:
                continue
    except Exception as exc:
        logger.debug("mail_reputation.domain_age_days(%s): %s", domain, exc)
    return None


# ---------------------------------------------------------------------------
# Cœur partagé : faits + verdict par boîte (sans DNS, rapide)
# ---------------------------------------------------------------------------
def _assess_core(client, *, now: Optional[datetime] = None) -> dict:
    """Renvoie {accounts, agg, history_ok, warmup_age_days, warmup_ids}.
    Sert à la fois à l'endpoint web et au robot de chauffe (warmup_tick)."""
    from . import shared_secrets
    now = now or _now_utc()
    accounts = shared_secrets.get_all_mail_accounts(client=client) or []
    rows = _read_history(client, now=now)
    history_ok = rows is not None
    agg = aggregate_for_accounts(rows or [], accounts, now=now)
    warmup_age, warmup_ids = _warmup_age_days(client, now=now)
    return {"accounts": accounts, "agg": agg, "history_ok": history_ok,
            "warmup_age_days": warmup_age, "warmup_ids": warmup_ids}


def established_addresses(client) -> set[str]:
    """Ensemble des adresses expéditrices RÉELLEMENT établies (historique
    d'envoi solide). Utilisé par le robot de chauffe pour distinguer les
    boîtes à chauffer (tout le reste) des boîtes en simple entretien —
    remplace l'ancienne règle « le domaine n'est pas dans une liste »."""
    try:
        core = _assess_core(client)
    except Exception as exc:
        logger.warning("mail_reputation.established_addresses: %s", exc)
        return set()
    out: set[str] = set()
    for acc in core["accounts"]:
        aid = str(acc.get("id") or "").strip()
        facts = core["agg"].get(aid, {})
        warmup_age = (core["warmup_age_days"]
                      if aid in core["warmup_ids"] else None)
        verdict = classify(facts, auth=None, warmup_age_days=warmup_age,
                           history_ok=core["history_ok"])
        if verdict["warmth"] == "etablie":
            addr = (acc.get("from_email") or "").strip().lower()
            if addr:
                out.add(addr)
    return out


# ---------------------------------------------------------------------------
# Orchestrateur complet pour l'écran Santé (avec DNS + âge domaine)
# ---------------------------------------------------------------------------
def assess_all(client, *, with_dns: bool = True, with_age: bool = True,
               now: Optional[datetime] = None) -> dict:
    """Fiche de réputation complète de toutes les boîtes d'envoi.

    with_dns : interroge SPF/DKIM/DMARC/MX (réseau, parallélisé par domaine).
    with_age : interroge l'âge du domaine via RDAP (réseau).
    Renvoie {ok, boxes:[...], summary, history_ok, checked_at_hint}.
    """
    now = now or _now_utc()
    if client is None:
        return {"ok": False, "error": "Base non connectée.", "boxes": []}
    try:
        core = _assess_core(client, now=now)
    except Exception as exc:
        logger.warning("mail_reputation.assess_all core: %s", exc)
        return {"ok": False, "error": str(exc), "boxes": []}

    accounts = core["accounts"]
    if not accounts:
        return {"ok": True, "boxes": [], "history_ok": core["history_ok"],
                "summary": {"total": 0, "etablie": 0, "en_chauffe": 0,
                            "froide": 0, "a_probleme": 0}}

    # Clés « délivrabilité » (note Gmail + listes noires) — lues une fois.
    dqs_key, pm_creds = "", {}
    try:
        from . import shared_secrets
        keys = shared_secrets.get_deliverability_keys(client) or {}
        dqs_key = keys.get("spamhaus_dqs_key") or ""
        pm_creds = keys.get("postmaster") or {}
    except Exception as exc:
        logger.debug("mail_reputation clés délivrabilité: %s", exc)

    # Vérifs réseau, une seule fois par DOMAINE (boîtes du même domaine
    # partagées), en parallèle : tampons DNS + âge + liste noire + note Gmail.
    domains = sorted({_domain_of(a.get("from_email") or "")
                      for a in accounts if a.get("from_email")})
    dns_by_domain: dict[str, dict] = {}
    age_by_domain: dict[str, Optional[int]] = {}
    bl_by_domain: dict[str, dict] = {}
    pm_by_domain: dict[str, dict] = {}
    if with_dns and domains:
        from concurrent.futures import ThreadPoolExecutor
        from .mail_dns_doctor import check_domain
        from . import mail_blacklist, mail_postmaster

        def _one(dom: str):
            return (dom,
                    check_domain(dom),
                    domain_age_days(dom) if with_age else None,
                    mail_blacklist.check_domain(dom, dqs_key),
                    mail_postmaster.assess_domain(dom, pm_creds))

        try:
            with ThreadPoolExecutor(max_workers=min(8, len(domains))) as ex:
                for dom, dns, age, bl, pm in ex.map(_one, domains):
                    if dns is not None:
                        dns_by_domain[dom] = dns
                    age_by_domain[dom] = age
                    if bl is not None:
                        bl_by_domain[dom] = bl
                    if pm is not None:
                        pm_by_domain[dom] = pm
        except Exception as exc:
            logger.warning("mail_reputation.assess_all réseau: %s", exc)

    boxes = []
    summ = {"total": 0, "etablie": 0, "en_chauffe": 0, "froide": 0, "a_probleme": 0}
    for acc in accounts:
        aid = str(acc.get("id") or "").strip()
        addr = (acc.get("from_email") or "").strip().lower()
        dom = _domain_of(addr)
        facts = core["agg"].get(aid, {})
        warmup_age = (core["warmup_age_days"]
                      if aid in core["warmup_ids"] else None)
        auth = dns_by_domain.get(dom)
        verdict = classify(facts, auth=auth, warmup_age_days=warmup_age,
                           history_ok=core["history_ok"], now=now)
        bl = bl_by_domain.get(dom)
        box = {
            "id": aid, "name": acc.get("label") or addr or aid,
            "email": addr, "domain": dom,
            "is_primary": bool(acc.get("is_primary")),
            "auth": auth,                       # détail des tampons (ou None)
            "domain_age_days": age_by_domain.get(dom),
            "blacklist": bl,                    # listes noires (ou None)
            "gmail": pm_by_domain.get(dom),     # note Postmaster (ou None)
            **verdict,
        }
        # Fait vérifié le plus grave : un domaine RÉELLEMENT sur liste noire.
        # On l'affiche en alerte rouge, par-dessus le reste.
        if bl and bl.get("state") == "listed":
            box["status"] = "risque"
            box["label"] = "Sur liste noire"
            box["tone"] = "danger"
            box["summary"] = ("Domaine sur liste noire (" + (bl.get("detail") or "")
                              + "). " + box.get("summary", ""))
            box["advice"] = ("Arrête les envois depuis ce domaine et demande son "
                             "retrait sur le site de Spamhaus : tes mails sont rejetés.")
        boxes.append(box)
        summ["total"] += 1
        if box["status"] in ("risque", "a_corriger"):
            summ["a_probleme"] += 1
        elif box["warmth"] in summ:
            summ[box["warmth"]] += 1

    # Les boîtes à problème d'abord, puis froides, puis en chauffe, puis établies.
    order = {"risque": 0, "a_corriger": 1, "froide": 2, "inconnu": 3,
             "en_chauffe": 4, "etablie": 5}
    boxes.sort(key=lambda b: (order.get(b["status"], 9), b["email"]))

    return {"ok": True, "boxes": boxes, "history_ok": core["history_ok"],
            "with_dns": with_dns, "summary": summ}
