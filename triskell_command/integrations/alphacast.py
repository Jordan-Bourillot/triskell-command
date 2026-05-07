"""Client API du service Réseaux (AlphaCast).

Wrapper minimal autour de l'API HTTP exposée localement par le projet
`Réseaux/` (par défaut http://localhost:3001). Utilise `requests` (déjà
dépendance de Triskell Command).

Toutes les fonctions :
  - prennent `base_url` + `token` en argument
  - sont synchrones et lèvent `AlphaCastError` en cas d'échec
  - timeout court (5-15s) — on est sur localhost en dev
  - pas d'état partagé : chaque appel est indépendant

L'orchestration (caching, threading, UI feedback) se fait dans la vue
appelante (`views/publish.py`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)


# ─── Erreurs ─────────────────────────────────────────────────────────


class AlphaCastError(Exception):
    """Erreur de communication ou métier avec l'API AlphaCast."""

    def __init__(self, message: str, *, status_code: int | None = None,
                 payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


# ─── Modèles légers ──────────────────────────────────────────────────


@dataclass
class Draft:
    """Représentation simplifiée d'un draft AlphaCast pour l'UI."""

    id: str
    platform: str       # linkedin | x | bluesky | youtube | instagram | ...
    content: str        # texte du post
    status: str         # pending_review | approved | published | failed
    created_at: str     # ISO timestamp
    workspace_id: str | None = None
    source_material_id: str | None = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_api(cls, d: dict) -> "Draft":
        return cls(
            id=str(d.get("id") or d.get("_id") or ""),
            platform=str(d.get("platform") or ""),
            content=str(d.get("content") or d.get("body") or ""),
            status=str(d.get("status") or "pending_review"),
            created_at=str(d.get("createdAt") or d.get("created_at") or ""),
            workspace_id=d.get("workspaceId") or d.get("workspace_id"),
            source_material_id=d.get("sourceMaterialId") or d.get("source_material_id"),
            metadata={k: v for k, v in d.items()
                      if k not in {"id", "_id", "platform", "content", "body", "status",
                                   "createdAt", "created_at",
                                   "workspaceId", "workspace_id",
                                   "sourceMaterialId", "source_material_id"}},
        )


# ─── HTTP helpers ────────────────────────────────────────────────────


def _normalize_base(base_url: str) -> str:
    return (base_url or "http://localhost:3001").rstrip("/")


def _auth_headers(token: str) -> dict[str, str]:
    if not token:
        raise AlphaCastError("JWT manquant — Réglages > Service AlphaCast.")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _raise_for_response(r: requests.Response, action: str) -> None:
    if r.status_code >= 400:
        try:
            payload = r.json()
        except Exception:
            payload = r.text
        msg = f"{action} → HTTP {r.status_code}"
        if isinstance(payload, dict):
            err = payload.get("error") or payload.get("message")
            if err:
                msg += f" : {err}"
        raise AlphaCastError(msg, status_code=r.status_code, payload=payload)


# ─── Health & workspaces ─────────────────────────────────────────────


def health_check(base_url: str, *, timeout: float = 3.0) -> bool:
    """Renvoie True si /health répond 200, False sinon (silencieux)."""
    try:
        r = requests.get(f"{_normalize_base(base_url)}/health", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def list_workspaces(base_url: str, token: str, *, timeout: float = 5.0) -> list[dict]:
    r = requests.get(
        f"{_normalize_base(base_url)}/api/v1/workspaces",
        headers=_auth_headers(token), timeout=timeout,
    )
    _raise_for_response(r, "list_workspaces")
    data = r.json()
    if isinstance(data, dict) and "items" in data:
        return list(data["items"])
    return list(data) if isinstance(data, list) else []


# ─── Drafts (generated-posts) ────────────────────────────────────────


def list_drafts(base_url: str, token: str, *,
                status: str | None = "pending_review",
                limit: int = 50, timeout: float = 10.0) -> list[Draft]:
    """Liste les drafts. Par défaut filtre sur status=pending_review."""
    params: dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status
    r = requests.get(
        f"{_normalize_base(base_url)}/api/v1/generated-posts",
        headers=_auth_headers(token), params=params, timeout=timeout,
    )
    _raise_for_response(r, "list_drafts")
    data = r.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    return [Draft.from_api(d) for d in (items or [])]


def update_draft(base_url: str, token: str, draft_id: str,
                 *, content: str | None = None, status: str | None = None,
                 timeout: float = 10.0) -> Draft:
    """PATCH /api/v1/generated-posts/:id — édite content et/ou status."""
    body: dict[str, Any] = {}
    if content is not None:
        body["content"] = content
    if status is not None:
        body["status"] = status
    if not body:
        raise AlphaCastError("update_draft: rien à mettre à jour.")
    r = requests.patch(
        f"{_normalize_base(base_url)}/api/v1/generated-posts/{draft_id}",
        headers=_auth_headers(token), json=body, timeout=timeout,
    )
    _raise_for_response(r, "update_draft")
    return Draft.from_api(r.json())


def publish_draft(base_url: str, token: str, draft_id: str,
                  *, timeout: float = 30.0) -> dict:
    """POST /api/v1/generated-posts/:id/publish — déclenche la publication."""
    r = requests.post(
        f"{_normalize_base(base_url)}/api/v1/generated-posts/{draft_id}/publish",
        headers=_auth_headers(token), json={}, timeout=timeout,
    )
    _raise_for_response(r, "publish_draft")
    return r.json() if r.text else {"id": draft_id, "status": "queued"}


def delete_draft(base_url: str, token: str, draft_id: str,
                 *, timeout: float = 10.0) -> None:
    """Pas de DELETE explicite documenté — on PATCH status=archived."""
    update_draft(base_url, token, draft_id, status="archived", timeout=timeout)


# ─── Source materials & génération ───────────────────────────────────


def create_source_material(base_url: str, token: str, *,
                           title: str, content: str,
                           workspace_id: str | None = None,
                           tags: list[str] | None = None,
                           timeout: float = 15.0) -> dict:
    """POST /api/v1/source-materials — crée une source à partir de laquelle générer."""
    body: dict[str, Any] = {"title": title, "content": content}
    if workspace_id:
        body["workspaceId"] = workspace_id
    if tags:
        body["tags"] = tags
    r = requests.post(
        f"{_normalize_base(base_url)}/api/v1/source-materials",
        headers=_auth_headers(token), json=body, timeout=timeout,
    )
    _raise_for_response(r, "create_source_material")
    return r.json()


def generate_draft(base_url: str, token: str, *,
                   platform: str,
                   source_material_id: str | None = None,
                   content: str | None = None,
                   workspace_id: str | None = None,
                   timeout: float = 60.0) -> Draft:
    """POST /api/v1/generate — déclenche le pipeline de génération.

    Soit source_material_id (preferred — utilise la source enregistrée),
    soit content brut (mode "compose libre").
    """
    body: dict[str, Any] = {"platform": platform}
    if workspace_id:
        body["workspaceId"] = workspace_id
    if source_material_id:
        body["sourceMaterialId"] = source_material_id
    elif content:
        body["content"] = content
    else:
        raise AlphaCastError("generate_draft: source_material_id ou content requis.")
    r = requests.post(
        f"{_normalize_base(base_url)}/api/v1/generate",
        headers=_auth_headers(token), json=body, timeout=timeout,
    )
    _raise_for_response(r, "generate_draft")
    return Draft.from_api(r.json())


def generate_and_publish(base_url: str, token: str, *,
                         platform: str, content: str,
                         workspace_id: str | None = None,
                         timeout_total: float = 90.0) -> dict:
    """Compose libre : génère un draft puis le publie en chaînant.

    C'est le flow attendu par l'ancien bouton "Publier" qui faisait juste
    /api/v1/generate (bug : ça ne publiait jamais réellement).
    """
    draft = generate_draft(
        base_url, token,
        platform=platform, content=content,
        workspace_id=workspace_id,
        timeout=timeout_total / 2,
    )
    if not draft.id:
        raise AlphaCastError("generate_and_publish: draft sans id.")
    return publish_draft(base_url, token, draft.id, timeout=timeout_total / 2)


# ─── Recommendations (Phase 5) ──────────────────────────────────────


def list_recommendations(base_url: str, token: str, *,
                         workspace_id: str | None = None,
                         timeout: float = 10.0) -> list[dict]:
    """GET /api/v1/recommendations — top/weak posts + insights actionnables."""
    params: dict[str, Any] = {}
    if workspace_id:
        params["workspaceId"] = workspace_id
    r = requests.get(
        f"{_normalize_base(base_url)}/api/v1/recommendations",
        headers=_auth_headers(token), params=params, timeout=timeout,
    )
    _raise_for_response(r, "list_recommendations")
    data = r.json()
    if isinstance(data, dict) and "items" in data:
        return list(data["items"])
    return list(data) if isinstance(data, list) else []
