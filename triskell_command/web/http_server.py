"""Serveur HTTP — expose la classe Api existante via routes REST.

But : permettre d'utiliser Triskell Command dans n'importe quel navigateur
(PC, mobile, distant) en plus du wrapper pywebview local. Zéro modif de
api.py — on auto-génère les routes à partir des méthodes publiques.

Usage :
    python run_http.py            # lance ce serveur sur localhost:8765
    # puis ouvrir http://localhost:8765 dans Chrome / Firefox / mobile

Architecture :
- Classe Api unique partagée (singleton)
- Pour chaque méthode publique (sans underscore initial) : route POST
  /api/<method_name> qui prend un body JSON et renvoie le résultat JSON
- Sert les fichiers statiques de web/ui/ à la racine
- CORS permissif (auth gérée plus tard, Phase 3.2)
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from . import auth as tcauth
from . import push as tcpush
from .api import Api

logger = logging.getLogger(__name__)

UI_DIR = Path(__file__).parent / "ui"


def create_app() -> FastAPI:
    """Construit l'app FastAPI avec routes auto-générées depuis Api."""
    app = FastAPI(
        title="Triskell Command HTTP API",
        version="0.1.0",
        docs_url="/api/_docs",
        redoc_url=None,
    )

    # CORS — configurable via TRISKELL_CORS_ORIGINS (origines séparées par
    # des virgules). Défaut "*" car les sites clients Pixel Pros (dizaines
    # de domaines, dont des domaines custom) postent leurs formulaires de
    # contact sur les endpoints publics — impossible de lister les origines
    # à l'avance. Le risque est contenu : le cookie de session est
    # SameSite=Lax + HttpOnly, donc un site tiers ne peut PAS faire d'appel
    # authentifié avec le cookie de Jordan (anti-CSRF), et toutes les
    # routes /api/* non publiques exigent ce cookie.
    _cors_raw = (os.environ.get("TRISKELL_CORS_ORIGINS") or "*").strip()
    _cors_origins = ([o.strip() for o in _cors_raw.split(",") if o.strip()]
                     or ["*"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------------- Middleware d'auth ----------------
    # Bloque toutes les routes /api/* sauf celles dans PUBLIC_API_PATHS,
    # tant qu'aucun cookie de session valide n'est présent.

    @app.middleware("http")
    async def cache_control_middleware(request: Request, call_next):
        """Anti-interface-fantôme : les navigateurs gardaient les vieux
        scripts en cache après un déploiement → « je ne vois aucun
        changement ». On force la revalidation des fichiers de l'UI à
        chaque chargement (réponse 304 ultra-légère si rien n'a bougé,
        version fraîche sinon). Les assets lourds (images) restent cachés.
        """
        response = await call_next(request)
        p = request.url.path
        if (p.startswith("/scripts/") or p.startswith("/styles/")
                or p in ("/", "/index.html", "/login.html")):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in tcauth.PUBLIC_API_PATHS:
            cookie = request.cookies.get(tcauth.COOKIE_NAME)
            user_id = tcauth.read_session_cookie(cookie)
            if not user_id:
                return JSONResponse(
                    status_code=401,
                    content={"ok": False, "error": "auth_required"},
                )
            # Attache l'user au request pour usage downstream
            request.state.user_id = user_id
            # Pose l'identité locale dans un contextvar lisible depuis les
            # modules métier (ex: integrations/messages.py pour le chat).
            token = tcauth.set_current_local_user(user_id)
            try:
                return await call_next(request)
            finally:
                tcauth.reset_current_local_user(token)
        return await call_next(request)

    # Marqueur de présence : CE process est LE serveur. Les robots qui
    # tournent ailleurs (app desktop ouverte sur le PC de Jordan) verront
    # son battement de cœur et s'effaceront — fin du double traitement.
    try:
        from ..integrations import server_presence
        server_presence.mark_server_process()
    except Exception as exc:
        logger.debug("server_presence indisponible : %s", exc)

    # Rôle du process : "all" (défaut, comportement historique = web +
    # robots), "web" (sert uniquement le site/API, aucun robot) ou
    # "workers" (robots sans vocation à servir le front). Prépare la
    # séparation serveur web / robots en 2 déploiements SANS rien casser :
    # tant que la variable n'est pas posée, rien ne change.
    role = (os.environ.get("TRISKELL_ROLE") or "all").strip().lower()
    if role not in ("all", "web", "workers"):
        role = "all"
    run_workers = role in ("all", "workers")
    logger.info("Rôle du process : %s (robots de fond : %s)",
                role, "oui" if run_workers else "non")

    # Singleton Api (workers backend démarrent au premier accès)
    api_instance = Api()

    # Restaure automatiquement la session Supabase si elle existe sur disque
    # (~/.triskell-command/auth.json). Sinon Jordan devrait se reconnecter à
    # chaque restart du serveur HTTP, ce qui est insupportable.
    try:
        st = api_instance.auth_status()
        if st.get("connected"):
            logger.info("Session Supabase restaurée : %s", st.get("display_name") or st.get("user_id"))
            # Refresh tout de suite : si le token a expiré pendant que le serveur
            # était down, on récupère un nouveau access_token via le refresh_token.
            _try_refresh_supabase()
        else:
            logger.info("Session Supabase non restaurée (raison : %s). Login requis via Réglages.",
                        st.get("reason") or "inconnue")
    except Exception as exc:
        logger.warning("auth_status au boot a échoué : %s", exc)

    # Lance un thread daemon qui refresh la session Supabase toutes les 30 min.
    # Empêche l'expiration de l'access_token (durée typique : 1h).
    _start_supabase_refresh_thread()

    if run_workers:
        # Thread des rappels Brain : check toutes les 5 min si des notes ont
        # un remind_at échu et envoie une push notification.
        _start_brain_reminders_thread()

        # Battement de cœur serveur (toutes les 5 min dans shared_settings) :
        # signale aux robots du desktop que le serveur travaille.
        _start_server_heartbeat_thread()

        # Chien de garde : alerte push si un robot est en panne / muet.
        # (La panne silencieuse de juin 2026 — 6 robots morts pendant des
        # semaines — ne doit JAMAIS se reproduire.)
        _start_watchdog_thread(api_instance)

        # Réchauffeur Pixel Pros : le serveur (hébergé en Europe) visite la
        # home toutes les 3 min pour que l'edge européen ne s'endorme jamais.
        # Sinon, faute de trafic, le 1er visiteur (et le test Google, toujours
        # à froid) attend ~1,6 s → note de vitesse mobile dans le rouge.
        # Demande Jordan le 18/06/2026 (le ping vient d'Europe = bonne « porte »).
        _start_keepwarm_thread()

        # Concierge disque + filet GEO : purge quotidienne des vieux exports
        # et chasses terminées (un disque plein = les 503 de juin), copie
        # cloud des données GEO au boot puis chaque jour, et restauration
        # automatique si le volume serveur est reparti de zéro.
        try:
            from ..integrations import disk_janitor
            _janitor_state = getattr(api_instance, "_app_state", None)
            if _janitor_state is not None:
                disk_janitor.start_worker(_janitor_state)
        except Exception as exc:
            logger.warning("disk_janitor indisponible : %s", exc)

        # Promotion des commissions affiliés (toutes les 6 h) : ce worker
        # n'était démarré QUE par l'app desktop → sur le serveur, les
        # commissions n'avançaient jamais. On le lance ici avec les autres.
        try:
            from ..integrations.pixelpros import affiliate_payouts_runner
            affiliate_payouts_runner.start_worker(
                getattr(api_instance, "_app_state", None))
        except Exception as exc:
            logger.warning("affiliate_payouts_runner indisponible : %s", exc)

        # Le guetteur du copilote : dépose les évènements (réponse de
        # prospect, chasse finie, rappels) dans le fil + push si chaud.
        try:
            from ..integrations import copilot_watch
            copilot_watch.start_worker()
            logger.info("Guetteur du copilote démarré (cycle %d s).",
                        copilot_watch.CYCLE_SECONDS)
        except Exception as exc:
            logger.warning("copilot_watch indisponible : %s", exc)

        # Démarre les workers backend (pollers IMAP, autopilot, drip, etc.)
        # SANS attendre que le front se connecte. Comme ça, le serveur fait
        # son boulot même si personne n'a la page ouverte.
        try:
            boot_result = api_instance.boot()
            if boot_result.get("ok"):
                logger.info("Workers backend démarrés au boot du serveur HTTP.")
        except Exception as exc:
            logger.warning("boot() au démarrage HTTP a échoué : %s", exc)

    # Reprise auto des envois Convoi qui ont ete tues par le redemarrage
    # precedent (ex: redeploiement Coolify pendant un convoi en cours).
    # On lance dans un thread daemon pour ne PAS bloquer la creation du
    # serveur : si Supabase est lent au demarrage, on ne veut pas qu'on
    # retarde la prise en charge des requetes HTTP.
    def _resume_convoy_later():
        # Petit delai pour laisser le boot finir + l'auth Supabase se faire
        time.sleep(15)
        try:
            res = api_instance.resume_convoy_sends()
            n = res.get("resumed", 0) if isinstance(res, dict) else 0
            c = res.get("cleaned", 0) if isinstance(res, dict) else 0
            if n or c:
                logger.info(
                    "Convoi : %d envoi(s) repris apres redemarrage, "
                    "%d campagne(s) nettoyee(s).", n, c,
                )
        except Exception as exc:
            logger.warning("resume_convoy_sends au boot a echoue : %s", exc)

    if run_workers:
        threading.Thread(
            target=_resume_convoy_later, name="convoy-resume-boot", daemon=True,
        ).start()

    # Auto-génération des routes depuis les méthodes publiques
    method_count = 0
    for name, method in inspect.getmembers(api_instance, inspect.ismethod):
        if name.startswith("_"):
            continue
        # Wrap chaque méthode dans une closure qui lit le body JSON
        _register_route(app, name, method)
        method_count += 1

    logger.info("HTTP API : %d méthodes exposées sous /api/", method_count)

    # ---------------- Routes système ----------------

    @app.get("/api/_health")
    async def health() -> dict:
        return {"ok": True, "service": "triskell-command-http", "methods": method_count}

    @app.post("/api/perceval_voice")
    async def perceval_voice(request: Request) -> Response:
        """Voix de Perceval : texte → MP3 (voix neurale Microsoft via
        edge-tts). En cas d'échec (paquet absent, service muet), renvoie une
        erreur JSON → le navigateur reprend avec sa propre voix."""
        try:
            payload = (await request.json()) or {}
        except Exception:
            payload = {}
        text = str((payload or {}).get("text") or "")
        voice = str((payload or {}).get("voice") or "")
        if not text.strip():
            return JSONResponse(status_code=400, content={"ok": False, "error": "no_text"})
        try:
            from ..integrations import voice_tts
            audio = await voice_tts.synthesize(text, voice)
        except Exception as exc:
            logger.warning("perceval_voice indisponible : %s", exc)
            return JSONResponse(status_code=502, content={"ok": False, "error": "tts_unavailable"})
        if not audio:
            return JSONResponse(status_code=502, content={"ok": False, "error": "tts_empty"})
        return Response(
            content=audio,
            media_type="audio/mpeg",
            headers={"Cache-Control": "private, max-age=86400"},
        )

    @app.post("/api/perceval_pulse")
    async def perceval_pulse(request: Request) -> JSONResponse:
        """Le « cerveau » de Perceval : renvoie UNE remarque d'associé
        (avis + éventuelle action) générée par l'IA, à partir de l'écran
        courant, de ce qui vient de se passer et de l'état réel. Exécuté
        dans un threadpool pour ne pas bloquer le serveur pendant l'appel
        IA. Échec → {ok:false} : le navigateur retombe sur ses remarques
        toutes faites (gratuites)."""
        try:
            payload = (await request.json()) or {}
        except Exception:
            payload = {}
        view = str(payload.get("view") or "")
        event = str(payload.get("event") or "")[:200]
        last_said = payload.get("last_said") or []
        if not isinstance(last_said, list):
            last_said = []
        last_said = [str(x) for x in last_said][-6:]
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict):
            snapshot = None
        from ..integrations import claude_advisor
        from starlette.concurrency import run_in_threadpool
        try:
            res = await run_in_threadpool(
                claude_advisor.perceval_take,
                api_instance._app_state,
                view=view, last_said=last_said, event=event, snapshot=snapshot,
            )
        except Exception as exc:
            logger.warning("perceval_pulse: %s", exc)
            return JSONResponse(content={"ok": False, "error": "pulse_failed"})
        return JSONResponse(content=res if isinstance(res, dict) else {"ok": False})

    # ---------------- Auth : login / logout / me ----------------

    @app.post("/api/login")
    async def login(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        username = (payload or {}).get("username", "")
        password = (payload or {}).get("password", "")
        user_id = tcauth.authenticate(username, password)
        if not user_id:
            return JSONResponse(
                status_code=401,
                content={"ok": False, "error": "credentials_invalid"},
            )
        cookie_value = tcauth.make_session_cookie_value(user_id)
        response = JSONResponse(content={
            "ok": True,
            "user_id": user_id,
            "display_name": tcauth.get_display_name(user_id),
        })
        # Cookie "secure" (jamais transmis en HTTP clair) dès que la requête
        # arrive en HTTPS — c'est le cas en prod derrière le proxy Coolify
        # (en-tête x-forwarded-proto). En local (http://localhost) il reste
        # non-secure pour que le login marche en dev.
        _fwd_proto = (request.headers.get("x-forwarded-proto") or "").lower()
        _is_https = request.url.scheme == "https" or _fwd_proto == "https"
        response.set_cookie(
            key=tcauth.COOKIE_NAME,
            value=cookie_value,
            max_age=tcauth.COOKIE_MAX_AGE,
            httponly=True,
            secure=_is_https,
            samesite="lax",
            path="/",
        )
        return response

    @app.post("/api/logout")
    async def logout() -> JSONResponse:
        response = JSONResponse(content={"ok": True})
        response.delete_cookie(tcauth.COOKIE_NAME, path="/")
        return response

    @app.get("/api/me")
    async def me(request: Request) -> JSONResponse:
        cookie = request.cookies.get(tcauth.COOKIE_NAME)
        user_id = tcauth.read_session_cookie(cookie)
        if not user_id:
            return JSONResponse(content={"ok": True, "connected": False})
        return JSONResponse(content={
            "ok": True,
            "connected": True,
            "user_id": user_id,
            "display_name": tcauth.get_display_name(user_id),
        })

    @app.post("/api/me_update")
    async def me_update(request: Request) -> JSONResponse:
        """Met à jour le profil personnel de l'utilisateur connecté :
        - display_name : nom affiché (stocké par user_id, personnel à chaque
          utilisateur — Jordan et Thomas ont chacun le leur)
        - email : email d'expéditeur par défaut (partagé via outreach.from_email)
        """
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            return JSONResponse(status_code=401,
                                content={"ok": False, "error": "auth_required"})
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        payload = payload or {}
        display_name = (payload.get("display_name") or "").strip()
        email = (payload.get("email") or "").strip()
        if not display_name:
            return JSONResponse(content={"ok": False, "error": "Le nom est requis."})
        # Enregistre le display_name personnalisé pour ce user_id
        if not tcauth.set_display_name(user_id, display_name):
            return JSONResponse(content={"ok": False, "error": "Sauvegarde du nom impossible."})
        # Email partagé : on passe par save_user_identity (qui écrit outreach.from_email)
        if email:
            try:
                api_instance.save_user_identity({"full_name": display_name, "email": email})
            except Exception as exc:
                logger.warning("me_update outreach save : %s", exc)
        return JSONResponse(content={
            "ok": True,
            "user_id": user_id,
            "display_name": display_name,
            "email": email,
        })

    # ---------------- Web Push notifications ----------------

    @app.get("/api/push/public_key")
    async def push_public_key() -> JSONResponse:
        """Renvoie la clé publique VAPID pour que le navigateur puisse
        souscrire aux push. Public (pas besoin d'être loggé pour la lire)."""
        key = tcpush.get_public_key()
        if not key:
            return JSONResponse(content={"ok": False, "error": "vapid_not_configured"}, status_code=503)
        return JSONResponse(content={"ok": True, "public_key": key})

    @app.post("/api/push/subscribe")
    async def push_subscribe(request: Request) -> JSONResponse:
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            return JSONResponse(status_code=401, content={"ok": False, "error": "auth_required"})
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        sub = (payload or {}).get("subscription") or payload
        result = tcpush.save_subscription(user_id, sub)
        return JSONResponse(content=result)

    @app.post("/api/push/unsubscribe")
    async def push_unsubscribe(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        endpoint = (payload or {}).get("endpoint") or ""
        return JSONResponse(content=tcpush.remove_subscription(endpoint))

    @app.post("/api/push/test")
    async def push_test(request: Request) -> JSONResponse:
        """Envoie une notif de test à TOUTES les subs du user connecté."""
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            return JSONResponse(status_code=401, content={"ok": False, "error": "auth_required"})
        result = tcpush.send_push(
            title="Triskell Command",
            body=f"Notif de test pour {tcauth.get_display_name(user_id)} — ça marche !",
            user_id=user_id,
            tag="test",
        )
        return JSONResponse(content={"ok": True, **result})

    # ---------------- Désinscription en 1 clic (public) ----------------
    # GET  : page de confirmation (n'agit PAS — évite qu'un antivirus/proxy
    #        qui préfetche le lien désinscrive à tort).
    # POST : désinscrit réellement. C'est aussi ce qu'appelle le one-click
    #        des messageries (RFC 8058, body « List-Unsubscribe=One-Click »).
    _UNSUB_PAGE_CSS = (
        "body{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;"
        "background:#f8fafc;color:#1f2937;display:flex;min-height:100vh;"
        "align-items:center;justify-content:center;margin:0;padding:24px}"
        ".card{background:#fff;border:1px solid #e5e7eb;border-radius:16px;"
        "padding:32px 28px;max-width:440px;box-shadow:0 4px 24px rgba(0,0,0,.06);"
        "text-align:center}h1{font-size:20px;margin:0 0 12px}"
        "p{font-size:15px;line-height:1.6;color:#4b5563;margin:0 0 20px}"
        ".btn{display:inline-block;background:#dc2626;color:#fff;border:0;"
        "border-radius:10px;padding:12px 22px;font-size:15px;font-weight:600;"
        "cursor:pointer;text-decoration:none}.ok{color:#059669;font-size:34px}"
        ".muted{color:#9ca3af;font-size:13px;margin-top:16px}")

    def _unsub_page(title: str, body_html: str, status: int = 200) -> HTMLResponse:
        return HTMLResponse(status_code=status, content=(
            "<!doctype html><html lang=fr><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<meta name=robots content='noindex'>"
            f"<title>{title}</title><style>{_UNSUB_PAGE_CSS}</style></head>"
            f"<body><div class=card>{body_html}</div></body></html>"))

    @app.get("/api/unsubscribe")
    async def unsubscribe_get(request: Request) -> HTMLResponse:
        from html import escape
        from ..integrations import unsubscribe as unsub
        token = request.query_params.get("u", "")
        info = unsub.verify_token(token)
        if not info:
            return _unsub_page(
                "Lien invalide",
                "<h1>Lien invalide</h1><p>Ce lien de désinscription n'est "
                "pas valide ou a expiré.</p>", status=400)
        email = escape(info["email"])
        return _unsub_page("Confirmer la désinscription", (
            "<h1>Se désinscrire</h1>"
            f"<p>Confirmez la désinscription de <b>{email}</b>.<br>"
            "Vous ne recevrez plus aucun message de notre part.</p>"
            f"<form method=post action='/api/unsubscribe?u={escape(token)}'>"
            "<button class=btn type=submit>Confirmer la désinscription</button>"
            "</form>"))

    @app.post("/api/unsubscribe")
    async def unsubscribe_post(request: Request) -> HTMLResponse:
        from ..integrations import unsubscribe as unsub
        token = request.query_params.get("u", "")
        if not token:
            # one-click : le token peut être dans le corps de formulaire
            try:
                form = await request.form()
                token = str(form.get("u", "") or "")
            except Exception:
                token = ""
        result = unsub.process_unsubscribe(token)
        if result.get("ok"):
            return _unsub_page("Désinscription confirmée", (
                "<div class=ok>✓</div><h1>C'est fait</h1>"
                "<p>Vous êtes désinscrit. Vous ne recevrez plus aucun "
                "message de notre part.</p>"
                "<div class=muted>Vous pouvez fermer cette page.</div>"))
        return _unsub_page("Désinscription", (
            "<h1>Un instant</h1>"
            f"<p>{result.get('error') or 'Réessayez dans quelques minutes.'}</p>"),
            status=400)

    @app.get("/api/_methods")
    async def list_methods() -> dict:
        """Liste les méthodes API disponibles (utile pour debug front)."""
        names = [n for n, m in inspect.getmembers(api_instance, inspect.ismethod)
                 if not n.startswith("_")]
        return {"ok": True, "methods": sorted(names)}

    # ---------------- Le Copilote : réponse au fil de l'eau (SSE) ----------------
    # Le volet de discussion affiche la réponse mot à mot. Route protégée
    # par le middleware d'auth (pas dans PUBLIC_API_PATHS). Le générateur
    # est synchrone : Starlette l'itère dans un threadpool, l'event loop
    # n'est pas bloqué pendant l'appel IA.

    @app.post("/api/copilot_stream")
    async def copilot_stream(request: Request) -> StreamingResponse:
        user_id = getattr(request.state, "user_id", None) or "jordan"
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        question = str((payload or {}).get("question") or "")
        view = str((payload or {}).get("view") or "")
        briefing = bool((payload or {}).get("briefing"))

        from ..integrations import copilot as _copilot

        def event_source():
            try:
                if briefing:
                    gen = _copilot.stream_briefing(
                        api_instance._app_state, user_id, view=view)
                else:
                    gen = _copilot.stream_reply(
                        api_instance._app_state, user_id, question, view=view)
                for evt in gen:
                    yield ("data: "
                           + json.dumps(evt, ensure_ascii=False)
                           + "\n\n")
            except Exception as exc:  # ceinture : ne jamais couper sans mot
                logger.warning("copilot_stream: %s", exc)
                yield ("data: "
                       + json.dumps({"type": "error",
                                     "error": "Le serveur a perdu le fil — réessaie."},
                                    ensure_ascii=False)
                       + "\n\n")

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ---------------- Avatars (photo de profil par utilisateur) ----------------
    # Stockés dans ~/.triskell-command/avatars/{user_id}.{ext}. Chaque user du
    # cookie de session (Jordan / Thomas) a sa propre photo, indépendamment du
    # compte Supabase partagé.

    AVATARS_DIR = Path.home() / ".triskell-command" / "avatars"
    ALLOWED_AVATAR_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}
    MAX_AVATAR_SIZE = 4 * 1024 * 1024  # 4 Mo

    def _find_avatar(user_id: str) -> Path | None:
        if not AVATARS_DIR.exists():
            return None
        for ext in ALLOWED_AVATAR_EXTS:
            p = AVATARS_DIR / f"{user_id}.{ext}"
            if p.is_file():
                return p
        return None

    @app.post("/api/avatar")
    async def upload_avatar(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            return JSONResponse(status_code=401, content={"ok": False, "error": "auth_required"})
        filename = (file.filename or "").lower()
        ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
        if ext not in ALLOWED_AVATAR_EXTS:
            return JSONResponse(status_code=400, content={
                "ok": False,
                "error": f"Format non supporté. Utilise : {', '.join(sorted(ALLOWED_AVATAR_EXTS))}",
            })
        data = await file.read()
        if len(data) > MAX_AVATAR_SIZE:
            return JSONResponse(status_code=400, content={
                "ok": False,
                "error": "Image trop lourde (max 4 Mo).",
            })
        AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        # Supprime les anciennes versions avec d'autres extensions
        for old_ext in ALLOWED_AVATAR_EXTS:
            old = AVATARS_DIR / f"{user_id}.{old_ext}"
            if old.is_file() and old_ext != ext:
                try: old.unlink()
                except Exception: pass
        target = AVATARS_DIR / f"{user_id}.{ext}"
        target.write_bytes(data)
        return JSONResponse(content={"ok": True, "url": f"/api/avatar/{user_id}?v={int(time.time())}"})

    @app.delete("/api/avatar")
    async def delete_avatar(request: Request) -> JSONResponse:
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            return JSONResponse(status_code=401, content={"ok": False, "error": "auth_required"})
        p = _find_avatar(user_id)
        if p:
            try: p.unlink()
            except Exception: pass
        return JSONResponse(content={"ok": True})

    @app.get("/api/avatar/{user_id}")
    async def get_avatar(user_id: str) -> FileResponse:
        # Public — pas besoin d'auth pour lire (comme un favicon). Permet aux
        # autres users connectés de voir la photo de l'autre dans le chat Thomas/Jordan.
        p = _find_avatar(user_id)
        if not p:
            raise HTTPException(status_code=404, detail="Pas de photo")
        return FileResponse(str(p))

    # ---------------- Pièces jointes du chat ----------------
    # Stockées dans ~/.triskell-command/chat-attachments/{aid}/{filename}.
    # `aid` est un UUID v4 généré côté serveur — fait office de "secret" pour
    # éviter qu'on devine les URLs des pièces jointes des autres conversations.
    # 10 Mo max, tous types autorisés (le chat est privé Jordan ↔ Thomas).

    CHAT_ATTACH_DIR = Path.home() / ".triskell-command" / "chat-attachments"
    MAX_CHAT_ATTACH_SIZE = 10 * 1024 * 1024  # 10 Mo

    def _sanitize_filename(name: str) -> str:
        """Nettoie le nom de fichier : enlève les sous-dossiers, garde
        seulement le basename et limite la longueur."""
        import os.path
        base = os.path.basename(name or "").strip()
        # Remplace les caractères chelous par "_"
        safe = "".join(c if c.isalnum() or c in "._- ()[]" else "_" for c in base)
        safe = safe.strip(". ") or "fichier"
        return safe[:120]

    @app.post("/api/chat_attachment")
    async def upload_chat_attachment(
        request: Request,
        file: UploadFile = File(...),
    ) -> JSONResponse:
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            return JSONResponse(status_code=401, content={"ok": False, "error": "auth_required"})
        data = await file.read()
        if len(data) == 0:
            return JSONResponse(status_code=400, content={"ok": False, "error": "Fichier vide."})
        if len(data) > MAX_CHAT_ATTACH_SIZE:
            return JSONResponse(status_code=400, content={
                "ok": False,
                "error": "Fichier trop lourd (max 10 Mo).",
            })
        # Identifiant unique pour le sous-dossier — fait aussi office d'URL.
        import uuid
        aid = uuid.uuid4().hex
        safe_name = _sanitize_filename(file.filename or "fichier")
        target_dir = CHAT_ATTACH_DIR / aid
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe_name
        target.write_bytes(data)
        url = f"/api/chat_attachment/{aid}/{safe_name}"
        return JSONResponse(content={
            "ok": True,
            "url": url,
            "name": safe_name,
            "type": file.content_type or "application/octet-stream",
            "size": len(data),
        })

    @app.get("/api/chat_attachment/{aid}/{name}")
    async def get_chat_attachment(request: Request, aid: str, name: str) -> FileResponse:
        # Auth requise — seul un user loggé voit les pièces jointes du chat.
        # (Le chat est privé Jordan ↔ Thomas, pas public comme les avatars.)
        cookie = request.cookies.get(tcauth.COOKIE_NAME)
        if not tcauth.read_session_cookie(cookie):
            raise HTTPException(status_code=401, detail="auth_required")
        # Garde-fou : on n'autorise que des `aid` hex (UUID) pour empêcher
        # l'évasion de répertoire (../../etc/passwd, etc.).
        if not aid.isalnum() or len(aid) > 64:
            raise HTTPException(status_code=400, detail="aid invalide")
        safe_name = _sanitize_filename(name)
        p = CHAT_ATTACH_DIR / aid / safe_name
        if not p.is_file():
            raise HTTPException(status_code=404, detail="Pièce jointe introuvable")
        return FileResponse(str(p))

    # ---------------- Facturation SaaS (Stripe) ----------------
    # Routes minimales pour brancher l'abonnement. Aucune ne nécessite
    # le SDK Stripe d'être installé tant qu'on ne les appelle pas — elles
    # le chargent en lazy via billing_saas.checkout._stripe().

    @app.post("/api/billing/create_checkout")
    async def billing_create_checkout(request: Request) -> JSONResponse:
        """Crée une Stripe Checkout Session.

        Body attendu : {"modules": ["essential", "phare"], "email": "..."}
        Renvoie {"ok": true, "url": "https://checkout.stripe.com/..."}.
        """
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            return JSONResponse(status_code=401,
                                content={"ok": False, "error": "auth_required"})
        try:
            payload = (await request.json()) or {}
        except Exception:
            payload = {}
        modules = payload.get("modules") or ["essential"]
        email   = (payload.get("email") or "").strip()
        # En attendant le multi-tenant réel (migration 20), on utilise
        # l'user_id comme workspace_id temporaire (1 user = 1 workspace).
        workspace_id = user_id
        try:
            from ..integrations.billing_saas import checkout
            url = checkout.create_session(
                workspace_id=workspace_id,
                workspace_email=email,
                modules=modules,
            )
            return JSONResponse(content={"ok": True, "url": url})
        except Exception as exc:
            logger.exception("billing.create_checkout a échoué")
            return JSONResponse(status_code=500,
                                content={"ok": False, "error": str(exc)})

    @app.post("/api/billing/portal")
    async def billing_portal(request: Request) -> JSONResponse:
        """Renvoie l'URL Stripe Customer Portal pour gérer son abonnement."""
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            return JSONResponse(status_code=401,
                                content={"ok": False, "error": "auth_required"})
        try:
            payload = (await request.json()) or {}
        except Exception:
            payload = {}
        customer_id = (payload.get("stripe_customer_id") or "").strip()
        if not customer_id:
            return JSONResponse(status_code=400,
                                content={"ok": False,
                                         "error": "stripe_customer_id requis"})
        try:
            from ..integrations.billing_saas import portal
            url = portal.create_session(customer_id)
            return JSONResponse(content={"ok": True, "url": url})
        except Exception as exc:
            logger.exception("billing.portal a échoué")
            return JSONResponse(status_code=500,
                                content={"ok": False, "error": str(exc)})

    @app.post("/api/billing/webhook")
    async def billing_webhook(request: Request) -> JSONResponse:
        """Reçoit les évènements Stripe (signature vérifiée).

        Cette route DOIT être dans PUBLIC_API_PATHS (côté tcauth) sinon
        Stripe se prend un 401. À ajouter manuellement quand on active
        vraiment la facturation.
        """
        sig = request.headers.get("stripe-signature", "")
        payload_bytes = await request.body()
        try:
            from ..integrations.billing_saas import webhook
            event = webhook.parse_event(payload_bytes, sig)
            result = webhook.handle_event(event)
            return JSONResponse(content=result)
        except ValueError as exc:
            return JSONResponse(status_code=400,
                                content={"ok": False, "error": str(exc)})
        except Exception as exc:
            logger.exception("billing.webhook a échoué")
            return JSONResponse(status_code=500,
                                content={"ok": False, "error": str(exc)})

    # ------------------------------------------------------------------
    # Pixel Pros — endpoints publics appelés par les webhooks externes
    # ------------------------------------------------------------------
    # Le secret partagé est PP_HOOK_TOKEN. Il est passé en Bearer header
    # par :
    #   1. Le webhook Stripe Netlify (`stripe-webhook.ts`), via la variable
    #      d'env `PP_TRIGGER_BUILD_TOKEN`, pour appeler /on_paid.
    #   2. Le builder Python (`build_site.py`), via la même variable, pour
    #      appeler /on_built à la fin de la construction.

    def _check_pp_token(request: Request) -> bool:
        expected = (os.environ.get("PP_HOOK_TOKEN") or "").strip()
        if not expected:
            # Pas de token configuré côté serveur → on bloque par défaut.
            return False
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return False
        return auth[7:].strip() == expected

    @app.post("/api/pixelpros/on_paid")
    async def pixelpros_on_paid(request: Request) -> JSONResponse:
        """Appelé par le webhook Stripe Netlify juste après mark_paid.

        Body attendu : {"draftId": "<uuid>", "email": "...", "stripeSessionId": "..."}.
        Actions : envoi du mail "merci paiement" + déclenchement du build.
        """
        if not _check_pp_token(request):
            return JSONResponse(status_code=401,
                                content={"ok": False, "error": "unauthorized"})
        try:
            body = await request.json()
        except Exception:
            body = {}
        draft_id = (body.get("draftId") or body.get("draft_id") or "").strip()
        if not draft_id:
            return JSONResponse(status_code=400,
                                content={"ok": False, "error": "draftId manquant"})
        try:
            from ..integrations.pixelpros import repo as r, mailer as m
            intake = r.get_intake(draft_id)
            if intake is None:
                return JSONResponse(status_code=404,
                                    content={"ok": False, "error": "intake introuvable"})

            # Idempotence : Stripe REJOUE le webhook en cas de timeout. Sans
            # ce marqueur, chaque rejeu renvoyait push + mail + build.
            _data = intake.get("data") or {}
            if isinstance(_data, dict) and _data.get("paid_hook_done_at"):
                return JSONResponse(content={"ok": True, "already": True})

            mail_auto = m.is_auto("paid")
            # Notification INCONDITIONNELLE : un paiement ne doit JAMAIS être
            # silencieux. En mode mail manuel + construction coupée, sans ce
            # push le client payait et rien ni personne n'était prévenu.
            try:
                _pp_name = (intake.get("business_name")
                            or intake.get("business-name")
                            or intake.get("name")
                            or intake.get("email") or draft_id)
                _pp_hint = ("" if mail_auto
                            else " — mail de bienvenue à envoyer depuis l'écran Pixel Pros")
                tcpush.send_push(
                    f"💳 Paiement reçu — {_pp_name}",
                    f"Nouveau site Pixel Pros payé{_pp_hint}.",
                    user_id="jordan", priority="urgent",
                    tag=f"pp_paid_{draft_id}", tag_group="pixelpros",
                    url="/?view=pixelpros",
                    extra_data={"type": "pp_paid", "draft_id": draft_id},
                )
            except Exception:
                logger.exception("pixelpros.on_paid : push paiement KO")

            if mail_auto:
                mail_ok, mail_msg = m.send_paid_mail(intake)
            else:
                mail_ok, mail_msg = False, "skipped (mode manuel — déclencher depuis l'UI)"
            build_ok, build_msg = r.dispatch_build(draft_id)
            try:
                r.update_intake_data(draft_id, {
                    "paid_hook_done_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                })
            except Exception:
                logger.exception("pixelpros.on_paid : marqueur idempotence KO")
            return JSONResponse(content={
                "ok": True,
                "mail": {"ok": mail_ok, "message": mail_msg},
                "build": {"ok": build_ok, "message": build_msg},
            })
        except Exception as exc:
            logger.exception("pixelpros.on_paid a échoué")
            return JSONResponse(status_code=500,
                                content={"ok": False, "error": str(exc)})

    @app.post("/api/pixelpros/on_built")
    async def pixelpros_on_built(request: Request) -> JSONResponse:
        """Appelé par le builder Python à la fin d'un build réussi.

        Body attendu : {"draftId": "<uuid>", "siteUrl": "https://..."}.
        Actions : marque le draft 'live' avec l'URL, envoie le mail "site en ligne".
        Le builder peut aussi déjà avoir fait mark_live lui-même ; on idempotent.
        """
        if not _check_pp_token(request):
            return JSONResponse(status_code=401,
                                content={"ok": False, "error": "unauthorized"})
        try:
            body = await request.json()
        except Exception:
            body = {}
        draft_id = (body.get("draftId") or body.get("draft_id") or "").strip()
        site_url = (body.get("siteUrl") or body.get("site_url") or "").strip()
        if not draft_id:
            return JSONResponse(status_code=400,
                                content={"ok": False, "error": "draftId manquant"})
        try:
            from ..integrations.pixelpros import repo as r, mailer as m
            if site_url:
                r.mark_live(draft_id, site_url=site_url)
            intake = r.get_intake(draft_id)
            if intake is None:
                return JSONResponse(status_code=404,
                                    content={"ok": False, "error": "intake introuvable"})
            if m.is_auto("live"):
                mail_ok, mail_msg = m.send_live_mail(intake)
            else:
                mail_ok, mail_msg = False, "skipped (mode manuel — déclencher depuis l'UI)"
            return JSONResponse(content={
                "ok": True,
                "mail": {"ok": mail_ok, "message": mail_msg},
                "site_url": intake.get("site_url"),
            })
        except Exception as exc:
            logger.exception("pixelpros.on_built a échoué")
            return JSONResponse(status_code=500,
                                content={"ok": False, "error": str(exc)})

    # ---------------- Affiliés : magic link de reconnexion ----------------
    # Endpoint PUBLIC (pas de PP_HOOK_TOKEN car appelé par le navigateur des
    # affiliés). Rate-limité grossièrement par IP pour éviter le bourrage de mails.

    _affiliate_login_rate: dict[str, list[float]] = {}

    def _rate_limit_ok(ip: str, max_per_hour: int = 5) -> bool:
        import time
        now = time.time()
        bucket = _affiliate_login_rate.setdefault(ip, [])
        # purge les hits > 1h
        cutoff = now - 3600
        bucket[:] = [t for t in bucket if t > cutoff]
        if len(bucket) >= max_per_hour:
            return False
        bucket.append(now)
        # Limite globale du dict (anti memory leak)
        if len(_affiliate_login_rate) > 5000:
            _affiliate_login_rate.clear()
        return True

    @app.post("/api/pixelpros/affiliate-login-request")
    async def pixelpros_affiliate_login_request(request: Request) -> JSONResponse:
        """Reçoit {email}, génère un magic link et l'envoie par mail.

        Renvoie toujours un message générique (ne révèle pas si l'email existe).
        Rate-limit : 5 requêtes par IP par heure.
        """
        ip = (request.client.host if request.client else "?") or "?"
        if not _rate_limit_ok(ip):
            return JSONResponse(status_code=429, content={
                "ok": False,
                "error": "Trop de demandes. Réessaie dans une heure."
            })

        try:
            body = await request.json()
        except Exception:
            body = {}
        email = (body.get("email") or "").strip()
        if not email or "@" not in email:
            return JSONResponse(status_code=400, content={
                "ok": False, "error": "Email invalide."
            })

        # Réponse générique uniforme (anti-énumération)
        generic_response = {
            "ok": True,
            "message": "Si cet email correspond à un compte affilié, on vient d'envoyer un lien de connexion. Vérifie ta boîte (et tes spams)."
        }

        try:
            from ..integrations.pixelpros import affiliates as a_repo
            from ..integrations.pixelpros import mailer as m

            sb = a_repo._sb() if hasattr(a_repo, '_sb') else None
            if sb is None:
                # Tente via le repo principal qui partage la connexion
                from ..integrations.pixelpros.repo import _sb as _main_sb
                sb = _main_sb()

            if sb is None:
                logger.warning("affiliate-login-request: Supabase indispo")
                return JSONResponse(content=generic_response)

            res = sb.rpc("pp_affiliate_request_login", {"p_email": email}).execute()
            rows = res.data or []
            row = rows[0] if isinstance(rows, list) and rows else (rows if isinstance(rows, dict) else None)
            if not row or not row.get("success"):
                # Email inconnu OU compte non actif → on garde la réponse générique
                return JSONResponse(content=generic_response)

            token = row.get("token") or ""
            firstname = row.get("firstname") or ""
            ok, msg = m.send_affiliate_login_mail(email, token, firstname)
            if not ok:
                logger.warning("affiliate-login-request: envoi KO : %s", msg)
            return JSONResponse(content=generic_response)
        except Exception as exc:
            logger.exception("affiliate-login-request a échoué")
            return JSONResponse(content=generic_response)

    # ---------------- Formulaire de contact des sites clients ----------------
    # Endpoint PUBLIC appelé par le navigateur des visiteurs d'un site client
    # ({slug}.pixel-pros.fr). On résout TOUJOURS l'email du client côté serveur
    # à partir du slug (jamais une adresse écrite dans la page) → certitude que
    # le message part vers le bon client. Anti-spam : honeypot + rate-limit IP.

    _contact_rate: dict[str, list[float]] = {}

    def _contact_rate_ok(ip: str, max_per_hour: int = 12) -> bool:
        import time
        now = time.time()
        bucket = _contact_rate.setdefault(ip, [])
        cutoff = now - 3600
        bucket[:] = [t for t in bucket if t > cutoff]
        if len(bucket) >= max_per_hour:
            return False
        bucket.append(now)
        if len(_contact_rate) > 5000:
            _contact_rate.clear()
        return True

    def _slug_from_origin(request: Request) -> str:
        import re
        src = request.headers.get("origin") or request.headers.get("referer") or ""
        m = re.search(r"https?://([a-z0-9-]+)\.pixel-pros\.fr", src, re.I)
        if m:
            s = m.group(1).lower()
            if s not in ("www", "api", "app"):
                return s
        return ""

    @app.post("/api/pixelpros/contact")
    async def pixelpros_contact(request: Request):
        """Reçoit un message du formulaire de contact d'un site client et le
        relaie par mail au client (destinataire résolu via le slug)."""
        ip = (request.client.host if request.client else "?") or "?"
        try:
            form = await request.form()
        except Exception:
            form = {}

        def _f(key: str) -> str:
            v = form.get(key) if form else None
            return str(v).strip() if v is not None else ""

        slug = _f("slug")
        name = _f("name")
        email = _f("email")
        message = _f("message")
        honey = _f("website")  # champ piège anti-bot (invisible dans la page)

        accept = (request.headers.get("accept") or "").lower()
        wants_json = "application/json" in accept

        def _esc(s: str) -> str:
            return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;"))

        def _reply(ok: bool, msg: str, status: int = 200):
            code = 200 if ok else status
            if wants_json:
                return JSONResponse(status_code=code, content={"ok": ok, "message": msg})
            if ok:
                html = (
                    "<!doctype html><html lang=\"fr\"><meta charset=\"utf-8\">"
                    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                    "<title>Message envoyé</title>"
                    "<div style=\"font-family:system-ui,-apple-system,sans-serif;max-width:520px;"
                    "margin:14vh auto;text-align:center;padding:0 22px;color:#0b0d1a;\">"
                    "<div style=\"width:66px;height:66px;border-radius:50%;background:#22c55e;"
                    "color:#fff;font-size:36px;line-height:66px;margin:0 auto 20px;\">✓</div>"
                    "<h1 style=\"font-size:23px;margin:0 0 10px;\">Message envoyé&nbsp;!</h1>"
                    "<p style=\"opacity:.72;font-size:16px;line-height:1.5;\">Merci, on a bien reçu "
                    "ton message. On te répond très vite.</p>"
                    "<p style=\"margin-top:26px;\"><a href=\"javascript:history.back()\" "
                    "style=\"color:#2563eb;font-weight:700;text-decoration:none;\">← Retour au site</a></p>"
                    "</div>"
                )
                return HTMLResponse(content=html, status_code=200)
            return HTMLResponse(
                content="<!doctype html><meta charset=\"utf-8\"><div style=\"font-family:"
                        "system-ui,sans-serif;max-width:520px;margin:14vh auto;text-align:center;"
                        "padding:0 22px;\"><p>" + _esc(msg) + "</p>"
                        "<p><a href=\"javascript:history.back()\">← Retour</a></p></div>",
                status_code=code,
            )

        # Bot : honeypot rempli → on fait semblant d'accepter, sans rien envoyer.
        if honey:
            return _reply(True, "Merci !")
        if not _contact_rate_ok(ip):
            return _reply(False, "Trop de messages d'affilée. Réessaie dans un moment.", status=429)
        if not name or not email or "@" not in email or "." not in email.split("@")[-1] or not message:
            return _reply(False, "Merci d'indiquer ton prénom, un email valide et un message.", status=400)
        if len(name) > 200 or len(email) > 320 or len(message) > 5000:
            return _reply(False, "Un des champs est trop long.", status=400)

        if not slug:
            slug = _slug_from_origin(request)

        try:
            from ..integrations.pixelpros import repo as r, mailer as m
            intake = r.get_intake_by_slug(slug) if slug else None
            ok, info = m.send_contact_message(
                intake, slug=slug, visitor_name=name,
                visitor_email=email, visitor_message=message,
            )
            if not ok:
                logger.warning("pixelpros.contact: envoi KO (slug=%s) : %s", slug, info)
                return _reply(False, "L'envoi n'a pas marché, réessaie dans un instant.", status=502)
            logger.info("pixelpros.contact: message relayé (slug=%s) : %s", slug, info)
            return _reply(True, "Message envoyé")
        except Exception:
            logger.exception("pixelpros.contact a échoué")
            return _reply(False, "L'envoi n'a pas marché, réessaie dans un instant.", status=500)

    @app.post("/api/pixelpros/contact_studio")
    async def pixelpros_contact_studio(request: Request):
        """Message reçu via le formulaire de contact de pixel-pros.fr LUI-MÊME
        (le site vitrine, pas un site client). On prévient l'équipe Pixel Pros
        par mail + notification push. Le message est, en parallèle, déjà
        enregistré dans le Pipeline côté Supabase (RPC pp_create_contact
        appelée depuis le site) — donc même si ce relais échoue, rien n'est
        perdu."""
        ip = (request.client.host if request.client else "?") or "?"
        payload: dict = {}
        try:
            payload = await request.json()
        except Exception:
            try:
                form = await request.form()
                payload = {k: form.get(k) for k in form} if form else {}
            except Exception:
                payload = {}

        def _g(key: str) -> str:
            v = payload.get(key) if isinstance(payload, dict) else None
            return str(v).strip() if v is not None else ""

        name = _g("name")
        email = _g("email")
        phone = _g("phone")
        message = _g("message")
        page_source = _g("page_source")
        honey = _g("website")  # honeypot anti-bot

        if honey:
            return JSONResponse(content={"ok": True})  # bot : on fait semblant
        if not _contact_rate_ok(ip):
            return JSONResponse(status_code=429, content={"ok": False, "error": "rate_limited"})
        if not name or not email or "@" not in email or not message:
            return JSONResponse(status_code=400, content={"ok": False, "error": "invalid"})
        if len(name) > 200 or len(email) > 320 or len(message) > 5000 or len(phone) > 60:
            return JSONResponse(status_code=400, content={"ok": False, "error": "too_long"})

        sent_mail = False
        try:
            from ..integrations.pixelpros import mailer as m
            ok, info = m.send_studio_contact(
                name=name, email=email, phone=phone,
                message=message, page_source=page_source,
            )
            sent_mail = bool(ok)
            if not ok:
                logger.warning("pixelpros.contact_studio mail KO : %s", info)
        except Exception:
            logger.exception("pixelpros.contact_studio mail a échoué")

        # Notification push (best-effort) — Jordan pilote Pixel Pros.
        try:
            from .push import send_push
            preview = (message[:90] + "…") if len(message) > 90 else message
            send_push(
                f"📬 Message de {name}", preview,
                user_id="jordan", priority="normal",
                tag="contact", tag_group="contact", url="/",
                extra_data={"type": "pp_contact"},
            )
        except Exception as exc:
            logger.debug("pixelpros.contact_studio push KO : %s", exc)

        return JSONResponse(content={"ok": True, "mailed": sent_mail})

    # ---------------- Static files (UI) ----------------

    if UI_DIR.exists():
        # Sert /assets, /scripts, /styles via StaticFiles
        for sub in ("assets", "scripts", "styles"):
            sub_dir = UI_DIR / sub
            if sub_dir.exists():
                app.mount(f"/{sub}", StaticFiles(directory=str(sub_dir)), name=sub)

        @app.get("/")
        async def index(request: Request):
            # Pas connecté → page de login
            cookie = request.cookies.get(tcauth.COOKIE_NAME)
            if not tcauth.read_session_cookie(cookie):
                return RedirectResponse(url="/login.html", status_code=302)
            return FileResponse(str(UI_DIR / "index.html"))

        # Catch-all pour les fichiers à la racine de ui/
        @app.get("/{filename:path}")
        async def static_root(filename: str) -> FileResponse:
            # Un GET /api/<méthode inconnue> retombe ici : réponse JSON claire
            # plutôt qu'un 404 fichier trompeur.
            if filename.startswith("api/"):
                return JSONResponse(
                    status_code=404,
                    content={"ok": False, "error": "Cette méthode n'existe pas (ou pas encore) sur ce serveur."},
                )
            # Confinement : ne JAMAIS servir un fichier hors du dossier ui/
            # (bloque les chemins du type ../../api.py, même percent-encodés).
            try:
                target = (UI_DIR / filename).resolve()
                ui_root = UI_DIR.resolve()
            except (OSError, ValueError):
                raise HTTPException(status_code=404, detail="Not found")
            if ui_root not in target.parents:
                raise HTTPException(status_code=404, detail="Not found")
            if target.is_file():
                return FileResponse(str(target))
            # Fallback SPA-style : rediriger vers index pour routes non trouvées
            raise HTTPException(status_code=404, detail="Not found")
    else:
        logger.warning("UI dir introuvable : %s", UI_DIR)

    return app


def _try_refresh_supabase() -> bool:
    """Refresh la session Supabase une fois. Renvoie True si OK."""
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return False
        if getattr(c, "service_mode", False):
            # Mode service_role : l'accès base n'expire jamais, rien à faire.
            return True
        if not c.is_authenticated:
            return False
        ok = c.refresh_session()
        if ok:
            logger.info("Session Supabase rafraîchie (token renouvelé).")
        else:
            logger.warning(
                "Refresh Supabase ÉCHOUÉ — le token va expirer. "
                "Ajoute SUPABASE_SERVICE_ROLE_KEY à l'environnement du serveur "
                "pour un accès permanent sans session."
            )
        return ok
    except Exception as exc:
        logger.debug("_try_refresh_supabase: %s", exc)
        return False


def _start_supabase_refresh_thread(interval_sec: int = 1800) -> None:
    """Démarre un thread daemon qui refresh Supabase toutes les 30 min.

    Le thread se termine automatiquement avec le process (daemon=True).
    """
    def loop():
        while True:
            try:
                time.sleep(interval_sec)
                _try_refresh_supabase()
            except Exception as exc:
                logger.debug("refresh thread: %s", exc)

    t = threading.Thread(target=loop, name="supabase-refresh", daemon=True)
    t.start()
    logger.info("Thread auto-refresh Supabase démarré (toutes les %d s).", interval_sec)


def _start_keepwarm_thread(interval_sec: int = 180) -> None:
    """Garde le site Pixel Pros « chaud » depuis l'Europe.

    Sans trafic, le routage des sous-domaines clients (edge function Netlify)
    et le cache CDN s'endorment : la 1re visite suivante met ~1,6 s à répondre
    (LCP mobile dans le rouge côté Google, qui teste toujours à froid). Un ping
    toutes les 3 min depuis ce serveur — situé en Europe, comme les vrais
    visiteurs — réchauffe la bonne « porte » et supprime ce délai. Daemon,
    échecs silencieux : ne casse jamais le serveur. Demande Jordan 18/06/2026.
    """
    pages = (
        "https://pixel-pros.fr/",
        "https://pixel-pros.fr/configurer",
    )

    def loop():
        import requests
        time.sleep(25)  # laisse le boot se terminer avant le 1er ping
        while True:
            for url in pages:
                try:
                    requests.get(
                        url, timeout=15,
                        headers={"User-Agent": "TriskellKeepWarm/1.0"},
                    )
                except Exception as exc:
                    logger.debug("keepwarm %s : %s", url, exc)
            time.sleep(interval_sec)

    t = threading.Thread(target=loop, name="pixelpros-keepwarm", daemon=True)
    t.start()
    logger.info("Réchauffeur Pixel Pros démarré (ping toutes les %d s).",
                interval_sec)


def _start_server_heartbeat_thread() -> None:
    """Battement de cœur serveur : toutes les 5 min dans shared_settings.

    Les robots qui tournent hors du serveur (app desktop) le consultent
    pour s'effacer pendant que le serveur est vivant.
    """
    def loop():
        from ..integrations import server_presence
        while True:
            try:
                from triskell_core.db import get_client, SupabaseNotConfigured
                try:
                    c = get_client()
                except SupabaseNotConfigured:
                    c = None
                if c is not None and c.is_authenticated:
                    server_presence.beat(c)
            except Exception as exc:
                logger.debug("heartbeat thread : %s", exc)
            time.sleep(server_presence.HEARTBEAT_INTERVAL_SEC)

    t = threading.Thread(target=loop, name="server-heartbeat", daemon=True)
    t.start()
    logger.info("Battement de cœur serveur démarré (toutes les 5 min).")


def _start_watchdog_thread(api_instance) -> None:
    """Chien de garde : vérifie l'état des robots toutes les 30 min et
    pousse une notification si l'un d'eux est en panne ou muet."""
    def loop():
        from ..integrations import worker_watchdog as wd
        time.sleep(wd.BOOT_DELAY_SEC)  # laisse les robots faire un passage
        while True:
            try:
                res = wd.check_and_alert(api_instance)
                if res.get("alerted") or res.get("recovered"):
                    logger.info("Watchdog : %s", res)
            except Exception as exc:
                logger.warning("watchdog thread : %s", exc)
            time.sleep(wd.CHECK_INTERVAL_SEC)

    t = threading.Thread(target=loop, name="worker-watchdog", daemon=True)
    t.start()
    logger.info("Chien de garde des robots démarré (passage toutes les 30 min).")


def _start_brain_reminders_thread(interval_sec: int = 300) -> None:
    """Démarre un thread daemon qui parcourt les rappels Brain échus
    et pousse une notification push, toutes les 5 min par défaut."""
    def loop():
        # Petit délai initial pour laisser le serveur finir son boot
        time.sleep(60)
        while True:
            try:
                from ..integrations import brain
                res = brain.process_reminders()
                if res.get("sent"):
                    logger.info("Brain reminders : %d envoyés (sur %d échus)",
                                res.get("sent", 0), res.get("checked", 0))
            except Exception as exc:
                logger.debug("brain reminders thread: %s", exc)
            time.sleep(interval_sec)

    t = threading.Thread(target=loop, name="brain-reminders", daemon=True)
    t.start()
    logger.info("Thread rappels Brain démarré (toutes les %d s).", interval_sec)


def _register_route(app: FastAPI, name: str, method) -> None:
    """Enregistre une route POST /api/<name> qui appelle method(payload)."""
    sig = inspect.signature(method)
    # Méthodes Api : soit aucun arg, soit un seul arg (payload dict / dict|None)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    takes_payload = len(params) >= 1

    from starlette.concurrency import run_in_threadpool

    async def handler(request: Request) -> JSONResponse:
        try:
            payload: Any = None
            # Lit le body seulement si la méthode attend un payload
            if takes_payload:
                try:
                    raw = await request.body()
                    payload = (await request.json()) if raw else None
                except Exception:
                    payload = None
            # La méthode Api est SYNCHRONE et peut être longue (versement de
            # milliers de prospects, rendu Playwright…). On l'exécute dans le
            # threadpool au lieu de la boucle événementielle : sinon un seul
            # appel lent gèle TOUT le serveur (une requête à la fois, y
            # compris /api/_health → healthcheck Docker en échec → 503).
            if takes_payload:
                result = await run_in_threadpool(method, payload)
            else:
                result = await run_in_threadpool(method)
            return JSONResponse(content=result if result is not None else {"ok": True})
        except Exception as exc:
            logger.exception("API method %s failed", name)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": f"{type(exc).__name__}: {exc}"},
            )

    handler.__name__ = f"api_{name}"
    app.post(f"/api/{name}", name=f"api_{name}")(handler)


# Instance par défaut pour `uvicorn triskell_command.web.http_server:app`
app = create_app()
