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
import logging
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
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

    # CORS — permissif en dev. À restreindre quand on déploie public.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------------- Middleware d'auth ----------------
    # Bloque toutes les routes /api/* sauf celles dans PUBLIC_API_PATHS,
    # tant qu'aucun cookie de session valide n'est présent.

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
        return await call_next(request)

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
        response.set_cookie(
            key=tcauth.COOKIE_NAME,
            value=cookie_value,
            max_age=tcauth.COOKIE_MAX_AGE,
            httponly=True,
            secure=False,  # Sera passé à True en prod via env (cf. Phase 3.3)
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

    @app.get("/api/_methods")
    async def list_methods() -> dict:
        """Liste les méthodes API disponibles (utile pour debug front)."""
        names = [n for n, m in inspect.getmembers(api_instance, inspect.ismethod)
                 if not n.startswith("_")]
        return {"ok": True, "methods": sorted(names)}

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
            target = UI_DIR / filename
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
        if not c.is_authenticated:
            return False
        ok = c.refresh_session()
        if ok:
            logger.info("Session Supabase rafraîchie (token renouvelé).")
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


def _register_route(app: FastAPI, name: str, method) -> None:
    """Enregistre une route POST /api/<name> qui appelle method(payload)."""
    sig = inspect.signature(method)
    # Méthodes Api : soit aucun arg, soit un seul arg (payload dict / dict|None)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    takes_payload = len(params) >= 1

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
            # Appel synchrone (Api est sync)
            if takes_payload:
                result = method(payload)
            else:
                result = method()
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
