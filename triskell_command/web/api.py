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
