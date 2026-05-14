"""Site Agent — pipeline auto qui crée un site à partir d'un brief.

S'appuie sur `claude-agent-sdk` (Anthropic). Le SDK utilise soit :
  - le binaire `claude` local de l'utilisateur (consomme l'abonnement Claude Pro/Max)
  - une clé API Anthropic en environnement (facturée au token)

L'agent dispose des outils Claude Code natifs (Read, Write, Edit, Bash, Glob,
Grep, WebSearch, WebFetch) pour réaliser la pipeline complète :
copier le template, chercher des infos, adapter les fichiers, builder, etc.

Le streaming des messages permet d'afficher la progression en temps réel
dans la zone log de la vue Studio.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Callable

logger = logging.getLogger("triskell.command.site_agent")


class SiteAgentError(RuntimeError):
    """Erreur de pipeline (SDK manquant, clé absente, etc.)."""


def is_available() -> bool:
    """Retourne True si claude-agent-sdk est importable."""
    try:
        import claude_agent_sdk  # noqa: F401
        return True
    except ImportError:
        return False


def _format_message(message) -> str:
    """Convertit un message du SDK en ligne de log lisible.

    Le SDK retourne des messages typés (AssistantMessage, UserMessage,
    SystemMessage…). On extrait le texte ou la description d'outil.
    """
    cls = type(message).__name__
    # Outils en cours
    if hasattr(message, "content"):
        parts = []
        for block in (message.content or []):
            btype = type(block).__name__
            if btype == "TextBlock":
                txt = getattr(block, "text", "").strip()
                if txt:
                    parts.append(txt[:400] + ("…" if len(txt) > 400 else ""))
            elif btype == "ToolUseBlock":
                tool = getattr(block, "name", "?")
                inp = getattr(block, "input", {}) or {}
                if tool in ("Write", "Edit"):
                    fp = inp.get("file_path", "?")
                    parts.append(f"🛠 {tool} → {fp}")
                elif tool == "Bash":
                    cmd = (inp.get("command") or "")[:120]
                    parts.append(f"⚙ Bash → {cmd}")
                elif tool in ("Read", "Glob", "Grep"):
                    target = inp.get("file_path") or inp.get("pattern") or inp.get("path") or "?"
                    parts.append(f"🔍 {tool} → {target}")
                elif tool in ("WebSearch", "WebFetch"):
                    q = inp.get("query") or inp.get("url") or "?"
                    parts.append(f"🌐 {tool} → {q[:80]}")
                else:
                    parts.append(f"🛠 {tool}")
            elif btype == "ToolResultBlock":
                # Trop verbeux pour le log standard
                continue
        if parts:
            return "\n".join(parts)
    # Résultats finaux et messages système
    if cls == "ResultMessage":
        return f"✓ Pipeline terminée (durée {getattr(message, 'duration_ms', '?')} ms)"
    return ""


async def _run_agent_async(
    prompt: str,
    cwd: Path,
    on_log: Callable[[str], None],
) -> None:
    """Boucle async : appelle l'agent et streame les messages vers on_log."""
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions  # type: ignore
    except ImportError as exc:
        raise SiteAgentError(
            "claude-agent-sdk n'est pas installé. Lance : pip install claude-agent-sdk"
        ) from exc

    options = ClaudeAgentOptions(
        cwd=str(cwd),
        # Tous les outils natifs Claude Code — l'agent a un accès total
        # au système de fichiers + bash + web depuis le dossier brief.
        allowed_tools=[
            "Read", "Write", "Edit", "Bash", "Glob", "Grep",
            "WebSearch", "WebFetch",
        ],
        # Mode permissif : pas de prompt utilisateur entre chaque action.
        permission_mode="acceptEdits",
    )

    on_log("▶ Pipeline démarrée — Claude Agent SDK")
    on_log(f"  Dossier de travail : {cwd}")
    on_log("")

    async for message in query(prompt=prompt, options=options):
        line = _format_message(message)
        if line:
            on_log(line)


def run_in_background(
    prompt: str,
    cwd: Path,
    on_log: Callable[[str], None],
    on_done: Callable[[bool, str | None], None] | None = None,
) -> threading.Thread:
    """Lance la pipeline dans un thread daemon.

    `on_log(line)` est appelé à chaque message reçu (déjà thread-safe via
    `Tk.after(0, ...)` dans la vue).
    `on_done(success, error)` est appelé à la fin (succès ou échec).
    """

    def _runner():
        try:
            asyncio.run(_run_agent_async(prompt, cwd, on_log))
            if on_done:
                on_done(True, None)
        except SiteAgentError as exc:
            on_log(f"✗ {exc}")
            if on_done:
                on_done(False, str(exc))
        except Exception as exc:
            logger.exception("Site agent pipeline failed")
            on_log(f"✗ Échec : {exc}")
            if on_done:
                on_done(False, str(exc))

    thread = threading.Thread(target=_runner, daemon=True, name="SiteAgent")
    thread.start()
    return thread
