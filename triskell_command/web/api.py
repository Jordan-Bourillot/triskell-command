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
        }
        self._autopilot_lock = threading.Lock()

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
        """Renvoie les réponses non traitées + le détail des prospects."""
        category = (payload or {}).get("category") or "all"
        client = self._supabase()
        if client is None:
            return {"ok": False, "error": "not_connected"}
        try:
            sb = client.raw
            res = (sb.table("email_history").select("*")
                   .eq("kind", "reply_received")
                   .order("ts", desc=True).limit(200).execute())
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
                if category != "all":
                    cat = (extra.get("classification") or {}).get(
                        "category", "unknown")
                    if cat != category:
                        continue
                r["extra"] = extra
                out.append(r)
            # Hydrate prospects
            ids = list({x.get("prospect_id") for x in out
                        if x.get("prospect_id")})
            prospects = {}
            if ids:
                pres = (sb.table("prospects").select(
                    "id,name,legal_name,emails,status")
                    .in_("id", ids).execute())
                prospects = {p["id"]: p for p in (pres.data or [])
                              if p.get("id")}
            return {"ok": True, "rows": out, "prospects": prospects}
        except Exception as exc:
            logger.warning("get_replies: %s", exc)
            return {"ok": False, "error": str(exc)}

    def reply_send_now(self, payload: dict) -> dict:
        """Force l'envoi d'un brouillon de réponse suggéré."""
        rid = (payload or {}).get("id") or ""
        client = self._supabase()
        if client is None:
            return {"ok": False, "error": "not_connected"}
        try:
            from ..integrations import reply_responder
            return reply_responder.send_now(client, self._app_state, rid)
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

    # ------------------------------------------------------------------
    # Brouillons à valider
    # ------------------------------------------------------------------
    def get_drafts(self) -> dict:
        try:
            from triskell_core.prospect.pipeline import list_pending_drafts
            pairs = list_pending_drafts()
        except Exception as exc:
            return {"ok": False, "error": str(exc), "rows": []}
        rows = []
        for prospect, draft in pairs:
            rows.append({
                "key": prospect.match_keys[0] if prospect.match_keys else "",
                "name": prospect.name or prospect.legal_name or "(sans nom)",
                "email": (prospect.emails[0] if prospect.emails else ""),
                "city": prospect.city or "",
                "subject": draft.get("subject", ""),
                "body": draft.get("body", ""),
                "ts": draft.get("ts", ""),
                "provider": draft.get("provider", ""),
                "model": draft.get("model", ""),
            })
        return {"ok": True, "rows": rows}

    def draft_approve(self, payload: dict) -> dict:
        p = payload or {}
        key = p.get("key") or ""
        body = p.get("body")
        try:
            from triskell_core.prospect.core.crm import CRM
            from triskell_core.prospect.pipeline import approve_draft
            if body is not None:
                # Met à jour le 1er brouillon avec body édité
                crm = CRM()
                target = next((x for x in crm.all()
                                if key in x.match_keys), None)
                if target and target.pending_drafts:
                    target.pending_drafts[0]["body"] = body
                    crm._dirty = True  # noqa
                    crm.save()
            return approve_draft(key, draft_index=0)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def draft_reject(self, payload: dict) -> dict:
        key = (payload or {}).get("key") or ""
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

    def phare_sites(self) -> dict:
        try:
            from ..integrations.phare import repo
            sites = repo.list_sites(active_only=True)
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
        content = ((payload or {}).get("content") or "").strip()
        if not content:
            return {"ok": False, "error": "Contenu vide."}
        try:
            from ..integrations import brain
            client = self._supabase()
            author = brain._user_alias(client)
            note = brain.add_note(content, author=author, client=client,
                                   ai_keys=self._brain_ai_keys())
            if note is None:
                return {"ok": False, "error": "Insertion échouée"}
            return {"ok": True, "note": note}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def brain_update(self, payload: dict) -> dict:
        p = payload or {}
        nid = (p.get("id") or "").strip()
        if not nid:
            return {"ok": False, "error": "id manquant"}
        patch = {}
        if "status" in p:   patch["status"] = p["status"]
        if "category" in p: patch["category"] = p["category"]
        if "remind_at" in p: patch["remind_at"] = p["remind_at"]
        if not patch:
            return {"ok": False, "error": "Rien à mettre à jour"}
        try:
            from ..integrations import brain
            ok = brain.update_note(nid, patch, client=self._supabase())
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
    def mail_templates_list(self) -> dict:
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

    def mail_template_save(self, payload: dict) -> dict:
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
            cur = self.mail_templates_list()
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

    def mail_template_remove(self, payload: dict) -> dict:
        tid = ((payload or {}).get("id") or "").strip()
        if not tid:
            return {"ok": False, "error": "id manquant"}
        try:
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            cur = self.mail_templates_list()
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

            # Log dans email_history (best-effort)
            if client:
                try:
                    sb = getattr(client, "client", None) or getattr(client, "_client", None)
                    if sb is not None:
                        sb.table("email_history").insert({
                            "kind": "email_sent",
                            "ts":   __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                            "subject": subject[:200],
                            "body":    body[:5000],
                            "message_id": msg_id,
                            "extra": {
                                "to": to,
                                "from": from_email,
                                "account_id": account_id,
                                "in_reply_to": in_reply_to,
                                "manual_reply": bool(in_reply_to),
                                "has_html": bool(body_html),
                                "attachments_count": len([a for a in attachments
                                    if isinstance(a, dict) and not a.get("inline")]),
                                "inline_images_count": len([a for a in attachments
                                    if isinstance(a, dict) and a.get("inline") and a.get("cid")]),
                            },
                            "created_by": getattr(client, "user_id", None),
                        }).execute()
                except Exception as exc:
                    logger.debug("log email_sent KO: %s", exc)

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
        if subtype not in ("template", "personalized"):
            subtype = "personalized" if category == "celebrity" else "personalized"
        # Récupère les modèles (best-effort)
        templates = []
        try:
            r = self.mail_templates_list()
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
            sb = getattr(client, "client", None) or getattr(client, "_client", None)
            if sb is None:
                return {"ok": False, "error": "Client Supabase introuvable"}
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
        # Cherche apps.json depuis quelques emplacements possibles
        candidates = [
            Path(__file__).resolve().parents[3]
                / "Triskell 0 - Lanceur" / "apps.json",
            Path(__file__).resolve().parents[4]
                / "Triskell 0 - Lanceur" / "apps.json",
        ]
        apps_json = None
        for p in candidates:
            if p.exists():
                apps_json = p
                break
        if apps_json is None:
            return {"ok": False, "error": "apps.json introuvable"}
        try:
            data = json.loads(apps_json.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"ok": False, "error": f"parse: {exc}"}
        out = []
        for app in data.get("apps", []):
            slug_info = ID_TO_SLUG.get(app.get("id"))
            if not slug_info:
                continue
            slug, ext = slug_info
            out.append({
                "id":          app.get("id"),
                "name":        app.get("name"),
                "tagline":     app.get("tagline", ""),
                "category":    app.get("category", ""),
                "tier":        app.get("tier", ""),
                "price":       app.get("price"),
                "price_original": app.get("priceOriginal"),
                "buy_url":     app.get("buyUrl", ""),
                "exe_path":    app.get("exePath", ""),
                "installed":   bool(app.get("installed")),
                "coming_soon": bool(app.get("comingSoon")),
                "logo":        f"assets/apps/{slug}.{ext}",
            })
        return {"ok": True, "apps": out}

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
    # Calendly — propose un créneau quand un prospect dit "intéressé"
    # ------------------------------------------------------------------
    def calendly_get_config(self) -> dict:
        try:
            from ..integrations import calendly_client
            client = self._supabase()
            cfg = calendly_client.load_config(client)
            safe = dict(cfg)
            tk = safe.get("personal_access_token", "")
            safe["_has_token"] = bool(tk)
            if tk:
                safe["personal_access_token"] = tk[:6] + "•" * 8 + tk[-4:]
            return {"ok": True, "config": safe}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def calendly_save_config(self, payload: dict) -> dict:
        try:
            from ..integrations import calendly_client
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            cfg_in = (payload or {}).get("config") or {}
            tk = (cfg_in.get("personal_access_token") or "").strip()
            if not tk or "•" in tk:
                existing = calendly_client.load_config(client)
                cfg_in["personal_access_token"] = existing.get("personal_access_token", "")
            calendly_client.save_config(cfg_in, client)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def calendly_test(self) -> dict:
        """Vérifie que le PAT marche en appelant /users/me."""
        try:
            from ..integrations import calendly_client
            client = self._supabase()
            cfg = calendly_client.load_config(client)
            tk = cfg.get("personal_access_token") or ""
            if not tk:
                return {"ok": False, "error": "PAT manquant"}
            return calendly_client.health_check(tk)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def calendly_list_event_types(self) -> dict:
        try:
            from ..integrations import calendly_client
            client = self._supabase()
            cfg = calendly_client.load_config(client)
            tk = cfg.get("personal_access_token") or ""
            if not tk:
                return {"ok": False, "error": "PAT manquant"}
            user_uri = cfg.get("user_uri") or ""
            if not user_uri:
                u = calendly_client.get_current_user(tk)
                user_uri = u.get("uri", "")
                if user_uri:
                    cfg["user_uri"] = user_uri
                    calendly_client.save_config(cfg, client)
            evts = calendly_client.list_event_types(tk, user_uri)
            return {"ok": True, "event_types": [
                {"uri": e.get("uri"), "name": e.get("name"),
                 "duration": e.get("duration"),
                 "scheduling_url": e.get("scheduling_url")}
                for e in evts
            ]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def calendly_propose_to_reply(self, payload: dict) -> dict:
        """Pour une réponse interested : génère un lien Calendly à usage
        unique et envoie un mail au prospect avec ce lien.

        payload = {id: <email_history.id>}
        """
        rid = (payload or {}).get("id") or ""
        if not rid:
            return {"ok": False, "error": "id manquant"}
        try:
            from ..integrations import calendly_client
            client = self._supabase()
            if not client:
                return {"ok": False, "error": "Base partagée non connectée"}
            cfg = calendly_client.load_config(client)
            tk = cfg.get("personal_access_token") or ""
            evt_uri = cfg.get("default_event_type_uri") or ""
            if not tk or not evt_uri:
                return {"ok": False, "error": "Calendly non configuré dans Réglages"}

            sb = client.raw
            # Récupère la réponse
            res = (sb.table("email_history").select("*")
                   .eq("id", rid).limit(1).execute())
            rows = res.data or []
            if not rows:
                return {"ok": False, "error": "réponse introuvable"}
            row = rows[0]
            extra = row.get("extra") or {}
            if isinstance(extra, str):
                try: extra = json.loads(extra)
                except Exception: extra = {}
            to_email = (extra.get("from") or "").strip()
            pid = row.get("prospect_id")
            client_name = ""
            if pid:
                try:
                    pres = (sb.table("prospects").select("name,legal_name,emails")
                            .eq("id", pid).limit(1).execute())
                    p = (pres.data or [{}])[0]
                    client_name = p.get("name") or p.get("legal_name") or ""
                    if not to_email and p.get("emails"):
                        to_email = p["emails"][0]
                except Exception:
                    pass
            if not to_email:
                return {"ok": False, "error": "email destinataire manquant"}

            # Crée le lien à usage unique
            booking_url = calendly_client.create_single_use_link(tk, evt_uri)
            if not booking_url:
                return {"ok": False, "error": "Impossible de créer le lien Calendly"}

            # Compose et envoie le mail
            subject = f"Re: {row.get('subject') or 'Notre échange'}"
            from_name = (self._app_state.get("outreach", "from_name", default="") or "").strip()
            body = (
                f"Bonjour {client_name or ''},\n\n"
                f"Top, on cale un créneau ? Voici un lien direct vers mon "
                f"agenda — choisis l'horaire qui t'arrange :\n\n"
                f"{booking_url}\n\n"
                f"À très vite,\n{from_name}".strip()
            )

            # Envoi via SMTP existant
            from ..integrations import post_sale_runner as _psr
            smtp_cfg = _psr._resolve_smtp_config(self._app_state, client)
            if not smtp_cfg:
                return {"ok": False, "error": "SMTP non configuré"}
            from triskell_core.prospect.outreach.smtp_sender import send_email
            msg_id = send_email(smtp_cfg, to=to_email,
                                 subject=subject, body=body)

            # Trace dans email_history
            from datetime import datetime as _dt
            sb.table("email_history").insert({
                "prospect_id": pid,
                "kind": "email_sent",
                "ts": _dt.now().isoformat(timespec="seconds"),
                "subject": subject[:200],
                "body": body[:2000],
                "message_id": msg_id,
                "extra": {"calendly_invite_sent": True,
                          "calendly_booking_url": booking_url,
                          "in_reply_to": rid},
                "created_by": client.user_id,
            }).execute()

            # Marque la réponse comme traitée
            extra["calendly_invite_sent_at"] = _dt.now().isoformat(timespec="seconds")
            extra["calendly_booking_url"] = booking_url
            extra["handled"] = True
            sb.table("email_history").update({"extra": extra}).eq(
                "id", rid).execute()

            return {"ok": True, "booking_url": booking_url}
        except Exception as exc:
            logger.exception("calendly_propose_to_reply")
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
        """Lance le pipeline complet en arrière-plan. Retourne immédiatement.
        Le front polle ensuite autopilot_status() pour le log + stats."""
        # Refuse si un run est déjà en cours
        with self._autopilot_lock:
            if self._autopilot_state.get("running"):
                return {"ok": False, "error": "Un run est déjà en cours."}
            # Reset état
            from datetime import datetime
            self._autopilot_state.update({
                "running": True,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": "",
                "log": [],
                "stats": None,
                "error": "",
            })

        # Sauve la config avant lancement (si fournie)
        if payload and payload.get("config"):
            r = self.autopilot_save_config(payload)
            if not r.get("ok"):
                with self._autopilot_lock:
                    self._autopilot_state["running"] = False
                    self._autopilot_state["error"] = r.get("error", "")
                return r

        # Sync clés API au Core (au cas où)
        self._sync_keys_to_core()

        def _push_log(msg: str) -> None:
            from datetime import datetime
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
                _push_log(f"Lancement du pipeline (mode {cfg.mode})…")
                stats = run_full_pipeline(cfg, progress=_push_log)
                _push_log(
                    f"=== Fin === {stats.searched} trouvés, "
                    f"{stats.enriched} enrichis, {stats.drafts_sent} envoyés, "
                    f"{stats.drafts_pending} brouillons en attente, "
                    f"{stats.replies_detected} réponses, "
                    f"{len(stats.errors)} erreurs."
                )
                with self._autopilot_lock:
                    self._autopilot_state["stats"] = asdict(stats)
            except Exception as exc:
                logger.exception("autopilot_run a échoué")
                _push_log(f"✗ Pipeline a échoué : {exc}")
                with self._autopilot_lock:
                    self._autopilot_state["error"] = str(exc)
            finally:
                with self._autopilot_lock:
                    self._autopilot_state["running"] = False
                    self._autopilot_state["finished_at"] = (
                        datetime.now().isoformat(timespec="seconds")
                    )

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
            return {
                "ok": True,
                "running":     bool(self._autopilot_state["running"]),
                "started_at":  self._autopilot_state["started_at"],
                "finished_at": self._autopilot_state["finished_at"],
                "log":         new_lines,
                "log_len":     len(log),
                "stats":       self._autopilot_state["stats"],
                "error":       self._autopilot_state["error"],
            }

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
        """Renvoie mon user_id Supabase (pour aligner les bulles côté UI)."""
        try:
            from triskell_core.db import get_client
            c = get_client()
            return {"ok": True, "user_id": c.user_id}
        except Exception as exc:
            logger.debug("messages_me: %s", exc)
            return {"ok": False, "error": str(exc), "user_id": None}

    def messages_other_user(self) -> dict:
        """Renvoie le profil de l'autre user (Jordan voit Thomas, etc.)."""
        try:
            from ..integrations.messages import other_user
            return {"ok": True, "other": other_user()}
        except Exception as exc:
            logger.debug("messages_other_user: %s", exc)
            return {"ok": False, "error": str(exc)}

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
        """Envoie un message à l'autre user."""
        try:
            from ..integrations.messages import send_message
            body = (payload or {}).get("body", "")
            msg = send_message(body)
            return {"ok": bool(msg), "message": msg}
        except Exception as exc:
            logger.warning("messages_send: %s", exc)
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
