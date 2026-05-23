"""Api pywebview — passerelle entre le front HTML/JS et le back Python.

Toutes les méthodes publiques (sans underscore) sont exposées au front
via `pywebview.api.method_name(args)`. Elles renvoient des dicts
sérialisables JSON.

Réutilise massivement les modules Python existants :
- integrations/morning_digest, replies_poller, reply_responder, drip_runner,
  post_sale_runner, claude_advisor, claude_proactive
- state.AppState

Garde le pipeline async-friendly : on ne fait pas de calculs lourds dans
les méthodes (les workers tournent dans leurs threads). L'Api se contente
de relayer des informations.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from .. import theme as T
from ..state import AppState

logger = logging.getLogger(__name__)


class _AutopilotStopped(Exception):
    """Levée dans _push_log quand le bouton Stop a été cliqué."""


class Api:
    """Toutes les méthodes appelables depuis le front (pywebview)."""

    def __init__(self):
        self._app_state = AppState()
        self._workers_started = False
        # État du run auto-pilote en cours (un seul à la fois)
        self._autopilot_state = {
            "running": False,
            "started_at": "",
            "finished_at": "",
            "log": [],          # liste de lignes (plafonnée à 500)
            "stats": None,      # PipelineStats sérialisé en dict, ou None
            "error": "",
            # Visu temps réel : 5 maillons + activité courante + prospects touchés
            "stages": self._fresh_stages(),
            "current_activity": "",
            "touched_prospects": [],  # [{id, name, action, reason}, ...]
            # Bouton "Arrêter" : passé à True par autopilot_stop(), vérifié
            # dans _push_log à chaque appel pour interrompre le pipeline.
            "stop_requested": False,
        }
        self._autopilot_lock = threading.Lock()

    @staticmethod
    def _fresh_stages() -> dict:
        """État initial des 5 maillons (idle, vide)."""
        return {
            stage: {
                "state": "idle",      # idle | running | done | error
                "message": "",
                "count": 0,
                "started_at": "",
                "finished_at": "",
                "error": "",
            }
            for stage in ("search", "sort", "write", "review", "send")
        }

    def _push_event(self, ev: dict) -> None:
        """Met à jour l'état temps réel d'un run auto-pilote.

        Types d'événements reconnus :
          - {"type": "stage",       "id": "search"|..., "message": "...", "state": "running"}
          - {"type": "stage_done",  "id": "search"|..., "message": "...", "count": int}
          - {"type": "stage_error", "id": "search"|..., "message": "..."}
          - {"type": "activity",    "message": "Je rédige le mail pour..."}
          - {"type": "prospect_touched", "id": "...", "name": "...", "action": "sent"|"draft"|"skipped", "reason": "..."}
        """
        from datetime import datetime
        t = ev.get("type")
        with self._autopilot_lock:
            stages = self._autopilot_state["stages"]
            if t == "stage":
                sid = ev.get("id")
                if sid in stages:
                    stages[sid]["state"] = ev.get("state", "running")
                    stages[sid]["message"] = ev.get("message", "")
                    if "count" in ev:
                        stages[sid]["count"] = int(ev.get("count") or 0)
                    if not stages[sid]["started_at"]:
                        stages[sid]["started_at"] = datetime.now().isoformat(timespec="seconds")
            elif t == "stage_done":
                sid = ev.get("id")
                if sid in stages:
                    stages[sid]["state"] = "done"
                    stages[sid]["message"] = ev.get("message", "")
                    stages[sid]["count"] = int(ev.get("count", 0) or 0)
                    stages[sid]["finished_at"] = datetime.now().isoformat(timespec="seconds")
            elif t == "stage_error":
                sid = ev.get("id")
                if sid in stages:
                    stages[sid]["state"] = "error"
                    stages[sid]["error"] = ev.get("message", "")
                    stages[sid]["finished_at"] = datetime.now().isoformat(timespec="seconds")
            elif t == "activity":
                self._autopilot_state["current_activity"] = ev.get("message", "")
            elif t == "prospect_touched":
                buf = self._autopilot_state["touched_prospects"]
                buf.append({
                    "id":     ev.get("id", ""),
                    "name":   ev.get("name", ""),
                    "action": ev.get("action", ""),
                    "reason": ev.get("reason", ""),
                })
                # Plafond pour eviter une fuite memoire sur les gros runs :
                # on garde les 500 derniers prospects touches.
                if len(buf) > 500:
                    del buf[: len(buf) - 500]

        # État runtime des campagnes Convoi (génération de mails + envoi).
        # Clés = campaign_id ; valeur = dict {running, log, log_len, error, stats}.
        # Permet au front de poller sans recréer une boucle de génération.
        self._convoy_runtime: dict[str, dict] = {}
        self._convoy_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Settings / thème
    # ------------------------------------------------------------------
    def get_theme_mode(self) -> str:
        """Renvoie le mode courant : 'light' / 'mid' / 'dark'."""
        return T.normalize_mode(
            self._app_state.get("appearance_mode", default="mid")
        )

    def set_theme_mode(self, mode: str) -> dict:
        m = T.normalize_mode(mode)
        self._app_state.set("appearance_mode", value=m)
        try:
            self._app_state.save()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "mode": m}

    def cycle_theme(self) -> dict:
        cur = self.get_theme_mode()
        nxt = T.cycle_mode(cur)
        return self.set_theme_mode(nxt)

    def get_user_name(self) -> str:
        """Renvoie le prénom à afficher (Bonjour X). Vide si pas configuré."""
        name = (self._app_state.get("outreach", "from_name", default="")
                or "").strip()
        if "—" in name:
            name = name.split("—")[0].strip()
        if " " in name:
            name = name.split(" ")[0]
        return name  # Pas de fallback hardcodé — l'onboarding s'en charge

    def get_current_user(self) -> dict:
        """Renvoie {first_name, full_name, email, needs_onboarding}.

        needs_onboarding = True si pas de from_name configuré → la web UI
        affichera la modale d'onboarding au premier lancement.
        """
        full = (self._app_state.get("outreach", "from_name", default="")
                or "").strip()
        if "—" in full:
            full = full.split("—")[0].strip()
        first = full.split(" ")[0] if " " in full else full
        email = (self._app_state.get("outreach", "from_email", default="")
                 or "").strip()
        return {
            "first_name": first,
            "full_name":  full,
            "email":      email,
            "needs_onboarding": not bool(full),
        }

    def save_user_identity(self, payload: dict) -> dict:
        """Enregistre l'identité au premier lancement.
        payload = {full_name: str, email?: str}
        """
        p = payload or {}
        full = (p.get("full_name") or "").strip()
        email = (p.get("email") or "").strip()
        if not full:
            return {"ok": False, "error": "Prénom requis"}
        try:
            self._app_state.set("outreach", "from_name", value=full)
            if email:
                self._app_state.set("outreach", "from_email", value=email)
            self._app_state.save()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Matinale
    # ------------------------------------------------------------------
    def get_morning_digest(self) -> dict:
        try:
            from ..integrations import morning_digest
            return morning_digest.compute_digest()
        except Exception as exc:
            logger.warning("morning_digest: %s", exc)
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Allô Claude (sync + proactif)
    # ------------------------------------------------------------------
    def claude_ask(self, payload: dict) -> dict:
        question = (payload or {}).get("question") or None
        try:
            from ..integrations import claude_advisor
            return claude_advisor.ask_claude(
                self._app_state, mode="interactive",
                user_question=question,
            )
        except Exception as exc:
            logger.warning("claude_ask: %s", exc)
            return {"ok": False, "error": str(exc)}

    def claude_chat(self, payload: dict) -> dict:
        """Conversation vocale libre avec Claude.

        payload = {question: str, history: [{role, content}, ...]}
        Renvoie {ok, text, error}.
        """
        question = (payload or {}).get("question") or ""
        history = (payload or {}).get("history") or []
        try:
            from ..integrations import claude_advisor
            return claude_advisor.chat_with_claude(
                self._app_state,
                question=question,
                history=history,
            )
        except Exception as exc:
            logger.warning("claude_chat: %s", exc)
            return {"ok": False, "text": "", "error": str(exc)}

    def claude_consume_pending(self) -> dict | None:
        """Renvoie le conseil proactif en attente (ou None)."""
        try:
            from ..integrations import claude_proactive
            return claude_proactive.consume_pending_advice()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Réponses entrantes
    # ------------------------------------------------------------------
    def get_replies(self, payload: dict | None = None) -> dict:
        """Renvoie les réponses + mails entrants non traités.

        Inclut maintenant :
        - les reply_received (reponses matchees a un prospect, classees IA)
        - les inbox_received (mails entrants non matches : permet de ne plus
          perdre les mails recus depuis une adresse inconnue)

        Filtre optionnel par account_id (compte mail) : si fourni, ne montre
        que les entrants de ce compte. Resoud le bug du multi-comptes ou
        on melangeait les boites.
        """
        p = payload or {}
        category = p.get("category") or "all"
        account_id = (p.get("account_id") or "").strip()
        client = self._supabase()
        if client is None:
            return {"ok": False, "error": "not_connected"}
        try:
            sb = client.raw
            res = (sb.table("email_history").select("*")
                   .in_("kind", ["reply_received", "inbox_received"])
                   .order("ts", desc=True).limit(300).execute())
            rows = res.data or []
            out = []
            import json as _json
            for r in rows:
                extra = r.get("extra") or {}
                if isinstance(extra, str):
                    try:
                        extra = _json.loads(extra)
                    except Exception:
                        extra = {}
                if extra.get("handled"):
                    continue
                # Filtre compte mail (si demande explicitement)
                if account_id and extra.get("account_id") != account_id:
                    continue
                # Filtre categorie : exclut les inbox_received (pas de
                # classification IA) et filtre les reply_received par
                # catégorie demandée — sinon le filtre "interested" laisse
                # passer les mails inconnus et la liste ne colle plus au
                # chiffre affiché sur la carte Matinale.
                if category != "all":
                    if r.get("kind") != "reply_received":
                        continue
                    cat = (extra.get("classification") or {}).get(
                        "category", "unknown")
                    if cat != category:
                        continue
                r["extra"] = extra
                out.append(r)
            # Hydrate prospects (uniquement pour reply_received qui ont
            # un prospect_id)
            ids = list({x.get("prospect_id") for x in out
                        if x.get("prospect_id")})
            prospects = {}
            if ids:
                pres = (sb.table("prospects").select(
                    "id,name,legal_name,emails,status")
                    .in_("id", ids).execute())
                prospects = {p2["id"]: p2 for p2 in (pres.data or [])
                              if p2.get("id")}
            return {"ok": True, "rows": out, "prospects": prospects}
        except Exception as exc:
            logger.warning("get_replies: %s", exc)
            return {"ok": False, "error": str(exc)}

    def reply_send_now(self, payload: dict) -> dict:
        """Force l'envoi d'un brouillon de réponse suggéré.

        Si payload.force != True et que le destinataire est déjà client ou a
        déjà été contacté, renvoie {"ok": False, "warnings": [...]} pour
        permettre à l'UI d'afficher l'alerte douce.
        """
        p = payload or {}
        rid = p.get("id") or ""
        force = bool(p.get("force"))
        client = self._supabase()
        if client is None:
            return {"ok": False, "error": "not_connected"}
        try:
            from ..integrations import reply_responder
            r = reply_responder.send_now(client, self._app_state, rid,
                                          force=force) or {}
            # Normalise la sortie (le module interne utilise "success")
            out = dict(r)
            if "ok" not in out:
                out["ok"] = bool(out.get("success"))
            return out
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def reply_cancel(self, payload: dict) -> dict:
        rid = (payload or {}).get("id") or ""
        client = self._supabase()
        if client is None:
            return {"ok": False, "error": "not_connected"}
        try:
            from ..integrations import reply_responder
            return reply_responder.cancel_draft(client, rid)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def reply_update(self, payload: dict) -> dict:
        p = payload or {}
        rid = p.get("id") or ""
        subject = p.get("subject") or ""
        body = p.get("body") or ""
        client = self._supabase()
        if client is None:
            return {"ok": False, "error": "not_connected"}
        try:
            from ..integrations import reply_responder
            return reply_responder.update_draft(
                client, rid, subject=subject, body=body)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def reply_mark_handled(self, payload: dict) -> dict:
        rid = (payload or {}).get("id") or ""
        client = self._supabase()
        if client is None:
            return {"ok": False, "error": "not_connected"}
        try:
            import json as _json
            from datetime import datetime
            sb = client.raw
            res = (sb.table("email_history").select("extra")
                   .eq("id", rid).limit(1).execute())
            row = (res.data or [{}])[0]
            extra = row.get("extra") or {}
            if isinstance(extra, str):
                try: extra = _json.loads(extra)
                except Exception: extra = {}
            extra["handled"] = True
            extra["handled_at"] = datetime.now().isoformat(timespec="seconds")
            sb.table("email_history").update({"extra": extra}).eq(
                "id", rid).execute()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def replies_poll_now(self) -> dict:
        try:
            from ..integrations import replies_poller
            return replies_poller.poll_now(self._app_state)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def mail_health(self) -> dict:
        """Renvoie l'etat de sante du systeme mail : status du poller IMAP,
        comptes en alerte (erreurs consecutives), dernier poll reussi,
        drafts bloques 'needs_review' (variables non remplies). UI :
        afficher un toast rouge si alerts non vide ou needs_review > 0."""
        out: dict = {"ok": True}
        try:
            from ..integrations import replies_poller
            out.update(replies_poller.get_status())
        except Exception as exc:
            out["poller_error"] = str(exc)
        # Compte les drafts bloques (needs_review / skipped_duplicate) pour
        # qu'ils ne soient pas oublies
        try:
            client = self._supabase()
            needs_review = 0
            skipped_dup = 0
            bounced_count = 0
            unsubscribed_count = 0
            if client is not None:
                sb = client.raw
                # convoy_drafts avec status needs_review / skipped_duplicate
                try:
                    nr = (sb.table("convoy_drafts").select("id", count="exact")
                           .eq("status", "needs_review").execute())
                    needs_review = nr.count or 0
                except Exception:
                    pass
                try:
                    sd = (sb.table("convoy_drafts").select("id", count="exact")
                           .eq("status", "skipped_duplicate").execute())
                    skipped_dup = sd.count or 0
                except Exception:
                    pass
                # Compteurs prospects bloques par statut (visibilite cockpit)
                for st_name, ref in (("bounced", "bounced_count"),
                                       ("unsubscribed", "unsubscribed_count")):
                    try:
                        rr = (sb.table("prospects").select("id", count="exact")
                              .eq("status", st_name).execute())
                        if ref == "bounced_count":
                            bounced_count = rr.count or 0
                        else:
                            unsubscribed_count = rr.count or 0
                    except Exception:
                        pass
            out["needs_review_count"] = needs_review
            out["skipped_duplicate_count"] = skipped_dup
            out["bounced_count"] = bounced_count
            out["unsubscribed_count"] = unsubscribed_count
            # Augmente alerts si needs_review : Jordan doit le voir
            alerts = list(out.get("alerts") or [])
            if needs_review > 0:
                alerts.append({
                    "account_id": "drafts",
                    "kind": "needs_review",
                    "count": needs_review,
                    "message": (f"{needs_review} brouillon{'s' if needs_review > 1 else ''} "
                                f"bloque{'s' if needs_review > 1 else ''} (variables non remplies)"),
                })
            out["alerts"] = alerts
        except Exception as exc:
            out["counters_error"] = str(exc)
        return out

    # ------------------------------------------------------------------
    # Brouillons à valider
    # ------------------------------------------------------------------
    #
    # Source de vérité : Supabase (tables prospect_drafts + convoy_drafts).
    # Le compteur "X brouillons à valider" du cockpit lit ces deux tables ;
    # cette vue doit donc lire au même endroit, sinon mismatch (le compteur
    # affiche 660 mais la page renvoie "tu es à jour").
    #
    # Fallback CRM local : seulement si Supabase n'est pas connecté (mode
    # offline / 1ère utilisation). Sinon Supabase fait foi.
    # ------------------------------------------------------------------

    _DRAFTS_LIMIT_PER_SOURCE = 200

    # Plateformes considérées comme "créateur/influenceur" (même règle que
    # l'onglet Obélisk). Tout le reste est considéré "pro / entreprise".
    _CREATOR_PLATFORM_PATTERNS = (
        "youtube.com", "twitch.tv", "reddit.com", "bsky.app", "github.com",
        "tiktok.com", "instagram.com", "linkedin.com", "mastodon",
        "dailymotion.com", "kick.com", "podcasts.apple.com", "pypi.org",
    )

    @classmethod
    def _audience_from_platform_url(cls, platform_url: str) -> str:
        """'creator' si l'URL plateforme matche un réseau créateur connu,
        sinon 'pro' (y compris quand il n'y a pas d'URL plateforme : c'est
        typique des entreprises poussées par Le Chasseur depuis SIRENE).
        """
        u = (platform_url or "").lower()
        if not u:
            return "pro"
        for pat in cls._CREATOR_PLATFORM_PATTERNS:
            if pat in u:
                return "creator"
        return "pro"

    @staticmethod
    def _source_names_from_sources(sources) -> list:
        """Retourne la liste des noms de sources (dédupliqués, ordre stable)
        à partir du JSONB `sources` d'un prospect."""
        out: list = []
        seen: set = set()
        for s in (sources or []):
            if isinstance(s, dict):
                n = (s.get("name") or "").strip().lower()
            else:
                n = (getattr(s, "name", "") or "").strip().lower()
            if n and n not in seen:
                out.append(n)
                seen.add(n)
        return out

    @staticmethod
    def _meta_for_chosen_email(chosen_email: str,
                                emails_meta) -> dict | None:
        """Retrouve l'entrée meta correspondant à l'email choisi dans la
        liste `emails_meta` d'un prospect (insensible à la casse / espaces)."""
        if not chosen_email or not isinstance(emails_meta, list):
            return None
        target = chosen_email.strip().lower()
        for m in emails_meta:
            if isinstance(m, dict):
                e = (m.get("email") or "").strip().lower()
                if e and e == target:
                    return {
                        "source":    str(m.get("source") or "").lower(),
                        "source_id": str(m.get("source_id") or ""),
                        "url":       str(m.get("url") or ""),
                        "context":   str(m.get("context") or ""),
                        "found_at":  str(m.get("found_at") or ""),
                    }
        return None

    def _supabase_client_or_none(self):
        try:
            from triskell_core.db import get_client, SupabaseNotConfigured
        except ImportError:
            return None
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        if not getattr(c, "is_authenticated", False):
            try:
                c.restore_session()
            except Exception:
                return None
        return c if getattr(c, "is_authenticated", False) else None

    def get_drafts(self) -> dict:
        client = self._supabase_client_or_none()
        if client is None:
            return self._get_drafts_local_fallback()

        rows: list[dict] = []
        truncated = False
        try:
            sb = client.raw
            # ---- prospect_drafts (Dénicheur / Drip / Post-sale / Dormant) --
            # PostgREST embed : on récupère le prospect lié pour name/email/city.
            res = (sb.table("prospect_drafts")
                    .select("id, subject, body, kind, provider, model, "
                            "created_at, "
                            "prospects:prospect_id(name, legal_name, "
                            "emails, emails_meta, city, sources, platform_url)")
                    .eq("status", "pending")
                    .order("created_at", desc=True)
                    .limit(self._DRAFTS_LIMIT_PER_SOURCE * 4)
                    .execute())
            for r in (res.data or []):
                subj = (r.get("subject") or "").strip()
                bod = (r.get("body") or "").strip()
                # Skip les coquilles vides (en attente de génération IA)
                if not subj and not bod:
                    continue
                p = r.get("prospects") or {}
                emails = p.get("emails") or []
                platform_url = p.get("platform_url") or ""
                chosen_email = emails[0] if emails else ""
                email_meta = self._meta_for_chosen_email(
                    chosen_email, p.get("emails_meta"))
                rows.append({
                    "source": "prospect",
                    "id": r.get("id") or "",
                    "key": r.get("id") or "",   # compat ancien front
                    "name": (p.get("name")
                              or p.get("legal_name") or "(sans nom)"),
                    "email": chosen_email,
                    "city": p.get("city") or "",
                    "subject": r.get("subject") or "",
                    "body": r.get("body") or "",
                    "ts": (r.get("created_at") or "")[:19],
                    "provider": r.get("provider") or "",
                    "model": r.get("model") or "",
                    "kind": r.get("kind") or "",
                    # Origine globale du prospect + catégorie
                    "prospect_sources":
                        self._source_names_from_sources(p.get("sources")),
                    "platform_url": platform_url,
                    "audience":
                        self._audience_from_platform_url(platform_url),
                    # Provenance précise de l'email choisi pour ce brouillon
                    "email_meta": email_meta,
                })
                if len(rows) >= self._DRAFTS_LIMIT_PER_SOURCE:
                    break
        except Exception as exc:
            logger.warning("get_drafts: prospect_drafts KO: %s", exc)

        try:
            sb = client.raw
            # ---- convoy_drafts (campagnes Convoy / Relances) ---------------
            res = (sb.table("convoy_drafts")
                    .select("id, subject, body, offer_name, prospect, "
                            "is_test, created_at, "
                            "convoy_campaigns:campaign_id(name)")
                    .eq("status", "pending")
                    .order("created_at", desc=True)
                    .limit(self._DRAFTS_LIMIT_PER_SOURCE * 4)
                    .execute())
            convoy_added = 0
            for r in (res.data or []):
                subj = (r.get("subject") or "").strip()
                bod = (r.get("body") or "").strip()
                # Skip les coquilles vides (avant génération IA)
                if not subj and not bod:
                    continue
                p = r.get("prospect") or {}
                camp = r.get("convoy_campaigns") or {}
                convoy_platform_url = p.get("platform_url") or ""
                convoy_email = (p.get("email")
                                 or (p.get("emails") or [""])[0])
                convoy_email_meta = self._meta_for_chosen_email(
                    convoy_email, p.get("emails_meta"))
                rows.append({
                    "source": "convoy",
                    "id": r.get("id") or "",
                    "key": r.get("id") or "",   # compat ancien front
                    "name": (p.get("name") or p.get("legal_name")
                              or "(sans nom)"),
                    "email": convoy_email,
                    "city": p.get("city") or "",
                    "subject": r.get("subject") or "",
                    "body": r.get("body") or "",
                    "ts": (r.get("created_at") or "")[:19],
                    "provider": "",
                    "model": "",
                    "kind": "convoy",
                    "campaign_name": camp.get("name") or "",
                    "offer_name": r.get("offer_name") or "",
                    "is_test": bool(r.get("is_test")),
                    # Origine + catégorie (best-effort sur le snapshot Convoi —
                    # souvent un import CSV, donc pas toujours dispo)
                    "prospect_sources":
                        self._source_names_from_sources(p.get("sources"))
                        or (["convoy"] if not p.get("sources") else []),
                    "platform_url": convoy_platform_url,
                    "audience":
                        self._audience_from_platform_url(convoy_platform_url),
                    "email_meta": convoy_email_meta,
                })
                convoy_added += 1
                if convoy_added >= self._DRAFTS_LIMIT_PER_SOURCE:
                    break
        except Exception as exc:
            logger.warning("get_drafts: convoy_drafts KO: %s", exc)

        # Tri global desc par ts ; brouillons "test" Convoy remontent en tête
        rows.sort(key=lambda x: (
            0 if x.get("is_test") else 1, x.get("ts") or ""
        ), reverse=False)
        rows.sort(key=lambda x: x.get("ts") or "", reverse=True)
        # is_test en premier après tri ts → on rebouge en tête
        tests = [r for r in rows if r.get("is_test")]
        others = [r for r in rows if not r.get("is_test")]
        rows = tests + others

        # Indicateur si on a tronqué (au moins une source à pile la limite)
        if len(rows) >= self._DRAFTS_LIMIT_PER_SOURCE:
            truncated = True

        # === Merge local CRM ===
        # Le pipeline de l'autopilote stocke les drafts en mode validation dans
        # le CRM local (~/.triskell-prospect/prospects.json), PAS dans Supabase.
        # Sans ce merge, les drafts de l'autopilote sont invisibles tant que
        # Supabase est joignable. On les rajoute en bout de liste.
        try:
            local = self._get_drafts_local_fallback()
            local_rows = (local.get("rows") if local and local.get("ok") else []) or []
            # Anti-doublon basique : pas de drafts locaux deja presents en Supabase
            # (par exemple si un autre process les a syncronises). Cle = email+subject.
            seen = {(r.get("email", ""), r.get("subject", "")) for r in rows}
            for lr in local_rows:
                k = (lr.get("email", ""), lr.get("subject", ""))
                if k in seen:
                    continue
                rows.append(lr)
                seen.add(k)
        except Exception as exc:
            logger.debug("get_drafts: merge local KO: %s", exc)

        return {"ok": True, "rows": rows, "truncated": truncated,
                "limit_per_source": self._DRAFTS_LIMIT_PER_SOURCE}

    def _get_drafts_local_fallback(self) -> dict:
        """Lecture depuis le CRM JSON local — uniquement si Supabase KO."""
        try:
            from triskell_core.prospect.pipeline import list_pending_drafts
            pairs = list_pending_drafts()
        except Exception as exc:
            return {"ok": False, "error": str(exc), "rows": []}
        rows = []
        for prospect, draft in pairs:
            platform_url = getattr(prospect, "platform_url", "") or ""
            local_email = (prospect.emails[0] if prospect.emails else "")
            local_email_meta = None
            try:
                m = prospect.source_of_email(local_email)
                if m:
                    local_email_meta = {
                        "source":    str(m.get("source") or "").lower(),
                        "source_id": str(m.get("source_id") or ""),
                        "url":       str(m.get("url") or ""),
                        "context":   str(m.get("context") or ""),
                        "found_at":  str(m.get("found_at") or ""),
                    }
            except Exception:
                local_email_meta = None
            rows.append({
                "source": "local",
                "id": prospect.match_keys[0] if prospect.match_keys else "",
                "key": prospect.match_keys[0] if prospect.match_keys else "",
                "name": prospect.name or prospect.legal_name or "(sans nom)",
                "email": (prospect.emails[0] if prospect.emails else ""),
                "city": prospect.city or "",
                "subject": draft.get("subject", ""),
                "body": draft.get("body", ""),
                "body_html": draft.get("body_html", ""),
                "ts": draft.get("ts", ""),
                "provider": draft.get("provider", ""),
                "model": draft.get("model", ""),
                "kind": draft.get("kind", ""),
                # Origine + catégorie (depuis l'objet Prospect en mémoire)
                "prospect_sources":
                    self._source_names_from_sources(prospect.sources),
                "platform_url": platform_url,
                "audience": self._audience_from_platform_url(platform_url),
                "email_meta": local_email_meta,
                # Note 2e IA (presente uniquement si la relecture a tourne
                # avec autopilot_review_min_score > 0). Permet a l'UI
                # Brouillons d'afficher la note + le commentaire pour aider
                # Jordan a trier vite les mails surs vs douteux.
                "review_score":   draft.get("review_score"),
                "review_verdict": draft.get("review_verdict", ""),
                "review_comment": draft.get("review_comment", ""),
            })
        return {"ok": True, "rows": rows}

    def draft_approve(self, payload: dict) -> dict:
        p = payload or {}
        source = (p.get("source") or "").strip()
        draft_id = (p.get("id") or p.get("key") or "").strip()
        body = p.get("body")

        # Fallback ancien front (pas de source) → on tente Supabase, sinon
        # CRM local. Le "key" envoyé est soit un uuid (nouveau), soit un
        # match_key (ancien).
        if source == "prospect" or (not source and self._looks_like_uuid(draft_id)):
            return self._approve_prospect_draft(draft_id, body)
        if source == "convoy":
            return self._approve_convoy_draft(draft_id, body)
        # Fallback ultime : ancien chemin CRM local
        return self._approve_local_draft(draft_id, body)

    def draft_reject(self, payload: dict) -> dict:
        p = payload or {}
        source = (p.get("source") or "").strip()
        draft_id = (p.get("id") or p.get("key") or "").strip()

        if source == "prospect" or (not source and self._looks_like_uuid(draft_id)):
            return self._reject_supabase_draft("prospect_drafts", draft_id)
        if source == "convoy":
            return self._reject_supabase_draft("convoy_drafts", draft_id)
        return self._reject_local_draft(draft_id)

    @staticmethod
    def _looks_like_uuid(s: str) -> bool:
        import re
        return bool(re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$", (s or "").lower()))

    @staticmethod
    def _iso_now() -> str:
        from datetime import datetime
        return datetime.now().isoformat(timespec="seconds")

    # ----- prospect_drafts : approve = update body + envoi SMTP + log ----
    def _approve_prospect_draft(self, draft_id: str, body) -> dict:
        if not draft_id:
            return {"ok": False, "error": "id manquant"}
        client = self._supabase_client_or_none()
        if client is None:
            return {"ok": False, "error": "Supabase non connecté"}

        from ..integrations import shared_secrets
        from ..integrations.multi_tenant import with_workspace
        from triskell_core.prospect.outreach.smtp_sender import send_email

        sb = client.raw

        # 1) lit le draft + prospect lié
        try:
            res = (sb.table("prospect_drafts")
                    .select("id, subject, body, prospect_id, "
                            "prospects:prospect_id(id, name, emails)")
                    .eq("id", draft_id).limit(1).execute())
        except Exception as exc:
            return {"ok": False, "error": f"lecture draft KO : {exc}"}

        data = res.data or []
        if not data:
            return {"ok": False, "error": "draft introuvable"}
        d = data[0]
        subject = d.get("subject") or ""
        final_body = body if body is not None else (d.get("body") or "")
        prospect = d.get("prospects") or {}
        to = ((prospect.get("emails") or [""])[0] or "").strip()
        if not to:
            return {"ok": False, "error": "pas d'email sur le prospect"}

        # 2) résout la config SMTP avant de toucher au statut
        smtp_cfg = shared_secrets.resolve_smtp_for_send(
            client=client, app_state=self._app_state)
        if not smtp_cfg:
            return {"ok": False,
                    "error": "config SMTP introuvable — rien envoyé"}

        # 3) statut → approved + body mis à jour
        try:
            sb.table("prospect_drafts").update({
                "body": final_body,
                "status": "approved",
                "approved_at": self._iso_now(),
                "approved_by": client.user_id,
            }).eq("id", draft_id).execute()
        except Exception as exc:
            return {"ok": False, "error": f"update KO : {exc}"}

        # 4) envoi SMTP
        try:
            msg_id = send_email(smtp_cfg, to=to,
                                 subject=subject, body=final_body)
        except Exception as exc:
            # Envoi KO → on remet en pending pour ne pas perdre le brouillon
            try:
                sb.table("prospect_drafts").update({
                    "status": "pending",
                }).eq("id", draft_id).execute()
            except Exception:
                pass
            return {"ok": False, "error": f"envoi KO : {exc}"}

        # 5) statut → sent + log email_history + prospect contacté
        try:
            sb.table("prospect_drafts").update({
                "status": "sent",
                "sent_at": self._iso_now(),
            }).eq("id", draft_id).execute()
        except Exception as exc:
            logger.warning("update draft sent KO: %s", exc)

        try:
            sb.table("email_history").insert(with_workspace(client, {
                "prospect_id": prospect.get("id"),
                "kind": "email_sent",
                "ts": self._iso_now(),
                "subject": subject[:200],
                "body": final_body[:5000],
                "message_id": msg_id,
                "extra": {"from_draft_id": draft_id,
                          "approved_from_sas": True},
                "created_by": client.user_id,
            })).execute()
        except Exception as exc:
            logger.warning("log email_history KO: %s", exc)

        try:
            sb.table("prospects").update({
                "status": "contacted",
                "last_contact_at": self._iso_now(),
            }).eq("id", prospect.get("id")).execute()
        except Exception as exc:
            logger.debug("update prospect after approve: %s", exc)

        return {"ok": True, "message_id": msg_id}

    # ----- convoy_drafts : approve = update body + status='approved' -----
    # (l'envoi est piloté par convoy_runner qui scrute les 'approved')
    def _approve_convoy_draft(self, draft_id: str, body) -> dict:
        if not draft_id:
            return {"ok": False, "error": "id manquant"}
        client = self._supabase_client_or_none()
        if client is None:
            return {"ok": False, "error": "Supabase non connecté"}
        try:
            update: dict = {"status": "approved"}
            if body is not None:
                update["body"] = body
            client.raw.table("convoy_drafts").update(update).eq(
                "id", draft_id).execute()
            return {"ok": True, "queued": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ----- ménage : supprime les coquilles pending sans contenu ---------
    def cleanup_empty_drafts(self, payload: dict | None = None) -> dict:
        """Supprime tous les drafts status='pending' sans subject ni body.

        Ce sont des prospects en attente de génération IA qui n'a jamais
        abouti — ils polluent le compteur et la file. Ne touche jamais
        aux drafts approuvés, envoyés, rejetés ou avec contenu.
        """
        client = self._supabase_client_or_none()
        if client is None:
            return {"ok": False, "error": "Supabase non connecté"}
        sb = client.raw
        deleted = {"prospect_drafts": 0, "convoy_drafts": 0}
        errors: list[str] = []

        for table in ("prospect_drafts", "convoy_drafts"):
            try:
                page_size = 500
                offset = 0
                empty_ids: list[str] = []
                while True:
                    res = (sb.table(table).select("id, subject, body")
                            .eq("status", "pending")
                            .range(offset, offset + page_size - 1).execute())
                    data = res.data or []
                    if not data:
                        break
                    for r in data:
                        if not (r.get("subject") or "").strip() \
                           and not (r.get("body") or "").strip():
                            empty_ids.append(r["id"])
                    if len(data) < page_size:
                        break
                    offset += page_size
                    if offset > 50000:
                        break
                # delete par lots de 100
                for i in range(0, len(empty_ids), 100):
                    batch = empty_ids[i:i + 100]
                    sb.table(table).delete().in_("id", batch).execute()
                deleted[table] = len(empty_ids)
            except Exception as exc:
                errors.append(f"{table}: {exc}")

        total = deleted["prospect_drafts"] + deleted["convoy_drafts"]
        return {
            "ok": not errors,
            "deleted": deleted,
            "total": total,
            "errors": errors,
        }

    def cleanup_broken_drafts(self, payload: dict | None = None) -> dict:
        """Supprime les drafts pending dont le corps ressemble a un refus IA
        (meta-analyse au lieu d'un mail : 'PROBLEME MAJEUR', 'Je ne peux pas
        rediger', 'Contradiction directe dans les consignes', etc.).

        Couvre les 3 sources :
          - Supabase prospect_drafts
          - Supabase convoy_drafts
          - CRM JSON local (prospect.pending_drafts)
        """
        try:
            from triskell_core.prospect.pipeline import _looks_like_ai_refusal
        except Exception as exc:
            return {"ok": False, "error": f"detection indispo : {exc}"}

        deleted = {"prospect_drafts": 0, "convoy_drafts": 0, "local": 0}
        errors: list[str] = []

        # === Supabase ===
        client = self._supabase_client_or_none()
        if client is not None:
            sb = client.raw
            for table in ("prospect_drafts", "convoy_drafts"):
                try:
                    page_size = 500
                    offset = 0
                    broken_ids: list[str] = []
                    while True:
                        res = (sb.table(table).select("id, subject, body")
                                .eq("status", "pending")
                                .range(offset, offset + page_size - 1).execute())
                        data = res.data or []
                        if not data:
                            break
                        for r in data:
                            body = (r.get("body") or "").strip()
                            if body and _looks_like_ai_refusal(body):
                                broken_ids.append(r["id"])
                        if len(data) < page_size:
                            break
                        offset += page_size
                        if offset > 50000:
                            break
                    for i in range(0, len(broken_ids), 100):
                        batch = broken_ids[i:i + 100]
                        sb.table(table).delete().in_("id", batch).execute()
                    deleted[table] = len(broken_ids)
                except Exception as exc:
                    errors.append(f"{table}: {exc}")

        # === CRM local ===
        try:
            from triskell_core.prospect.core.crm import CRM
            crm = CRM()
            n_local = 0
            for p in crm.all():
                if not p.pending_drafts:
                    continue
                kept = []
                for d in p.pending_drafts:
                    body = (d.get("body") or "").strip()
                    if body and _looks_like_ai_refusal(body):
                        n_local += 1
                    else:
                        kept.append(d)
                if len(kept) != len(p.pending_drafts):
                    p.pending_drafts = kept
                    crm._dirty = True  # noqa: SLF001
            if crm._dirty:  # noqa: SLF001
                crm.save()
            deleted["local"] = n_local
        except Exception as exc:
            errors.append(f"local: {exc}")

        total = deleted["prospect_drafts"] + deleted["convoy_drafts"] + deleted["local"]
        return {
            "ok": not errors,
            "deleted": deleted,
            "total": total,
            "errors": errors,
        }

    def cleanup_all_pending_drafts(self, payload: dict | None = None) -> dict:
        """Supprime TOUS les drafts pending, sans aucun filtre. Bouton "reset
        complet" -- utilise quand Jordan veut repartir d'une page blanche.

        Couvre : Supabase prospect_drafts, Supabase convoy_drafts, CRM local
        (prospect.pending_drafts).
        """
        deleted = {"prospect_drafts": 0, "convoy_drafts": 0, "local": 0}
        errors: list[str] = []

        client = self._supabase_client_or_none()
        if client is not None:
            sb = client.raw
            for table in ("prospect_drafts", "convoy_drafts"):
                try:
                    res = (sb.table(table).delete()
                            .eq("status", "pending")
                            .execute())
                    # supabase-py renvoie data = lignes supprimées
                    deleted[table] = len(res.data or [])
                except Exception as exc:
                    errors.append(f"{table}: {exc}")

        try:
            from triskell_core.prospect.core.crm import CRM
            crm = CRM()
            n_local = 0
            for p in crm.all():
                if p.pending_drafts:
                    n_local += len(p.pending_drafts)
                    p.pending_drafts = []
                    crm._dirty = True  # noqa: SLF001
            if crm._dirty:  # noqa: SLF001
                crm.save()
            deleted["local"] = n_local
        except Exception as exc:
            errors.append(f"local: {exc}")

        total = deleted["prospect_drafts"] + deleted["convoy_drafts"] + deleted["local"]
        return {
            "ok": not errors,
            "deleted": deleted,
            "total": total,
            "errors": errors,
        }

    # ----- reject Supabase ---------------------------------------------
    def _reject_supabase_draft(self, table: str, draft_id: str) -> dict:
        if not draft_id:
            return {"ok": False, "error": "id manquant"}
        client = self._supabase_client_or_none()
        if client is None:
            return {"ok": False, "error": "Supabase non connecté"}
        try:
            client.raw.table(table).update({"status": "rejected"}).eq(
                "id", draft_id).execute()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ----- fallback CRM local ------------------------------------------
    def _approve_local_draft(self, key: str, body) -> dict:
        try:
            from triskell_core.prospect.core.crm import CRM
            from triskell_core.prospect.pipeline import approve_draft
            # Capture les infos AVANT envoi : on en aura besoin apres
            # pour logger dans Supabase email_history (sans ca, le mail
            # part bien mais n'apparait pas dans la vue "Messages envoyes"
            # -- bug remonte par Jordan 2026-05-23).
            crm = CRM()
            target = next((x for x in crm.all()
                            if key in x.match_keys), None)
            captured = None
            if target and target.pending_drafts:
                if body is not None:
                    target.pending_drafts[0]["body"] = body
                    crm._dirty = True  # noqa
                    crm.save()
                d = target.pending_drafts[0]
                captured = {
                    "to":         (target.emails[0] if target.emails else ""),
                    "subject":    d.get("subject") or "",
                    "body":       d.get("body") or "",
                    "body_html":  d.get("body_html") or "",
                    "prospect_id": getattr(target, "id", "") or "",
                }
            res = approve_draft(key, draft_index=0)
            # Log Supabase si l'envoi a reussi : ainsi la vue Mails ->
            # Messages envoyes recupere bien le mail dans la base partagee.
            if res and res.get("ok") and captured:
                self._log_sent_email_to_history(
                    message_id=res.get("message_id") or "",
                    captured=captured,
                )
            return res
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _log_sent_email_to_history(self, *, message_id: str,
                                   captured: dict) -> None:
        """Insere une ligne email_sent dans Supabase email_history apres
        l'approbation d'un brouillon depuis l'autopilote. Tolerant : si
        Supabase est indisponible, on log mais on n'echoue pas (l'envoi
        SMTP a deja eu lieu)."""
        try:
            client = self._supabase()
            if not client:
                return
            sb = client.raw
            row = {
                "kind":       "email_sent",
                "ts":         self._iso_now(),
                "subject":    (captured.get("subject") or "")[:200],
                "body":       (captured.get("body") or "")[:5000],
                "message_id": message_id,
                "extra": {
                    "to":          captured.get("to") or "",
                    "to_all":      captured.get("to") or "",
                    "from":        "",   # le compte primary est utilise
                    "account_id":  "primary",
                    "has_html":    bool(captured.get("body_html")),
                    "body_html":   (captured.get("body_html") or "")[:50000],
                    "source":      "autopilot_draft_approve",
                },
                "created_by": getattr(client, "user_id", None),
            }
            if captured.get("prospect_id"):
                row["prospect_id"] = captured["prospect_id"]
            try:
                from ..integrations.multi_tenant import with_workspace
                row = with_workspace(client, row)
            except Exception:
                # with_workspace pas dispo dans ce contexte -> on continue
                # sans workspace_id (la base accepte NULL).
                pass
            sb.table("email_history").insert(row).execute()
        except Exception as exc:
            logger.warning(
                "log email_sent KO depuis approve_draft "
                "(le mail est parti, mais ne s'affichera pas dans "
                "Messages envoyes) : %s", exc
            )

    def _reject_local_draft(self, key: str) -> dict:
        try:
            from triskell_core.prospect.pipeline import reject_draft
            return reject_draft(key, draft_index=0)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Conversions (Funnel)
    # ------------------------------------------------------------------
    def get_funnel(self, payload: dict | None = None) -> dict:
        p = payload or {}
        try:
            from ..integrations import funnel_metrics
            return funnel_metrics.compute_funnel(
                period=p.get("period") or "30d",
                segment=p.get("segment") or "all",
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Projets clients
    # ------------------------------------------------------------------
    def get_clients(self) -> dict:
        try:
            from ..integrations import clients_repo
            grouped = clients_repo.list_grouped()
            return {"ok": True, "groups": grouped}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def client_create(self, payload: dict) -> dict:
        try:
            from ..integrations import clients_repo
            p = clients_repo.create_project(payload or {})
            return {"ok": bool(p), "project": p}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def client_update(self, payload: dict) -> dict:
        p = payload or {}
        try:
            from ..integrations import clients_repo
            ok = clients_repo.update_project(p.get("id") or "",
                                              p.get("patch") or {})
            return {"ok": ok}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def client_transition(self, payload: dict) -> dict:
        p = payload or {}
        try:
            from ..integrations import clients_repo
            ok = clients_repo.transition(p.get("id") or "",
                                          p.get("status") or "")
            return {"ok": ok}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def client_delete(self, payload: dict) -> dict:
        p = payload or {}
        try:
            from ..integrations import clients_repo
            ok = clients_repo.delete_project(p.get("id") or "")
            return {"ok": ok}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Fichier clients (table master `clients` — vue 360°)
    # ------------------------------------------------------------------
    def get_clients_master(self, payload: dict | None = None) -> dict:
        """Liste tous les clients (table master) avec compteurs agrégés.
        payload: { status?, search?, limit? }"""
        p = payload or {}
        try:
            from ..integrations import clients_master_repo as cm
            rows = cm.list_clients(
                status=(p.get("status") or None),
                search=(p.get("search") or ""),
                limit=int(p.get("limit") or 500),
            )
            return {"ok": True, "clients": rows, "total": len(rows)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_client_master(self, payload: dict) -> dict:
        """Fiche détaillée d'un client : ligne clients_360 + timeline."""
        p = payload or {}
        cid = (p.get("id") or "").strip()
        if not cid:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations import clients_master_repo as cm
            client = cm.get_client_360(cid)
            if not client:
                return {"ok": False, "error": "client introuvable"}
            timeline = cm.get_client_timeline(cid, limit=80)
            return {"ok": True, "client": client, "timeline": timeline}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def client_master_update(self, payload: dict) -> dict:
        """Met à jour les champs autorisés d'un client (whitelist côté repo)."""
        p = payload or {}
        cid = (p.get("id") or "").strip()
        patch = p.get("patch") or {}
        if not cid or not isinstance(patch, dict):
            return {"ok": False, "error": "payload invalide"}
        try:
            from ..integrations import clients_master_repo as cm
            ok = cm.update_client(cid, **patch)
            return {"ok": ok}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def client_master_add_tag(self, payload: dict) -> dict:
        p = payload or {}
        cid = (p.get("id") or "").strip()
        tag = (p.get("tag") or "").strip()
        if not cid or not tag:
            return {"ok": False, "error": "id et tag requis"}
        try:
            from ..integrations import clients_master_repo as cm
            ok = cm.add_tag(cid, tag)
            return {"ok": ok}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Réglages
    # ------------------------------------------------------------------
    def get_settings(self) -> dict:
        """Lit les settings : Supabase prioritaire (partagé Jordan ↔ Thomas),
        local fallback. Mots de passe masqués pour l'affichage."""
        from ..integrations import shared_secrets
        client = self._supabase()
        # SMTP/IMAP : Supabase d'abord, fallback local
        outreach = shared_secrets.get_smtp_config(
            client=client, app_state=self._app_state)
        if outreach.get("smtp_password"):
            outreach["smtp_password"] = "•" * 8
        if outreach.get("imap_password"):
            outreach["imap_password"] = "•" * 8
        # Clés IA : Supabase d'abord, fallback local
        keys_raw = shared_secrets.get_ai_keys(
            client=client, app_state=self._app_state)
        keys_masked = {p: ("•" * 8 if v else "") for p, v in keys_raw.items()}
        # On garantit la présence des providers connus dans l'UI
        for p in shared_secrets.PROVIDERS:
            keys_masked.setdefault(p, "")
        return {
            "ok": True,
            "appearance_mode": self.get_theme_mode(),
            "outreach": outreach,
            "ai": {"api_keys": keys_masked},
        }

    def save_setting(self, payload: dict) -> dict:
        """Sauve UNE clé : payload = {path: ['ai','api_keys','anthropic'], value: '...'}

        Si path commence par 'outreach.*' ou 'ai.api_keys.*', on miroir
        aussi dans shared_settings Supabase pour partager avec Thomas.
        """
        p = payload or {}
        path = p.get("path") or []
        value = p.get("value")
        if not path:
            return {"ok": False, "error": "no_path"}
        try:
            # 1) Sauve local (toujours)
            self._app_state.set(*path, value=value)
            self._app_state.save()

            # 2) Miroir vers shared_settings si pertinent
            from ..integrations import shared_secrets
            client = self._supabase()
            if client is not None:
                if path[0] == "outreach":
                    cfg = shared_secrets.get_smtp_config(client=client,
                                                         app_state=self._app_state)
                    cfg[path[1]] = value
                    shared_secrets.save_smtp_config(cfg, client=client,
                                                     app_state=self._app_state)
                elif path[0] == "ai" and len(path) >= 3 and path[1] == "api_keys":
                    keys = shared_secrets.get_ai_keys(client=client,
                                                      app_state=self._app_state)
                    keys[path[2]] = value
                    shared_secrets.save_ai_keys(keys, client=client,
                                                 app_state=self._app_state)
                    shared_secrets.sync_ai_keys_to_core(client=client,
                                                        app_state=self._app_state)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Le Phare — agence SEO autonome multi-sites
    # ------------------------------------------------------------------
    def phare_overview(self) -> dict:
        try:
            from ..integrations.phare import orchestrator
            return orchestrator.ecosystem_overview()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def phare_sites(self, payload: dict | None = None) -> dict:
        """Liste les sites Phare. Payload optionnel :
        - `external_only` (bool) : ne renvoie que les sites clients externes
        - `internal_only` (bool) : ne renvoie que les sites internes Triskell
        - `include_inactive` (bool) : inclut les sites désactivés
        """
        p = payload or {}
        try:
            from ..integrations.phare import repo
            sites = repo.list_sites(active_only=not bool(p.get("include_inactive")))
            if p.get("external_only"):
                sites = [s for s in sites if s.get("is_external_client")]
            elif p.get("internal_only"):
                sites = [s for s in sites if not s.get("is_external_client")]
            return {"ok": True, "sites": sites}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def phare_site(self, payload: dict) -> dict:
        sid = (payload or {}).get("id") or ""
        try:
            from ..integrations.phare import repo
            site = repo.get_site(sid)
            audit = repo.latest_audit(sid)
            kws = repo.list_keywords(sid, limit=50)
            actions = repo.list_actions(site_id=sid)
            briefs = repo.list_briefs(sid, limit=10)
            return {
                "ok": True,
                "site": site, "audit": audit, "keywords": kws,
                "actions": actions, "briefs": briefs,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def phare_pending_actions(self) -> dict:
        try:
            from ..integrations.phare import repo
            actions = repo.list_actions(status="pending_review")
            return {"ok": True, "actions": actions}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def phare_dashboard_pulse(self) -> dict:
        """Pulse de la salle de contrôle : tout d'un coup pour la home du Phare.

        Renvoie :
        - scheduler.running / last_tick_at / last_run_result
        - recent_actions : les 10 derniers événements (actions Phare)
        - pending_count : nombre de modifs en attente
        - sites_map : id → name (pour resolver site_id sans 2e appel)
        """
        out: dict = {"ok": True}
        # 1. Statut du scheduler en mémoire
        try:
            from ..integrations.phare import scheduler
            out["scheduler"] = scheduler.get_status()
        except Exception as exc:
            out["scheduler"] = {"running": False, "error": str(exc)}
        # 2. Dernières actions persistées (10 max, tous sites confondus)
        try:
            from ..integrations.phare import repo
            recent = repo.list_actions(limit=10) or []
            out["recent_actions"] = recent
            pending = [a for a in (repo.list_actions(limit=50) or [])
                       if (a.get("status") or "") == "pending_review"]
            out["pending_count"] = len(pending)
        except Exception as exc:
            out["recent_actions"] = []
            out["pending_count"] = 0
            out.setdefault("warnings", []).append(f"actions: {exc}")
        # 3. Map id → nom pour résoudre les site_id côté UI
        try:
            from ..integrations.phare import repo
            sites = repo.list_sites(active_only=False) or []
            out["sites_map"] = {s.get("id"): s.get("name") or s.get("domain")
                                for s in sites if s.get("id")}
        except Exception as exc:
            out["sites_map"] = {}
            out.setdefault("warnings", []).append(f"sites: {exc}")
        return out

    def phare_run_audit(self, payload: dict) -> dict:
        sid = (payload or {}).get("id") or ""
        # Lancement non-bloquant : on délègue à un thread
        try:
            from ..integrations.phare import orchestrator
            def _run():
                try: orchestrator.run_audit(sid, app_state=self._app_state)
                except Exception as exc: logger.warning("phare_run_audit: %s", exc)
            threading.Thread(target=_run, daemon=True,
                              name=f"PhareAudit-{sid[:8]}").start()
            return {"ok": True, "started": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def phare_merge_action(self, payload: dict) -> dict:
        aid = (payload or {}).get("id") or ""
        force = bool((payload or {}).get("force"))
        try:
            from ..integrations.phare import orchestrator
            return orchestrator.merge_action(aid, force=force)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def phare_reject_action(self, payload: dict) -> dict:
        """Refuse une recommandation : status → 'rejected'.

        Payload : { id: str, reason?: str }
        """
        aid = ((payload or {}).get("id") or "").strip()
        reason = ((payload or {}).get("reason") or "").strip()
        if not aid:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.phare import orchestrator
            return orchestrator.reject_action(aid, reason=reason)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def phare_archive_action(self, payload: dict) -> dict:
        """Cache une action 'merged' de la liste 'Ce qui a été fait'.

        Payload : { id: str }
        """
        aid = ((payload or {}).get("id") or "").strip()
        if not aid:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.phare import orchestrator
            return orchestrator.archive_action(aid)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def phare_home(self, payload: dict | None = None) -> dict:
        """Vue d'accueil 1-minute : 1 carte par site avec son état global.

        Renvoie pour chaque site :
        - id, name, domain, is_external_client, is_active
        - health (0-100 ou null) — Lighthouse SEO du dernier audit
        - health_tone : 'ok' (>=80) / 'warn' (50-79) / 'bad' (<50) / 'unknown'
        - clicks_30d, clicks_30d_prev, delta_pct (peut être null)
        - pending_count : actions en attente (draft + pending_review + preview)
        - has_bulletin : bulletin Analyste publié dans les dernières 24h
        - last_run_at : date du dernier passage d'un agent
        """
        p = payload or {}
        out: dict = {"ok": True, "sites": []}
        try:
            from ..integrations.phare import repo
            sites = repo.list_sites(active_only=not bool(p.get("include_inactive")))
            if p.get("external_only"):
                sites = [s for s in sites if s.get("is_external_client")]
            elif p.get("internal_only"):
                sites = [s for s in sites if not s.get("is_external_client")]
            for s in sites:
                sid = s.get("id")
                latest = repo.latest_audit(sid) or {}
                actions = repo.list_actions(site_id=sid, limit=100) or []
                pending = [a for a in actions
                           if (a.get("status") or "") in ("draft", "preview", "pending_review")]
                metrics30 = repo.metrics_window(sid, days=30) or []
                clicks30 = sum((m.get("organic_clicks") or 0) for m in metrics30)
                metrics_prev = []
                try:
                    metrics_prev = repo.metrics_window(sid, days=60) or []
                except Exception:
                    metrics_prev = []
                clicks_prev = sum((m.get("organic_clicks") or 0) for m in metrics_prev) - clicks30
                delta_pct = None
                if clicks_prev > 0:
                    delta_pct = round(((clicks30 - clicks_prev) / clicks_prev) * 100.0, 1)
                # Bulletin Analyste du jour ?
                from datetime import datetime as _dt, timedelta as _td
                cutoff = (_dt.now() - _td(hours=30)).isoformat()
                has_bull = any(
                    (a.get("agent") == "analyste") and ((a.get("created_at") or "") >= cutoff)
                    for a in actions
                )
                # Tone santé
                health = latest.get("lighthouse_seo")
                tone = "unknown"
                if isinstance(health, (int, float)):
                    if health >= 80: tone = "ok"
                    elif health >= 50: tone = "warn"
                    else: tone = "bad"
                # Dernier passage agent
                last_run = None
                if actions:
                    last_run = max((a.get("created_at") or "" for a in actions), default=None) or None
                out["sites"].append({
                    "id": sid,
                    "name": s.get("name") or s.get("domain"),
                    "domain": s.get("domain"),
                    "is_external_client": bool(s.get("is_external_client")),
                    "is_active": bool(s.get("is_active", True)),
                    "stack": s.get("stack") or "",
                    "priority": s.get("priority") or 50,
                    "health": health,
                    "health_tone": tone,
                    "clicks_30d": clicks30,
                    "delta_pct": delta_pct,
                    "pending_count": len(pending),
                    "has_bulletin": has_bull,
                    "last_run_at": last_run,
                })
            # Tri : priorité décroissante puis nom
            out["sites"].sort(key=lambda x: (-(x.get("priority") or 0),
                                             (x.get("name") or "").lower()))
            return out
        except Exception as exc:
            logger.warning("phare_home: %s", exc)
            return {"ok": False, "error": str(exc), "sites": []}

    def phare_site_dashboard(self, payload: dict) -> dict:
        """Vue détail 1-minute d'un site : tout en 1 appel.

        Renvoie :
        - site : ligne phare_sites complète
        - kpis : { clicks_30d, position_avg, health, delta_pct }
        - to_review : actions status in (draft, pending_review, preview), triées par impact
        - recently_done : actions status=merged (10 dernières)
        - rejected_recent : actions status=rejected (5 dernières)
        - bulletin : dernier bulletin Analyste (action kind=recommandation agent=analyste, 48h)
        - in_progress : missions en cours d'écriture (heuristique : draft sans contenu)
        """
        sid = ((payload or {}).get("id") or "").strip()
        if not sid:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.phare import repo
            from datetime import datetime as _dt, timedelta as _td
            site = repo.get_site(sid)
            if not site:
                return {"ok": False, "error": "site introuvable"}
            latest = repo.latest_audit(sid) or {}
            actions = repo.list_actions(site_id=sid, limit=200) or []
            metrics30 = repo.metrics_window(sid, days=30) or []
            clicks30 = sum((m.get("organic_clicks") or 0) for m in metrics30)
            positions = [m.get("avg_position") for m in metrics30
                         if isinstance(m.get("avg_position"), (int, float))]
            position_avg = round(sum(positions) / len(positions), 1) if positions else None
            metrics_prev_all = []
            try:
                metrics_prev_all = repo.metrics_window(sid, days=60) or []
            except Exception:
                pass
            clicks_prev = sum((m.get("organic_clicks") or 0) for m in metrics_prev_all) - clicks30
            delta_pct = None
            if clicks_prev > 0:
                delta_pct = round(((clicks30 - clicks_prev) / clicks_prev) * 100.0, 1)
            # Classification des actions
            to_review = []
            done = []
            rejected = []
            bulletin = None
            cutoff_bull = (_dt.now() - _td(hours=48)).isoformat()
            for a in actions:
                st = (a.get("status") or "").lower()
                if st in ("draft", "pending_review", "preview"):
                    to_review.append(a)
                elif st == "merged":
                    done.append(a)
                elif st == "rejected":
                    rejected.append(a)
                if (a.get("agent") == "analyste"
                        and (a.get("created_at") or "") >= cutoff_bull
                        and bulletin is None):
                    bulletin = a
            # Tri "à regarder" : impact desc puis date desc
            to_review.sort(key=lambda x: (-(x.get("impact") or 0),
                                          -(len(x.get("created_at") or ""))),)
            # Tone santé
            health = latest.get("lighthouse_seo")
            tone = "unknown"
            if isinstance(health, (int, float)):
                if health >= 80: tone = "ok"
                elif health >= 50: tone = "warn"
                else: tone = "bad"
            elif latest:
                # Un audit a tourné mais PageSpeed n'a pas renvoyé de note
                # (quota Google, site injoignable, etc.)
                tone = "failed"
            return {
                "ok": True,
                "site": site,
                "audit": latest,
                "kpis": {
                    "clicks_30d": clicks30,
                    "position_avg": position_avg,
                    "health": health,
                    "health_tone": tone,
                    "delta_pct": delta_pct,
                },
                "to_review": to_review[:20],
                "recently_done": done[:10],
                "rejected_recent": rejected[:5],
                "bulletin": bulletin,
            }
        except Exception as exc:
            logger.warning("phare_site_dashboard: %s", exc)
            return {"ok": False, "error": str(exc)}

    def phare_site_quick_add(self, payload: dict) -> dict:
        """Ajoute un site avec UNE seule info : son URL.

        Claude + un fetch HTML extraient nom, stack, pages clés, notes,
        externe/interne. Renvoie {ok, site, autoconfig} pour que l'UI
        puisse afficher ce qui a été détecté.
        """
        url = ((payload or {}).get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "URL manquante."}
        try:
            from ..integrations.phare import site_autoconfig, repo
            site_payload = site_autoconfig.build_site_payload(url, app_state=self._app_state)
            autoconfig = site_payload.pop("_autoconfig", {})
            row = repo.upsert_site(site_payload)
            if not row:
                return {"ok": False, "error": "Impossible d'enregistrer le site (Supabase non joignable)."}
            return {"ok": True, "site": row, "autoconfig": autoconfig}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.warning("phare_site_quick_add: %s", exc)
            return {"ok": False, "error": str(exc)}

    def phare_site_upsert(self, payload: dict) -> dict:
        """Crée ou met à jour un site dans Le Phare.

        Champs acceptés : id (optionnel pour edit), name, domain, repo_github,
        repo_branch_main, netlify_site_id, stack, priority, key_paths,
        notes, is_external_client, is_active.
        """
        p = payload or {}
        name = (p.get("name") or "").strip()
        domain = (p.get("domain") or "").strip().lower()
        if not name or not domain:
            return {"ok": False, "error": "Le nom et le domaine sont obligatoires."}
        try:
            from ..integrations.phare import repo
            site = {
                "name": name,
                "domain": domain,
                "repo_github": (p.get("repo_github") or "").strip() or None,
                "repo_branch_main": (p.get("repo_branch_main") or "main").strip(),
                "netlify_site_id": (p.get("netlify_site_id") or "").strip() or None,
                "stack": (p.get("stack") or "html").strip(),
                "priority": int(p.get("priority") or 50),
                "key_paths": p.get("key_paths") or ["/"],
                "notes": (p.get("notes") or "").strip(),
                "is_external_client": bool(p.get("is_external_client", False)),
                "is_active": bool(p.get("is_active", True)),
            }
            if p.get("id"):
                site["id"] = p["id"]
            row = repo.upsert_site(site)
            if not row:
                return {"ok": False, "error": "Impossible d'enregistrer le site (Supabase non joignable)."}
            return {"ok": True, "site": row}
        except Exception as exc:
            logger.warning("phare_site_upsert: %s", exc)
            return {"ok": False, "error": str(exc)}

    def phare_site_deactivate(self, payload: dict) -> dict:
        sid = (payload or {}).get("id") or ""
        if not sid:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.phare import repo
            ok = repo.deactivate_site(sid)
            return {"ok": ok}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def phare_site_activate(self, payload: dict) -> dict:
        """Réactive un site précédemment désactivé."""
        sid = (payload or {}).get("id") or ""
        if not sid:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.phare import repo
            row = repo.upsert_site({"id": sid, "is_active": True})
            return {"ok": True, "site": row}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def phare_agents_status(self) -> dict:
        """Renvoie le statut des 8 agents (nom, modèle, cadence, dernier passage).

        Lit `phare_actions` pour deviner le dernier run de chaque agent.
        Tolère l'absence de Supabase : renvoie le catalogue figé sans last_run.
        """
        catalog = [
            {"name": "auditeur", "label": "L'Auditeur Technique", "emoji": "🔍",
             "tagline": "Détecte tout ce qui freine.",
             "description": "Passe chaque site au peigne fin : pages lentes, balises manquantes, liens cassés, problèmes Core Web Vitals. Note de santé sur 100.",
             "missions": ["Analyser le crawl + Lighthouse + PageSpeed",
                          "Identifier les 5 problèmes critiques",
                          "Lister les quick wins (effort < 30 min)"],
             "cadence": "Lundi 6h-22h, 1 site par heure",
             "model": "claude-sonnet-4-6", "model_short": "Sonnet 4.6"},
            {"name": "veilleur", "label": "Le Veilleur Mots-Clés", "emoji": "🎯",
             "tagline": "Trouve les mots-clés qui payent.",
             "description": "Analyse tes positions GSC + les SERP concurrents pour repérer les mots-clés à fort potentiel. Construit le cocon sémantique.",
             "missions": ["10 mots-clés prioritaires (volume FR > 50)",
                          "20 long-traîne en cluster",
                          "Cocon sémantique (thème pivot + sous-thèmes)"],
             "cadence": "Lundi & jeudi 7h",
             "model": "claude-sonnet-4-6", "model_short": "Sonnet 4.6"},
            {"name": "redacteur", "label": "Le Rédacteur", "emoji": "✍️",
             "tagline": "Écrit comme un humain. Mieux.",
             "description": "Produit des articles SEO complets (1000-1500 mots) à partir des briefs du Veilleur. Voix Triskell, anti-slop activé.",
             "missions": ["Brief + article complet à partir d'un mot-clé",
                          "Structure H1/H2/H3 propre",
                          "Suggestions de maillage interne"],
             "cadence": "À la demande (déclenché par le Chef d'Orchestre)",
             "model": "claude-sonnet-4-6", "model_short": "Sonnet 4.6"},
            {"name": "optimiseur_onpage", "label": "L'Optimiseur On-Page", "emoji": "⚡",
             "tagline": "Affûte chaque page au scalpel.",
             "description": "Réécrit titres, meta descriptions, Hn, alts et JSON-LD pour booster le SEO sans toucher au contenu. Ouvre une PR auto.",
             "missions": ["Patches HTML balisés (title/meta/Hn/alt/JSON-LD)",
                          "Score avant/après estimé",
                          "PR GitHub + preview Netlify"],
             "cadence": "Mar/Mer/Ven 10h, 1 site par cycle",
             "model": "claude-sonnet-4-6", "model_short": "Sonnet 4.6"},
            {"name": "tisseur", "label": "Le Tisseur", "emoji": "🕸️",
             "tagline": "Relie tous tes sites en cocon.",
             "description": "Maillage interne intra-site + inter-sites Triskell. Détecte les pages orphelines, propose les liens manquants.",
             "missions": ["Liens internes manquants",
                          "Liens inter-sites Triskell (cocon global)",
                          "Pages orphelines à reconnecter"],
             "cadence": "Lundi 9h",
             "model": "claude-sonnet-4-6", "model_short": "Sonnet 4.6"},
            {"name": "chasseur_backlinks", "label": "Le Chasseur Backlinks", "emoji": "🪝",
             "tagline": "Va chercher les liens externes.",
             "description": "Analyse le gap concurrentiel, repère les mentions non-liées, identifie les opportunités HARO. Score d'impact 0-100.",
             "missions": ["Top 10 opportunités d'acquisition",
                          "5 HARO/expert quotes envisageables",
                          "5 mentions non-liées à transformer"],
             "cadence": "Mercredi 9h",
             "model": "claude-sonnet-4-6", "model_short": "Sonnet 4.6"},
            {"name": "analyste", "label": "L'Analyste", "emoji": "📊",
             "tagline": "Te dit la vérité chaque matin.",
             "description": "Lit tes métriques GSC sur 30 jours, repère les pages qui montent / descendent, chiffre le ROI des actions Phare.",
             "missions": ["Bulletin quotidien 8h (top 3 sites)",
                          "Pages qui décollent / décrochent",
                          "Recommandation pour la semaine"],
             "cadence": "Tous les jours 8h",
             "model": "claude-sonnet-4-6", "model_short": "Sonnet 4.6"},
            {"name": "chef_orchestre", "label": "Le Chef d'Orchestre", "emoji": "👑",
             "tagline": "Le cerveau stratégique. Opus.",
             "description": "Une fois par mois, le modèle le plus puissant prend tout l'écosystème en main et trace le plan du mois pour les 7 autres.",
             "missions": ["3 sites prioritaires du mois",
                          "1 chantier transverse",
                          "Briefs cadrés pour chaque agent",
                          "Critères de succès chiffrés"],
             "cadence": "1er du mois 9h",
             "model": "claude-opus-4-7", "model_short": "Opus 4.7"},
        ]
        # Tente d'enrichir avec le dernier run réel par agent
        try:
            from ..integrations.phare import repo
            for a in catalog:
                try:
                    last = repo.last_action_by_agent(a["name"])
                    if last:
                        a["last_run_at"] = last.get("created_at")
                        a["status"] = "ok"
                except Exception:
                    pass
        except Exception:
            pass
        return {"ok": True, "agents": catalog}

    def phare_run_agent(self, payload: dict) -> dict:
        """Lance la mission par défaut d'un agent en arrière-plan.

        Mappe le nom de l'agent vers une fonction orchestrator. Si l'agent
        nécessite un site précis et qu'aucun n'est fourni, prend le 1er
        actif par priorité.
        """
        agent = (payload or {}).get("agent") or ""
        site_id = (payload or {}).get("site_id") or ""
        if not agent:
            return {"ok": False, "error": "agent manquant"}
        try:
            from ..integrations.phare import orchestrator, repo
            # Choisit un site cible si non fourni
            if not site_id and agent != "chef_orchestre":
                sites = repo.list_sites(active_only=True) or []
                if not sites:
                    return {"ok": False, "error": "Aucun site actif à traiter."}
                site_id = sites[0]["id"]

            def _run():
                try:
                    if agent == "auditeur":
                        orchestrator.run_audit(site_id, app_state=self._app_state)
                    elif agent == "veilleur":
                        orchestrator.run_keywords(site_id, app_state=self._app_state)
                    elif agent == "optimiseur_onpage":
                        orchestrator.run_onpage_optim(site_id, app_state=self._app_state)
                    elif agent == "tisseur":
                        orchestrator.run_tisseur(site_id, app_state=self._app_state)
                    elif agent == "chasseur_backlinks":
                        orchestrator.run_backlinks(site_id, app_state=self._app_state)
                    elif agent == "analyste":
                        orchestrator.run_analyst(site_id, app_state=self._app_state)
                    elif agent == "chef_orchestre":
                        orchestrator.run_strategy(app_state=self._app_state)
                    elif agent == "redacteur":
                        # Rédacteur a besoin d'un mot-clé cible ; on lance un cycle veilleur d'abord
                        orchestrator.run_keywords(site_id, app_state=self._app_state)
                    else:
                        logger.warning("phare_run_agent: agent inconnu %s", agent)
                except Exception as exc:
                    logger.warning("phare_run_agent[%s]: %s", agent, exc)

            threading.Thread(target=_run, daemon=True,
                              name=f"PhareAgent-{agent}").start()
            return {"ok": True, "started": True, "agent": agent, "site_id": site_id}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Lagriffe — éditeur de templates de mail (4 mails du pipeline)
    # ------------------------------------------------------------------
    def lagriffe_mail_templates_list(self) -> dict:
        """Liste les 4 templates de mail Lagriffe, fusionnés avec les
        overrides Supabase et enrichis de leurs métadonnées (label, trigger,
        variables dispos)."""
        try:
            from ..integrations.lagriffe import mail_templates
            return {"ok": True, "templates": mail_templates.list_templates()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def lagriffe_mail_template_save(self, payload: dict) -> dict:
        """Sauvegarde un template de mail Lagriffe.

        Payload requis :
          - key (str)   : brief_received | preview_ready | payment_confirmed | site_delivered
          - subject (str)
          - preheader (str, optionnel)
          - eyebrow (str, optionnel)
          - title (str)
          - cta_label (str, optionnel)
          - cta_url (str, optionnel)
        """
        p = payload or {}
        key = (p.get("key") or "").strip()
        if not key:
            return {"ok": False, "error": "clé template manquante"}
        if not (p.get("subject") or "").strip():
            return {"ok": False, "error": "le sujet est obligatoire"}
        if not (p.get("title") or "").strip():
            return {"ok": False, "error": "le titre est obligatoire"}
        try:
            from ..integrations.lagriffe import mail_templates
            updated_by = ""
            try:
                cu = self.get_current_user() or {}
                updated_by = cu.get("display_name") or cu.get("email") or ""
            except Exception:
                pass
            row = mail_templates.save_template(key, p, updated_by=updated_by)
            if not row:
                return {"ok": False, "error": "impossible d'enregistrer (Supabase indispo ou clé inconnue)"}
            return {"ok": True, "template": row}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Studio WoW — validations et plomberie
    # ------------------------------------------------------------------
    def wow_list_intakes(self, payload: dict | None = None) -> dict:
        """Liste les intakes WoW. Payload optionnel : {status, limit}.

        Renvoie {ok: True, intakes: [...]}.
        """
        p = payload or {}
        status = (p.get("status") or "").strip() or None
        try:
            limit = int(p.get("limit") or 100)
        except (TypeError, ValueError):
            limit = 100
        try:
            from ..integrations.wow import repo as wow_repo
            rows = wow_repo.list_intakes(status=status, limit=limit)
            return {"ok": True, "intakes": rows}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def wow_get_intake(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        if not iid:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.wow import repo as wow_repo
            intake = wow_repo.get_intake(iid)
            if intake is None:
                return {"ok": False, "error": "intake introuvable"}
            timeline = wow_repo.intake_timeline(iid)
            return {"ok": True, "intake": intake, "timeline": timeline}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def wow_approve_intake(self, payload: dict) -> dict:
        """Approuve un intake : status → 'approved'. Le cron Netlify
        le ramassera dans les 5 minutes prochaines (ou on peut forcer
        avec wow_dispatch_now).
        """
        iid = ((payload or {}).get("id") or "").strip()
        if not iid:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.wow import repo as wow_repo
            ok = wow_repo.approve_intake(iid)
            return {"ok": bool(ok)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def wow_reject_intake(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        reason = ((payload or {}).get("reason") or "").strip()
        if not iid:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.wow import repo as wow_repo
            ok = wow_repo.reject_intake(iid, reason)
            return {"ok": bool(ok)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def wow_dispatch_now(self, payload: dict) -> dict:
        """Force le déclenchement immédiat du pipeline preview pour un
        intake déjà approved (sans attendre le cron 5 min).
        """
        iid = ((payload or {}).get("id") or "").strip()
        if not iid:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.wow import repo as wow_repo
            ok, msg = wow_repo.dispatch_now(iid)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def wow_pipeline_state(self) -> dict:
        """Renvoie l'état agrégé du pipeline WoW : compteurs par status
        + 5 dernières activités. Utilisé par la vue Plomberie en polling.
        """
        try:
            from ..integrations.wow import repo as wow_repo
            counts = wow_repo.count_by_status()
            recent = wow_repo.list_intakes(limit=5)
            return {"ok": True, "counts": counts, "recent": recent}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Vue Mails — lecture de la table email_history
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Signatures mail (multiples, locales par utilisateur)
    # ------------------------------------------------------------------
    # Stocke dans settings.json -> outreach.signatures = [
    #   {id, name, body_text, body_html, account_ids: ['primary', 'lagriffe']}
    # ]
    # Les anciens champs outreach.signature / signature_html servent toujours
    # de fallback (rétrocompatibilité avec l'ancienne version mono-signature).

    def _signatures_load(self) -> list[dict]:
        raw = self._app_state.get("outreach", "signatures", default=None)
        if isinstance(raw, list):
            return [s for s in raw if isinstance(s, dict) and s.get("id")]
        # Fallback : convertit l'ancienne signature unique en liste
        legacy_text = self._app_state.get("outreach", "signature", default="") or ""
        legacy_html = self._app_state.get("outreach", "signature_html", default="") or ""
        if legacy_text or legacy_html:
            return [{
                "id": "default",
                "name": "Ma signature",
                "body_text": legacy_text,
                "body_html": legacy_html,
                "account_ids": [],   # vide = s'applique à tous les comptes
            }]
        return []

    def _signatures_save(self, sigs: list[dict]) -> None:
        clean = [s for s in (sigs or []) if isinstance(s, dict) and s.get("id")]
        self._app_state.set("outreach", "signatures", value=clean)
        # Sync l'ancien champ pour compat (= 1ère signature par défaut)
        first = clean[0] if clean else {}
        self._app_state.set("outreach", "signature", value=first.get("body_text", ""))
        self._app_state.set("outreach", "signature_html", value=first.get("body_html", ""))
        self._app_state.save()

    def signatures_list(self) -> dict:
        """Renvoie toutes les signatures configurées."""
        return {"ok": True, "signatures": self._signatures_load()}

    def signature_for_account(self, payload: dict) -> dict:
        """Renvoie la signature à utiliser pour un compte donné.
        Stratégie : 1ère signature dont account_ids contient le compte,
        sinon 1ère signature sans contrainte (account_ids vide),
        sinon vide.
        """
        account_id = ((payload or {}).get("account_id") or "primary").strip()
        sigs = self._signatures_load()
        match = next((s for s in sigs if account_id in (s.get("account_ids") or [])), None)
        if match is None:
            match = next((s for s in sigs if not (s.get("account_ids") or [])), None)
        if match is None:
            return {"ok": True, "signature": None}
        return {"ok": True, "signature": match}

    def signature_save(self, payload: dict) -> dict:
        """Crée ou met à jour une signature. Si pas d'id → en crée une nouvelle.

        Payload : { signature: { id?, name, body_text?, body_html?, account_ids[] } }
        Backward-compat : si payload contient signature/signature_html directs,
        on les écrit dans la 1re signature ('default').
        """
        import uuid as _uuid
        p = payload or {}

        # Mode legacy : { signature: "text", signature_html: "html" } directs
        if "signature" in p and isinstance(p.get("signature"), str):
            sigs = self._signatures_load()
            if not sigs:
                sigs = [{"id": "default", "name": "Ma signature",
                         "body_text": "", "body_html": "", "account_ids": []}]
            sigs[0]["body_text"] = p.get("signature", "")
            if "signature_html" in p:
                sigs[0]["body_html"] = p.get("signature_html", "")
            try:
                self._signatures_save(sigs)
                return {"ok": True}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        # Mode nouveau : { signature: {dict complet} }
        sig = (p.get("signature") or {})
        if not isinstance(sig, dict):
            return {"ok": False, "error": "signature attendue (dict)"}
        sid = (sig.get("id") or "").strip() or _uuid.uuid4().hex[:10]
        name = (sig.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "Nom de signature requis."}
        new = {
            "id": sid,
            "name": name,
            "body_text": sig.get("body_text", ""),
            "body_html": sig.get("body_html", ""),
            "account_ids": [a for a in (sig.get("account_ids") or []) if isinstance(a, str)],
        }
        try:
            sigs = self._signatures_load()
            sigs = [s for s in sigs if s.get("id") != sid]
            sigs.append(new)
            self._signatures_save(sigs)
            return {"ok": True, "id": sid}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def signature_remove(self, payload: dict) -> dict:
        sid = ((payload or {}).get("id") or "").strip()
        if not sid:
            return {"ok": False, "error": "id manquant"}
        try:
            sigs = self._signatures_load()
            sigs = [s for s in sigs if s.get("id") != sid]
            self._signatures_save(sigs)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def signature_get(self) -> dict:
        """Backward-compat : renvoie la 1re signature au format legacy."""
        sigs = self._signatures_load()
        if not sigs:
            return {"ok": True, "signature": "", "signature_html": ""}
        first = sigs[0]
        return {
            "ok": True,
            "signature":      first.get("body_text", ""),
            "signature_html": first.get("body_html", ""),
        }

    # ------------------------------------------------------------------
    # Brain — boîte à idées partagée Jordan/Thomas (sync command-voice mobile)
    # ------------------------------------------------------------------
    def _brain_ai_keys(self) -> dict:
        try:
            from ..integrations import shared_secrets
            return shared_secrets.get_ai_keys(
                client=self._supabase(), app_state=self._app_state) or {}
        except Exception:
            return {}

    def brain_list(self, payload: dict | None = None) -> dict:
        p = payload or {}
        try:
            from ..integrations import brain
            client = self._supabase()
            notes = brain.list_notes(
                status=p.get("status") or None,
                category=p.get("category") or None,
                limit=int(p.get("limit") or 100),
                client=client,
            )
            return {"ok": True, "notes": notes}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def brain_list_by_category(self) -> dict:
        try:
            from ..integrations import brain
            return {"ok": True, "groups": brain.list_by_category(client=self._supabase())}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def brain_add(self, payload: dict) -> dict:
        p = payload or {}
        content = (p.get("content") or "").strip()
        attachments = [a for a in (p.get("attachments") or []) if a]
        analyze_images = bool(p.get("analyze_images"))
        if not content and not attachments:
            return {"ok": False, "error": "Note vide (ni texte ni image)."}
        try:
            from ..integrations import brain
            client = self._supabase()
            author = brain._user_alias(client)
            note = brain.add_note(content, author=author, client=client,
                                   ai_keys=self._brain_ai_keys(),
                                   attachments=attachments,
                                   analyze_images=analyze_images)
            if note is None:
                return {"ok": False, "error": "Insertion échouée"}
            return {"ok": True, "note": note}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def brain_upload(self, payload: dict) -> dict:
        """Upload d'un fichier (base64) → URL publique dans le bucket."""
        p = payload or {}
        data_b64 = (p.get("data") or "").strip()
        filename = (p.get("filename") or "upload.bin").strip()
        content_type = (p.get("content_type") or "").strip() or None
        if not data_b64:
            return {"ok": False, "error": "Fichier manquant"}
        try:
            import base64
            file_bytes = base64.b64decode(data_b64)
            # Garde-fou taille (10 Mo max)
            if len(file_bytes) > 10 * 1024 * 1024:
                return {"ok": False, "error": "Fichier > 10 Mo"}
            from ..integrations import brain
            url = brain.upload_attachment(file_bytes, filename,
                                           content_type=content_type,
                                           client=self._supabase())
            if not url:
                return {"ok": False, "error": "Upload échoué"}
            return {"ok": True, "url": url}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def brain_update(self, payload: dict) -> dict:
        p = payload or {}
        nid = (p.get("id") or "").strip()
        if not nid:
            return {"ok": False, "error": "id manquant"}
        patch = {}
        if "status" in p:     patch["status"] = p["status"]
        if "category" in p:   patch["category"] = p["category"]
        if "remind_at" in p:
            patch["remind_at"] = p["remind_at"]
            patch["reminded_at"] = None
        if "urgency" in p:
            try: patch["urgency"] = max(1, min(5, int(p["urgency"]))) if p["urgency"] is not None else None
            except Exception: pass
        if "importance" in p:
            try: patch["importance"] = max(1, min(5, int(p["importance"]))) if p["importance"] is not None else None
            except Exception: pass
        if not patch:
            return {"ok": False, "error": "Rien à mettre à jour"}
        try:
            from ..integrations import brain
            ok = brain.update_note(nid, patch, client=self._supabase())
            return {"ok": bool(ok)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def brain_process_reminders(self, payload: dict | None = None) -> dict:
        """Envoie les rappels push pour les notes dont remind_at est échu.
        À appeler périodiquement (cron / scheduled function)."""
        p = payload or {}
        dry = bool(p.get("dry_run"))
        try:
            from ..integrations import brain
            res = brain.process_reminders(client=self._supabase(), dry_run=dry)
            return {"ok": True, **res}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def brain_due_reminders(self, payload: dict | None = None) -> dict:
        """Liste les notes 'open' dont remind_at est échu ET pas encore
        marquées comme rappelées. Utilisé par le bandeau in-app qui se
        déclenche même quand les notifs push ne sont pas activées."""
        try:
            from ..integrations import brain
            from datetime import datetime, timezone
            sb = brain._sb(self._supabase())
            if sb is None:
                return {"ok": True, "notes": []}
            now_iso = datetime.now(timezone.utc).isoformat()
            rows = (sb.table(brain.TABLE).select("*")
                      .eq("status", "open")
                      .is_("reminded_at", "null")
                      .lte("remind_at", now_iso)
                      .order("remind_at", desc=False)
                      .limit(20)
                      .execute().data) or []
            # Filtre par destinataire : on ne ramène que les rappels qui
            # concernent l'utilisateur courant (assigned_to ou auteur).
            me = brain._user_alias(self._supabase())
            mine = [n for n in rows
                    if (n.get("assigned_to") or n.get("author") or me) == me
                    or n.get("assigned_to") in (None, "", me)]
            return {"ok": True, "notes": mine}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def brain_dismiss_reminder(self, payload: dict) -> dict:
        """Marque un rappel comme vu (sans toucher au statut de la note)."""
        p = payload or {}
        nid = (p.get("id") or "").strip()
        if not nid:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations import brain
            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).isoformat()
            ok = brain.update_note(nid, {"reminded_at": now_iso},
                                    client=self._supabase())
            return {"ok": bool(ok)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def brain_delete(self, payload: dict) -> dict:
        nid = ((payload or {}).get("id") or "").strip()
        if not nid:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations import brain
            return {"ok": bool(brain.delete_note(nid, client=self._supabase()))}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def brain_edit(self, payload: dict) -> dict:
        p = payload or {}
        nid = (p.get("id") or "").strip()
        content = (p.get("content") or "").strip()
        analyze_images = bool(p.get("analyze_images"))
        # attachments : si absent du payload → garde l'existant ; si présent (même vide) → remplace
        attachments = p.get("attachments")
        if attachments is not None:
            attachments = [a for a in attachments if a]
        if not nid:
            return {"ok": False, "error": "id manquant"}
        if not content and not (attachments or []):
            # autorisé si la note garde ses attachments existants
            if attachments is not None:
                return {"ok": False, "error": "Note vide (ni texte ni image)."}
        try:
            from ..integrations import brain
            note = brain.edit_content(nid, content, client=self._supabase(),
                                       ai_keys=self._brain_ai_keys(),
                                       attachments=attachments,
                                       analyze_images=analyze_images)
            if note is None:
                return {"ok": False, "error": "Édition échouée"}
            return {"ok": True, "note": note}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def brain_reply(self, payload: dict) -> dict:
        p = payload or {}
        nid = (p.get("id") or "").strip()
        content = (p.get("content") or "").strip()
        if not nid or not content:
            return {"ok": False, "error": "id et content requis"}
        try:
            from ..integrations import brain
            client = self._supabase()
            author = brain._user_alias(client)
            note = brain.add_reply(nid, content, author=author, client=client,
                                    ai_keys=self._brain_ai_keys())
            if note is None:
                return {"ok": False, "error": "Réponse échouée"}
            return {"ok": True, "note": note}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Templates HTML pour mails (réutilisables, partagés Jordan/Thomas)
    # ------------------------------------------------------------------
    # Stockage : shared_settings.mail_templates = {"templates": [...]}
    # Chaque template : { id, name, subject_default, body_html, updated_at }
    #
    # Préfixés `user_` pour éviter la collision de nom Python avec les
    # méthodes `mail_templates_*` plus bas (modèles système Lagriffe lus
    # depuis la table `triskell_email_templates`).
    def user_mail_templates_list(self) -> dict:
        try:
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            raw = client.get_shared_setting("mail_templates", {}) or {}
            if isinstance(raw, str):
                import json as _json
                try: raw = _json.loads(raw)
                except Exception: raw = {}
            templates = (raw.get("templates") if isinstance(raw, dict) else None) or []
            templates = [t for t in templates if isinstance(t, dict) and t.get("id")]
            templates.sort(key=lambda t: (t.get("name") or "").lower())
            return {"ok": True, "templates": templates}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def user_mail_template_save(self, payload: dict) -> dict:
        """Crée ou met à jour un template par id. Si id absent, génère un nouveau."""
        import uuid
        from datetime import datetime
        p = (payload or {}).get("template") or {}
        tid = (p.get("id") or "").strip() or uuid.uuid4().hex[:12]
        name = (p.get("name") or "").strip()
        body_html = p.get("body_html") or ""
        subject_default = (p.get("subject_default") or "").strip()
        if not name:
            return {"ok": False, "error": "Le nom du template est requis."}
        if not body_html.strip():
            return {"ok": False, "error": "Le contenu du template est vide."}
        try:
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            cur = self.user_mail_templates_list()
            templates = cur.get("templates", []) if cur.get("ok") else []
            templates = [t for t in templates if t.get("id") != tid]
            templates.append({
                "id": tid,
                "name": name,
                "subject_default": subject_default,
                "body_html": body_html,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
            client.set_shared_setting("mail_templates", {"templates": templates})
            return {"ok": True, "id": tid}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def user_mail_template_remove(self, payload: dict) -> dict:
        tid = ((payload or {}).get("id") or "").strip()
        if not tid:
            return {"ok": False, "error": "id manquant"}
        try:
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            cur = self.user_mail_templates_list()
            templates = cur.get("templates", []) if cur.get("ok") else []
            templates = [t for t in templates if t.get("id") != tid]
            client.set_shared_setting("mail_templates", {"templates": templates})
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _normalize_addr_list(val) -> list:
        """Normalise un champ cc/bcc en liste d'adresses uniques.
        Accepte : str ("a@x.fr, b@y.fr"), list, None."""
        if not val:
            return []
        if isinstance(val, str):
            parts = [p.strip() for p in val.replace(";", ",").split(",")]
        elif isinstance(val, (list, tuple)):
            parts = [str(p).strip() for p in val]
        else:
            return []
        out, seen = [], set()
        for p in parts:
            if p and "@" in p and p.lower() not in seen:
                seen.add(p.lower())
                out.append(p)
        return out

    def mail_send_reply(self, payload: dict) -> dict:
        """Backward-compat wrapper — utilise mail_send. À garder tant que la
        modale Mails > Répondre référence cet endpoint."""
        return self.mail_send(payload)

    def mail_send(self, payload: dict) -> dict:
        """Envoie un mail depuis l'un des comptes configurés.

        Payload :
          - account_id : id du compte expéditeur ('primary' ou autre)
          - to         : email destinataire (1 adresse, ou "a@x.fr, b@y.fr")
          - cc         (optionnel) : copies — string ou liste
          - bcc        (optionnel) : copies cachées — string ou liste
          - subject    : sujet
          - body       : corps en texte simple (toujours requis pour le fallback)
          - body_html  (optionnel) : version HTML, envoyée en multipart/alternative
          - in_reply_to (optionnel) : Message-ID du mail d'origine pour le threading
          - attachments (optionnel) : liste de { filename, content_b64, content_type,
              inline (bool), cid (str si inline=True) }. Les pièces inline sont
              attachées à la partie HTML via multipart/related ; les autres sont
              attachées au mail global via multipart/mixed.
        """
        p = payload or {}
        account_id = (p.get("account_id") or "primary").strip()
        to = (p.get("to") or "").strip()
        cc = self._normalize_addr_list(p.get("cc"))
        bcc = self._normalize_addr_list(p.get("bcc"))
        subject = (p.get("subject") or "").strip()
        body = (p.get("body") or "").strip()
        body_html = (p.get("body_html") or "").strip()
        in_reply_to = (p.get("in_reply_to") or "").strip()
        attachments = p.get("attachments") or []

        if not to or not subject:
            return {"ok": False, "error": "Champs requis manquants (to/subject)."}
        if not body and not body_html:
            return {"ok": False, "error": "Le message est vide."}
        if "@" not in to:
            return {"ok": False, "error": "Adresse destinataire invalide."}
        # Si HTML fourni mais pas de body texte, génère un fallback simple en
        # strippant les balises (les clients mail très anciens ne lisent que le plain)
        if body_html and not body:
            import re as _re
            body = _re.sub(r"<[^>]+>", "", body_html).strip()

        # Fix 5 : refus si variables non remplacees dans subject/body
        # (genre "Bonjour {name}" ou {{company}}). Bloque tout l'envoi.
        try:
            from ..integrations import prospect_status as PS
            safety = PS.mail_is_safe_to_send(subject, body or body_html)
            if not safety.get("ok"):
                return {
                    "ok": False,
                    "error": "Le mail contient des variables non remplies : "
                             + ", ".join(safety.get("unrendered") or [])
                             + ". Remplis-les avant d'envoyer.",
                    "unrendered": safety.get("unrendered") or [],
                }
        except Exception as exc:
            logger.debug("mail safety check skipped: %s", exc)

        # Warnings doux pour envoi manuel : adresse déjà contactée et/ou
        # présente dans la base clients. Pas de blocage dur — si l'UI re-poste
        # avec force=true, on ignore.
        if not bool(p.get("force")):
            try:
                from ..integrations import prospect_status as PS
                _client_for_check = self._supabase()
                all_addrs = [a.strip() for a in (to or "").split(",")
                             if a.strip()] + list(cc) + list(bcc)
                warns = PS.check_manual_send_warnings(
                    _client_for_check, *all_addrs)
                if warns:
                    return {"ok": False, "warnings": warns}
            except Exception as exc:
                logger.debug("manual send warnings KO: %s", exc)

        # Tracking d'ouvertures (pixel) — si l'utilisateur l'a active.
        # On injecte un <img> invisible dans le HTML du mail ; quand le
        # destinataire ouvre le mail, l'image hit la Netlify Function qui
        # ecrit dans email_events. tracking_id_for_log permet de retrouver
        # le mail au moment du hit.
        tracking_id_for_log = ""
        try:
            from ..integrations import email_tracker
            client_for_tracker = self._supabase()
            tcfg = email_tracker.load_config(client=client_for_tracker)
            if tcfg.get("enabled") and tcfg.get("pixel_endpoint"):
                tid = email_tracker.generate_tracking_id()
                tracking_id_for_log = tid
                prospect_id_hint = (payload or {}).get("prospect_id") or ""
                # Si pas de body_html, on en cree un (sinon impossible
                # d'injecter le pixel proprement)
                if not body_html and body:
                    body_html = email_tracker.wrap_plain_in_html(body)
                if body_html:
                    body_html = email_tracker.inject_into_html(
                        body_html,
                        email_tracker.build_pixel_html(
                            tid, tcfg.get("pixel_endpoint", ""),
                            prospect_id=prospect_id_hint),
                    )
        except Exception as exc:
            logger.debug("tracking pixel skipped: %s", exc)

        try:
            from ..integrations import shared_secrets
            client = self._supabase()

            acc = shared_secrets.get_account_by_id(
                account_id, client=client, app_state=self._app_state)
            if not acc:
                return {"ok": False, "error": f"Compte '{account_id}' introuvable."}
            smtp_host = acc.get("smtp_host", "")
            smtp_port = int(acc.get("smtp_port") or 587)
            smtp_user = acc.get("smtp_user", "")
            smtp_password = acc.get("smtp_password", "")
            from_email = acc.get("from_email", "")
            from_name = acc.get("from_name", "") or from_email
            for k, v in (("smtp_host", smtp_host), ("smtp_user", smtp_user),
                         ("smtp_password", smtp_password), ("from_email", from_email)):
                if not v:
                    return {"ok": False, "error": f"Config SMTP incomplète pour '{account_id}' (manque {k})."}

            # Construit l'EmailMessage (multipart/alternative si body_html dispo)
            from email.message import EmailMessage
            from email.utils import formatdate, make_msgid
            import smtplib, ssl

            msg = EmailMessage()
            msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
            msg["To"] = to
            if cc:
                msg["Cc"] = ", ".join(cc)
            if bcc:
                # smtplib.send_message lit Bcc pour les destinataires SMTP
                # puis retire le header avant envoi (RFC 5322 compliant).
                msg["Bcc"] = ", ".join(bcc)
            msg["Subject"] = subject
            msg["Date"] = formatdate(localtime=True)
            domain = from_email.split("@", 1)[1]
            msg_id = make_msgid(domain=domain)
            msg["Message-ID"] = msg_id
            msg["Reply-To"] = from_email
            if in_reply_to:
                irt = in_reply_to if in_reply_to.startswith("<") else f"<{in_reply_to}>"
                msg["In-Reply-To"] = irt
                msg["References"] = irt
            # Texte d'abord, HTML en alternative
            msg.set_content(body or " ")
            if body_html:
                msg.add_alternative(body_html, subtype="html")

            # ------------------------------------------------------------------
            # Pièces jointes
            # ------------------------------------------------------------------
            # Deux catégories :
            #   - inline (avec cid) : attachées à la partie HTML en multipart/related,
            #     référencées dans le HTML via <img src="cid:XXX">
            #   - normales : attachées au message global en multipart/mixed
            if attachments:
                import base64 as _b64
                inline_atts = [a for a in attachments
                               if isinstance(a, dict) and a.get("inline") and a.get("cid")]
                other_atts = [a for a in attachments
                              if isinstance(a, dict) and not (a.get("inline") and a.get("cid"))]

                # --- Inline (CID) : attachées au sous-message HTML ---
                if inline_atts and body_html:
                    html_part = None
                    try:
                        # msg.iter_parts() retourne les parts du multipart/alternative
                        for part in msg.iter_parts():
                            if part.get_content_type() == "text/html":
                                html_part = part
                                break
                    except Exception:
                        html_part = None
                    if html_part is not None:
                        for att in inline_atts:
                            try:
                                data = _b64.b64decode(att.get("content_b64") or "")
                            except Exception:
                                continue
                            if not data:
                                continue
                            ctype = (att.get("content_type") or "image/png").strip()
                            maintype, _, subtype = ctype.partition("/")
                            if not subtype:
                                maintype, subtype = "image", "png"
                            cid = att.get("cid") or ""
                            html_part.add_related(
                                data,
                                maintype=maintype,
                                subtype=subtype,
                                cid=f"<{cid}>",
                                filename=att.get("filename") or f"{cid}.{subtype}",
                            )

                # --- Pièces jointes normales (multipart/mixed) ---
                for att in other_atts:
                    try:
                        data = _b64.b64decode(att.get("content_b64") or "")
                    except Exception:
                        continue
                    if not data:
                        continue
                    ctype = (att.get("content_type") or "application/octet-stream").strip()
                    maintype, _, subtype = ctype.partition("/")
                    if not subtype:
                        maintype, subtype = "application", "octet-stream"
                    msg.add_attachment(
                        data,
                        maintype=maintype,
                        subtype=subtype,
                        filename=att.get("filename") or "fichier",
                    )

            # Envoi
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as s:
                    s.login(smtp_user, smtp_password)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as s:
                    s.ehlo()
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                    s.login(smtp_user, smtp_password)
                    s.send_message(msg)

            # Log dans email_history — CRITIQUE : alimente le compteur
            # "Envoyés aujourd'hui" du cockpit. Sans cette ligne, les KPIs
            # restent à 0. On loggue en warning si ça échoue (avant c'était
            # debug → invisible) pour qu'un futur bug ressorte vite.
            #
            # Comptage : 1 ligne par destinataire UNIQUE (To + Cc + Bcc).
            # Jordan veut tenir des stats par personne touchée, donc envoyer
            # à 3 adresses d'un coup = 3 lignes "email_sent" = compteur +3.
            if client:
                try:
                    sb = client.raw
                    # Construit la liste des destinataires uniques. On parse
                    # le champ To (qui peut etre "a@x.fr, b@y.fr") + Cc + Bcc.
                    to_list = [a.strip() for a in (to or "").split(",") if a.strip()]
                    all_recipients = []
                    seen = set()
                    for addr in (to_list + list(cc) + list(bcc)):
                        a = addr.strip().lower()
                        if a and a not in seen:
                            seen.add(a)
                            all_recipients.append(addr.strip())
                    if not all_recipients:
                        all_recipients = [to]  # filet de sécurité

                    now_iso = __import__("datetime").datetime.now().isoformat(
                        timespec="seconds")
                    # Workspace_id requis depuis migration 20 (multi-tenant).
                    ws_id = None
                    try:
                        ws_id = client._current_workspace_id()
                    except Exception:
                        pass

                    # On stocke le HTML et la liste légère des pièces jointes
                    # (sans le binaire base64) dans `extra` pour pouvoir afficher
                    # mise en forme + liste des PJ quand on rouvre un mail envoyé.
                    # Plafond HTML à ~80 Ko pour ne pas faire exploser la ligne.
                    _BODY_HTML_MAX = 80_000
                    body_html_log = body_html[:_BODY_HTML_MAX] if body_html else ""
                    attachments_meta = [
                        {
                            "filename": a.get("filename") or "",
                            "size": int(a.get("size") or 0),
                            "content_type": a.get("content_type") or "",
                            "inline": bool(a.get("inline")),
                            "cid": a.get("cid") or "",
                        }
                        for a in attachments if isinstance(a, dict)
                    ]
                    rows = []
                    for recipient in all_recipients:
                        extra_log = {
                            "to": recipient,
                            "to_all": ", ".join(all_recipients),
                            "recipients_count": len(all_recipients),
                            "from": from_email,
                            "account_id": account_id,
                            "in_reply_to": in_reply_to,
                            "manual_reply": bool(in_reply_to),
                            "has_html": bool(body_html),
                            "body_html": body_html_log,
                            "attachments_meta": attachments_meta,
                            "attachments_count": len([a for a in attachments_meta
                                if not a.get("inline")]),
                            "inline_images_count": len([a for a in attachments_meta
                                if a.get("inline") and a.get("cid")]),
                        }
                        if tracking_id_for_log:
                            extra_log["tracking_id"] = tracking_id_for_log
                        row = {
                            "kind": "email_sent",
                            "ts":   now_iso,
                            "subject": subject[:200],
                            "body":    body[:5000],
                            "message_id": msg_id,
                            "extra": extra_log,
                            "created_by": getattr(client, "user_id", None),
                        }
                        if ws_id:
                            row["workspace_id"] = ws_id
                        rows.append(row)
                    sb.table("email_history").insert(rows).execute()
                except Exception as exc:
                    logger.warning("log email_sent KO (compteur cockpit ne montera pas): %s", exc)

            return {"ok": True, "message_id": msg_id}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Mails programmés (envoi différé)
    # ------------------------------------------------------------------
    def mail_schedule(self, payload: dict) -> dict:
        """Programme un mail à envoyer plus tard. Mêmes champs que mail_send,
        avec en plus :
          - scheduled_at : ISO 8601 (avec timezone) — quand envoyer
        Le mail est stocké localement et envoyé par le worker
        scheduled_mail_runner quand l'heure est venue.
        """
        p = payload or {}
        to = (p.get("to") or "").strip()
        cc = self._normalize_addr_list(p.get("cc"))
        bcc = self._normalize_addr_list(p.get("bcc"))
        subject = (p.get("subject") or "").strip()
        body = (p.get("body") or "").strip()
        body_html = (p.get("body_html") or "").strip()
        scheduled_at = (p.get("scheduled_at") or "").strip()
        if not to or not subject:
            return {"ok": False, "error": "Champs requis manquants (to/subject)."}
        if not body and not body_html:
            return {"ok": False, "error": "Le message est vide."}
        if "@" not in to:
            return {"ok": False, "error": "Adresse destinataire invalide."}
        if not scheduled_at:
            return {"ok": False, "error": "Date d'envoi manquante."}
        # Validation de scheduled_at + futur
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt <= datetime.now(timezone.utc):
                return {"ok": False, "error": "La date doit être dans le futur."}
        except Exception:
            return {"ok": False, "error": "Date d'envoi invalide (format ISO 8601 attendu)."}

        # Warnings doux pour envoi manuel programmé (même règles que mail_send).
        # Si l'UI re-poste avec force=true, on ignore.
        if not bool(p.get("force")):
            try:
                from ..integrations import prospect_status as PS
                _client_for_check = self._supabase()
                all_addrs = [a.strip() for a in (to or "").split(",")
                             if a.strip()] + list(cc) + list(bcc)
                warns = PS.check_manual_send_warnings(
                    _client_for_check, *all_addrs)
                if warns:
                    return {"ok": False, "warnings": warns}
            except Exception as exc:
                logger.debug("manual schedule warnings KO: %s", exc)

        entry = {
            "account_id":   (p.get("account_id") or "primary").strip(),
            "to":           to,
            "cc":           cc,
            "bcc":          bcc,
            "subject":      subject,
            "body":         body,
            "body_html":    body_html,
            "in_reply_to":  (p.get("in_reply_to") or "").strip(),
            "attachments":  p.get("attachments") or [],
            "scheduled_at": scheduled_at,
            "status":       "pending",
        }
        try:
            from ..integrations import scheduled_mail_runner
            saved = scheduled_mail_runner.add(entry)
            if saved is None:
                return {"ok": False, "error": "Sauvegarde impossible."}
            return {"ok": True, "id": saved.get("id"), "scheduled_at": scheduled_at}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def mail_scheduled_list(self, payload: dict | None = None) -> dict:
        """Liste les mails programmés (pending). Si payload.include_done=True,
        inclut aussi sent / failed / cancelled."""
        p = payload or {}
        include_done = bool(p.get("include_done"))
        try:
            from ..integrations import scheduled_mail_runner
            return {"ok": True, "mails": scheduled_mail_runner.list_pending(include_done)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def prospect_generate_mail(self, payload: dict) -> dict:
        """Analyse l'URL d'un site cible et génère un mail de prospection
        personnalisé via Claude, en s'appuyant sur les modèles existants.

        Payload :
          - url      : URL du site (obligatoire)
          - category : 'celebrity' ou 'business' (par défaut 'business')

        Renvoie {ok, subject, body_html, target_name, used_template, ...}
        """
        p = payload or {}
        url = (p.get("url") or "").strip()
        category = (p.get("category") or "business").strip()
        subtype = (p.get("subtype") or "").strip()
        if not url:
            return {"ok": False, "error": "URL manquante."}
        if category not in ("celebrity", "business"):
            category = "business"
        # Subtype valide selon catégorie :
        #   - business    → 'template' | 'personalized'
        #   - celebrity   → 'sport' | 'influencer'
        valid_subs = {
            "business":  {"template", "personalized"},
            "celebrity": {"sport", "influencer"},
        }
        if subtype not in valid_subs.get(category, set()):
            subtype = "influencer" if category == "celebrity" else "personalized"
        # Récupère les modèles (best-effort)
        templates = []
        try:
            r = self.user_mail_templates_list()
            if r and r.get("ok"):
                templates = r.get("templates") or []
        except Exception as exc:
            logger.debug("templates fetch: %s", exc)
        # Clés IA depuis Supabase ou local
        ai_keys = {}
        try:
            from ..integrations import shared_secrets
            ai_keys = shared_secrets.get_ai_keys(
                client=self._supabase(), app_state=self._app_state) or {}
        except Exception as exc:
            logger.debug("ai_keys: %s", exc)
        try:
            from ..integrations import prospect_mail
            return prospect_mail.generate(url, category, templates, ai_keys,
                                          subtype=subtype)
        except Exception as exc:
            logger.exception("prospect_generate_mail failed")
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def mail_scheduled_cancel(self, payload: dict) -> dict:
        """Annule un mail programmé (s'il est encore pending)."""
        p = payload or {}
        mail_id = (p.get("id") or "").strip()
        if not mail_id:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations import scheduled_mail_runner
            ok = scheduled_mail_runner.cancel(mail_id)
            return {"ok": ok, "cancelled": ok}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Revenue overview (Stripe + AppSumo + manuel)
    # ------------------------------------------------------------------
    def revenue_overview(self, payload: dict | None = None) -> dict:
        """Agrège les paiements de toutes les sources et renvoie une vue
        consolidée (mois en cours, 7j, 30j, top clients, répartitions,
        prévisions).

        Sources :
          - email_history (kind=payment_received) pour Stripe / AppSumo
          - client_projects (cartes avec amount_cents et paid_at)
        """
        try:
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            now = _dt.now(_tz.utc)
            first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            first_of_prev_month = (first_of_month - _td(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            d7  = now - _td(days=7)
            d30 = now - _td(days=30)

            transactions = []

            # Source 1 : projets clients avec paid_at
            try:
                from ..integrations import clients_repo
                groups = clients_repo.list_grouped() or {}
                for status, items in groups.items():
                    for p in (items or []):
                        if not isinstance(p, dict):
                            continue
                        paid_at = p.get("paid_at") or p.get("created_at")
                        if not paid_at or not p.get("amount_cents"):
                            continue
                        try:
                            ts = _dt.fromisoformat(str(paid_at).replace("Z", "+00:00"))
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=_tz.utc)
                        except Exception:
                            continue
                        transactions.append({
                            "ts": ts,
                            "amount_cents": int(p.get("amount_cents") or 0),
                            "client_name": p.get("client_name") or "",
                            "client_email": p.get("client_email") or "",
                            "product": p.get("product_name") or p.get("title") or "",
                            "source": p.get("source") or ("stripe" if p.get("stripe_session_id")
                                                          else "appsumo" if p.get("appsumo_code")
                                                          else "manual"),
                        })
            except Exception as exc:
                logger.debug("revenue clients: %s", exc)

            # Source 2 : email_history kind=payment_received (best-effort)
            try:
                client = self._supabase()
                sb = client.raw if client else None
                if sb is not None:
                    res = (sb.table("email_history")
                            .select("ts,subject,extra")
                            .eq("kind", "payment_received")
                            .order("ts", desc=True)
                            .limit(500).execute())
                    for row in (res.data or []):
                        extra = row.get("extra") or {}
                        if not extra.get("amount_cents"):
                            continue
                        try:
                            ts = _dt.fromisoformat(str(row.get("ts")).replace("Z", "+00:00"))
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=_tz.utc)
                        except Exception:
                            continue
                        # On évite les doublons avec les projets (même client_email + même montant + même jour)
                        already = any(
                            t["client_email"] == extra.get("client_email", "")
                            and t["amount_cents"] == extra.get("amount_cents", 0)
                            and abs((t["ts"] - ts).total_seconds()) < 86400
                            for t in transactions
                        )
                        if already:
                            continue
                        transactions.append({
                            "ts": ts,
                            "amount_cents": int(extra.get("amount_cents") or 0),
                            "client_name": extra.get("client_name") or "",
                            "client_email": extra.get("client_email") or "",
                            "product": extra.get("product") or "",
                            "source": extra.get("source") or "stripe",
                        })
            except Exception as exc:
                logger.debug("revenue email_history: %s", exc)

            # Aggrégations
            def _filter(ts_start, ts_end=None):
                return [t for t in transactions
                        if t["ts"] >= ts_start and (ts_end is None or t["ts"] < ts_end)]
            cur_month = _filter(first_of_month)
            prev_month = _filter(first_of_prev_month, first_of_month)
            l7 = _filter(d7)
            l30 = _filter(d30)

            def _sum(items, by=None):
                if by is None:
                    return sum(t["amount_cents"] for t in items)
                buckets = {}
                for t in items:
                    key = t.get(by) or "other"
                    buckets[key] = buckets.get(key, 0) + t["amount_cents"]
                return buckets

            # Top clients du mois (agrégés par client_name)
            client_totals = {}
            for t in cur_month:
                key = t["client_name"] or t["client_email"] or "—"
                if key not in client_totals:
                    client_totals[key] = {"client_name": t["client_name"], "client_email": t["client_email"],
                                           "product": t["product"], "amount_cents": 0, "source": t["source"]}
                client_totals[key]["amount_cents"] += t["amount_cents"]
            top_clients = sorted(client_totals.values(), key=lambda x: x["amount_cents"], reverse=True)

            # Forecast pour la fin du mois (basique : extrapolation linéaire)
            days_in_month = (first_of_month + _td(days=32)).replace(day=1) - first_of_month
            days_elapsed = max((now - first_of_month).days + 1, 1)
            cur_total = _sum(cur_month)
            projected = int(cur_total * (days_in_month.days / days_elapsed)) if days_elapsed < days_in_month.days else cur_total

            # Marge basée sur intakes en pipeline
            pipeline_count = 0
            conv_rate = 0
            try:
                # Compte les intakes 'approved' / 'devis' qui pourraient closer ce mois
                # (estimation simple, sans détail des prix)
                from ..integrations import clients_repo as _cr
                groups = _cr.list_grouped() or {}
                pipeline_count = len(groups.get("briefing", [])) + len(groups.get("in_progress", []))
                # Conversion rate observée : closed_won / (closed_won + closed_lost) sur 90j
                conv_rate = 35  # estimation par défaut
            except Exception:
                pass

            label_for = lambda d: d.strftime("%B %Y").lower()

            return {
                "ok": True,
                "current_month": {
                    "label": label_for(first_of_month),
                    "total_cents": cur_total,
                    "transactions_count": len(cur_month),
                },
                "previous_month": {
                    "label": label_for(first_of_prev_month),
                    "total_cents": _sum(prev_month),
                    "transactions_count": len(prev_month),
                },
                "last_7_days":  {"total_cents": _sum(l7),  "transactions_count": len(l7)},
                "last_30_days": {"total_cents": _sum(l30), "transactions_count": len(l30)},
                "top_clients_month":  top_clients,
                "by_source_month":    _sum(cur_month, by="source"),
                "by_product_month":   _sum(cur_month, by="product"),
                "forecast": {
                    "projected_month_cents":   projected,
                    "confidence_low_cents":    int(projected * 0.8),
                    "confidence_high_cents":   int(projected * 1.2),
                    "pipeline_count":          pipeline_count,
                    "conversion_rate_pct":     conv_rate,
                },
            }
        except Exception as exc:
            logger.exception("revenue_overview")
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Backups locaux
    # ------------------------------------------------------------------
    def backup_run_now(self, payload: dict | None = None) -> dict:
        """Force un backup immédiat des données critiques."""
        try:
            from ..integrations import backup_runner
            return backup_runner.run_now(self._app_state)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def backup_list(self, payload: dict | None = None) -> dict:
        """Liste les backups disponibles."""
        try:
            from ..integrations import backup_runner
            return {"ok": True, "backups": backup_runner.list_backups()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def backup_preview(self, payload: dict) -> dict:
        """Renvoie un aperçu d'un backup donné (résumé, pas tout le contenu)."""
        p = payload or {}
        filename = (p.get("filename") or "").strip()
        try:
            from ..integrations import backup_runner
            data = backup_runner.read_backup(filename)
            if not data:
                return {"ok": False, "error": "Backup introuvable"}
            summary = {
                "ts": data.get("ts"),
                "templates_count":    len(data.get("mail_templates") or []),
                "signatures_count":   len(data.get("signatures") or []),
                "accounts_count":     len(data.get("mail_accounts") or []),
                "brain_notes_count":  len(data.get("brain_notes") or []),
                "scheduled_mails_count": len(data.get("scheduled_mails") or []) if isinstance(data.get("scheduled_mails"), list) else 0,
                "has_settings": bool(data.get("settings")),
                "has_display_names": bool(data.get("display_names")),
            }
            return {"ok": True, "summary": summary}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Signalement de bug (depuis le bouton flottant côté front)
    # ------------------------------------------------------------------
    def bug_report(self, payload: dict) -> dict:
        """Enregistre un rapport de bug envoyé depuis l'UI.

        Stocké dans ~/.triskell-command/bug_reports/YYYY-MM-DD-HHMMSS.txt
        (best-effort). On peut brancher un envoi mail/Supabase plus tard.
        """
        try:
            from datetime import datetime as _dt
            from pathlib import Path as _P
            p = payload or {}
            base = _P.home() / ".triskell-command" / "bug_reports"
            base.mkdir(parents=True, exist_ok=True)
            ts = _dt.now().strftime("%Y-%m-%d-%H%M%S")
            path = base / f"bug-{ts}.txt"
            full = (p.get("full_report") or "").strip()
            if not full:
                # Reconstruit un rapport minimal depuis context+message
                full = (
                    f"Date : {ts}\n\n"
                    f"Message : {p.get('message') or '(vide)'}\n\n"
                    f"Context : {p.get('context') or {}}\n"
                )
            path.write_text(full, encoding="utf-8")
            logger.info("bug_report écrit : %s", path.name)

            # Capture d'écran jointe (data URL base64) — écrite à côté du .txt
            screenshot = p.get("screenshot")
            screenshot_filename = None
            if isinstance(screenshot, str) and screenshot.startswith("data:image/"):
                try:
                    import base64 as _b64
                    header, _, b64data = screenshot.partition(",")
                    mime = header.split(";")[0].replace("data:", "") or "image/png"
                    ext = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/gif": "gif", "image/webp": "webp"}.get(mime, "png")
                    img_path = base / f"bug-{ts}.{ext}"
                    img_path.write_bytes(_b64.b64decode(b64data))
                    screenshot_filename = img_path.name
                    logger.info("bug_report capture jointe : %s", img_path.name)
                except Exception:
                    logger.exception("bug_report capture")

            # TODO V2 : envoyer un mail à contact@triskell-studio.fr
            return {"ok": True, "filename": path.name, "screenshot": screenshot_filename}
        except Exception as exc:
            logger.exception("bug_report")
            return {"ok": False, "error": str(exc)}

    def mail_delete(self, payload: dict) -> dict:
        """Supprime une entrée d'email_history (mail envoyé / reçu).
        Ne supprime que la trace locale — n'agit pas sur la boîte mail distante.
        """
        mid = ((payload or {}).get("id") or "").strip()
        if not mid:
            return {"ok": False, "error": "id manquant"}
        try:
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            client.raw.table("email_history").delete().eq("id", mid).execute()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def mails_delete(self, payload: dict) -> dict:
        """Supprime plusieurs entrées d'email_history en une seule requête.
        Utilisé par la sélection multiple côté UI (cases à cocher).
        """
        ids = (payload or {}).get("ids") or []
        if not isinstance(ids, (list, tuple)):
            return {"ok": False, "error": "ids doit être une liste"}
        ids = [str(i).strip() for i in ids if str(i).strip()]
        if not ids:
            return {"ok": False, "error": "Aucun id fourni."}
        try:
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            client.raw.table("email_history").delete().in_("id", ids).execute()
            return {"ok": True, "deleted": len(ids)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def mails_list(self, payload: dict | None = None) -> dict:
        """Liste les mails enregistrés dans email_history.

        Payload :
          - kind : 'sent' | 'reply' | 'all'
          - limit : nombre max (défaut 50)
          - account_id : filtre sur extra.account_id (depuis phase 2 multi-comptes)
        """
        p = payload or {}
        kind = (p.get("kind") or "all").strip()
        account_id = (p.get("account_id") or "").strip()
        try: limit = int(p.get("limit") or 50)
        except (TypeError, ValueError): limit = 50
        try:
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            # Avant : getattr(client, "client") or getattr(client, "_client")
            # — pattern fragile qui retourne None tant que _ensure_sdk()
            # n'a pas ete declenche ailleurs. On utilise client.raw qui
            # garantit l'init du SDK.
            sb = client.raw
            q = (sb.table("email_history")
                 .select("id,kind,ts,subject,body,prospect_id,message_id,extra")
                 .order("ts", desc=True).limit(limit))
            if kind == "sent":
                q = q.eq("kind", "email_sent")
            elif kind == "reply":
                q = q.eq("kind", "reply_received")
            elif kind == "inbound":
                # Tous entrants = réponses prospects + autres entrants logs
                q = q.in_("kind", ["reply_received", "inbox_received"])
            if account_id:
                # PostgREST : filtre sur un champ d'un JSON column
                q = q.eq("extra->>account_id", account_id)
            mails = q.execute().data or []
            return {"ok": True, "mails": mails}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Comptes mail secondaires (en plus du compte principal smtp_config)
    # ------------------------------------------------------------------
    def mail_accounts_list(self) -> dict:
        """Renvoie tous les comptes mail (primary + secondaires), sans
        les mots de passe (juste un flag _has_smtp_pwd / _has_imap_pwd).
        """
        try:
            from ..integrations import shared_secrets
            client = self._supabase()
            return {"ok": True, "accounts": shared_secrets.get_all_mail_accounts(
                client=client, app_state=self._app_state)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def mail_account_save(self, payload: dict) -> dict:
        """Ajoute ou met à jour un compte secondaire. Pour le compte
        principal (id=primary), utiliser save_outreach_config().
        """
        try:
            from ..integrations import shared_secrets
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            acc = (payload or {}).get("account") or {}
            if not acc.get("id"):
                return {"ok": False, "error": "id manquant"}
            if acc.get("id") == "primary":
                return {"ok": False, "error": "Le compte principal se modifie via les Réglages SMTP/IMAP existants."}
            ok = shared_secrets.add_or_update_mail_account(acc, client=client)
            return {"ok": bool(ok)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def mail_account_remove(self, payload: dict) -> dict:
        try:
            from ..integrations import shared_secrets
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            aid = ((payload or {}).get("id") or "").strip()
            if not aid:
                return {"ok": False, "error": "id manquant"}
            ok = shared_secrets.remove_mail_account(aid, client=client)
            return {"ok": bool(ok)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def mail_account_test(self, payload: dict) -> dict:
        """Teste la connexion SMTP+IMAP d'un compte (par id ou par dict).
        Renvoie {ok: bool, smtp: bool, imap: bool, error: str}.
        """
        import smtplib, imaplib, ssl
        try:
            from ..integrations import shared_secrets
            client = self._supabase()
            payload = payload or {}
            acc = payload.get("account")
            if not acc and payload.get("id"):
                acc = shared_secrets.get_account_by_id(
                    payload["id"], client=client, app_state=self._app_state)
            if not acc:
                return {"ok": False, "error": "compte introuvable"}
            out = {"ok": True, "smtp": False, "imap": False, "error": ""}
            ctx = ssl.create_default_context()
            # SMTP
            try:
                with smtplib.SMTP(acc.get("smtp_host", ""),
                                   int(acc.get("smtp_port") or 587), timeout=10) as s:
                    s.starttls(context=ctx)
                    s.login(acc.get("smtp_user", ""), acc.get("smtp_password", ""))
                out["smtp"] = True
            except Exception as exc:
                out["error"] = f"SMTP: {exc}"
            # IMAP
            try:
                with imaplib.IMAP4_SSL(acc.get("imap_host", ""),
                                        int(acc.get("imap_port") or 993)) as i:
                    i.login(acc.get("imap_user", ""), acc.get("imap_password", ""))
                out["imap"] = True
            except Exception as exc:
                out["error"] = (out["error"] + f" · IMAP: {exc}").strip(" ·")
            out["ok"] = out["smtp"] and out["imap"]
            return out
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Auth Supabase — login utilisateur, restore session, sign out
    # ------------------------------------------------------------------
    def auth_status(self) -> dict:
        """Renvoie l'état de la session Supabase. Essaie de restaurer si
        non authentifié mais des tokens existent sur disque.
        """
        try:
            from triskell_core.db import get_client, SupabaseNotConfigured
            try:
                c = get_client()
            except SupabaseNotConfigured:
                return {"ok": True, "connected": False, "reason": "supabase_not_configured"}
            if not c.is_authenticated:
                try: c.restore_session()
                except Exception as exc:
                    logger.debug("auth_status restore: %s", exc)
            if not c.is_authenticated:
                return {"ok": True, "connected": False, "reason": "no_session"}
            return {
                "ok": True,
                "connected": True,
                "user_id": getattr(c, "user_id", None),
                "display_name": getattr(c, "user_display_name", None),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def auth_sign_in(self, payload: dict) -> dict:
        """Connecte un utilisateur Supabase via email/mot de passe."""
        email = ((payload or {}).get("email") or "").strip()
        password = ((payload or {}).get("password") or "").strip()
        if not email or not password:
            return {"ok": False, "error": "email et mot de passe requis"}
        try:
            from triskell_core.db import get_client, SupabaseNotConfigured
            try:
                c = get_client()
            except SupabaseNotConfigured:
                return {"ok": False, "error": "Supabase non configuré (manque url/anon_key dans settings.json)"}
            try:
                info = c.sign_in(email, password)
                return {"ok": True, **(info or {})}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def auth_sign_out(self) -> dict:
        try:
            from triskell_core.db import get_client, SupabaseNotConfigured
            try:
                c = get_client()
            except SupabaseNotConfigured:
                return {"ok": True, "connected": False}
            c.sign_out()
            return {"ok": True, "connected": False}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # RankUs Studio — mêmes endpoints que WoW, sur la table rankus_intakes
    # ------------------------------------------------------------------
    def rankus_list_intakes(self, payload: dict | None = None) -> dict:
        p = payload or {}
        status = (p.get("status") or "").strip() or None
        try: limit = int(p.get("limit") or 100)
        except (TypeError, ValueError): limit = 100
        try:
            from ..integrations.rankus import repo as r
            return {"ok": True, "intakes": r.list_intakes(status=status, limit=limit)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def rankus_get_intake(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.rankus import repo as r
            intake = r.get_intake(iid)
            if intake is None: return {"ok": False, "error": "intake introuvable"}
            return {"ok": True, "intake": intake, "timeline": r.intake_timeline(iid)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def rankus_approve_intake(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.rankus import repo as r
            return {"ok": bool(r.approve_intake(iid))}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def rankus_reject_intake(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        reason = ((payload or {}).get("reason") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.rankus import repo as r
            return {"ok": bool(r.reject_intake(iid, reason))}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def rankus_dispatch_now(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.rankus import repo as r
            ok, msg = r.dispatch_now(iid)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def rankus_pipeline_state(self) -> dict:
        try:
            from ..integrations.rankus import repo as r
            return {"ok": True, "counts": r.count_by_status(), "recent": r.list_intakes(limit=5)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Lagriffe Studio — mêmes endpoints + approve_final_and_send (validation
    # humaine du site final avant envoi du mail au client)
    # ------------------------------------------------------------------
    def lagriffe_list_intakes(self, payload: dict | None = None) -> dict:
        p = payload or {}
        status = (p.get("status") or "").strip() or None
        try: limit = int(p.get("limit") or 100)
        except (TypeError, ValueError): limit = 100
        try:
            from ..integrations.lagriffe import repo as r
            return {"ok": True, "intakes": r.list_intakes(status=status, limit=limit)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def lagriffe_get_intake(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.lagriffe import repo as r
            intake = r.get_intake(iid)
            if intake is None: return {"ok": False, "error": "intake introuvable"}
            return {"ok": True, "intake": intake, "timeline": r.intake_timeline(iid)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def lagriffe_approve_intake(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.lagriffe import repo as r
            return {"ok": bool(r.approve_intake(iid))}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def lagriffe_reject_intake(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        reason = ((payload or {}).get("reason") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.lagriffe import repo as r
            return {"ok": bool(r.reject_intake(iid, reason))}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def lagriffe_dispatch_now(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.lagriffe import repo as r
            ok, msg = r.dispatch_now(iid)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def lagriffe_pipeline_state(self) -> dict:
        try:
            from ..integrations.lagriffe import repo as r
            return {"ok": True, "counts": r.count_by_status(), "recent": r.list_intakes(limit=5)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def lagriffe_approve_final(self, payload: dict) -> dict:
        """Valide le site final (status final_ready_review) et déclenche
        l'envoi du mail final au client. Status → 'live'.
        """
        iid = ((payload or {}).get("id") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.lagriffe import repo as r
            ok, msg = r.approve_final_and_send(iid)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def lagriffe_finalize_now(self, payload: dict) -> dict:
        """Forcer la finalisation manuelle d'un intake 'paid' (utilisé quand
        le toggle 'paid' est en mode MANUEL, Jordan déclenche depuis la vue
        Pipeline → panneau 'En attente de ton action').
        """
        iid = ((payload or {}).get("id") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.lagriffe import repo as r
            # On appelle directement l'endpoint Netlify finalize-site-build
            ok, msg = r.trigger_finalize(iid)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Pipeline settings (toggles AUTO/MANUEL par produit × étape)
    # ------------------------------------------------------------------
    def pipeline_settings_read(self, payload: dict | None = None) -> dict:
        """Lit les modes auto/manuel pour un produit (lagriffe / rankus / wow)
        depuis Supabase via la table triskell_pipeline_settings."""
        product = ((payload or {}).get("product") or "lagriffe").strip()
        try:
            from ..integrations.lagriffe import repo as r
            return r.pipeline_settings_read(product)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pipeline_settings_write(self, payload: dict) -> dict:
        """Met à jour le mode auto/manuel pour (product, stage).
        Synchrone avec Supabase — le backend Netlify lira cette valeur au
        prochain check (cache 60s)."""
        product = ((payload or {}).get("product") or "").strip()
        stage   = ((payload or {}).get("stage") or "").strip()
        mode    = ((payload or {}).get("mode") or "").strip()
        if product not in ("lagriffe", "rankus", "wow"):
            return {"ok": False, "error": "product invalide"}
        if stage not in ("approved", "paid", "final_ready_review"):
            return {"ok": False, "error": "stage invalide"}
        if mode not in ("auto", "manual"):
            return {"ok": False, "error": "mode invalide"}
        try:
            from ..integrations.lagriffe import repo as r
            updated_by = self.get_user_name() or "triskell-command"
            return r.pipeline_settings_write(product, stage, mode, updated_by)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Pixel Pros — pipeline (draft → paid → building → live)
    # ------------------------------------------------------------------
    def pixelpros_list_intakes(self, payload: dict | None = None) -> dict:
        p = payload or {}
        status = (p.get("status") or "").strip() or None
        try: limit = int(p.get("limit") or 100)
        except (TypeError, ValueError): limit = 100
        try:
            from ..integrations.pixelpros import repo as r
            return {"ok": True, "intakes": r.list_intakes(status=status, limit=limit)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_get_intake(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.pixelpros import repo as r
            intake = r.get_intake(iid)
            if intake is None: return {"ok": False, "error": "intake introuvable"}
            return {"ok": True, "intake": intake, "timeline": r.intake_timeline(iid)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_dispatch_build(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.pixelpros import repo as r
            ok, msg = r.dispatch_build(iid)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_mark_failed(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        reason = ((payload or {}).get("reason") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.pixelpros import repo as r
            return {"ok": bool(r.mark_failed(iid, error_message=reason))}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_delete_intake(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.pixelpros import repo as r
            ok, msg = r.delete_intake(iid)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_mark_paid_manual(self, payload: dict) -> dict:
        """Override manuel : passe un draft au statut paid sans Stripe."""
        iid = ((payload or {}).get("id") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.pixelpros import repo as r
            ok, msg = r.mark_paid_manual(iid)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_simulate_full_flow(self, payload: dict) -> dict:
        """Simule un paiement Stripe complet : passe en 'paid', envoie le mail
        'paiement reçu', et lance la construction. Le mail 'site en ligne'
        sera envoyé tout seul à la fin du build (via on_built).

        Force l'envoi du mail même si le toggle Auto est désactivé
        (l'utilisateur a explicitement demandé à tout lancer).
        """
        iid = ((payload or {}).get("id") or "").strip()
        if not iid:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.pixelpros import repo as r, mailer as m
            intake = r.get_intake(iid)
            if intake is None:
                return {"ok": False, "error": "intake introuvable"}
            steps = []

            # 1. Mark paid (sauf si déjà au-delà)
            if intake.get("status") == "draft":
                ok_paid, msg_paid = r.mark_paid_manual(iid)
                steps.append({"step": "paid", "ok": ok_paid, "message": msg_paid})
                if not ok_paid:
                    return {"ok": False, "steps": steps, "error": f"paid: {msg_paid}"}
                # refresh intake pour avoir les bons champs (stripe_paid_at)
                intake = r.get_intake(iid) or intake
            else:
                steps.append({"step": "paid", "ok": True, "message": "déjà payé"})

            # 2. Mail paiement reçu (forcé même si toggle manuel)
            ok_mail, msg_mail = m.send_paid_mail(intake)
            steps.append({"step": "paid_mail", "ok": ok_mail, "message": msg_mail})

            # 3. Dispatch build
            ok_build, msg_build = r.dispatch_build(iid)
            steps.append({"step": "build", "ok": ok_build, "message": msg_build})

            all_ok = all(s["ok"] for s in steps)
            return {"ok": all_ok, "steps": steps,
                    "message": "Tout déclenché." if all_ok
                               else "Lancé avec des avertissements (voir détails)."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ----- Templates mails Pixel Pros (paid / live) -----
    def pixelpros_mail_template_get(self, payload: dict | None = None) -> dict:
        kind = ((payload or {}).get("kind") or "").strip()
        if kind not in ("paid", "live"):
            return {"ok": False, "error": "kind invalide (attendu 'paid' ou 'live')"}
        try:
            from ..integrations.pixelpros import mailer as m
            return {"ok": True, "template": m.load_template(kind)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_mail_template_save(self, payload: dict) -> dict:
        p = payload or {}
        kind = (p.get("kind") or "").strip()
        subject = (p.get("subject") or "").strip()
        body_text = p.get("body_text") or ""
        body_html = p.get("body_html") or ""
        if kind not in ("paid", "live"):
            return {"ok": False, "error": "kind invalide"}
        try:
            from ..integrations.pixelpros import mailer as m
            ok, msg = m.save_template(kind, subject, body_text, body_html)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_mail_template_reset(self, payload: dict) -> dict:
        kind = ((payload or {}).get("kind") or "").strip()
        if kind not in ("paid", "live"):
            return {"ok": False, "error": "kind invalide"}
        try:
            from ..integrations.pixelpros import mailer as m
            ok, msg = m.reset_template(kind)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_pipeline_state(self) -> dict:
        try:
            from ..integrations.pixelpros import repo as r
            return {"ok": True, "counts": r.count_by_status(),
                    "recent": r.list_intakes(limit=5)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_resend_paid_mail(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.pixelpros import repo as r, mailer as m
            intake = r.get_intake(iid)
            if not intake: return {"ok": False, "error": "intake introuvable"}
            ok, msg = m.send_paid_mail(intake)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_resend_live_mail(self, payload: dict) -> dict:
        iid = ((payload or {}).get("id") or "").strip()
        if not iid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.pixelpros import repo as r, mailer as m
            intake = r.get_intake(iid)
            if not intake: return {"ok": False, "error": "intake introuvable"}
            ok, msg = m.send_live_mail(intake)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_update_contact(self, payload: dict) -> dict:
        """Met à jour l'email et/ou le téléphone d'un intake Pixel Pros."""
        iid = ((payload or {}).get("id") or "").strip()
        if not iid:
            return {"ok": False, "error": "id manquant"}
        email = (payload or {}).get("email")
        phone = (payload or {}).get("phone")
        try:
            from ..integrations.pixelpros import repo as r
            ok, msg = r.update_intake_contact(iid, email=email, phone=phone)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_mail_auto_get(self, payload: dict | None = None) -> dict:
        """Renvoie l'état auto/manuel des mails 'paid' et 'live'."""
        try:
            from ..integrations.pixelpros import mailer as m
            return {"ok": True, "auto": {
                "paid": m.is_auto("paid"),
                "live": m.is_auto("live"),
            }}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_mail_auto_set(self, payload: dict) -> dict:
        """Bascule un mail en auto (True) ou manuel (False)."""
        kind = ((payload or {}).get("kind") or "").strip()
        if kind not in ("paid", "live"):
            return {"ok": False, "error": "kind doit être 'paid' ou 'live'"}
        value = bool((payload or {}).get("auto", True))
        try:
            from ..integrations.pixelpros import mailer as m
            ok, msg = m.set_auto(kind, value)
            return {"ok": ok, "message": msg, "auto": m.is_auto(kind)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Pixel Pros — Programme d'affiliation
    # ------------------------------------------------------------------
    def pixelpros_affiliates_list(self, payload: dict | None = None) -> dict:
        p = payload or {}
        status = ((p.get("status") or "").strip() or None)
        try: limit = int(p.get("limit") or 100)
        except (TypeError, ValueError): limit = 100
        try:
            from ..integrations.pixelpros import affiliates as a
            return {"ok": True,
                    "affiliates": a.list_affiliates(status=status, limit=limit),
                    "counts": a.count_by_status()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_affiliate_get(self, payload: dict) -> dict:
        aid = ((payload or {}).get("id") or "").strip()
        if not aid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.pixelpros import affiliates as a
            row = a.get_affiliate(aid)
            if row is None: return {"ok": False, "error": "affilié introuvable"}
            return {"ok": True,
                    "affiliate": row,
                    "stats": a.affiliate_stats(aid),
                    "sales": a.list_sales(affiliate_id=aid, limit=200)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_affiliate_set_status(self, payload: dict) -> dict:
        aid = ((payload or {}).get("id") or "").strip()
        new_status = ((payload or {}).get("status") or "").strip()
        if not aid or not new_status:
            return {"ok": False, "error": "id et status requis"}
        try:
            from ..integrations.pixelpros import affiliates as a
            ok, msg = a.set_affiliate_status(aid, new_status)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_affiliate_sales_list(self, payload: dict | None = None) -> dict:
        p = payload or {}
        status = ((p.get("status") or "").strip() or None)
        try: limit = int(p.get("limit") or 200)
        except (TypeError, ValueError): limit = 200
        try:
            from ..integrations.pixelpros import affiliates as a
            return {"ok": True,
                    "sales": a.list_sales_with_affiliate(payout_status=status, limit=limit)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_affiliate_mark_sales_paid(self, payload: dict) -> dict:
        ids = (payload or {}).get("ids") or []
        batch_ref = ((payload or {}).get("batch_ref") or "").strip()
        if not isinstance(ids, list) or not ids:
            return {"ok": False, "error": "ids manquants"}
        try:
            from ..integrations.pixelpros import affiliates as a
            n, msg = a.mark_sales_paid(ids, batch_ref=batch_ref)
            return {"ok": n > 0, "count": n, "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_affiliate_cancel_sale(self, payload: dict) -> dict:
        sid = ((payload or {}).get("id") or "").strip()
        reason = ((payload or {}).get("reason") or "").strip()
        if not sid: return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations.pixelpros import affiliates as a
            ok, msg = a.cancel_sale(sid, reason=reason)
            return {"ok": bool(ok), "message": msg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_affiliate_prepare_payouts(self, payload: dict | None = None) -> dict:
        """Calcule la liste des paiements à effectuer (commissions 'available'
        groupées par affilié, seuil 50 €). Ne fait PAS la transition de status."""
        try:
            from ..integrations.pixelpros import affiliates as a
            payouts = a.prepare_monthly_payouts()
            total_cents = sum(p["total_cents"] for p in payouts)
            return {"ok": True, "payouts": payouts, "total_cents": total_cents}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pixelpros_affiliate_promote_pending(self, payload: dict | None = None) -> dict:
        """Passe en 'available' toutes les ventes 'pending' > 30 jours.
        À appeler manuellement ou via cron mensuel."""
        try:
            from ..integrations.pixelpros import affiliates as a
            try: days = int((payload or {}).get("min_age_days") or 30)
            except (TypeError, ValueError): days = 30
            n = a.promote_pending_sales(min_age_days=days)
            return {"ok": True, "promoted": n,
                    "message": f"{n} commission(s) passée(s) en 'versable'."}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Modèles mails éditables (zone "Modèles Mails" dans la sidebar)
    # ------------------------------------------------------------------
    def mail_templates_list(self, payload: dict | None = None) -> dict:
        """Liste tous les templates mail groupés par product/expéditeur."""
        try:
            from ..integrations.lagriffe import repo as r
            return r.mail_templates_list()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def mail_templates_get(self, payload: dict) -> dict:
        """Charge un template complet (sujet + corps HTML)."""
        product = ((payload or {}).get("product") or "").strip()
        key     = ((payload or {}).get("key") or "").strip()
        if not product or not key:
            return {"ok": False, "error": "product/key requis"}
        try:
            from ..integrations.lagriffe import repo as r
            return r.mail_templates_get(product, key)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def mail_templates_save(self, payload: dict) -> dict:
        """Enregistre les modifs d'un template (sujet, corps, expéditeur…)."""
        product = ((payload or {}).get("product") or "").strip()
        key     = ((payload or {}).get("key") or "").strip()
        fields  = (payload or {}).get("fields") or {}
        if not product or not key:
            return {"ok": False, "error": "product/key requis"}
        if not isinstance(fields, dict):
            return {"ok": False, "error": "fields doit être un objet"}
        try:
            from ..integrations.lagriffe import repo as r
            updated_by = self.get_user_name() or "triskell-command"
            return r.mail_templates_save(product, key, fields, updated_by)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def mail_templates_delete(self, payload: dict) -> dict:
        """Supprime un template (la fonction Netlify retombe sur son fallback)."""
        product = ((payload or {}).get("product") or "").strip()
        key     = ((payload or {}).get("key") or "").strip()
        if not product or not key:
            return {"ok": False, "error": "product/key requis"}
        try:
            from ..integrations.lagriffe import repo as r
            return r.mail_templates_delete(product, key)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ==================================================================
    # OBELISK — Prospection créateurs (ex-app standalone, fusionnée 2026-05-16)
    # ==================================================================
    def obelisk_list_creators(self, payload: dict | None = None) -> dict:
        """Liste paginée des créateurs trouvés (filtres possibles)."""
        p = payload or {}
        try:
            from ..integrations.obelisk import repo as r
            has_email = p.get("has_email")
            if has_email == "yes":   has_email = True
            elif has_email == "no":  has_email = False
            else:                    has_email = None
            return r.list_creators(
                platform=str(p.get("platform") or "").strip(),
                status=str(p.get("status") or "").strip(),
                min_score=int(p.get("min_score") or 0),
                city=str(p.get("city") or "").strip(),
                q=str(p.get("q") or "").strip(),
                has_email=has_email,
                country=str(p.get("country") or "").strip(),
                job_id=str(p.get("job_id") or "").strip(),
                exported=str(p.get("exported") or "").strip(),
                contacted=str(p.get("contacted") or "").strip(),
                sort_by=str(p.get("sort_by") or "score").strip(),
                audience=str(p.get("audience") or "").strip(),
                limit=int(p.get("limit") or 100),
                offset=int(p.get("offset") or 0),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc), "rows": [], "count": 0}

    def obelisk_get_creator(self, payload: dict) -> dict:
        pid = ((payload or {}).get("id") or "").strip()
        if not pid:
            return {"ok": False, "error": "id requis"}
        try:
            from ..integrations.obelisk import repo as r
            return r.get_creator(pid)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def obelisk_update_creator(self, payload: dict) -> dict:
        pid = ((payload or {}).get("id") or "").strip()
        fields = (payload or {}).get("fields") or {}
        if not pid:
            return {"ok": False, "error": "id requis"}
        if not isinstance(fields, dict):
            return {"ok": False, "error": "fields doit être un objet"}
        try:
            from ..integrations.obelisk import repo as r
            return r.update_creator(pid, fields)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def obelisk_delete_creator(self, payload: dict) -> dict:
        pid = ((payload or {}).get("id") or "").strip()
        if not pid:
            return {"ok": False, "error": "id requis"}
        try:
            from ..integrations.obelisk import repo as r
            return r.delete_creator(pid)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def obelisk_delete_creators_bulk(self, payload: dict) -> dict:
        """Suppression de plusieurs créateurs par leurs IDs."""
        ids = (payload or {}).get("ids") or []
        if not isinstance(ids, list) or not ids:
            return {"ok": False, "error": "ids manquants"}
        try:
            from ..integrations.obelisk import repo as r
            return r.delete_creators_bulk(ids)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "deleted": 0}

    def obelisk_delete_creators_filtered(self, payload: dict | None = None) -> dict:
        """Supprime tous les créateurs qui matchent les filtres en cours.
        Filtres : platform, status, min_score, city, q, has_email."""
        p = payload or {}
        has_email = p.get("has_email")
        if has_email == "yes":   has_email = True
        elif has_email == "no":  has_email = False
        else:                    has_email = None
        try:
            from ..integrations.obelisk import repo as r
            return r.delete_creators_filtered(
                platform=str(p.get("platform") or "").strip(),
                status=str(p.get("status") or "").strip(),
                min_score=int(p.get("min_score") or 0),
                city=str(p.get("city") or "").strip(),
                q=str(p.get("q") or "").strip(),
                has_email=has_email,
                audience=str(p.get("audience") or "").strip(),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc), "deleted": 0}

    def obelisk_delete_all_creators(self, payload: dict | None = None) -> dict:
        """⚠ Supprime TOUS les créateurs. Le client doit avoir affiché une
        double confirmation utilisateur avant de l'appeler."""
        confirm = (payload or {}).get("confirm") or ""
        if confirm != "DELETE_ALL":
            return {"ok": False,
                    "error": "Confirmation manquante (payload.confirm doit valoir 'DELETE_ALL')",
                    "deleted": 0}
        try:
            from ..integrations.obelisk import repo as r
            return r.delete_all_creators()
        except Exception as exc:
            return {"ok": False, "error": str(exc), "deleted": 0}

    def obelisk_stats(self, payload: dict | None = None) -> dict:
        try:
            from ..integrations.obelisk import repo as r
            return r.stats()
        except Exception as exc:
            return {"ok": False, "error": str(exc), "stats": {}}

    def obelisk_audit_non_french(self, payload: dict | None = None) -> dict:
        """Scan de la base → renvoie le nombre de prospects non-francophones
        et 10 exemples. Sert au preview avant suppression."""
        try:
            from ..integrations.obelisk import repo as r
            return r.audit_non_francophones()
        except Exception as exc:
            logger.exception("obelisk_audit_non_french failed")
            return {"ok": False, "error": str(exc)}

    def obelisk_purge_non_french(self, payload: dict | None = None) -> dict:
        """Supprime les non-francophones de la base.
        Exige payload.confirm == 'PURGE_NON_FR'."""
        confirm = (payload or {}).get("confirm") or ""
        try:
            from ..integrations.obelisk import repo as r
            return r.purge_non_francophones(confirm=confirm)
        except Exception as exc:
            logger.exception("obelisk_purge_non_french failed")
            return {"ok": False, "error": str(exc)}

    def obelisk_audit_guessed_emails(self, payload: dict | None = None) -> dict:
        """Scan de la base → renvoie le nombre de prospects dont tous les
        emails sont génériques (contact@, info@, ...) + 10 exemples."""
        try:
            from ..integrations.obelisk import repo as r
            return r.audit_guessed_emails()
        except Exception as exc:
            logger.exception("obelisk_audit_guessed_emails failed")
            return {"ok": False, "error": str(exc)}

    def obelisk_purge_guessed_emails(self, payload: dict | None = None) -> dict:
        """Supprime tous les prospects dont les emails sont uniquement
        devinés (contact@, info@, ...). Exige payload.confirm == 'PURGE_GUESSED'."""
        confirm = (payload or {}).get("confirm") or ""
        try:
            from ..integrations.obelisk import repo as r
            return r.purge_guessed_emails(confirm=confirm)
        except Exception as exc:
            logger.exception("obelisk_purge_guessed_emails failed")
            return {"ok": False, "error": str(exc)}

    def obelisk_purge_below_subs(self, payload: dict | None = None) -> dict:
        """Supprime les prospects avec moins de N abonnés (les sans-valeur
        sont préservés, on ne peut pas savoir s'ils sont petits ou juste
        non mesurés). Sans confirm, renvoie un preview avec le compte +
        exemples. Avec confirm == 'PURGE_BELOW_SUBS', supprime pour de bon."""
        p = payload or {}
        threshold = p.get("threshold")
        confirm = p.get("confirm") or ""
        try:
            from ..integrations.obelisk import repo as r
            return r.purge_below_subscribers(threshold=threshold, confirm=confirm)
        except Exception as exc:
            logger.exception("obelisk_purge_below_subs failed")
            return {"ok": False, "error": str(exc)}

    def obelisk_export(self, payload: dict | None = None) -> dict:
        """Exporte la liste filtrée de prospects en xlsx ou pdf.

        Payload accepté :
            { "format": "xlsx" | "pdf",
              "platform": "", "status": "", "min_score": 0, "city": "",
              "q": "", "has_email": "yes"|"no"|"", "country": "",
              "job_id": "" }

        Renvoie {ok, filename, mime, b64, count}. Le front décode le b64 et
        déclenche un téléchargement.
        """
        p = payload or {}
        fmt = (p.get("format") or "xlsx").lower().strip()
        if fmt not in ("xlsx", "pdf"):
            return {"ok": False, "error": "format invalide (xlsx ou pdf)"}
        try:
            from ..integrations.obelisk import repo as r, export as ex
            has_email = p.get("has_email")
            if has_email == "yes":   has_email = True
            elif has_email == "no":  has_email = False
            else:                    has_email = None
            # Limite optionnelle : si l'user veut un sous-ensemble (ex. 50 premiers).
            # Capé à 5000 côté repo pour éviter d'exploser la mémoire.
            user_limit = p.get("limit")
            try:
                user_limit = int(user_limit) if user_limit is not None else None
            except (ValueError, TypeError):
                user_limit = None
            limit_max = max(1, min(user_limit, 5000)) if (user_limit and user_limit > 0) else 5000
            res = r.list_creators_for_export(
                limit_max=limit_max,
                platform=str(p.get("platform") or "").strip(),
                status=str(p.get("status") or "").strip(),
                min_score=int(p.get("min_score") or 0),
                city=str(p.get("city") or "").strip(),
                q=str(p.get("q") or "").strip(),
                has_email=has_email,
                country=str(p.get("country") or "").strip(),
                job_id=str(p.get("job_id") or "").strip(),
                audience=str(p.get("audience") or "").strip(),
            )
            if not res.get("ok"):
                return res
            rows = res.get("rows") or []
            # Marque les prospects exportés (exported_at = now) pour qu'on
            # puisse ensuite filtrer "déjà exporté" depuis l'UI Obelisk.
            try:
                ids = [row.get("id") for row in rows if row.get("id")]
                if ids:
                    r.mark_exported(ids)
            except Exception as exc:
                logger.debug("mark_exported a échoué (non bloquant) : %s", exc)
            from datetime import datetime as _dt
            stamp = _dt.now().strftime("%Y-%m-%d_%Hh%M")
            if fmt == "xlsx":
                data = ex.to_xlsx(rows, title=f"Prospects Obelisk — {stamp}")
                mime = ("application/vnd.openxmlformats-officedocument"
                        ".spreadsheetml.sheet")
                filename = f"obelisk_prospects_{stamp}.xlsx"
            else:
                data = ex.to_pdf(rows, title=f"Prospects Obelisk — {stamp}")
                mime = "application/pdf"
                filename = f"obelisk_prospects_{stamp}.pdf"
            import base64
            return {
                "ok": True,
                "filename": filename,
                "mime": mime,
                "b64": base64.b64encode(data).decode("ascii"),
                "count": len(rows),
            }
        except Exception as exc:
            logger.exception("obelisk_export failed")
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def obelisk_import_file(self, payload: dict) -> dict:
        """Import d'un fichier Excel/CSV de prospects → table Supabase prospects.

        Payload : { filename, data (base64), industry? }
        Réponse : { ok, inserted, skipped, duplicates, total, errors, error? }

        Le mapping des colonnes est auto-détecté à partir des en-têtes
        (suggest_mapping). Dédup sur (email principal) ou (website) pour
        éviter les doublons. L'industrie passée par l'UI est appliquée à
        toutes les lignes qui n'ont pas de colonne secteur mappée.
        """
        import base64
        import tempfile
        from pathlib import Path
        p = payload or {}
        data_b64 = (p.get("data") or "").strip()
        filename = (p.get("filename") or "import.xlsx").strip()
        industry_override = (p.get("industry") or "").strip()
        if not data_b64:
            return {"ok": False, "error": "Fichier manquant"}

        try:
            file_bytes = base64.b64decode(data_b64)
        except Exception:
            return {"ok": False, "error": "Fichier illisible (base64 invalide)"}
        if len(file_bytes) > 20 * 1024 * 1024:
            return {"ok": False, "error": "Fichier > 20 Mo"}

        suffix = Path(filename).suffix.lower() or ".xlsx"
        if suffix not in (".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".txt"):
            return {"ok": False,
                    "error": "Format non supporté (utilise .xlsx ou .csv)"}

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(file_bytes)
            tmp.close()
            tmp_path = Path(tmp.name)
            try:
                from triskell_core.prospect.sources import file_import as fi
            except ImportError as exc:
                return {"ok": False,
                        "error": f"Module file_import indisponible : {exc}"}

            try:
                headers, rows = fi.read_file(tmp_path)
            except Exception as exc:
                return {"ok": False,
                        "error": f"Lecture du fichier impossible : {exc}"}
            if not rows:
                return {"ok": False, "error": "Aucune ligne dans le fichier"}

            mapping = fi.suggest_mapping(headers)
            if not any(k in mapping for k in
                       ("name", "legal_name", "emails", "phones",
                        "website", "siren")):
                return {"ok": False,
                        "error": ("Impossible de détecter les colonnes. "
                                  "Vérifie que ton fichier a au moins une "
                                  "colonne Nom, Email, Téléphone, Site web "
                                  "ou Raison sociale.")}

            sb = self._supabase()
            if sb is None:
                return {"ok": False, "error": "Supabase non configuré"}
            # Pour les contraintes RLS : on a besoin du wrapper Triskell.
            try:
                from triskell_core.db import (
                    get_client as _gc, SupabaseNotConfigured,
                )
                tc = _gc()
                triskell_client = tc if tc.is_authenticated else None
            except Exception:
                triskell_client = None
            try:
                from ..integrations import multi_tenant
                with_workspace = multi_tenant.with_workspace
            except Exception:
                with_workspace = lambda _c, row: row  # noqa: E731

            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            source_label = Path(filename).name

            inserted = 0
            duplicates = 0
            skipped = 0
            errors = 0

            for raw_row in rows:
                try:
                    prospect = fi._row_to_prospect(
                        raw_row, mapping, source_label=source_label,
                    )
                except Exception:
                    errors += 1
                    continue
                if prospect is None:
                    skipped += 1
                    continue

                emails = list(prospect.emails or [])
                phones = list(prospect.phones or [])
                website = (prospect.website or "").strip()
                industry = (prospect.industry or industry_override or "").strip()

                # Dédup : si email ou website déjà connu, on saute.
                is_dup = False
                try:
                    if emails:
                        first_email = emails[0].strip().lower()
                        if first_email:
                            res = (sb.table("prospects")
                                   .select("id")
                                   .contains("emails", [first_email])
                                   .limit(1).execute())
                            if res.data:
                                is_dup = True
                    if not is_dup and website:
                        wn = website.rstrip("/").lower()
                        if wn:
                            res = (sb.table("prospects")
                                   .select("id, website")
                                   .ilike("website", f"%{wn[-40:]}%")
                                   .limit(5).execute())
                            for er in (res.data or []):
                                if ((er.get("website") or "")
                                        .rstrip("/").lower() == wn):
                                    is_dup = True
                                    break
                except Exception as exc:
                    logger.warning("obelisk_import_file dedup: %s", exc)

                if is_dup:
                    duplicates += 1
                    continue

                row = {
                    "name":        (prospect.name or "").strip()
                                    or (prospect.legal_name or "").strip(),
                    "handle":      "",
                    "legal_name":  (prospect.legal_name or "").strip(),
                    "emails":      emails,
                    "phones":      phones,
                    "website":     website,
                    "other_urls":  [],
                    "address":     (prospect.address or "").strip(),
                    "city":        (prospect.city or "").strip(),
                    "postal_code": (prospect.postal_code or "").strip(),
                    "country":     (prospect.country or "").strip(),
                    "industry":    industry,
                    "description": "",
                    "language":    "",
                    "monetized":          False,
                    "monetization_reasons": [],
                    "has_legal_mentions":   False,
                    "score":       0,
                    "score_label": "",
                    "subscribers": None,
                    "platform_url": "",
                    "status":      "new",
                    "tags":        [industry] if industry else [],
                    "notes":       (prospect.notes or "").strip(),
                    "sources":     [{
                        "name":      "file_import",
                        "source_id": getattr(prospect, "siren", "") or "",
                        "url":       "",
                        "found_at":  now_iso,
                        "filename":  source_label,
                    }],
                    "match_keys":  [],
                }
                # Garde-fou : au moins un nom OU un email
                if not row["name"] and not emails and not phones:
                    skipped += 1
                    continue

                try:
                    row = with_workspace(triskell_client, row)
                    sb.table("prospects").insert(row).execute()
                    inserted += 1
                except Exception as exc:
                    logger.warning("obelisk_import_file insert: %s", exc)
                    errors += 1

            return {
                "ok": True,
                "inserted":   inserted,
                "duplicates": duplicates,
                "skipped":    skipped,
                "errors":     errors,
                "total":      len(rows),
                "filename":   source_label,
            }
        finally:
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except Exception:
                pass

    def obelisk_get_config(self, payload: dict | None = None) -> dict:
        try:
            from ..integrations.obelisk import repo as r
            user_email = self._safe_user_email()
            return r.get_user_config(user_email)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def obelisk_save_config(self, payload: dict) -> dict:
        cfg = (payload or {}).get("config") or {}
        if not isinstance(cfg, dict):
            return {"ok": False, "error": "config doit être un objet"}
        try:
            from ..integrations.obelisk import repo as r
            user_email = self._safe_user_email()
            return r.save_user_config(user_email, cfg)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def obelisk_start_search(self, payload: dict) -> dict:
        """Lance une recherche dans un thread background. Retourne le job_id
        à poller via obelisk_get_job.

        payload = {
            niche, platforms, max_per_platform,
            filters: {
                monetized_mode:  "all"|"unmonetized"|"monetized",
                min_subscribers: int,
                max_subscribers: int,
                country, language,
                only_with_email, only_uncontacted,
            }
        }
        """
        p = payload or {}
        niche = (p.get("niche") or "").strip()
        platforms = p.get("platforms") or []
        if not isinstance(platforms, list):
            platforms = []
        max_pp = int(p.get("max_per_platform") or 30)
        filters = (p.get("filters") or {}) if isinstance(p.get("filters"), dict) else {}
        if not niche:
            return {"ok": False, "error": "niche requise"}
        if not platforms:
            return {"ok": False, "error": "au moins une plateforme requise"}
        try:
            from ..integrations.obelisk import runner
            user_email = self._safe_user_email()
            return runner.start_search(user_email, niche, platforms, max_pp,
                                        config_overrides=filters)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def obelisk_get_job(self, payload: dict) -> dict:
        jid = ((payload or {}).get("job_id") or "").strip()
        if not jid:
            return {"ok": False, "error": "job_id requis"}
        try:
            from ..integrations.obelisk import repo as r
            return r.get_search_job(jid)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def obelisk_list_jobs(self, payload: dict | None = None) -> dict:
        try:
            from ..integrations.obelisk import repo as r
            user_email = self._safe_user_email()
            limit = int((payload or {}).get("limit") or 10)
            return r.list_recent_jobs(user_email, limit=limit)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "jobs": []}

    def obelisk_unseen_done_jobs(self, payload: dict | None = None) -> dict:
        """Renvoie les jobs Obelisk terminés (status=done) après la date
        "since" passée par le front. Le front stocke en localStorage la
        date de la dernière visite Obelisk et passe cette date ici pour
        savoir combien de recherches sont arrivées depuis.

        payload = {since: "YYYY-MM-DDTHH:MM:SS"}
        """
        try:
            from ..integrations.obelisk import repo as r
            user_email = self._safe_user_email()
            since = ((payload or {}).get("since") or "").strip()
            # Récupère les 20 derniers jobs done et filtre côté Python
            raw = r.list_recent_jobs(user_email, limit=20)
            jobs = (raw or {}).get("jobs") or []
            done = [j for j in jobs if (j.get("status") == "done")]
            if since:
                done = [j for j in done if (j.get("finished_at") or "") > since]
            # Format compact pour la sidebar / cockpit
            return {
                "ok": True,
                "count": len(done),
                "jobs": [{
                    "id":           j.get("id"),
                    "niche":        j.get("niche") or "",
                    "platforms":    j.get("platforms") or [],
                    "finished_at":  j.get("finished_at") or "",
                    "stats":        j.get("stats") or {},
                } for j in done[:5]],
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "count": 0, "jobs": []}

    # ------------------------------------------------------------------
    # Activité agrégée des 4 pipelines sites (Lagriffe / RankUs / WoW /
    # Pixel Pros) — utilisée par la sidebar (badge "il a bougé X trucs
    # depuis ta dernière visite") et le bloc Cockpit.
    # ------------------------------------------------------------------
    def pipelines_activity(self, payload: dict | None = None) -> dict:
        """Renvoie pour chaque pipeline les 20 derniers intakes triés par
        date de dernier changement (max(updated_at, last_attempt_at,
        created_at)). Le front compare ces timestamps à sa date locale
        "dernière visite" pour calculer le compteur de nouveautés.

        Payload optionnel : {limit: int} (par défaut 20).
        """
        try:
            limit = int((payload or {}).get("limit") or 20)
        except (TypeError, ValueError):
            limit = 20

        def _change_at(it: dict) -> str:
            return (it.get("updated_at")
                    or it.get("last_attempt_at")
                    or it.get("created_at")
                    or "")

        def _display_name(it: dict) -> str:
            company = (it.get("company_name") or "").strip()
            first = (it.get("client_first_name") or it.get("first_name") or "").strip()
            last = (it.get("client_last_name") or it.get("last_name") or "").strip()
            full = (first + " " + last).strip()
            if company and full:
                return f"{company} · {full}"
            return company or full or (it.get("client_email") or it.get("email") or "—")

        def _shape(prefix: str, intakes: list[dict]) -> dict:
            shaped = []
            for it in intakes or []:
                shaped.append({
                    "id":     it.get("id") or "",
                    "name":   _display_name(it),
                    "status": it.get("status") or "",
                    "at":     _change_at(it),
                })
            shaped.sort(key=lambda x: x["at"] or "", reverse=True)
            latest = shaped[0]["at"] if shaped else ""
            return {"prefix": prefix, "recent": shaped, "latest_change_at": latest}

        out: dict[str, dict] = {}
        try:
            from ..integrations.wow import repo as _wow
            out["wow"] = _shape("wow", _wow.list_intakes(limit=limit))
        except Exception as exc:
            out["wow"] = {"prefix": "wow", "recent": [], "latest_change_at": "", "error": str(exc)}
        try:
            from ..integrations.rankus import repo as _rank
            out["rankus"] = _shape("rankus", _rank.list_intakes(limit=limit))
        except Exception as exc:
            out["rankus"] = {"prefix": "rankus", "recent": [], "latest_change_at": "", "error": str(exc)}
        try:
            from ..integrations.lagriffe import repo as _lag
            out["lagriffe"] = _shape("lagriffe", _lag.list_intakes(limit=limit))
        except Exception as exc:
            out["lagriffe"] = {"prefix": "lagriffe", "recent": [], "latest_change_at": "", "error": str(exc)}
        try:
            from ..integrations.pixelpros import repo as _pp
            out["pixelpros"] = _shape("pixelpros", _pp.list_intakes(limit=limit))
        except Exception as exc:
            out["pixelpros"] = {"prefix": "pixelpros", "recent": [], "latest_change_at": "", "error": str(exc)}
        return {"ok": True, "pipelines": out}

    def _safe_user_email(self) -> str:
        """Récupère l'email user de manière défensive (les méthodes
        existantes varient selon le mode pywebview/HTTP). Fallback sur
        outreach.from_email (settings classique de Triskell Command)."""
        try:
            val = (self._app_state.get("outreach", "from_email", default="")
                   or "").strip()
            if val:
                return val
        except Exception:
            pass
        for meth in ("get_user_email", "current_user_email"):
            fn = getattr(self, meth, None)
            if callable(fn):
                try:
                    v = fn()
                    if isinstance(v, str) and v:
                        return v
                except Exception:
                    pass
        return ""

    # ------------------------------------------------------------------
    # Catalogue des outils Triskell (pour le launcher Ctrl+K)
    # ------------------------------------------------------------------
    def get_apps_catalog(self) -> dict:
        """Renvoie la liste des produits Triskell + leurs métadonnées
        (lue depuis Triskell 0 - Lanceur/apps.json), avec le slug du
        logo normalisé (web/ui/assets/apps/<slug>.png|svg)."""
        import json
        from pathlib import Path
        # Mapping id apps.json → slug logo (cf. scripts/normalize_app_logos.py)
        ID_TO_SLUG = {
            "suite-des-heros":      ("suite-des-heros", "png"),
            "delinote":             ("delinote", "png"),
            "studio-pdf":           ("studio-pdf", "png"),
            "bobeez":               ("bobeez", "png"),
            "pirate-life-mail":     ("pirate-life-mail", "png"),
            "le-denicheur":         ("obelisk", "png"),
            "triskell-studio-sites":("triskell-studio-sites", "png"),
            "eliks-studio":         ("eliks-studio", "svg"),
            "le-heraut":            ("alphacast", "png"),
            "ultimate-prompt-builder":("alphabeast", "png"),
            "alphapitch":           ("alphapitch", "png"),
            "outils-batiment":      ("outils-batiment", "png"),
            "pack-electricien-pro": ("pack-electricien-pro", "png"),
            "teddy-mail":           ("teddy-mail", "png"),
        }
        # Cherche apps.json :
        # 1) copie embarquee dans le package (deployable Docker/serveur)
        # 2) sibling Triskell 0 - Lanceur sur la machine du dev (cas desktop)
        # On evalue chaque candidat dans un try : sur le serveur Docker
        # `__file__` est /app/triskell_command/web/api.py et parents[4]
        # leve un IndexError, ce qui faisait tout planter avant meme de
        # tester parents[1] (le bon chemin embarque).
        here = Path(__file__).resolve()
        apps_json = None
        for depth, subpath in (
            (1, ("data", "apps.json")),
            (3, ("Triskell 0 - Lanceur", "apps.json")),
            (4, ("Triskell 0 - Lanceur", "apps.json")),
        ):
            try:
                p = here.parents[depth].joinpath(*subpath)
            except IndexError:
                continue
            if p.exists():
                apps_json = p
                break
        if apps_json is None:
            return {"ok": False, "error": "apps.json introuvable"}
        try:
            data = json.loads(apps_json.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"ok": False, "error": f"parse: {exc}"}

        # Charge les overrides utilisateur (produits desactives par toggle)
        from ..integrations import catalog_overrides
        disabled_ids = catalog_overrides.get_disabled_ids()

        out = []
        for app in data.get("apps", []):
            slug_info = ID_TO_SLUG.get(app.get("id"))
            if not slug_info:
                continue
            slug, ext = slug_info
            app_id = app.get("id")
            out.append({
                "id":          app_id,
                "name":        app.get("name"),
                "tagline":     app.get("tagline", ""),
                "category":    app.get("category", ""),
                "pro_section": app.get("proSection", ""),
                "tier":        app.get("tier", ""),
                "kind":        app.get("kind", ""),
                "price":       app.get("price"),
                "price_original": app.get("priceOriginal"),
                "price_from":  app.get("priceFrom"),
                "price_note":  app.get("priceNote", ""),
                "buy_url":     app.get("buyUrl", ""),
                "exe_path":    app.get("exePath", ""),
                "installed":   bool(app.get("installed")),
                "coming_soon": bool(app.get("comingSoon")),
                "featured":    bool(app.get("featured")),
                "featured_label": app.get("featuredLabel", ""),
                "logo":        f"assets/apps/{slug}.{ext}",
                # Détail riche pour la vue Catalogue
                "motto":       app.get("motto", ""),
                "sales_pitch": app.get("salesPitch", ""),
                "description": app.get("description", ""),
                "features":    app.get("features", []) or [],
                "personas":    app.get("personas", []) or [],
                "links":       app.get("links", []) or [],
                "service":     app.get("service", {}) or {},
                "plans":       app.get("plans", []) or [],
                # Etat actif/inactif (toggle UI). Par defaut actif.
                "is_active":   app_id not in disabled_ids,
            })
        return {"ok": True, "apps": out, "disabled_ids": sorted(disabled_ids)}

    def catalog_set_active(self, payload: dict) -> dict:
        """Active ou desactive un produit du catalogue (toggle UI).

        Payload : {"id": "...", "active": true|false}
        Quand un produit est inactif, il n'apparait plus dans le picker
        des mails ni dans les suggestions de la prospection IA.
        """
        from ..integrations import catalog_overrides
        p = payload or {}
        pid = (p.get("id") or "").strip()
        active = bool(p.get("active", True))
        if not pid:
            return {"ok": False, "error": "no_id"}
        # Source de verite : catalog_central (qui mirroir aussi catalog_overrides)
        from ..integrations import catalog_central
        r = catalog_central.set_active(pid, active)
        # Compat ascendante si quelqu'un appelle l'ancien chemin
        catalog_overrides.set_disabled(pid, disabled=not active)
        return r

    # ------------------------------------------------------------------
    # Catalogue editable (produits + bundles)
    # ------------------------------------------------------------------
    def catalog_get_full(self) -> dict:
        """Renvoie tous les produits + bundles editables (vue Catalogue)."""
        from ..integrations import catalog_central
        data = catalog_central.get_full()
        return {"ok": True, **data}

    def catalog_save_product(self, payload: dict) -> dict:
        """Cree ou met a jour un produit. Payload = champs editables du produit."""
        from ..integrations import catalog_central
        return catalog_central.save_product(payload or {})

    def catalog_delete_product(self, payload: dict) -> dict:
        from ..integrations import catalog_central
        return catalog_central.delete_product((payload or {}).get("id") or "")

    def catalog_save_bundle(self, payload: dict) -> dict:
        """Cree ou met a jour un pack."""
        from ..integrations import catalog_central
        return catalog_central.save_bundle(payload or {})

    def catalog_delete_bundle(self, payload: dict) -> dict:
        from ..integrations import catalog_central
        return catalog_central.delete_bundle((payload or {}).get("id") or "")

    def catalog_seed_lagriffe_demos(self, payload: dict | None = None) -> dict:
        """Seed les 21 démos métier Lagriffe en un appel.
        Idempotent : relancer ne crée pas de doublons (save_product upsert
        sur id slugifié déterministe)."""
        from ..integrations import catalog_central
        DEMOS = [
            ("Démo brasserie — La Rose des Vents", "https://brasserie-la-rose-des-vents.netlify.app",
             "brasserie, bar à bières, microbrasserie, taverne, pub, débit de boissons, bar artisanal"),
            ("Démo services à la personne — Ingrid Services", "https://ingrid-services.fr",
             "ménage, services à la personne, aide à domicile, nettoyage, entretien maison, repassage, garde d'enfants"),
            ("Démo boutique vape — Vaporlux", "https://vaporlux.triskell-studio.fr",
             "vape, cigarette électronique, e-cigarette, vapoteur, e-liquide, CBD, boutique vape, vape shop"),
            ("Démo atelier sculpteur — Missor", "https://missor.triskell-studio.fr",
             "sculpteur, sculpture, fonderie, fondeur d'art, atelier d'art, bronze, statuaire, artisan d'art"),
            ("Démo influenceur / créateur — Anyme", "https://anyme.triskell-studio.fr",
             "influenceur, streamer, créateur de contenu, content creator, twitch, youtube, instagram, tiktok, personal branding"),
            ("Démo garagiste — Triskell", "https://garage.triskell-studio.fr",
             "garagiste, garage, mécanicien, mécanique auto, réparation automobile, carrosserie, entretien voiture, dépannage, automobile"),
            ("Démo paysagiste — Triskell", "https://paysagiste.triskell-studio.fr",
             "paysagiste, jardinier, espaces verts, aménagement paysager, jardin, entretien jardin, taille, élagage, terrasse, gazon"),
            ("Démo thérapeute / bien-être — Graphothérapeute", "https://graphotherapeute.triskell-studio.fr",
             "graphothérapeute, graphothérapie, yoga, professeur de yoga, orthophoniste, orthophonie, sophrologue, sophrologie, naturopathe, hypnothérapeute, médecine douce, bien-être, thérapeute, praticien, ostéopathe, réflexologue"),
            ("Démo boutique vape — Variante moderne", "https://vape.triskell-studio.fr",
             "vape, cigarette électronique, e-cigarette, vapoteur, e-liquide, CBD, boutique vape, vape shop"),
            ("Démo plombier — Triskell", "https://plombier.triskell-studio.fr",
             "plombier, plomberie, chauffagiste, dépannage plomberie, sanitaire, fuite d'eau, chauffage, installation sanitaire, robinetterie"),
            ("Démo peintre — Triskell", "https://peintre.triskell-studio.fr",
             "peintre, peinture, peintre en bâtiment, ravalement, papier peint, décoration murale, façade, peinture intérieure, peinture extérieure"),
            ("Démo plaquiste — Triskell", "https://plaquiste.triskell-studio.fr",
             "plaquiste, placo, cloisons, isolation, faux plafond, doublage, BA13, aménagement intérieur"),
            ("Démo maçon — Triskell", "https://macon.triskell-studio.fr",
             "maçon, maçonnerie, gros œuvre, construction, fondations, rénovation, BTP, entrepreneur, terrassement"),
            ("Démo carreleur — Triskell", "https://carreleur.triskell-studio.fr",
             "carreleur, carrelage, faïence, pose carrelage, salle de bain, sol, mosaïque, dallage"),
            ("Démo électricien — Triskell", "https://electricien.triskell-studio.fr",
             "électricien, électricité, installation électrique, dépannage électrique, tableau électrique, mise aux normes, courant fort, courant faible, domotique"),
            ("Démo boulangerie — Le Fournil de Goulven", "https://boulangerie.triskell-studio.fr",
             "boulanger, boulangerie, pain, viennoiserie, pâtisserie, baguette, artisan boulanger, fournil, pâtissier"),
            ("Démo restaurant — La Belle Époque", "https://restaurant.triskell-studio.fr",
             "restaurant, restaurateur, cuisine, brasserie, traiteur, bistrot, gastronomie, cuisine traditionnelle, menu, carte"),
            ("Démo salon de coiffure — Maison Lou", "https://salon-coiffure.triskell-studio.fr",
             "coiffeur, coiffeuse, salon de coiffure, coupe, coloration, balayage, mèches, brushing, soin capillaire"),
            ("Démo barbier — L'Atelier de Brieuc", "https://salons.triskell-studio.fr",
             "barbier, barber shop, barberie, rasage, taille de barbe, salon de barbier, soin homme, coupe homme"),
            ("Démo restaurant cubain — Clandestino", "https://clandestino.triskell-studio.fr",
             "restaurant cubain, cuisine latino, world food, bar à cocktails, restaurant à thème, tapas, ambiance, rhum, latino"),
            ("Démo tatoueur — Despiertos", "https://despiertos.triskell-studio.fr",
             "tatoueur, tatouage, tattoo, salon de tatouage, tattoo artist, piercing, body art, ink, atelier tatouage"),
        ]
        ok = 0
        errs: list[dict] = []
        for name, url, kws in DEMOS:
            res = catalog_central.save_product({
                "name":           name,
                "kind":           "demo",
                "category":       "sites",
                "buy_url":        url,
                "keywords":       kws,
                "prospect_pitch": "Démo prête à montrer aux prospects de "
                                   "ce métier : preuve visuelle directe "
                                   "de ce qu'on peut leur faire.",
            })
            if res and res.get("ok"):
                ok += 1
            else:
                errs.append({"name": name, "error": (res or {}).get("error", "?")})
        return {"ok": len(errs) == 0, "added": ok, "errors": errs,
                "total": len(DEMOS)}

    def open_url(self, payload: dict) -> dict:
        """Ouvre une URL dans le navigateur par défaut (depuis le launcher)."""
        url = (payload or {}).get("url") or ""
        if not url:
            return {"ok": False, "error": "no_url"}
        try:
            import webbrowser
            webbrowser.open(url)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Teddy Mail — pont depuis Triskell Command
    # ------------------------------------------------------------------
    # Note : Teddy Mail v0.5.1 est en Tauri (IPC interne au webview, pas
    # de CLI/HTTP). Donc aujourd'hui on ne peut faire que :
    #  1) Lancer l'app (Popen sur teddy-mail-shell.exe)
    #  2) Composer via mailto: (Windows ouvre alors le client mail
    #     défini par défaut → Teddy Mail si Jordan l'a configuré tel quel).
    # Quand Teddy Mail v0.6 exposera un endpoint IPC (custom URL scheme
    # `teddy://compose?to=…` ou serveur HTTP local), on le branchera ici.

    def _resolve_teddy_exe(self) -> str:
        """Lit l'exePath de Teddy Mail depuis le catalogue apps.json.
        Retourne '' si introuvable."""
        try:
            cat = self.get_apps_catalog()
            if not cat.get("ok"):
                return ""
            for a in cat.get("apps", []):
                if a.get("id") == "teddy-mail":
                    return a.get("exe_path") or ""
        except Exception:
            pass
        return ""

    def open_teddy_mail(self, payload: dict | None = None) -> dict:
        """Lance Teddy Mail (sans rien composer). Wrap launch_app avec
        l'exePath résolu depuis le catalogue."""
        exe = self._resolve_teddy_exe()
        if not exe:
            return {"ok": False, "error": "Teddy Mail introuvable dans le catalogue"}
        return self.launch_app({"exe_path": exe})

    def compose_mail(self, payload: dict) -> dict:
        """Ouvre une fenêtre de composition pré-remplie via mailto:.
        Le client mail défini comme défaut sous Windows reçoit l'appel
        (= Teddy Mail si Jordan l'a configuré tel quel).

        payload = {to?: str|list, subject?: str, body?: str, cc?: str|list, bcc?: str|list}
        """
        from urllib.parse import quote
        p = payload or {}

        def _join(v) -> str:
            if isinstance(v, (list, tuple)):
                return ",".join(x for x in v if x)
            return str(v or "")

        to = _join(p.get("to"))
        subject = str(p.get("subject") or "")
        body = str(p.get("body") or "")
        cc = _join(p.get("cc"))
        bcc = _join(p.get("bcc"))

        # Construit l'URL mailto:
        url = f"mailto:{to}" if to else "mailto:"
        params = []
        if subject: params.append(f"subject={quote(subject)}")
        if body:    params.append(f"body={quote(body)}")
        if cc:      params.append(f"cc={quote(cc)}")
        if bcc:     params.append(f"bcc={quote(bcc)}")
        if params:
            url += "?" + "&".join(params)

        try:
            # Sous Windows, os.startfile gère mailto: correctement (passe
            # par le handler système → client mail par défaut).
            import os, sys
            if sys.platform.startswith("win"):
                os.startfile(url)  # type: ignore[attr-defined]
            else:
                import webbrowser
                webbrowser.open(url)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def launch_app(self, payload: dict) -> dict:
        """Lance un outil Triskell : exe local en priorité, sinon URL web.

        payload = {exe_path?: str, url?: str}
        - exe_path : si présent et le fichier existe → subprocess.Popen
        - url      : sinon, ouverture dans le navigateur par défaut
        """
        p = payload or {}
        exe = (p.get("exe_path") or "").strip()
        url = (p.get("url") or "").strip()
        # 1) Tentative exe local
        if exe:
            try:
                from pathlib import Path
                exe_path = Path(exe)
                if exe_path.exists():
                    import subprocess
                    subprocess.Popen(
                        [str(exe_path)],
                        shell=False,
                        cwd=str(exe_path.parent),
                    )
                    return {"ok": True, "mode": "exe"}
                # Fichier introuvable → fallback URL si dispo
                logger.warning("launch_app: exe introuvable %s", exe)
            except Exception as exc:
                logger.warning("launch_app exe: %s", exc)
                # On tente quand même l'URL en fallback
        # 2) Fallback URL
        if url:
            try:
                import webbrowser
                webbrowser.open(url)
                return {"ok": True, "mode": "url"}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": "no_target"}

    # ------------------------------------------------------------------
    # Livraison auto après vente (kits par produit)
    # ------------------------------------------------------------------
    def delivery_kits_list(self) -> dict:
        """Renvoie le dict {product_key → kit} courant."""
        try:
            from ..integrations import delivery_kits
            client = self._supabase()
            kits = delivery_kits.load_kits(client=client)
            return {"ok": True, "kits": kits}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def delivery_kits_save(self, payload: dict) -> dict:
        """Sauve le dict complet des kits (local + miroir Supabase)."""
        kits = (payload or {}).get("kits") or {}
        if not isinstance(kits, dict):
            return {"ok": False, "error": "kits doit être un dict"}
        try:
            from ..integrations import delivery_kits
            client = self._supabase()
            delivery_kits.save_kits(kits, client=client)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def delivery_kit_preview(self, payload: dict) -> dict:
        """Preview un kit rendu avec un nom client de test."""
        p = payload or {}
        product_key = p.get("product_key") or ""
        client_name = p.get("client_name") or "Marie Dupont"
        try:
            from ..integrations import delivery_kits
            client = self._supabase()
            signature = (self._app_state.get(
                "outreach", "from_name", default="") or "").strip()
            welcome = delivery_kits.render_welcome(
                product_key, client_name=client_name,
                signature=signature, client=client,
            )
            fus = []
            for i in range(20):  # safe upper bound
                rendered = delivery_kits.render_follow_up(
                    product_key, i, client_name=client_name,
                    signature=signature, client=client,
                )
                if rendered is None:
                    break
                fus.append(rendered)
            return {"ok": True, "welcome": welcome, "follow_ups": fus}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def delivery_trigger_now(self, payload: dict) -> dict:
        """Déclenche immédiatement la livraison pour un client_project donné.
        N'envoie que la stage welcome_at_paid (les follow-ups suivront via le
        cycle horaire normal selon les days du kit).

        payload = {client_project_id: str}  ou  {client_email, client_name,
        product_key, signature?}  pour test ad-hoc sans Supabase.
        """
        p = payload or {}
        cpid = p.get("client_project_id")
        try:
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}

            # Mode 1 : déclenchement sur un client_project existant
            if cpid:
                sb = client.raw
                res = (sb.table("client_projects").select("*")
                       .eq("id", cpid).limit(1).execute())
                rows = res.data or []
                if not rows:
                    return {"ok": False, "error": "client_project introuvable"}
                proj = rows[0]
                # S'assurer que paid_at est rempli (sinon le cycle ne le verra pas)
                if not proj.get("paid_at"):
                    from datetime import datetime as _dt
                    sb.table("client_projects").update({
                        "paid_at": _dt.now().isoformat(timespec="seconds"),
                    }).eq("id", cpid).execute()
                    proj["paid_at"] = _dt.now().isoformat(timespec="seconds")
                # Force la stage welcome_at_paid avec mode=instant
                from ..integrations import post_sale_runner
                config = post_sale_runner.load_config(client)
                # Surcharge ponctuelle
                stages = (config.get("stages") or {})
                stages["welcome_at_paid"] = {"days": 0, "mode": "instant"}
                config["stages"] = stages
                drafted = post_sale_runner._create_post_sale_draft(  # noqa
                    client, self._app_state, proj,
                    "welcome_at_paid", config,
                )
                return {"ok": bool(drafted.get("auto_sent")), "result": drafted}
            return {"ok": False, "error": "client_project_id manquant"}
        except Exception as exc:
            logger.exception("delivery_trigger_now")
            return {"ok": False, "error": str(exc)}

    def post_sale_run_now(self) -> dict:
        """Force un cycle complet du post-sale runner (utile pour debug)."""
        try:
            from ..integrations import post_sale_runner
            return {"ok": True, "result": post_sale_runner.run_now(self._app_state)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def post_sale_status(self) -> dict:
        """Renvoie l'état du worker post-sale (running, last run, counters)."""
        try:
            from ..integrations import post_sale_runner
            return {"ok": True, "status": post_sale_runner.get_status()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Bascule auto "prospect intéressé → projet client"
    # ------------------------------------------------------------------
    def lead_to_client_get_config(self) -> dict:
        try:
            from ..integrations import lead_to_client
            client = self._supabase()
            if not client:
                return {"ok": True, "config": dict(lead_to_client.DEFAULT_CONFIG)}
            return {"ok": True, "config": lead_to_client.load_config(client)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def lead_to_client_save_config(self, payload: dict) -> dict:
        try:
            from ..integrations import lead_to_client
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            cfg = (payload or {}).get("config") or {}
            # Validation légère
            if cfg.get("mode") not in lead_to_client.MODES:
                cfg["mode"] = "strong"
            lead_to_client.save_config(client, cfg)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def lead_to_client_run_now(self) -> dict:
        """Force un cycle (utile en debug ou pour bouton 'tester maintenant')."""
        try:
            from ..integrations import lead_to_client
            return {"ok": True, "result": lead_to_client.run_now(self._app_state)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def lead_to_client_status(self) -> dict:
        try:
            from ..integrations import lead_to_client
            return {"ok": True, "status": lead_to_client.get_status()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Relance multi-canal (LinkedIn DM préparé par IA)
    # ------------------------------------------------------------------
    def multichannel_get_actions(self) -> dict:
        try:
            from ..integrations import multichannel_followup
            return {"ok": True, "actions": multichannel_followup.list_pending()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def multichannel_mark_done(self, payload: dict) -> dict:
        aid = (payload or {}).get("id") or ""
        try:
            from ..integrations import multichannel_followup
            return {"ok": multichannel_followup.mark_done(aid)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def multichannel_discard(self, payload: dict) -> dict:
        aid = (payload or {}).get("id") or ""
        try:
            from ..integrations import multichannel_followup
            return {"ok": multichannel_followup.discard_action(aid)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def multichannel_run_now(self) -> dict:
        try:
            from ..integrations import multichannel_followup
            return {"ok": True, "result": multichannel_followup.run_now(self._app_state)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def multichannel_get_config(self) -> dict:
        try:
            from ..integrations import multichannel_followup
            client = self._supabase()
            return {"ok": True, "config": multichannel_followup.load_config(client)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def multichannel_save_config(self, payload: dict) -> dict:
        try:
            from ..integrations import multichannel_followup
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            multichannel_followup.save_config(client, (payload or {}).get("config") or {})
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def multichannel_dispatch_phantombuster(self) -> dict:
        """Envoie toutes les actions LinkedIn pending au Phantom configuré."""
        try:
            from ..integrations import multichannel_followup
            client = self._supabase()
            return multichannel_followup.auto_dispatch_to_phantombuster(client)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Phantombuster — pour DM LinkedIn auto
    # ------------------------------------------------------------------
    def phantombuster_get_config(self) -> dict:
        try:
            from ..integrations import phantombuster_client as pb
            client = self._supabase()
            cfg = pb.load_config(client)
            safe = dict(cfg)
            tk = safe.get("api_key", "")
            safe["_has_key"] = bool(tk)
            if tk:
                safe["api_key"] = tk[:6] + "•" * 8 + tk[-4:]
            return {"ok": True, "config": safe}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def phantombuster_save_config(self, payload: dict) -> dict:
        try:
            from ..integrations import phantombuster_client as pb
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            cfg_in = (payload or {}).get("config") or {}
            tk = (cfg_in.get("api_key") or "").strip()
            if not tk or "•" in tk:
                existing = pb.load_config(client)
                cfg_in["api_key"] = existing.get("api_key", "")
            pb.save_config(cfg_in, client)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Tracking d'ouvertures de mail (pixel transparent)
    # ------------------------------------------------------------------
    def tracker_get_config(self) -> dict:
        try:
            from ..integrations import email_tracker
            client = self._supabase()
            return {"ok": True, "config": email_tracker.load_config(client)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def tracker_save_config(self, payload: dict) -> dict:
        try:
            from ..integrations import email_tracker
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            email_tracker.save_config((payload or {}).get("config") or {}, client)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def tracker_stats(self) -> dict:
        """Renvoie les stats d'ouverture sur 7j et 30j."""
        try:
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            from datetime import datetime, timedelta
            sb = client.raw
            now = datetime.now()
            cutoff_7d  = (now - timedelta(days=7)).isoformat(timespec="seconds")
            cutoff_30d = (now - timedelta(days=30)).isoformat(timespec="seconds")

            def _count(kind: str, since: str) -> int:
                try:
                    r = (sb.table("email_history").select("id", count="exact")
                         .eq("kind", kind).gte("ts", since).execute())
                    return int(r.count or 0)
                except Exception:
                    return 0

            sent_7d  = _count("email_sent", cutoff_7d)
            opened_7d = _count("email_opened", cutoff_7d)
            sent_30d = _count("email_sent", cutoff_30d)
            opened_30d = _count("email_opened", cutoff_30d)
            return {
                "ok": True,
                "sent_7d": sent_7d, "opened_7d": opened_7d,
                "open_rate_7d": round(100.0 * opened_7d / max(sent_7d, 1), 1),
                "sent_30d": sent_30d, "opened_30d": opened_30d,
                "open_rate_30d": round(100.0 * opened_30d / max(sent_30d, 1), 1),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def phantombuster_test(self) -> dict:
        try:
            from ..integrations import phantombuster_client as pb
            client = self._supabase()
            cfg = pb.load_config(client)
            tk = cfg.get("api_key", "")
            if not tk:
                return {"ok": False, "error": "Clé API manquante"}
            return pb.health_check(tk)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Recyclage des prospects dormants ("pas maintenant" anciens)
    # ------------------------------------------------------------------
    def dormant_get_config(self) -> dict:
        try:
            from ..integrations import dormant_recycler
            client = self._supabase()
            return {"ok": True, "config": dormant_recycler.load_config(client)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def dormant_save_config(self, payload: dict) -> dict:
        try:
            from ..integrations import dormant_recycler
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            dormant_recycler.save_config(client, (payload or {}).get("config") or {})
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def dormant_run_now(self) -> dict:
        try:
            from ..integrations import dormant_recycler
            return {"ok": True, "result": dormant_recycler.run_now(self._app_state)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def dormant_status(self) -> dict:
        try:
            from ..integrations import dormant_recycler
            return {"ok": True, "status": dormant_recycler.get_status()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Stripe — polling des paiements pour déclencher la livraison
    # ------------------------------------------------------------------
    def stripe_get_config(self) -> dict:
        try:
            from ..integrations import stripe_poller
            client = self._supabase()
            cfg = stripe_poller.load_config(client)
            # Masque la clé pour l'affichage (mais on connait sa présence)
            sk = cfg.get("secret_key", "")
            cfg_safe = dict(cfg)
            if sk:
                cfg_safe["secret_key"] = sk[:8] + "•" * 8 + sk[-4:]
                cfg_safe["_has_key"] = True
            else:
                cfg_safe["_has_key"] = False
            return {"ok": True, "config": cfg_safe}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def stripe_save_config(self, payload: dict) -> dict:
        try:
            from ..integrations import stripe_poller
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            cfg_in = (payload or {}).get("config") or {}
            # Si secret_key contient des bullets, on garde la clé existante
            sk = (cfg_in.get("secret_key") or "").strip()
            if not sk or "•" in sk:
                existing = stripe_poller.load_config(client)
                cfg_in["secret_key"] = existing.get("secret_key", "")
            stripe_poller.save_config(client, cfg_in)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def stripe_run_now(self) -> dict:
        try:
            from ..integrations import stripe_poller
            return {"ok": True, "result": stripe_poller.run_now(self._app_state)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def stripe_status(self) -> dict:
        try:
            from ..integrations import stripe_poller
            return {"ok": True, "status": stripe_poller.get_status()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Tests A/B des sujets de mail
    # ------------------------------------------------------------------
    def ab_get_results(self) -> dict:
        try:
            from ..integrations import subject_ab_test
            client = self._supabase()
            return {"ok": True,
                    "campaigns": subject_ab_test.get_results(client),
                    "config": subject_ab_test.load_config(client)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def ab_add_campaign(self, payload: dict) -> dict:
        p = payload or {}
        name = (p.get("name") or "").strip()
        variants = p.get("variants") or []
        if not name or len(variants) < 2:
            return {"ok": False, "error": "nom + au moins 2 variantes requis"}
        try:
            from ..integrations import subject_ab_test
            client = self._supabase()
            camp = subject_ab_test.add_campaign(name, variants, client)
            return {"ok": True, "campaign": camp}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def ab_delete_campaign(self, payload: dict) -> dict:
        cid = (payload or {}).get("id") or ""
        try:
            from ..integrations import subject_ab_test
            client = self._supabase()
            return {"ok": subject_ab_test.delete_campaign(cid, client)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def ab_save_config(self, payload: dict) -> dict:
        try:
            from ..integrations import subject_ab_test
            client = self._supabase()
            cfg = (payload or {}).get("config") or {}
            subject_ab_test.save_config(cfg, client)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Tableau de bord santé du système
    # ------------------------------------------------------------------
    def system_health(self) -> dict:
        """Renvoie l'état de tous les workers + métriques de délivrabilité.

        Format :
        {
          ok: bool,
          workers: [{name, label, running, last_run_at, last_run_result, error?}],
          delivrabilité: {
            sent_24h, sent_7d, replies_24h, replies_7d,
            bounce_rate_estimate, smtp_configured, imap_configured,
          },
          summary: { healthy: int, warning: int, error: int }
        }
        """
        out = {"ok": True, "workers": [], "delivrabilité": {},
               "summary": {"healthy": 0, "warning": 0, "error": 0}}

        # 1) Statuts des workers
        worker_modules = [
            ("replies_poller",        "Lecture boîte mail (IMAP)"),
            ("reply_responder",       "Réponses automatiques"),
            ("drip_runner",           "Relances espacées (drip)"),
            ("post_sale_runner",      "Suivi après vente"),
            ("lead_to_client",        "Bascule intéressé → projet"),
            ("multichannel_followup", "Relances LinkedIn préparées"),
            ("dormant_recycler",      "Recyclage dormants"),
            ("stripe_poller",         "Polling paiements Stripe"),
            ("claude_proactive",      "Veille proactive Claude"),
            ("autopilot_runner",      "Prospection nocturne (3h Paris)"),
        ]
        for mod_name, label in worker_modules:
            try:
                mod = __import__(
                    f"triskell_command.integrations.{mod_name}",
                    fromlist=["get_status"],
                )
                status = mod.get_status() if hasattr(mod, "get_status") else {}
                running = bool(status.get("running"))
                last_run = status.get("last_run_at") or ""
                last_result = status.get("last_run_result") or {}
                has_error = bool(last_result.get("error") or last_result.get("errors", 0))
                health = "healthy" if running and not has_error else (
                    "warning" if running else "error"
                )
                out["workers"].append({
                    "name": mod_name,
                    "label": label,
                    "running": running,
                    "last_run_at": last_run,
                    "last_run_result": last_result,
                    "health": health,
                })
                out["summary"][health] += 1
            except Exception as exc:
                out["workers"].append({
                    "name": mod_name, "label": label,
                    "running": False, "last_run_at": "",
                    "last_run_result": {}, "health": "error",
                    "error": str(exc),
                })
                out["summary"]["error"] += 1

        # 2) Métriques de délivrabilité (envois + réponses sur 24h et 7j)
        client = self._supabase()
        deliv = {
            "sent_24h": 0, "sent_7d": 0, "replies_24h": 0, "replies_7d": 0,
            "reply_rate_7d": 0.0,
            "smtp_configured": False, "imap_configured": False,
        }
        outreach = self._app_state.get("outreach", default={}) or {}
        deliv["smtp_configured"] = bool(outreach.get("smtp_host") and
                                         outreach.get("smtp_user"))
        deliv["imap_configured"] = bool(outreach.get("imap_host") and
                                         outreach.get("imap_user"))
        if client:
            try:
                from datetime import datetime, timedelta
                sb = client.raw
                now = datetime.now()
                cutoff_24h = (now - timedelta(hours=24)).isoformat(timespec="seconds")
                cutoff_7d  = (now - timedelta(days=7)).isoformat(timespec="seconds")

                def _count(kind: str, since: str) -> int:
                    try:
                        r = (sb.table("email_history")
                             .select("id", count="exact")
                             .eq("kind", kind).gte("ts", since).execute())
                        return int(r.count or 0)
                    except Exception:
                        return 0

                deliv["sent_24h"] = _count("email_sent", cutoff_24h)
                deliv["sent_7d"]  = _count("email_sent", cutoff_7d)
                deliv["replies_24h"] = _count("reply_received", cutoff_24h)
                deliv["replies_7d"]  = _count("reply_received", cutoff_7d)
                if deliv["sent_7d"] > 0:
                    deliv["reply_rate_7d"] = round(
                        100.0 * deliv["replies_7d"] / deliv["sent_7d"], 1)
            except Exception as exc:
                deliv["error"] = str(exc)

        out["delivrabilité"] = deliv
        return out

    def reply_convert_to_client(self, payload: dict) -> dict:
        """Bascule manuelle d'une réponse interested vers un projet client.
        Bypass le mode 'strong' (l'utilisateur a déjà décidé).

        payload = {id: <email_history.id>}
        """
        rid = (payload or {}).get("id") or ""
        if not rid:
            return {"ok": False, "error": "id manquant"}
        try:
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            from ..integrations import lead_to_client
            sb = client.raw
            res = (sb.table("email_history").select("*")
                   .eq("id", rid).limit(1).execute())
            rows = res.data or []
            if not rows:
                return {"ok": False, "error": "réponse introuvable"}
            row = rows[0]
            extra = row.get("extra") or {}
            if isinstance(extra, str):
                import json as _json
                try: extra = _json.loads(extra)
                except Exception: extra = {}
            if extra.get("lead_converted_at"):
                return {"ok": False, "error": "déjà converti",
                        "client_project_id": extra.get("lead_converted_to")}
            cfg = lead_to_client.load_config(client)
            ok = lead_to_client._convert_to_client_project(  # noqa
                client, sb, row, extra,
                cfg.get("default_product_key", "custom-dev"),
                cfg.get("default_product_name", "Service Triskell"),
                has_strong=False,  # explicite : déclenchement manuel
            )
            return {"ok": ok}
        except Exception as exc:
            logger.exception("reply_convert_to_client")
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Auto-pilote — pipeline complet (cible → recherche → IA → envoi → suivi)
    # ------------------------------------------------------------------
    def autopilot_get_config(self) -> dict:
        """Renvoie la config courante du pipeline (dict sérialisable)."""
        try:
            from dataclasses import asdict
            from triskell_core.prospect.pipeline import PipelineConfig
            cfg = PipelineConfig.load()
            return {"ok": True, "config": asdict(cfg)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def autopilot_save_config(self, payload: dict) -> dict:
        """Sauve la config (et synchronise les clés API/SMTP vers le Core)."""
        p = (payload or {}).get("config") or {}
        try:
            from triskell_core.prospect.pipeline import PipelineConfig
            valid = {f for f in PipelineConfig.__dataclass_fields__}
            clean = {k: v for k, v in p.items() if k in valid}
            cfg = PipelineConfig(**clean)
            cfg.save()
            self._sync_keys_to_core()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def autopilot_run(self, payload: dict | None = None) -> dict:
        """Lance le pipeline en arrière-plan. Retourne immédiatement.
        Le front polle ensuite autopilot_status() pour le log + stats.

        payload.stages : liste optionnelle parmi
        ['imap','search','enrich','send','follow_up']. Si absent, tout tourne.
        L'Éclaireur passe ['search','enrich'] ; l'Auto-pilote passe
        ['imap','send','follow_up'].
        """
        # Refuse si un run est déjà en cours -- check local (clic "Lancer"
        # deja actif) ET global (worker nocturne en train de tourner).
        from triskell_command.integrations import autopilot_runner as _apr
        with self._autopilot_lock:
            if self._autopilot_state.get("running"):
                return {"ok": False, "error": "Un run est déjà en cours."}
            if not _apr.acquire_run_lock():
                return {
                    "ok": False,
                    "error": "Le run nocturne est en cours, attends la fin."
                }
            # Reset état + reset du flag stop global
            _apr.clear_stop()
            from datetime import datetime
            self._autopilot_state.update({
                "running": True,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": "",
                "log": [],
                "stats": None,
                "error": "",
                "stages": self._fresh_stages(),
                "current_activity": "",
                "touched_prospects": [],
                "stop_requested": False,
            })

        # Sauve la config avant lancement (si fournie)
        if payload and payload.get("config"):
            r = self.autopilot_save_config(payload)
            if not r.get("ok"):
                with self._autopilot_lock:
                    self._autopilot_state["running"] = False
                    self._autopilot_state["error"] = r.get("error", "")
                return r

        # Sélection des étapes. None/absent = "bouton Lancer maintenant"
        # de l'auto-pilote -> on respecte les interrupteurs UI exactement
        # comme le declencheur automatique. Sinon (ex: Eclaireur qui passe
        # ['search','enrich']) -> on garde l'ancien comportement explicite.
        stages_in = (payload or {}).get("stages") if isinstance(payload, dict) else None
        use_ui_modes = stages_in is None
        if not use_ui_modes:
            stages = {str(s).strip().lower() for s in stages_in if s}

        # Sync clés API au Core (au cas où)
        self._sync_keys_to_core()

        # _push_log : accepte une string (log texte) OU un dict (evenement
        # structure pour la visu temps reel). Les deux peuvent etre emis
        # par le pipeline / le runner via le callback `progress`.
        def _push_log(msg) -> None:
            from datetime import datetime
            # Bouton Stop : si l'utilisateur a demandé l'arrêt, on lève une
            # exception pour interrompre le pipeline. _push_log est appelé
            # très souvent par run_full_pipeline (à chaque étape + activity),
            # donc on attrape l'arrêt rapidement.
            with self._autopilot_lock:
                if self._autopilot_state.get("stop_requested"):
                    raise _AutopilotStopped()
            if isinstance(msg, dict):
                self._push_event(msg)
                # Si l'evenement porte aussi un message lisible, on log
                t = msg.get("type")
                txt = msg.get("message") or ""
                if txt and t in ("stage", "stage_done", "stage_error"):
                    stage_label = {
                        "search": "Cherche",
                        "sort": "Trie",
                        "write": "Rédige",
                        "review": "Relit",
                        "send": "Envoie",
                    }.get(msg.get("id"), msg.get("id", ""))
                    prefix = "✓" if t == "stage_done" else ("✗" if t == "stage_error" else "→")
                    line = f"[{datetime.now().strftime('%H:%M:%S')}] {prefix} {stage_label} — {txt}"
                    with self._autopilot_lock:
                        self._autopilot_state["log"].append(line)
                        buf = self._autopilot_state["log"]
                        if len(buf) > 500:
                            del buf[: len(buf) - 500]
                return
            line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
            with self._autopilot_lock:
                buf = self._autopilot_state["log"]
                buf.append(line)
                if len(buf) > 500:
                    del buf[: len(buf) - 500]

        def _worker():
            from dataclasses import asdict
            from datetime import datetime
            try:
                from triskell_core.prospect.pipeline import (
                    PipelineConfig, run_full_pipeline,
                )
                cfg = PipelineConfig.load()
                if use_ui_modes:
                    from triskell_command.integrations.autopilot_runner import (
                        run_pipeline_with_ui_modes,
                    )
                    stats = run_pipeline_with_ui_modes(cfg, _push_log)
                else:
                    _push_log(
                        "Lancement : " + ", ".join(sorted(stages))
                        + f" (mode {cfg.mode})…"
                    )
                    stats = run_full_pipeline(
                        cfg,
                        progress=_push_log,
                        poll_imap=("imap" in stages),
                        do_search=("search" in stages),
                        do_enrich=("enrich" in stages),
                        do_send=("send" in stages),
                        do_follow_up=("follow_up" in stages),
                    )
                _push_log(
                    f"=== Fin === {stats.searched} trouvés, "
                    f"{stats.enriched} enrichis, {stats.drafts_sent} envoyés, "
                    f"{stats.drafts_pending} brouillons en attente, "
                    f"{stats.replies_detected} réponses, "
                    f"{len(stats.errors)} erreurs."
                )
                with self._autopilot_lock:
                    self._autopilot_state["stats"] = asdict(stats)
            except _AutopilotStopped:
                # Arrêt demandé via le bouton Stop : on note dans le log sans
                # passer par _push_log (qui re-leverait l'exception).
                from datetime import datetime
                line = (
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"⏹ Run arrêté à la demande de l'utilisateur."
                )
                with self._autopilot_lock:
                    self._autopilot_state["log"].append(line)
                    self._autopilot_state["error"] = (
                        "Arrêté à la demande de l'utilisateur."
                    )
            except Exception as exc:
                logger.exception("autopilot_run a échoué")
                _push_log(f"✗ Pipeline a échoué : {exc}")
                with self._autopilot_lock:
                    self._autopilot_state["error"] = str(exc)
            finally:
                with self._autopilot_lock:
                    self._autopilot_state["running"] = False
                    self._autopilot_state["stop_requested"] = False
                    self._autopilot_state["finished_at"] = (
                        datetime.now().isoformat(timespec="seconds")
                    )
                # Relache le lock global et reset le flag stop, dans tous
                # les cas (succes, exception, stop demande).
                _apr.release_run_lock()
                _apr.clear_stop()

        threading.Thread(
            target=_worker, daemon=True, name="AutopilotRun",
        ).start()
        return {"ok": True, "started": True}

    def autopilot_status(self, payload: dict | None = None) -> dict:
        """Renvoie l'état du run (logs nouveaux depuis l'offset, running, stats).

        payload = {since: int}  → indice à partir duquel renvoyer le log
        """
        since = int((payload or {}).get("since") or 0)
        with self._autopilot_lock:
            log = self._autopilot_state["log"]
            new_lines = log[since:]
            import copy
            return {
                "ok": True,
                "running":     bool(self._autopilot_state["running"]),
                "started_at":  self._autopilot_state["started_at"],
                "finished_at": self._autopilot_state["finished_at"],
                "log":         new_lines,
                "log_len":     len(log),
                "stats":       self._autopilot_state["stats"],
                "error":       self._autopilot_state["error"],
                # Visu temps réel
                "stages":            copy.deepcopy(self._autopilot_state["stages"]),
                "current_activity":  self._autopilot_state["current_activity"],
                "touched_prospects": list(self._autopilot_state["touched_prospects"]),
                "stop_requested":    bool(self._autopilot_state.get("stop_requested")),
            }

    def autopilot_stop(self, payload: dict | None = None) -> dict:
        """Demande l'arrêt du run en cours. Le pipeline lèvera _AutopilotStopped
        à la prochaine émission de log (typiquement < 1s).

        Couvre les 2 declenchements : run via bouton "Lancer maintenant"
        (state local) ET run nocturne (flag global du module runner)."""
        from triskell_command.integrations import autopilot_runner as _apr
        # Cas run via bouton "Lancer" : state local
        with self._autopilot_lock:
            local_running = bool(self._autopilot_state.get("running"))
            if local_running:
                self._autopilot_state["stop_requested"] = True
        # Cas run nocturne : flag global du module runner
        nightly_running = _apr.is_pipeline_running() and not local_running
        if nightly_running:
            _apr.request_stop()
        if not (local_running or nightly_running):
            return {"ok": False, "error": "Aucun run en cours."}
        return {"ok": True}

    # ------------------------------------------------------------------
    # Tableau de commande Auto-pilote v2 — compteurs des 5 maillons
    # ------------------------------------------------------------------
    def autopilot_last_run_counts(self) -> dict:
        """Renvoie les compteurs des 5 maillons pour le DERNIER run de
        l'autopilote (en mémoire). Si aucun run n'a tourné depuis le boot
        du serveur, tous les chiffres sont None et `has_data` est False.

        Les chiffres viennent de `self._autopilot_state["stages"]` qui est
        rempli en temps réel pendant un run (events `stage_done`).
        """
        with self._autopilot_lock:
            stages = dict(self._autopilot_state.get("stages") or {})
            started_at = self._autopilot_state.get("started_at") or ""
            finished_at = self._autopilot_state.get("finished_at") or ""
            running = bool(self._autopilot_state.get("running"))
        # has_data = au moins UN stage a tourné (running, done ou error)
        has_data = any(
            (info or {}).get("state") not in (None, "", "idle")
            for info in stages.values()
        )
        out: dict = {
            "ok": True,
            "has_data": has_data,
            "running": running,
            "started_at": started_at,
            "finished_at": finished_at,
        }
        for stage_key in ("search", "sort", "write", "review", "send"):
            info = stages.get(stage_key) or {}
            # On expose count uniquement si le stage a vraiment tourné,
            # sinon None pour que le front affiche "—"
            if info.get("state") in (None, "", "idle"):
                out[stage_key] = None
            else:
                out[stage_key] = int(info.get("count") or 0)
        return out

    def autopilot_target_count(self) -> dict:
        """Compte les prospects qui pourraient être ciblés par un run.

        Pour éviter une logique métier dupliquée, on reprend les filtres
        structurels du pipeline d'éligibilité :
          - status ∈ {'new', 'qualified'} (les autres sont déjà avancés)
          - au moins un email (sans email l'app ne peut rien envoyer)
        On ne refait PAS ici le filtre "jamais contacté" (qui regarde
        l'historique des mails) — c'est coûteux et de toute façon le
        run réel re-filtrera. Ce chiffre est une **borne supérieure
        de ce qui peut potentiellement être traité**.

        Renvoie :
          {ok, eligible_total, target_per_run, nightly_target,
           pickable: min(target_per_run, eligible_total)}
        """
        client = self._supabase_client_or_none()
        if client is None:
            return {"ok": False, "error": "Supabase indisponible"}
        sb = client.raw
        try:
            r = (sb.table("prospects")
                   .select("id", count="exact")
                   .in_("status", ["new", "qualified"])
                   .neq("emails", "[]")
                   .execute())
            eligible_total = int(r.count or 0)
        except Exception as exc:
            logger.debug("autopilot_target_count : %s", exc)
            eligible_total = 0
        # Récupère le nightly_target courant pour montrer combien sera
        # piocé sur cette base éligible.
        nightly_target = 0
        try:
            cfg_r = self.autopilot_get_config()
            cfg = (cfg_r.get("config") or {}) if isinstance(cfg_r, dict) else {}
            nightly_target = int(cfg.get("nightly_target") or 0)
        except Exception:
            nightly_target = 0
        pickable = (min(nightly_target, eligible_total)
                    if nightly_target > 0 else eligible_total)
        return {
            "ok": True,
            "eligible_total": eligible_total,
            "nightly_target": nightly_target,
            "pickable":       pickable,
        }

    def autopilot_pulse(self, payload: dict | None = None) -> dict:
        """Renvoie les compteurs des 5 maillons de la chaine, sur les
        `hours` dernieres heures (defaut : 24h).

        payload = {hours: int}   optionnel, borne [1, 720]

        Renvoie :
          ok, hours, since,
          search : nouveaux prospects entres dans la base
          sort   : prospects passes au statut 'qualified'
          write  : brouillons crees
          review : a venir (toujours 0 pour l'instant -- etape 7 du chantier)
          send   : mails envoyes (kind='email_sent' dans email_history)
        """
        from datetime import datetime, timedelta, timezone
        hours = int((payload or {}).get("hours") or 24)
        hours = max(1, min(hours, 30 * 24))
        client = self._supabase()
        if client is None:
            return {"ok": False, "error": "Supabase indisponible"}
        sb = client.raw
        since = (datetime.now(timezone.utc)
                 - timedelta(hours=hours)).isoformat()

        def _count(table: str, ts_col: str, **filters) -> int:
            try:
                q = (sb.table(table).select("id", count="exact")
                     .gte(ts_col, since))
                for k, v in filters.items():
                    q = q.eq(k, v)
                r = q.execute()
                return int(r.count or 0)
            except Exception as exc:
                logger.debug("autopilot_pulse count %s: %s", table, exc)
                return 0

        return {
            "ok": True,
            "hours":  hours,
            "since":  since,
            "search": _count("prospects",       "created_at"),
            "sort":   _count("prospects",       "created_at", status="qualified"),
            "write":  _count("prospect_drafts", "created_at"),
            "review": _count("email_history",   "ts", kind="email_reviewed"),
            "send":   _count("email_history",   "ts", kind="email_sent"),
        }

    # ------------------------------------------------------------------
    # Tableau de commande Auto-pilote v2 — modes Auto / Manuel par maillon
    # ------------------------------------------------------------------
    _AP_STAGE_KEYS = ("search", "sort", "write", "review", "send")
    _AP_STAGE_MODES = ("auto", "manual")
    _AP_STAGE_DEFAULTS = {
        "search": "auto", "sort": "auto", "write": "auto",
        "review": "manual", "send": "manual",
    }
    _AP_STAGE_SETTING_KEY = "autopilot_stage_modes"

    def autopilot_get_stage_modes(self) -> dict:
        """Renvoie le dict des 5 modes Auto/Manuel par maillon.

        Lit shared_settings.autopilot_stage_modes ; merge avec les defauts
        si une cle est absente (compat ajout futur de maillons).
        """
        client = self._supabase()
        defaults = dict(self._AP_STAGE_DEFAULTS)
        if client is None:
            return {"ok": True, "modes": defaults, "source": "defaults"}
        try:
            saved = client.get_shared_setting(self._AP_STAGE_SETTING_KEY, None)
        except Exception as exc:
            logger.debug("autopilot_get_stage_modes: %s", exc)
            saved = None
        modes = dict(defaults)
        if isinstance(saved, dict):
            for k in self._AP_STAGE_KEYS:
                v = saved.get(k)
                if v in self._AP_STAGE_MODES:
                    modes[k] = v
        return {
            "ok": True,
            "modes": modes,
            "source": "saved" if isinstance(saved, dict) else "defaults",
        }

    def autopilot_list_products(self) -> dict:
        """Liste les produits ayant au moins un template de prospection actif
        ET qui sont actives dans le catalogue (toggle on dans la vue Catalogue).

        Source 1 : table triskell_email_templates filtree sur
                   category='prospection' et enabled=true.
        Source 2 : shared_settings.catalog_overrides.disabled_ids -> on
                   exclut tout produit dont l'id matche (compare lowercased).

        Renvoie : {ok, products: [{key, label, audiences: ['creator', 'pro']}]}
        """
        client = self._supabase()
        if client is None:
            return {"ok": False, "error": "Supabase indisponible"}
        try:
            res = (client.raw.table("triskell_email_templates")
                   .select("product, audience")
                   .eq("category", "prospection")
                   .eq("enabled", True)
                   .execute())
            rows = res.data or []
        except Exception as exc:
            logger.warning("autopilot_list_products: %s", exc)
            return {"ok": False, "error": str(exc)}

        # Recupere la liste des produits desactives dans le catalogue
        try:
            from ..integrations.catalog_overrides import get_disabled_ids
            disabled = {d.lower() for d in get_disabled_ids()}
        except Exception as exc:
            logger.debug("autopilot_list_products: catalog_overrides KO (%s)", exc)
            disabled = set()

        # Regroupe par produit + collecte les audiences ; exclut les desactives
        by_product: dict = {}
        for r in rows:
            p = (r.get("product") or "").strip()
            if not p:
                continue
            if p.lower() in disabled:
                continue  # produit desactive dans le catalogue -> on cache
            entry = by_product.setdefault(p, {"key": p, "audiences": set()})
            a = (r.get("audience") or "").strip()
            if a:
                entry["audiences"].add(a)
        products = []
        for k in sorted(by_product):
            e = by_product[k]
            products.append({
                "key":       e["key"],
                "label":     e["key"],   # pas de label produit dans la table -- afficher la cle
                "audiences": sorted(e["audiences"]),
            })
        return {"ok": True, "products": products}

    def autopilot_set_stage_mode(self, payload: dict) -> dict:
        """Sauvegarde le mode (auto/manual) d'un maillon.

        payload = {stage: 'search|sort|write|review|send', mode: 'auto|manual'}
        """
        stage = (payload or {}).get("stage") or ""
        mode  = (payload or {}).get("mode") or ""
        if stage not in self._AP_STAGE_KEYS:
            return {"ok": False, "error": f"stage invalide : {stage}"}
        if mode not in self._AP_STAGE_MODES:
            return {"ok": False, "error": f"mode invalide : {mode}"}
        client = self._supabase()
        if client is None:
            return {"ok": False, "error": "Supabase indisponible"}
        try:
            current = client.get_shared_setting(
                self._AP_STAGE_SETTING_KEY, {}) or {}
            if not isinstance(current, dict):
                current = {}
            current[stage] = mode
            client.set_shared_setting(self._AP_STAGE_SETTING_KEY, current)
        except Exception as exc:
            logger.warning("autopilot_set_stage_mode: %s", exc)
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "stage": stage, "mode": mode}

    # ------------------------------------------------------------------
    # Modes simples — bouton "envoi direct" vs "validation manuelle"
    # exposés dans le cockpit pour bascule en 1 clic
    # ------------------------------------------------------------------
    def get_simple_modes(self) -> dict:
        """Renvoie l'état des 2 modes principaux : prospection + réponses.

        Chacun vaut "direct" (envoi auto, sans demander) ou "validation"
        (l'humain valide chaque mail).
        """
        out = {"ok": True, "prospection": "validation", "reponses": "validation"}
        try:
            from triskell_core.prospect.pipeline import PipelineConfig
            cfg = PipelineConfig.load()
            out["prospection"] = "direct" if cfg.mode == "auto" else "validation"
        except Exception as exc:
            logger.debug("get_simple_modes prospection: %s", exc)
        try:
            from ..integrations import reply_responder
            client = self._supabase()
            if client:
                cfg = reply_responder.load_config(client)
                if cfg.get("enabled") is False:
                    out["reponses"] = "off"
                else:
                    gm = cfg.get("global_mode") or "manual"
                    per = cfg.get("per_category") or {}
                    all_instant = bool(per) and all(v == "instant" for v in per.values())
                    out["reponses"] = "direct" if (gm == "instant" or all_instant) else "validation"
        except Exception as exc:
            logger.debug("get_simple_modes reponses: %s", exc)
        return out

    def set_simple_mode(self, payload: dict) -> dict:
        """Bascule un mode global.

        payload = {kind: "prospection"|"reponses", mode: "direct"|"validation"}
        """
        kind = (payload or {}).get("kind") or ""
        mode = (payload or {}).get("mode") or ""
        if kind not in ("prospection", "reponses"):
            return {"ok": False, "error": "kind invalide"}
        # Le mode "off" est uniquement valable pour les réponses pour le moment.
        if kind == "reponses":
            if mode not in ("direct", "validation", "off"):
                return {"ok": False, "error": "mode invalide"}
        else:
            if mode not in ("direct", "validation"):
                return {"ok": False, "error": "mode invalide"}
        try:
            if kind == "prospection":
                from triskell_core.prospect.pipeline import PipelineConfig
                cfg = PipelineConfig.load()
                cfg.mode = "auto" if mode == "direct" else "validation"
                cfg.save()
            else:
                from ..integrations import reply_responder
                client = self._supabase()
                if not client:
                    return {"ok": False, "error": "Base partagée non connectée"}
                cfg = reply_responder.load_config(client)
                if mode == "off":
                    cfg["enabled"] = False
                else:
                    cfg["enabled"] = True
                    target = "instant" if mode == "direct" else "manual"
                    cfg["global_mode"] = target
                    per = dict(cfg.get("per_category") or {})
                    for k in list(per.keys()):
                        per[k] = target
                    cfg["per_category"] = per
                reply_responder.save_config(client, cfg)
            return {"ok": True}
        except Exception as exc:
            logger.exception("set_simple_mode")
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Log d'une prospection manuelle — crée/upserte un prospect et le
    # marque comme contacté. Utilisé par les campagnes hors-Convoy où
    # les destinataires n'existent pas encore en base (prospection au
    # fil de l'eau, mails de partenariat, etc.).
    # ------------------------------------------------------------------
    def prospect_log_outreach(self, payload: dict) -> dict:
        """Crée (ou met à jour) un prospect et le marque comme contacté.

        Si un prospect existe déjà avec cet email, on met seulement à jour
        son statut, last_contact_at, et on concatène les notes. Sinon on
        l'insère.

        payload = {
            name:     str (requis) — nom de l'organisation/contact
            email:    str (requis) — adresse mail principale
            website:  str (optionnel)
            city:     str (optionnel)
            industry: str (optionnel) — secteur d'activité
            status:   str (défaut 'contacted')
            notes:    str (optionnel)
            tags:     list[str] (optionnel)
        }
        """
        p = payload or {}
        name = (p.get("name") or "").strip()
        email = (p.get("email") or "").strip().lower()
        website = (p.get("website") or "").strip()
        city = (p.get("city") or "").strip()
        industry = (p.get("industry") or "").strip()
        status = (p.get("status") or "contacted").strip() or "contacted"
        notes = (p.get("notes") or "").strip()
        tags = p.get("tags") or []
        if not isinstance(tags, list):
            tags = []

        if not name or not email:
            return {"ok": False, "error": "name et email requis"}
        if "@" not in email:
            return {"ok": False, "error": "Email invalide"}

        client = self._supabase()
        if not client:
            return {"ok": False, "error": "Base partagée non connectée"}
        sb = client.raw
        now_iso = self._iso_now()

        ws_id = None
        try:
            ws_id = client._current_workspace_id()
        except Exception:
            pass

        # Cherche un prospect existant par email (jsonb contains)
        existing: list = []
        try:
            res = (sb.table("prospects")
                   .select("id, status, notes, tags")
                   .contains("emails", [email])
                   .limit(1)
                   .execute())
            existing = res.data or []
        except Exception as exc:
            logger.debug("prospect_log_outreach lookup KO: %s", exc)

        if existing:
            pid = existing[0]["id"]
            old_notes = (existing[0].get("notes") or "").strip()
            merged_notes = old_notes
            if notes:
                stamp = now_iso[:10]
                merged_notes = (old_notes
                                + ("\n" if old_notes else "")
                                + f"[{stamp}] {notes}").strip()
            old_tags = existing[0].get("tags") or []
            if isinstance(old_tags, str):
                try:
                    old_tags = json.loads(old_tags)
                except Exception:
                    old_tags = []
            merged_tags = list({*(old_tags or []), *tags})
            update_row = {
                "status": status,
                "last_contact_at": now_iso,
            }
            if merged_notes:
                update_row["notes"] = merged_notes
            if merged_tags:
                update_row["tags"] = merged_tags
            try:
                sb.table("prospects").update(update_row).eq("id", pid).execute()
                return {"ok": True, "prospect_id": pid, "action": "updated"}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        # Insert nouveau prospect
        row = {
            "name": name,
            "emails": [email],
            "website": website,
            "city": city,
            "industry": industry,
            "status": status,
            "last_contact_at": now_iso,
            "notes": notes,
            "tags": tags,
        }
        if ws_id:
            row["workspace_id"] = ws_id
        try:
            res = sb.table("prospects").insert(row).execute()
            new_id = ""
            if res.data:
                first = res.data[0] or {}
                new_id = first.get("id", "")
            return {"ok": True, "prospect_id": new_id, "action": "created"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Timeline d'un prospect — agrégation de tout son parcours
    # ------------------------------------------------------------------
    def prospect_timeline(self, payload: dict) -> dict:
        """Reconstitue le parcours complet d'un prospect en une seule liste
        chronologique d'événements (ajout en base, mails envoyés, ouvertures,
        réponses classées, bascule client, paiement, livraisons, post-vente).

        payload = {id: <prospect_id>}
        """
        pid = ((payload or {}).get("id") or "").strip()
        if not pid:
            return {"ok": False, "error": "id manquant"}
        try:
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            sb = client.raw

            pres = (sb.table("prospects").select("*")
                    .eq("id", pid).limit(1).execute())
            prows = pres.data or []
            if not prows:
                return {"ok": False, "error": "prospect introuvable"}
            prospect = prows[0]

            hres = (sb.table("email_history").select("*")
                    .eq("prospect_id", pid).order("ts", desc=False)
                    .limit(500).execute())
            history = hres.data or []

            try:
                cpres = (sb.table("client_projects").select("*")
                         .eq("prospect_id", pid).order("created_at", desc=False)
                         .limit(5).execute())
                projects = cpres.data or []
            except Exception:
                projects = []

            import json as _json
            events: list[dict] = []

            sources = prospect.get("sources") or []
            if isinstance(sources, str):
                try: sources = _json.loads(sources)
                except Exception: sources = []
            src_name = ""
            if isinstance(sources, list) and sources:
                first = sources[0] or {}
                src_name = (first.get("name") or "").strip()
            events.append({
                "ts":       prospect.get("created_at") or "",
                "type":     "prospect_added",
                "icon":     "🔍",
                "title":    "Ajouté à ta base",
                "subtitle": (f"Source : {src_name}" if src_name else ""),
            })

            for row in history:
                extra = row.get("extra") or {}
                if isinstance(extra, str):
                    try: extra = _json.loads(extra)
                    except Exception: extra = {}
                kind = row.get("kind") or ""
                ts = row.get("ts") or ""
                subj = (row.get("subject") or "").strip()
                body = (row.get("body") or "").strip()
                body_excerpt = body[:280] + ("…" if len(body) > 280 else "")

                if kind == "email_sent":
                    events.append({
                        "ts": ts, "type": "email_sent", "icon": "✉",
                        "title": "Mail envoyé",
                        "subject": subj, "body_excerpt": body_excerpt,
                    })
                elif kind == "reply_received":
                    classif = extra.get("classification") or {}
                    cat = (classif.get("category") or "").strip()
                    cat_labels = {
                        "interested":  "Intéressé",
                        "not_now":     "Pas maintenant",
                        "no":          "Refus",
                        "unsubscribe": "Désinscription",
                        "unknown":     "À trier",
                    }
                    cat_label = cat_labels.get(cat, cat or "à trier")
                    events.append({
                        "ts": ts, "type": "reply_received", "icon": "📨",
                        "title": f"Réponse reçue — {cat_label}",
                        "subject": subj,
                        "body_excerpt": body_excerpt,
                        "category": cat,
                    })
                elif kind == "inbox_received":
                    events.append({
                        "ts": ts, "type": "inbox_received", "icon": "📥",
                        "title": "Mail reçu (non classé)",
                        "subject": subj, "body_excerpt": body_excerpt,
                    })
                elif kind == "dormant_recycle":
                    events.append({
                        "ts": ts, "type": "dormant_recycle", "icon": "♻️",
                        "title": "Réveil d'un dormant",
                        "body_excerpt": body_excerpt,
                    })
                else:
                    events.append({
                        "ts": ts, "type": kind or "event", "icon": "•",
                        "title": kind or "Événement",
                        "subject": subj, "body_excerpt": body_excerpt,
                    })

                opened_at = extra.get("opened_at") or extra.get("first_opened_at")
                if opened_at and kind == "email_sent":
                    events.append({
                        "ts": opened_at, "type": "email_opened", "icon": "👁",
                        "title": "Mail ouvert par le prospect",
                        "subject": subj,
                    })

            for proj in projects:
                created = proj.get("created_at") or ""
                product = (proj.get("product_name") or
                           proj.get("title") or "Projet").strip()
                if created:
                    events.append({
                        "ts": created, "type": "lead_converted", "icon": "🎯",
                        "title": "Devenu projet client",
                        "subtitle": product,
                        "project_id": proj.get("id"),
                    })
                paid_at = proj.get("paid_at")
                if paid_at:
                    cents = proj.get("amount_cents") or 0
                    currency = proj.get("currency") or "EUR"
                    amount_str = ""
                    if cents:
                        amount_str = f"{cents / 100:.2f} {currency}"
                    events.append({
                        "ts": paid_at, "type": "payment", "icon": "💳",
                        "title": "Paiement reçu",
                        "subtitle": amount_str or product,
                    })
                status = (proj.get("status") or "").lower()
                if status == "delivered":
                    events.append({
                        "ts": proj.get("updated_at") or paid_at or created,
                        "type": "delivered", "icon": "🎁",
                        "title": "Kit de livraison envoyé",
                        "subtitle": product,
                    })
                if proj.get("cross_sell_sent_at"):
                    events.append({
                        "ts": proj["cross_sell_sent_at"],
                        "type": "cross_sell", "icon": "🔁",
                        "title": "Mail cross-sell envoyé",
                    })
                if proj.get("nps_sent_at"):
                    events.append({
                        "ts": proj["nps_sent_at"],
                        "type": "nps", "icon": "⭐",
                        "title": "Demande d'avis NPS envoyée",
                    })

            events.sort(key=lambda e: (e.get("ts") or ""))

            emails = prospect.get("emails") or []
            if isinstance(emails, str):
                try: emails = _json.loads(emails)
                except Exception: emails = []
            primary_email = (emails[0] if isinstance(emails, list) and emails
                             else "")
            summary = {
                "id":          prospect.get("id"),
                "name":        (prospect.get("name")
                                or prospect.get("legal_name") or ""),
                "email":       primary_email,
                "city":        prospect.get("city") or "",
                "country":     prospect.get("country") or "",
                "industry":    prospect.get("industry") or "",
                "website":     prospect.get("website") or "",
                "status":      prospect.get("status") or "",
                "created_at":  prospect.get("created_at") or "",
                "source_name": src_name,
            }

            return {
                "ok": True,
                "prospect": summary,
                "events":   events,
                "has_project": bool(projects),
            }
        except Exception as exc:
            logger.exception("prospect_timeline")
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Setup status — bilan rapide des connexions nécessaires
    # ------------------------------------------------------------------
    def setup_status(self) -> dict:
        """Renvoie une checklist de tout ce qui doit être branché pour que
        le workflow tourne tout seul. Chaque item a un statut et une
        destination dans les Réglages.

        items[i] = {
          key, label, status: "ok"|"warn"|"missing",
          why, goto: {"view": "config", "tab": "..."}
        }
        """
        from ..integrations import shared_secrets
        client = self._supabase()
        items: list[dict] = []

        # 1. Base partagée
        connected = bool(client)
        items.append({
            "key": "supabase",
            "label": "Base partagée connectée",
            "status": "ok" if connected else "missing",
            "why": ("Tout passe par la base partagée Triskell : sans elle, "
                    "rien n'est sauvegardé." if not connected else ""),
            "goto": {"view": "config", "tab": "account"},
        })

        # 2. Adresse mail d'envoi (SMTP)
        smtp = shared_secrets.get_smtp_config(
            client=client, app_state=self._app_state) or {}
        smtp_ok = bool(smtp.get("smtp_host") and smtp.get("smtp_user")
                       and smtp.get("smtp_password") and smtp.get("from_email"))
        items.append({
            "key": "smtp",
            "label": "Adresse mail d'envoi",
            "status": "ok" if smtp_ok else "missing",
            "why": ("Sans adresse mail configurée, aucun mail ne peut partir."
                    if not smtp_ok else ""),
            "goto": {"view": "config", "tab": "mails"},
        })

        # 3. Lecture de la boîte mail (IMAP) — nécessaire pour voir les réponses
        imap_ok = bool(smtp.get("imap_host") and smtp.get("imap_user")
                       and smtp.get("imap_password"))
        items.append({
            "key": "imap",
            "label": "Lecture de la boîte mail",
            "status": "ok" if imap_ok else "missing",
            "why": ("Sans accès en lecture, l'app ne peut pas détecter les "
                    "réponses des prospects." if not imap_ok else ""),
            "goto": {"view": "config", "tab": "mails"},
        })

        # 4. Au moins une clé IA (pour rédiger les mails)
        ai_keys = shared_secrets.get_ai_keys(
            client=client, app_state=self._app_state) or {}
        has_ai = any(bool(v) for v in ai_keys.values())
        items.append({
            "key": "ai",
            "label": "Service d'intelligence artificielle",
            "status": "ok" if has_ai else "missing",
            "why": ("Sans IA, les mails ne peuvent pas être rédigés "
                    "automatiquement." if not has_ai else ""),
            "goto": {"view": "config", "tab": "ai"},
        })

        # 5. Stripe (clé secrète)
        stripe_ok = False
        stripe_has_mapping = False
        try:
            from ..integrations import stripe_poller
            scfg = stripe_poller.load_config(client) if client else {}
            stripe_ok = bool(scfg.get("secret_key") and scfg.get("enabled"))
            stripe_has_mapping = bool(scfg.get("product_mapping") or {})
        except Exception:
            pass
        items.append({
            "key": "stripe",
            "label": "Stripe — encaissement automatique",
            "status": "ok" if stripe_ok else "missing",
            "why": ("Sans clé Stripe, l'app ne voit pas les paiements et "
                    "ne déclenche pas la livraison." if not stripe_ok else ""),
            "goto": {"view": "config", "tab": "integrations"},
        })

        # 6. Mapping des produits Stripe (pas bloquant mais recommandé)
        items.append({
            "key": "stripe_mapping",
            "label": "Lien Stripe ↔ kits de livraison",
            "status": ("ok" if stripe_has_mapping
                       else ("warn" if stripe_ok else "missing")),
            "why": ("Sans ce lien, tous les paiements déclenchent le kit "
                    "générique au lieu du bon kit produit."
                    if not stripe_has_mapping else ""),
            "goto": {"view": "config", "tab": "integrations"},
        })

        summary = {"ok": 0, "warn": 0, "missing": 0}
        for it in items:
            summary[it["status"]] = summary.get(it["status"], 0) + 1
        return {"ok": True, "items": items, "summary": summary}

    def _sync_keys_to_core(self) -> None:
        """Recopie les clés API + SMTP/IMAP du state Triskell Command vers
        config.json Core, pour que run_full_pipeline les retrouve."""
        try:
            import json
            from triskell_core.prospect.core.crm import (
                CONFIG_FILE, ensure_dirs,
            )
            ensure_dirs()
            current = {}
            if CONFIG_FILE.exists():
                try:
                    current = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                except Exception:
                    current = {}
            # SMTP/IMAP
            outreach = self._app_state.get("outreach", default={}) or {}
            for k in ("smtp_host", "smtp_port", "smtp_user", "smtp_password",
                      "from_email", "from_name", "imap_host", "imap_port",
                      "imap_user", "imap_password"):
                v = outreach.get(k)
                if v not in (None, ""):
                    current[k] = v
            # Clés API IA
            ai = self._app_state.get("ai", default={}) or {}
            api_keys = ai.get("api_keys") or {}
            for provider, key in api_keys.items():
                if key:
                    current[f"{provider}_api_key"] = key
            # Maps
            sources = self._app_state.get("sources", default={}) or {}
            if sources.get("google_places_api_key"):
                current["google_places_api_key"] = sources[
                    "google_places_api_key"
                ]
            CONFIG_FILE.write_text(
                json.dumps(current, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("_sync_keys_to_core: %s", exc)

    # ------------------------------------------------------------------
    # Helpers internes
    # ------------------------------------------------------------------
    def _supabase(self):
        try:
            from triskell_core.db import get_client, SupabaseNotConfigured
            try:
                client = get_client()
            except SupabaseNotConfigured:
                return None
            if not client.is_authenticated:
                return None
            return client
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Workers : démarrage au boot
    # ------------------------------------------------------------------
    def boot(self) -> dict:
        """Appelé par le front au chargement initial. Démarre les workers
        background une seule fois."""
        if self._workers_started:
            return {"ok": True, "already_started": True}
        self._workers_started = True

        # Restauration session Supabase (si configurée)
        try:
            from triskell_core.db import get_client, SupabaseNotConfigured
            try:
                client = get_client()
                if not client.is_authenticated:
                    try:
                        client.restore_session()
                    except Exception as exc:
                        logger.debug("restore session: %s", exc)
            except SupabaseNotConfigured:
                pass
        except Exception:
            pass

        # Migration one-shot des secrets locaux → shared_settings (Supabase),
        # pour que Jordan ET Thomas partagent leur SMTP/IMAP + clés API IA.
        # Idempotent : si Supabase a déjà des valeurs, on ne les écrase pas.
        try:
            from .. integrations import shared_secrets
            client = self._supabase()
            if client is not None:
                # SMTP/IMAP
                supabase_smtp = shared_secrets.get_smtp_config(client=client) or {}
                local_smtp = self._app_state.get("outreach", default={}) or {}
                if not supabase_smtp.get("smtp_host") and local_smtp.get("smtp_host"):
                    shared_secrets.save_smtp_config(
                        local_smtp, client=client, app_state=self._app_state)
                    logger.info("Migration SMTP local → Supabase faite")
                # Clés IA
                supabase_keys = shared_secrets.get_ai_keys(client=client) or {}
                local_keys = (self._app_state.get("ai", "api_keys", default={}) or {})
                if not supabase_keys and local_keys:
                    shared_secrets.save_ai_keys(
                        local_keys, client=client, app_state=self._app_state)
                    logger.info("Migration clés IA local → Supabase faite")
                # Sync vers Triskell Core config.json (pour que les pipelines
                # Core trouvent les clés sans connaître Supabase)
                shared_secrets.sync_ai_keys_to_core(
                    client=client, app_state=self._app_state)
        except Exception as exc:
            logger.debug("migration secrets: %s", exc)

        # Démarrage des workers (best-effort, no-op si dépendances absentes)
        worker_status = {}
        for mod_name, starter, label in [
            ("replies_poller",  "start_poller", "imap_replies"),
            ("reply_responder", "start_worker", "auto_responder"),
            ("drip_runner",     "start_worker", "drip"),
            ("post_sale_runner",       "start_worker", "post_sale"),
            ("lead_to_client",         "start_worker", "lead_to_client"),
            ("multichannel_followup",  "start_worker", "multichannel_followup"),
            ("dormant_recycler",       "start_worker", "dormant_recycler"),
            ("stripe_poller",          "start_worker", "stripe_poller"),
            ("claude_proactive",       "start_worker", "claude_proactive"),
            ("scheduled_mail_runner",  "start_worker", "scheduled_mails"),
            ("backup_runner",          "start_worker", "backup_runner"),
            ("autopilot_runner",       "start_worker", "autopilot_nightly"),
        ]:
            try:
                mod = __import__(
                    f"triskell_command.integrations.{mod_name}",
                    fromlist=[starter],
                )
                getattr(mod, starter)(self._app_state)
                worker_status[label] = True
            except Exception as exc:
                logger.debug("worker %s : %s", label, exc)
                worker_status[label] = False

        # Bridge proactive notifications → front
        try:
            from ..integrations import claude_proactive

            def on_notify(advice: dict) -> None:
                # On stocke côté Python, le front polle via
                # claude_consume_pending OU claude_get_pending
                pass

            claude_proactive.set_notify_callback(on_notify)
        except Exception:
            pass

        return {"ok": True, "workers": worker_status}

    # ------------------------------------------------------------------
    # Chat 1-à-1 Jordan ↔ Thomas (équivalent web du FAB Tk)
    # ------------------------------------------------------------------
    def messages_me(self) -> dict:
        """Renvoie mon identité locale (jordan/thomas) pour aligner les bulles côté UI.
        Inclut aussi la couleur de chat que JE ai choisie (visible dans les
        bulles que j'envoie, chez moi ET chez l'autre user)."""
        try:
            from .auth import get_current_local_user, get_display_name, get_chat_color
            uid = get_current_local_user()
            if not uid:
                return {"ok": False, "error": "not_logged_in", "user_id": None}
            return {
                "ok": True,
                "user_id": uid,
                "display_name": get_display_name(uid),
                "color": get_chat_color(uid),
            }
        except Exception as exc:
            logger.debug("messages_me: %s", exc)
            return {"ok": False, "error": str(exc), "user_id": None}

    def messages_other_user(self) -> dict:
        """Renvoie le profil de l'autre user (Jordan voit Thomas, etc.).
        La couleur est celle CHOISIE par l'autre user — appliquée à ses bulles."""
        try:
            from ..integrations.messages import other_user
            from .auth import get_chat_color
            other = other_user()
            if other and other.get("user_id"):
                other = {**other, "color": get_chat_color(other["user_id"])}
            return {"ok": True, "other": other}
        except Exception as exc:
            logger.debug("messages_other_user: %s", exc)
            return {"ok": False, "error": str(exc)}

    def messages_set_color(self, payload: dict) -> dict:
        """L'utilisateur courant change SA couleur de chat. La nouvelle
        couleur s'applique aux bulles qu'il envoie (vu chez lui et chez l'autre)."""
        try:
            from .auth import get_current_local_user, set_chat_color, get_chat_color
            uid = get_current_local_user()
            if not uid:
                return {"ok": False, "error": "not_logged_in"}
            color = (payload or {}).get("color", "")
            if not set_chat_color(uid, color):
                return {"ok": False, "error": "Couleur invalide. Format attendu : #RRGGBB"}
            return {"ok": True, "color": get_chat_color(uid)}
        except Exception as exc:
            logger.warning("messages_set_color: %s", exc)
            return {"ok": False, "error": str(exc)}

    def messages_color_palette(self) -> dict:
        """Renvoie la palette de couleurs proposée dans le sélecteur + la
        couleur courante de l'utilisateur."""
        try:
            from .auth import (
                get_current_local_user, get_chat_color, CHAT_COLOR_PALETTE,
            )
            uid = get_current_local_user()
            return {
                "ok": True,
                "palette": list(CHAT_COLOR_PALETTE),
                "current": get_chat_color(uid) if uid else None,
            }
        except Exception as exc:
            logger.debug("messages_color_palette: %s", exc)
            return {"ok": False, "error": str(exc), "palette": [], "current": None}

    def messages_list(self, payload: dict | None = None) -> dict:
        """Renvoie la liste des derniers messages échangés (chronologique)."""
        try:
            from ..integrations.messages import list_messages
            limit = int((payload or {}).get("limit", 100))
            return {"ok": True, "messages": list_messages(limit)}
        except Exception as exc:
            logger.debug("messages_list: %s", exc)
            return {"ok": False, "error": str(exc), "messages": []}

    def messages_send(self, payload: dict) -> dict:
        """Envoie un message à l'autre user. Le payload accepte :
            - body : texte du message (optionnel si attachment)
            - attachment : dict {url, name, type, size} (optionnel si body)
              produit par /api/chat_attachment.
            - reply_to_id : ID d'un message auquel on répond (optionnel).
        """
        try:
            from ..integrations.messages import send_message
            body = (payload or {}).get("body", "")
            attachment = (payload or {}).get("attachment") or None
            reply_to_id = (payload or {}).get("reply_to_id") or None
            msg = send_message(body, attachment, reply_to_id=reply_to_id)
            return {"ok": bool(msg), "message": msg}
        except Exception as exc:
            logger.warning("messages_send: %s", exc)
            return {"ok": False, "error": str(exc)}

    def gif_search(self, payload: dict | None = None) -> dict:
        """Cherche des GIFs via Giphy (proxy serveur).

        La clé API Giphy est lue depuis la variable d'env GIPHY_API_KEY
        (à configurer côté Coolify ou dans l'environnement du serveur).
        Si vide ou non défini → fallback sur la clé éventuellement stockée
        dans les settings locaux à `apis.giphy_key`. Sinon erreur claire.

        Payload : { q?: string, limit?: int }. Si q vide → trending.
        Réponse : { ok, items: [{ id, title, thumb_url, full_url }] }.
        """
        try:
            import os, urllib.request, urllib.parse, json as _json
            key = (os.environ.get("GIPHY_API_KEY") or "").strip()
            if not key:
                # Fallback : settings locaux apis.giphy_key
                try:
                    key = (self._app_state.get("apis", "giphy_key") or "").strip()
                except Exception:
                    key = ""
            if not key:
                return {"ok": False, "error": "no_giphy_key",
                        "items": [],
                        "message": ("Clé Giphy manquante. Crée-la (gratuit) "
                                    "sur developers.giphy.com puis ajoute "
                                    "GIPHY_API_KEY dans Coolify.")}
            q = ((payload or {}).get("q") or "").strip()
            limit = int((payload or {}).get("limit") or 24)
            params = {"api_key": key, "limit": str(limit), "rating": "pg-13"}
            if q:
                params["q"] = q
                url = "https://api.giphy.com/v1/gifs/search?" + urllib.parse.urlencode(params)
            else:
                url = "https://api.giphy.com/v1/gifs/trending?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={"User-Agent": "Triskell-Command"})
            with urllib.request.urlopen(req, timeout=8) as r:
                raw = r.read()
            data = _json.loads(raw.decode("utf-8")) if raw else {}
            items = []
            for g in (data.get("data") or []):
                images = g.get("images") or {}
                thumb = (images.get("fixed_height_small")
                         or images.get("fixed_height") or {})
                full  = (images.get("original")
                         or images.get("fixed_height") or {})
                if not thumb.get("url") or not full.get("url"):
                    continue
                items.append({
                    "id":        g.get("id") or "",
                    "title":     g.get("title") or "gif",
                    "thumb_url": thumb.get("url"),
                    "full_url":  full.get("url"),
                    "width":     full.get("width"),
                    "height":    full.get("height"),
                })
            return {"ok": True, "items": items}
        except Exception as exc:
            logger.warning("gif_search: %s", exc)
            return {"ok": False, "error": str(exc), "items": []}

    def messages_delete(self, payload: dict) -> dict:
        """Supprime (soft-delete) un message envoyé par l'utilisateur
        courant. Payload : { id }. Le serveur impose que sender_id ==
        utilisateur courant ; renvoie {ok: False} si pas autorisé.
        """
        try:
            from ..integrations.messages import delete_message
            msg_id = (payload or {}).get("id")
            msg = delete_message(msg_id)
            return {"ok": bool(msg), "message": msg}
        except Exception as exc:
            logger.warning("messages_delete: %s", exc)
            return {"ok": False, "error": str(exc)}

    def messages_react(self, payload: dict) -> dict:
        """Pose/retire une réaction emoji sur un message (toggle).
        Payload :
            - id    : ID du message
            - emoji : caractère emoji (ex: '❤️', '👍', '😂')
        """
        try:
            from ..integrations.messages import toggle_reaction
            msg_id = (payload or {}).get("id")
            emoji = (payload or {}).get("emoji")
            res = toggle_reaction(msg_id, emoji)
            return {"ok": bool(res), "result": res}
        except Exception as exc:
            logger.warning("messages_react: %s", exc)
            return {"ok": False, "error": str(exc)}

    def messages_edit(self, payload: dict) -> dict:
        """Modifie le texte d'un message déjà envoyé. Payload :
            - id   : ID du message à modifier
            - body : nouveau texte (non vide).
        Le backend impose que sender_id == utilisateur courant ;
        renvoie {ok: False} si pas autorisé / message introuvable.
        """
        try:
            from ..integrations.messages import edit_message
            msg_id = (payload or {}).get("id")
            body = (payload or {}).get("body", "")
            msg = edit_message(msg_id, body)
            return {"ok": bool(msg), "message": msg}
        except Exception as exc:
            logger.warning("messages_edit: %s", exc)
            return {"ok": False, "error": str(exc)}

    def messages_mark_read(self) -> dict:
        """Marque tous les messages reçus non-lus comme lus."""
        try:
            from ..integrations.messages import mark_all_read
            return {"ok": True, "count": mark_all_read()}
        except Exception as exc:
            logger.debug("messages_mark_read: %s", exc)
            return {"ok": False, "error": str(exc), "count": 0}

    def messages_count_unread(self) -> dict:
        """Nombre de messages reçus non lus."""
        try:
            from ..integrations.messages import count_unread
            return {"ok": True, "count": count_unread()}
        except Exception as exc:
            logger.debug("messages_count_unread: %s", exc)
            return {"ok": False, "error": str(exc), "count": 0}

    def messages_last_preview(self) -> dict:
        """Dernier message échangé (pour tooltip / aperçu)."""
        try:
            from ..integrations.messages import last_message_preview
            return {"ok": True, "preview": last_message_preview()}
        except Exception as exc:
            logger.debug("messages_last_preview: %s", exc)
            return {"ok": False, "error": str(exc)}

    def messages_set_typing(self, payload: dict | None = None) -> dict:
        """Notifie que je suis (ou ne suis plus) en train d'écrire."""
        try:
            from ..integrations.messages import set_typing
            active = bool((payload or {}).get("active", True))
            return {"ok": bool(set_typing(active))}
        except Exception as exc:
            logger.debug("messages_set_typing: %s", exc)
            return {"ok": False, "error": str(exc)}

    def messages_peer_typing(self) -> dict:
        """L'autre user est-il en train d'écrire ?"""
        try:
            from ..integrations.messages import peer_is_typing
            return {"ok": True, "typing": peer_is_typing()}
        except Exception as exc:
            logger.debug("messages_peer_typing: %s", exc)
            return {"ok": False, "error": str(exc), "typing": False}

    # ==================================================================
    # Le Convoi — Importer une liste (PDF/Word/Excel/Image/Texte)
    # ==================================================================
    # Le front pilote 5 étapes :
    #  1. Upload du fichier → extraction texte (fast path tabulaire si CSV/XLSX)
    #  2. Vérification du tableau de prospects extraits
    #  3. Catalogue + brief IA → génération des mails (un par prospect)
    #  4. Mode auto/validation + cap + délai + lancement
    #  5. Suivi des envois
    # Persistance partagée Supabase ou disque local — vu côté
    # integrations.convoy_runner. L'API ici se contente d'orchestrer.

    def _convoy_runtime_get(self, campaign_id: str) -> dict:
        """Renvoie l'entrée runtime d'une campagne (créée si absente)."""
        with self._convoy_lock:
            rt = self._convoy_runtime.get(campaign_id)
            if rt is None:
                rt = {
                    "gen_running": False,
                    "gen_log": [],
                    "gen_error": "",
                    "send_running": False,
                    "send_log": [],
                    "send_error": "",
                    "send_stop": None,   # callable pour interrompre l'envoi
                    "raw_text": "",      # texte brut du dernier upload
                }
                self._convoy_runtime[campaign_id] = rt
            return rt

    def _convoy_ai_config(self) -> dict | None:
        prov = self._app_state.get("ai", "selected_provider", default="anthropic")
        model = self._app_state.get("ai", "selected_model", default="claude-sonnet-4-5")
        keys = self._app_state.get("ai", "api_keys", default={}) or {}
        if not keys.get(prov):
            return None
        return {"provider": prov, "model": model, "api_keys": keys}

    def _convoy_smtp_config(self, account_id: str = "primary") -> dict | None:
        """Renvoie le dict SMTP pour le compte demandé.

        - account_id = "primary" (défaut) : compte principal (settings.outreach
          + miroir Supabase shared_secrets.smtp_config).
        - account_id = id d'un compte secondaire : utilise
          shared_secrets.get_account_by_id().

        None si configuration incomplète.
        """
        aid = (account_id or "primary").strip() or "primary"
        try:
            from ..integrations import shared_secrets
            client = self._supabase()
            if aid == "primary":
                cfg = shared_secrets.resolve_smtp_for_send(
                    client=client, app_state=self._app_state)
                return cfg  # déjà au bon format ou None
            acc = shared_secrets.get_account_by_id(
                aid, client=client, app_state=self._app_state)
            if not acc:
                return None
            required = ("smtp_host", "smtp_port", "smtp_user",
                        "smtp_password", "from_email")
            if any(not acc.get(k) for k in required):
                return None
            return {
                "smtp_host": acc.get("smtp_host"),
                "smtp_port": int(acc.get("smtp_port") or 587),
                "smtp_user": acc.get("smtp_user"),
                "smtp_password": acc.get("smtp_password"),
                "from_email": acc.get("from_email"),
                "from_name": acc.get("from_name", ""),
            }
        except Exception as exc:
            logger.warning("_convoy_smtp_config(%s) : %s", aid, exc)
            # Fallback ultime : settings local
            o = self._app_state.get("outreach", default={}) or {}
            required = ("smtp_host", "smtp_port", "smtp_user", "smtp_password",
                        "from_email")
            if any(not o.get(k) for k in required):
                return None
            return {
                "smtp_host": o.get("smtp_host"),
                "smtp_port": int(o.get("smtp_port", 587)),
                "smtp_user": o.get("smtp_user"),
                "smtp_password": o.get("smtp_password"),
                "from_email": o.get("from_email"),
                "from_name": o.get("from_name", ""),
            }

    def _convoy_serialize(self, camp) -> dict:
        """ConvoyCampaign → dict sérialisable pour le front."""
        return camp.to_dict()

    # ---- Catalogue central ---------------------------------------------------
    def convoy_get_catalog(self) -> dict:
        try:
            from ..integrations import catalog_repo
            return {"ok": True, "catalog": catalog_repo.get_catalog()}
        except Exception as exc:
            logger.warning("convoy_get_catalog: %s", exc)
            return {"ok": False, "error": str(exc), "catalog": []}

    def convoy_save_catalog(self, payload: dict | None = None) -> dict:
        items = (payload or {}).get("catalog") or []
        try:
            from ..integrations import catalog_repo
            ok = catalog_repo.set_catalog(items)
            return {"ok": bool(ok), "catalog": catalog_repo.get_catalog()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ---- Liste / lecture / création / suppression / renommage ---------------
    def convoy_list_campaigns(self) -> dict:
        try:
            from ..integrations import convoy_runner
            camps = convoy_runner.list_campaigns()
            rows = []
            for c in camps:
                counts = c.counts()
                rows.append({
                    "id": c.id,
                    "name": c.name,
                    "created_at": c.created_at,
                    "mode": c.mode,
                    "source_file": c.source_file,
                    "counts": counts,
                })
            return {"ok": True, "campaigns": rows}
        except Exception as exc:
            logger.warning("convoy_list_campaigns: %s", exc)
            return {"ok": False, "error": str(exc), "campaigns": []}

    def convoy_get_campaign(self, payload: dict | None = None) -> dict:
        cid = ((payload or {}).get("campaign_id") or "").strip()
        if not cid:
            return {"ok": False, "error": "campaign_id requis"}
        try:
            from ..integrations import convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            return {"ok": True, "campaign": self._convoy_serialize(camp)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def convoy_new_campaign(self, payload: dict | None = None) -> dict:
        try:
            from datetime import datetime
            import uuid
            from ..integrations import catalog_repo, convoy_runner
            name = ((payload or {}).get("name") or "").strip() or \
                f"Convoi du {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            cap_default = int(
                self._app_state.get("outreach", "daily_cap", default=40) or 40
            )
            camp = convoy_runner.ConvoyCampaign(
                id=uuid.uuid4().hex,
                name=name,
                created_at=datetime.now().isoformat(timespec="seconds"),
                source_file="",
                mode="validation",
                user_brief="",
                catalog=catalog_repo.get_catalog(),
                drafts=[],
                daily_cap=cap_default,
                delay_seconds=60,
            )
            camp.save()
            return {"ok": True, "campaign": self._convoy_serialize(camp)}
        except Exception as exc:
            logger.exception("convoy_new_campaign")
            return {"ok": False, "error": str(exc)}

    def convoy_rename_campaign(self, payload: dict | None = None) -> dict:
        p = payload or {}
        cid = (p.get("campaign_id") or "").strip()
        name = (p.get("name") or "").strip()
        if not cid or not name:
            return {"ok": False, "error": "campaign_id + name requis"}
        try:
            from ..integrations import convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            camp.name = name
            camp.save()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def convoy_delete_campaign(self, payload: dict | None = None) -> dict:
        cid = ((payload or {}).get("campaign_id") or "").strip()
        if not cid:
            return {"ok": False, "error": "campaign_id requis"}
        try:
            from ..integrations import convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            ok = convoy_runner.delete_campaign(camp)
            with self._convoy_lock:
                self._convoy_runtime.pop(cid, None)
            return {"ok": bool(ok)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ---- Étape 1 : upload + parse + (fast path tabulaire) -------------------
    def convoy_upload_and_parse(self, payload: dict | None = None) -> dict:
        """Reçoit un fichier en base64, l'écrit dans le dossier de la campagne,
        le parse, et tente le mapping direct (csv/xlsx). Renvoie un aperçu
        + d'éventuels prospects pré-détectés.

        payload = {campaign_id, filename, content_b64}
        """
        import base64
        import uuid
        from pathlib import Path
        p = payload or {}
        cid = (p.get("campaign_id") or "").strip()
        filename = (p.get("filename") or "").strip()
        content_b64 = p.get("content_b64") or ""
        if not cid or not filename or not content_b64:
            return {"ok": False, "error": "campaign_id + filename + content_b64 requis"}
        try:
            from ..integrations import convoy_parser, convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            # Garde le suffixe d'origine pour le parser
            safe = Path(filename).name
            ext = Path(safe).suffix.lower()
            if ext not in convoy_parser.SUPPORTED_EXTENSIONS:
                return {"ok": False, "error":
                        f"Format non supporté : {ext or '(sans extension)'}"}
            try:
                raw_bytes = base64.b64decode(content_b64, validate=False)
            except Exception as exc:
                return {"ok": False, "error": f"Fichier illisible : {exc}"}

            uploads_dir = (convoy_runner.CONVOY_DIR / "uploads" / cid)
            uploads_dir.mkdir(parents=True, exist_ok=True)
            target = uploads_dir / f"{uuid.uuid4().hex}{ext}"
            target.write_bytes(raw_bytes)

            try:
                parsed = convoy_parser.parse_file(target)
            except convoy_parser.ParserError as exc:
                return {"ok": False, "error": str(exc)}
            text = parsed.get("text", "") or ""
            rows = parsed.get("rows", []) or []
            warnings = parsed.get("warnings", []) or []

            # Fast path tabulaire (csv/xlsx avec colonne email reconnaissable)
            prospects = convoy_parser.rows_to_prospects(rows) if rows else []

            # Persistance côté campagne
            camp.source_file = str(target)
            camp.save()

            # Stocke le texte brut pour l'étape extraction IA si besoin
            rt = self._convoy_runtime_get(cid)
            with self._convoy_lock:
                rt["raw_text"] = text

            return {
                "ok": True,
                "format": parsed.get("format", ""),
                "filename": safe,
                "text_preview": text[:4000],
                "text_truncated": len(text) > 4000,
                "rows_count": len(rows),
                "warnings": warnings,
                "fast_path_prospects": prospects,
            }
        except Exception as exc:
            logger.exception("convoy_upload_and_parse")
            return {"ok": False, "error": str(exc)}

    def convoy_extract_prospects_ai(self, payload: dict | None = None) -> dict:
        """Appelle l'IA sur le texte brut du dernier upload pour structurer
        les prospects. Crée un draft vide par prospect dans la campagne.
        """
        cid = ((payload or {}).get("campaign_id") or "").strip()
        if not cid:
            return {"ok": False, "error": "campaign_id requis"}
        try:
            from ..integrations import convoy_ai, convoy_parser, convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            rt = self._convoy_runtime_get(cid)
            with self._convoy_lock:
                text = rt.get("raw_text") or ""
            if not text:
                # Si le serveur a redémarré, on reparse le fichier source
                if camp.source_file:
                    try:
                        parsed = convoy_parser.parse_file(camp.source_file)
                        text = parsed.get("text", "") or ""
                        with self._convoy_lock:
                            rt["raw_text"] = text
                    except Exception:
                        pass
            if not text.strip():
                return {"ok": False, "error":
                        "Texte vide — recharge un fichier."}
            ai_cfg = self._convoy_ai_config()
            if not ai_cfg:
                return {"ok": False, "error":
                        "Clé IA absente — configure-la dans Réglages."}
            basics = convoy_parser.harvest_basics(text)
            prospects = convoy_ai.extract_prospects(
                text,
                emails_hint=basics.get("emails", []),
                phones_hint=basics.get("phones", []),
                urls_hint=basics.get("urls", []),
                provider=ai_cfg["provider"],
                model=ai_cfg["model"],
                api_keys=ai_cfg["api_keys"],
            )
            return self._convoy_apply_prospects(camp, prospects)
        except Exception as exc:
            logger.exception("convoy_extract_prospects_ai")
            return {"ok": False, "error": str(exc)}

    def convoy_apply_fast_path(self, payload: dict | None = None) -> dict:
        """Reçoit la liste de prospects du fast path (mapping CSV/XLSX direct)
        et la matérialise en drafts vides dans la campagne.

        payload = {campaign_id, prospects: [...]}
        """
        p = payload or {}
        cid = (p.get("campaign_id") or "").strip()
        prospects = p.get("prospects") or []
        if not cid:
            return {"ok": False, "error": "campaign_id requis"}
        try:
            from ..integrations import convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            return self._convoy_apply_prospects(camp, prospects)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _convoy_apply_prospects(self, camp, prospects: list) -> dict:
        """Remplace les drafts d'une campagne par des drafts vides issus de
        la liste de prospects (étape 1→2 du flux)."""
        import uuid
        from ..integrations import convoy_ai, convoy_runner
        new_drafts = []
        for raw in (prospects or []):
            if not isinstance(raw, dict):
                continue
            cleaned = {k: (raw.get(k) or "") for k in convoy_ai.PROSPECT_FIELDS}
            if not any(cleaned.values()):
                continue
            new_drafts.append(convoy_runner.ConvoyDraft(
                id=uuid.uuid4().hex,
                prospect=cleaned,
            ))
        camp.drafts = new_drafts
        camp.save()
        # Compteurs de validation pour l'UI
        ok = warn = err = 0
        for d in camp.drafts:
            v = convoy_ai.validate_prospect(d.prospect)
            sev = v.get("severity")
            if sev == "ok": ok += 1
            elif sev == "warning": warn += 1
            else: err += 1
        return {
            "ok": True,
            "campaign": self._convoy_serialize(camp),
            "stats": {"complete": ok, "incomplete": warn, "missing_email": err,
                      "total": len(camp.drafts)},
        }

    # ---- Étape 2 : édition d'un prospect (ligne du tableau) -----------------
    def convoy_update_prospect(self, payload: dict | None = None) -> dict:
        p = payload or {}
        cid = (p.get("campaign_id") or "").strip()
        did = (p.get("draft_id") or "").strip()
        prospect = p.get("prospect") or {}
        if not cid or not did or not isinstance(prospect, dict):
            return {"ok": False, "error": "campaign_id + draft_id + prospect requis"}
        try:
            from ..integrations import convoy_ai, convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            for d in camp.drafts:
                if d.id == did:
                    # Merge propre — n'écrase que les champs canoniques fournis
                    for k in convoy_ai.PROSPECT_FIELDS:
                        if k in prospect:
                            d.prospect[k] = str(prospect.get(k) or "").strip()
                    camp.save()
                    return {"ok": True}
            return {"ok": False, "error": "Brouillon introuvable"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ---- Étape 3 : brief + catalogue + génération IA ------------------------
    def convoy_save_compose(self, payload: dict | None = None) -> dict:
        p = payload or {}
        cid = (p.get("campaign_id") or "").strip()
        if not cid:
            return {"ok": False, "error": "campaign_id requis"}
        try:
            from ..integrations import catalog_repo, convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            if "user_brief" in p:
                camp.user_brief = str(p.get("user_brief") or "")
            if "catalog" in p and isinstance(p.get("catalog"), list):
                catalog_repo.set_catalog(p["catalog"])
                camp.catalog = p["catalog"]
            camp.save()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def convoy_generate_messages(self, payload: dict | None = None) -> dict:
        """Lance la génération IA des mails en thread daemon, retour immédiat.
        Le front polle convoy_generation_status pour suivre.

        payload = {campaign_id, limit?: int, test_mode?: bool}
        Quand test_mode=True (typiquement appelé avec limit=5), les drafts
        générés sont marqués is_test=True pour les afficher en haut de la
        liste avec un badge.
        """
        from datetime import datetime
        p = payload or {}
        cid = (p.get("campaign_id") or "").strip()
        limit = p.get("limit")
        test_mode = bool(p.get("test_mode"))
        if not cid:
            return {"ok": False, "error": "campaign_id requis"}
        try:
            from ..integrations import convoy_ai, convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            ai_cfg = self._convoy_ai_config()
            if not ai_cfg:
                return {"ok": False, "error":
                        "Clé IA absente — configure-la dans Réglages."}

            rt = self._convoy_runtime_get(cid)
            with self._convoy_lock:
                if rt.get("gen_running"):
                    return {"ok": False, "error": "Génération déjà en cours."}
                rt["gen_running"] = True
                rt["gen_log"] = []
                rt["gen_error"] = ""

            sender = (
                self._app_state.get("outreach", "from_name", default="")
                or self._app_state.get("outreach", "mon_prenom", default="")
                or "L'équipe"
            )

            # On NE régénère JAMAIS les drafts déjà envoyés (status='sent')
            # — sinon Jordan perdrait la trace de ce qui est parti. Idem pour
            # ceux dont l'email a été contacté ailleurs récemment (anti-doublon
            # cross-campagne / cross-runner).
            from ..integrations import prospect_status as PS
            cli = self._supabase()
            already_contacted_emails: set[str] = set()
            already_skipped = 0
            sent_skipped = 0
            targets: list = []
            drafts_to_mark_skipped: list = []
            for d in camp.drafts:
                if d.status == "sent":
                    sent_skipped += 1
                    continue
                if not convoy_ai.validate_prospect(d.prospect).get("ok"):
                    continue
                to = (d.prospect or {}).get("email", "").lower().strip()
                if to and cli is not None:
                    try:
                        recent = PS.has_recent_send(cli, email=to)
                        if recent.get("recent"):
                            already_contacted_emails.add(to)
                            already_skipped += 1
                            # Marque le draft pour qu'il apparaisse comme
                            # rejeté avec une raison claire dans le preview,
                            # au lieu de rester "en attente" sans contenu.
                            drafts_to_mark_skipped.append(d)
                            continue
                    except Exception:
                        pass
                targets.append(d)
            if isinstance(limit, int) and limit > 0:
                targets = targets[:limit]

            # Pré-marque les skippés AVANT le worker pour que le preview
            # reflète immédiatement l'état (sinon Jordan voit ses
            # déjà-contactés "en attente").
            if drafts_to_mark_skipped:
                for d in drafts_to_mark_skipped:
                    d.status = "rejected"
                    d.error = ("Déjà contacté récemment (cooldown actif) — "
                               "non régénéré ni envoyé.")
                try: camp.save()
                except Exception: pass

            def push(msg: str) -> None:
                line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
                with self._convoy_lock:
                    rt["gen_log"].append(line)
                    if len(rt["gen_log"]) > 500:
                        del rt["gen_log"][: len(rt["gen_log"]) - 500]

            def worker():
                try:
                    if sent_skipped:
                        push(f"⏭  {sent_skipped} déjà envoyé(s) — non régénéré(s).")
                    if already_skipped:
                        push(f"⏭  {already_skipped} déjà contacté(s) ailleurs "
                              f"dans le cooldown — non régénéré(s).")
                    push(f"Génération de {len(targets)} mail(s)…")
                    # Mode "pioche dans templates" : si la campagne pointe
                    # vers un produit, on précharge sa liste de templates
                    # de prospection. L'IA pioche le plus pertinent par
                    # prospect au lieu de générer from scratch.
                    template_product = (getattr(camp, "template_product", "") or "").strip()
                    templates_pool: list[dict] = []
                    if template_product:
                        try:
                            from ..integrations import prospection_templates as pt
                            templates_pool = pt.list_prospection_templates(template_product)
                            push(f"📑 Mode templates : {len(templates_pool)} modèle(s) "
                                 f"de « {template_product} » chargé(s).")
                            if not templates_pool:
                                push("⚠ Aucun template trouvé pour ce produit — "
                                     "fallback génération libre.")
                        except Exception as exc:
                            push(f"⚠ Lecture templates échouée ({exc}) — "
                                 f"fallback génération libre.")
                            templates_pool = []
                    for i, draft in enumerate(targets, 1):
                        try:
                            if templates_pool:
                                msg = convoy_ai.generate_message_from_templates(
                                    draft.prospect,
                                    templates=templates_pool,
                                    template_product=template_product,
                                    sender_name=sender,
                                    user_brief=camp.user_brief,
                                    provider=ai_cfg["provider"],
                                    model=ai_cfg["model"],
                                    api_keys=ai_cfg["api_keys"],
                                )
                            else:
                                msg = convoy_ai.generate_message(
                                    draft.prospect,
                                    catalog=camp.catalog,
                                    sender_name=sender,
                                    user_brief=camp.user_brief,
                                    provider=ai_cfg["provider"],
                                    model=ai_cfg["model"],
                                    api_keys=ai_cfg["api_keys"],
                                )
                            draft.subject = msg.get("subject", "")
                            draft.body = msg.get("body", "")
                            draft.body_html = msg.get("body_html", "")
                            draft.offer_name = msg.get("offer_name", "")
                            draft.offer_mail_account_id = (
                                msg.get("offer_mail_account_id") or "")
                            if test_mode:
                                draft.is_test = True
                            push(f"  ({i}/{len(targets)}) {draft.prospect.get('email','')} OK")
                        except Exception as exc:
                            draft.error = f"génération échouée : {exc}"
                            push(f"  ({i}/{len(targets)}) ✗ {exc}")
                        camp.save()
                    push("✓ Génération terminée.")
                except Exception as exc:
                    with self._convoy_lock:
                        rt["gen_error"] = str(exc)
                    push(f"✗ {exc}")
                finally:
                    with self._convoy_lock:
                        rt["gen_running"] = False

            threading.Thread(
                target=worker, daemon=True, name=f"ConvoyGen-{cid[:8]}"
            ).start()
            return {"ok": True, "started": True, "target_count": len(targets)}
        except Exception as exc:
            logger.exception("convoy_generate_messages")
            with self._convoy_lock:
                rt = self._convoy_runtime.get(cid)
                if rt: rt["gen_running"] = False
            return {"ok": False, "error": str(exc)}

    def convoy_generation_status(self, payload: dict | None = None) -> dict:
        p = payload or {}
        cid = (p.get("campaign_id") or "").strip()
        since = int(p.get("since") or 0)
        if not cid:
            return {"ok": False, "error": "campaign_id requis"}
        rt = self._convoy_runtime_get(cid)
        with self._convoy_lock:
            log = rt.get("gen_log") or []
            return {
                "ok": True,
                "running": bool(rt.get("gen_running")),
                "error": rt.get("gen_error") or "",
                "log": log[since:],
                "log_len": len(log),
            }

    # ---- Étape 4 : réglages d'envoi + lancement -----------------------------
    def convoy_list_prospection_products(self, payload: dict | None = None) -> dict:
        """Renvoie la liste des produits qui ont au moins un template
        de prospection activé (pour le sélecteur du wizard Convoi)."""
        try:
            from ..integrations import prospection_templates as pt
            return pt.list_products_with_prospection_templates()
        except Exception as exc:
            logger.exception("convoy_list_prospection_products failed")
            return {"ok": False, "error": str(exc), "products": []}

    def convoy_save_send_settings(self, payload: dict | None = None) -> dict:
        p = payload or {}
        cid = (p.get("campaign_id") or "").strip()
        if not cid:
            return {"ok": False, "error": "campaign_id requis"}
        try:
            from ..integrations import convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            if "mode" in p:
                m = (p.get("mode") or "").strip()
                if m in ("auto", "validation"):
                    camp.mode = m
            if "daily_cap" in p:
                try: camp.daily_cap = max(1, int(p.get("daily_cap")))
                except Exception: pass
            if "delay_seconds" in p:
                try: camp.delay_seconds = max(5, int(p.get("delay_seconds")))
                except Exception: pass
            if "schedule_at" in p:
                camp.schedule_at = str(p.get("schedule_at") or "").strip()
            if "sender_account_id" in p:
                aid = (p.get("sender_account_id") or "primary").strip()
                camp.sender_account_id = aid or "primary"
            # Pool multi-adresses : liste [{account_id, daily_cap}]. On
            # nettoie au passage (id requis, cap > 0, dédoublonnage par id).
            if "sender_pool" in p:
                raw_pool = p.get("sender_pool") or []
                cleaned: list[dict] = []
                seen_ids: set[str] = set()
                if isinstance(raw_pool, list):
                    for entry in raw_pool:
                        if not isinstance(entry, dict):
                            continue
                        aid = str(entry.get("account_id") or "").strip()
                        if not aid or aid in seen_ids:
                            continue
                        try:
                            cap = int(entry.get("daily_cap") or 0)
                        except (ValueError, TypeError):
                            cap = 0
                        if cap <= 0:
                            continue
                        seen_ids.add(aid)
                        cleaned.append({"account_id": aid, "daily_cap": cap})
                camp.sender_pool = cleaned
            if "template_product" in p:
                camp.template_product = str(p.get("template_product") or "").strip()
            camp.save()
            return {"ok": True, "campaign": self._convoy_serialize(camp)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def convoy_approve_draft(self, payload: dict | None = None) -> dict:
        p = payload or {}
        cid = (p.get("campaign_id") or "").strip()
        did = (p.get("draft_id") or "").strip()
        if not cid or not did:
            return {"ok": False, "error": "campaign_id + draft_id requis"}
        try:
            from ..integrations import convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            # Sauve d'abord les édits éventuels
            if "subject" in p or "body" in p:
                convoy_runner.update_draft(
                    camp, did,
                    subject=p.get("subject"),
                    body=p.get("body"),
                )
                camp = convoy_runner.load_campaign(cid)  # reload après save
            ok = convoy_runner.approve_draft(camp, did)
            return {"ok": bool(ok)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def convoy_reject_draft(self, payload: dict | None = None) -> dict:
        p = payload or {}
        cid = (p.get("campaign_id") or "").strip()
        did = (p.get("draft_id") or "").strip()
        if not cid or not did:
            return {"ok": False, "error": "campaign_id + draft_id requis"}
        try:
            from ..integrations import convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            ok = convoy_runner.reject_draft(camp, did)
            return {"ok": bool(ok)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def convoy_update_draft(self, payload: dict | None = None) -> dict:
        p = payload or {}
        cid = (p.get("campaign_id") or "").strip()
        did = (p.get("draft_id") or "").strip()
        if not cid or not did:
            return {"ok": False, "error": "campaign_id + draft_id requis"}
        try:
            from ..integrations import convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            ok = convoy_runner.update_draft(
                camp, did,
                subject=p.get("subject"),
                body=p.get("body"),
            )
            return {"ok": bool(ok)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def convoy_approve_all(self, payload: dict | None = None) -> dict:
        cid = ((payload or {}).get("campaign_id") or "").strip()
        if not cid:
            return {"ok": False, "error": "campaign_id requis"}
        try:
            from ..integrations import convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            n = convoy_runner.approve_all_pending(camp)
            return {"ok": True, "approved": n}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def convoy_start_send(self, payload: dict | None = None) -> dict:
        """Démarre l'envoi des mails approuvés en thread daemon."""
        from datetime import datetime
        cid = ((payload or {}).get("campaign_id") or "").strip()
        if not cid:
            return {"ok": False, "error": "campaign_id requis"}
        try:
            from ..integrations import convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if not camp:
                return {"ok": False, "error": "Campagne introuvable"}
            aid = (camp.sender_account_id or "primary").strip() or "primary"
            smtp_cfg = self._convoy_smtp_config(aid)
            if not smtp_cfg:
                label = "compte principal" if aid == "primary" else f"compte « {aid} »"
                return {"ok": False, "error":
                        f"Le {label} n'est pas configuré ou il manque un "
                        "champ (SMTP/mot de passe). Vérifie les Réglages."}

            # Comptes additionnels potentiels :
            # 1) toutes les adresses du sender_pool (mode multi-adresses)
            # 2) celles liées à un produit via `offer_mail_account_id`
            #    sur un draft approuvé (override par draft)
            needed_account_ids: set[str] = set()
            for entry in (getattr(camp, "sender_pool", None) or []):
                if not isinstance(entry, dict):
                    continue
                pid = str(entry.get("account_id") or "").strip()
                if pid and pid != aid:
                    needed_account_ids.add(pid)
            for d in camp.drafts:
                if d.status != "approved":
                    continue
                oid = (getattr(d, "offer_mail_account_id", "") or "").strip()
                if oid and oid != aid:
                    needed_account_ids.add(oid)
            smtp_cfgs_by_account: dict[str, dict] = {}
            unavailable: list[str] = []
            for oid in sorted(needed_account_ids):
                cfg = self._convoy_smtp_config(oid)
                if cfg:
                    smtp_cfgs_by_account[oid] = cfg
                else:
                    unavailable.append(oid)
            if unavailable:
                # On ne bloque PAS l'envoi : les drafts concernés tomberont
                # juste sur le compte par défaut de la campagne avec un
                # message dans le journal.
                logger.info(
                    "convoy_start_send: comptes liés à un produit non "
                    "configurés (%s) — fallback compte campagne pour ces drafts",
                    unavailable,
                )

            rt = self._convoy_runtime_get(cid)
            with self._convoy_lock:
                if rt.get("send_running"):
                    return {"ok": False, "error": "Envoi déjà en cours."}

            # Mode auto : on approuve tout d'abord
            if camp.mode == "auto":
                convoy_runner.approve_all_pending(camp)
                camp = convoy_runner.load_campaign(cid)  # reload

            approved = [d for d in camp.drafts if d.status == "approved"]
            if not approved:
                return {"ok": False, "error":
                        "Aucun brouillon approuvé. Valide-les un par un "
                        "ou passe en mode auto."}

            with self._convoy_lock:
                rt["send_running"] = True
                rt["send_log"] = []
                rt["send_error"] = ""

            def push(msg: str) -> None:
                line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
                with self._convoy_lock:
                    rt["send_log"].append(line)
                    if len(rt["send_log"]) > 500:
                        del rt["send_log"][: len(rt["send_log"]) - 500]

            def worker():
                import time as _time
                start_ts = _time.time()
                start_iso = datetime.now().isoformat(timespec="seconds")
                planned = len(approved)
                stopped = False
                try:
                    push(f"Envoi de {planned} mail(s)…")
                    if smtp_cfgs_by_account:
                        push("Comptes additionnels (par produit) : "
                             + ", ".join(sorted(smtp_cfgs_by_account.keys())))
                    if unavailable:
                        push("⚠ Comptes liés à un produit non configurés : "
                             + ", ".join(unavailable)
                             + " — fallback compte campagne pour ces drafts.")
                    convoy_runner.run_campaign_send(
                        camp, smtp_cfg=smtp_cfg,
                        smtp_cfgs_by_account=smtp_cfgs_by_account,
                        progress=push,
                        stop_flag=lambda: bool(rt.get("send_stop_flag")),
                    )
                    stopped = bool(rt.get("send_stop_flag"))
                    push("Terminé.")
                except Exception as exc:
                    with self._convoy_lock:
                        rt["send_error"] = str(exc)
                    push(f"✗ {exc}")
                finally:
                    # Calcule un résumé de fin destiné à l'UI : compteurs
                    # post-envoi + durée. Le front l'affichera en encart.
                    summary: dict = {}
                    try:
                        camp_after = convoy_runner.load_campaign(cid)
                        counts = camp_after.counts() if camp_after else {}
                        dur = max(0, int(_time.time() - start_ts))
                        summary = {
                            "planned": planned,
                            "sent": int(counts.get("sent", 0)),
                            "failed": int(counts.get("failed", 0)),
                            "pending": int(counts.get("pending", 0)),
                            "rejected": int(counts.get("rejected", 0)),
                            "duration_s": dur,
                            "started_at": start_iso,
                            "ended_at": datetime.now()
                                                 .isoformat(timespec="seconds"),
                            "stopped_by_user": stopped,
                            "campaign_name": (camp_after.name
                                              if camp_after else camp.name),
                        }
                    except Exception:
                        pass
                    with self._convoy_lock:
                        rt["send_running"] = False
                        rt["send_stop_flag"] = False
                        if summary:
                            rt["send_summary"] = summary

            threading.Thread(
                target=worker, daemon=True, name=f"ConvoySend-{cid[:8]}",
            ).start()
            return {"ok": True, "started": True, "approved": len(approved)}
        except Exception as exc:
            logger.exception("convoy_start_send")
            return {"ok": False, "error": str(exc)}

    def resume_convoy_sends(self, payload: dict | None = None) -> dict:
        """Reprend automatiquement les envois Convoi interrompus par un crash
        / redemarrage du serveur (typiquement : redeploiement Coolify).

        Appelee au boot du serveur HTTP. Detecte les campagnes en
        send_state='running' dont le worker n'a pas renouvele son heartbeat
        depuis trop longtemps, et relance un worker pour chacune.

        Idempotent : si rien a reprendre, renvoie {"resumed": 0}.
        """
        try:
            from ..integrations import convoy_runner
            cids = convoy_runner.find_resumable_campaign_ids()
            if not cids:
                return {"ok": True, "resumed": 0}
            resumed = 0
            cleaned = 0
            errors: list[str] = []
            for cid in cids:
                try:
                    res = self.convoy_start_send({"campaign_id": cid})
                    if res.get("ok") and res.get("started"):
                        resumed += 1
                        logger.info("Convoi %s repris (drafts a envoyer: %s).",
                                    cid[:8], res.get("approved"))
                    else:
                        # Pas de draft approved → la campagne est en realite
                        # terminee (tout est sent/failed/rejected). On
                        # nettoie l'etat en base pour la sortir de la liste
                        # de reprise.
                        client = convoy_runner._supabase_client()
                        if client is not None:
                            try:
                                from datetime import datetime as _dt, timezone as _tz
                                (client.raw.table("convoy_campaigns")
                                 .update({
                                     "send_state": "done",
                                     "send_lock_token": None,
                                     "send_lock_heartbeat_at": None,
                                     "send_finished_at":
                                         _dt.now(_tz.utc).isoformat(),
                                 })
                                 .eq("id", cid)
                                 .execute())
                                cleaned += 1
                            except Exception as exc:
                                errors.append(f"{cid[:8]}: {exc}")
                except Exception as exc:
                    errors.append(f"{cid[:8]}: {exc}")
                    logger.exception("resume_convoy_sends %s", cid)
            return {
                "ok": True,
                "resumed": resumed,
                "cleaned": cleaned,
                "errors": errors,
            }
        except Exception as exc:
            logger.exception("resume_convoy_sends")
            return {"ok": False, "error": str(exc)}

    def convoy_send_status(self, payload: dict | None = None) -> dict:
        p = payload or {}
        cid = (p.get("campaign_id") or "").strip()
        since = int(p.get("since") or 0)
        if not cid:
            return {"ok": False, "error": "campaign_id requis"}
        rt = self._convoy_runtime_get(cid)
        with self._convoy_lock:
            log = rt.get("send_log") or []
            summary = rt.get("send_summary")
            out = {
                "ok": True,
                "running": bool(rt.get("send_running")),
                "error": rt.get("send_error") or "",
                "log": log[since:],
                "log_len": len(log),
                # send_summary est rempli quand le worker termine (succès,
                # échec ou stop). L'UI l'utilise pour afficher un bandeau
                # clair "Convoi terminé" avec durée et compteurs.
                "summary": dict(summary) if isinstance(summary, dict) else None,
            }
        # Renvoie aussi un snapshot des compteurs (utile à l'UI)
        try:
            from ..integrations import convoy_runner
            camp = convoy_runner.load_campaign(cid)
            if camp:
                out["counts"] = camp.counts()
        except Exception:
            pass
        return out

    def convoy_stop_send(self, payload: dict | None = None) -> dict:
        cid = ((payload or {}).get("campaign_id") or "").strip()
        if not cid:
            return {"ok": False, "error": "campaign_id requis"}
        rt = self._convoy_runtime_get(cid)
        with self._convoy_lock:
            rt["send_stop_flag"] = True
        return {"ok": True}

    # ------------------------------------------------------------------
    # Le Chasseur — découverte de PME et extraction de mails publics
    # ------------------------------------------------------------------
    def chasseur_presets(self, payload: dict | None = None) -> dict:
        """Renvoie la liste des secteurs préconfigurés (clé → libellé NAF)."""
        try:
            from ..integrations import chasseur
            return {
                "ok": True,
                "presets": [
                    {"id": k, "label": _PRESET_LABELS.get(k, k),
                     "naf": v.get("activite_principale", "")}
                    for k, v in chasseur.SECTOR_PRESETS.items()
                ],
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "presets": []}

    def chasseur_list_hunts(self, payload: dict | None = None) -> dict:
        try:
            from ..integrations import chasseur
            limit = int((payload or {}).get("limit") or 20)
            return {"ok": True, "hunts": chasseur.list_hunts(limit=limit)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "hunts": []}

    def chasseur_get_hunt(self, payload: dict) -> dict:
        hid = ((payload or {}).get("hunt_id") or "").strip()
        if not hid:
            return {"ok": False, "error": "hunt_id requis"}
        try:
            from ..integrations import chasseur
            h = chasseur.Hunt.load(hid)
            if not h:
                return {"ok": False, "error": "chasse introuvable"}
            return {
                "ok": True,
                "hunt": {
                    "id":         h.id,
                    "label":      h.label,
                    "created_at": h.created_at,
                    "status":     h.status,
                    "progress":   h.progress,
                    "stats":      h.stats,
                    "filters":    h.filters,
                    "error":      h.error,
                    "log_tail":   h.log[-30:],
                    "prospects":  h.prospects,
                    "running":    chasseur.is_running(hid),
                },
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def chasseur_start_hunt(self, payload: dict) -> dict:
        """Lance une chasse en arrière-plan.

        payload = {
            sector: str (clé preset OU code NAF OU mot-clé),
            zone:   {departement?, code_postal?, commune?},
            target: int (volume max retenu, par défaut 200),
            with_email_only: bool (par défaut True),
            mode:   "all" | "poor_sites" (par défaut "all" — toutes les
                     boîtes avec un mail trouvé. "poor_sites" filtre pour
                     ne garder que les sites visiblement obsolètes / amateurs.)
        }
        """
        p = payload or {}
        sector = (p.get("sector") or "").strip()
        zone = p.get("zone") or {}
        if not isinstance(zone, dict):
            zone = {}
        try:
            target = int(p.get("target") or 200)
        except (TypeError, ValueError):
            target = 200
        with_email_only = bool(p.get("with_email_only", True))
        mode = (p.get("mode") or "all").strip()
        if mode not in ("all", "poor_sites"):
            mode = "all"
        if not sector and not (zone.get("departement") or zone.get("code_postal")
                                or zone.get("commune")):
            return {"ok": False, "error":
                    "Précise au moins un secteur ou une zone géo."}
        try:
            from ..integrations import chasseur
            hunt = chasseur.start_hunt(
                sector=sector, zone=zone, target=target,
                with_email_only=with_email_only, mode=mode,
            )
            return {"ok": True, "hunt_id": hunt.id, "label": hunt.label}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def chasseur_export_csv(self, payload: dict) -> dict:
        hid = ((payload or {}).get("hunt_id") or "").strip()
        if not hid:
            return {"ok": False, "error": "hunt_id requis"}
        try:
            from ..integrations import chasseur
            return chasseur.export_csv(hid)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def chasseur_push_to_autopilot(self, payload: dict) -> dict:
        """Envoie les prospects d'une chasse dans la base partagée pour que
        l'Auto-Pilote les ramasse la nuit (enrich + rédige + envoie).

        payload = {hunt_id}
        Renvoie {ok, backend ("remote"/"local"), pushed, created, merged}.
        """
        hid = ((payload or {}).get("hunt_id") or "").strip()
        if not hid:
            return {"ok": False, "error": "hunt_id requis"}
        try:
            from ..integrations import chasseur
            return chasseur.push_to_autopilot(hid)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def chasseur_delete_hunt(self, payload: dict) -> dict:
        hid = ((payload or {}).get("hunt_id") or "").strip()
        if not hid:
            return {"ok": False, "error": "hunt_id requis"}
        try:
            from ..integrations import chasseur
            return chasseur.delete_hunt(hid)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


# Libellés humains pour les presets (séparés pour ne pas alourdir le module
# intégration qui doit rester pur code métier).
_PRESET_LABELS = {
    "restaurant":  "Restaurants",
    "boulangerie": "Boulangeries",
    "coiffeur":    "Coiffeurs",
    "garage":      "Garages auto",
    "plombier":    "Plombiers",
    "electricien": "Électriciens",
    "maconnerie":  "Maçons",
    "menuiserie":  "Menuisiers",
    "fleuriste":   "Fleuristes",
    "opticien":    "Opticiens",
    "pharmacie":   "Pharmacies",
    "hotel":       "Hôtels",
    "agence_immo": "Agences immo",
    "architecte":  "Architectes",
    "comptable":   "Experts-comptables",
    "avocat":      "Avocats",
    "auto_ecole":  "Auto-écoles",
    "salle_sport": "Salles de sport",
    "esthetique":  "Instituts beauté",
    "taxi":        "Taxis & VTC",
    "menage":      "Sociétés de ménage",
    "paysagiste":  "Paysagistes",
}
