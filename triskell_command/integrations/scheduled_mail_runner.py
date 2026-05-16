"""Worker qui envoie les mails programmés à l'heure dite.

Vérifie toutes les 30 secondes la file de mails programmés
(~/.triskell-command/scheduled_mails.json). Quand l'heure de scheduled_at
est passée et que le mail est encore en status 'pending', l'envoie via SMTP
puis marque comme 'sent' (ou 'failed' + error en cas d'erreur).

Schéma d'une entrée :
    {
      "id": "sm-XXX",
      "user_id": "jordan",
      "account_id": "primary",
      "to": "client@exemple.fr",
      "subject": "…",
      "body": "…",
      "body_html": "…",
      "in_reply_to": "",
      "attachments": [{filename, content_b64, content_type, inline, cid}, ...],
      "scheduled_at": "2026-05-17T09:00:00+02:00",   ISO 8601 avec fuseau
      "status": "pending" | "sent" | "failed" | "cancelled",
      "created_at": "...",
      "sent_at": "..."?,
      "error": "..."?
    }

Le fichier est lu/écrit avec un lock file pour éviter les races thread.
"""
from __future__ import annotations

import base64
import json
import logging
import smtplib
import ssl
import threading
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 30


def _store_path() -> Path:
    base = Path.home() / ".triskell-command"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.debug("store dir: %s", exc)
    return base / "scheduled_mails.json"


_lock = threading.Lock()
_worker_thread: threading.Thread | None = None


def _read_all() -> list[dict]:
    p = _store_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.warning("lecture %s : %s", p, exc)
        return []


def _write_all(items: list[dict]) -> bool:
    p = _store_path()
    try:
        p.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        return True
    except Exception as exc:
        logger.warning("écriture %s : %s", p, exc)
        return False


def add(item: dict) -> dict | None:
    """Ajoute un mail à la file. Renvoie l'entrée enregistrée (avec id)."""
    with _lock:
        items = _read_all()
        entry = dict(item)
        entry.setdefault("id", "sm-" + uuid4().hex[:12])
        entry.setdefault("status", "pending")
        entry.setdefault("created_at",
                         datetime.now(timezone.utc).isoformat(timespec="seconds"))
        items.append(entry)
        if not _write_all(items):
            return None
        # On masque les attachments dans le retour (pour pas alourdir)
        light = dict(entry)
        if "attachments" in light:
            light["attachments_count"] = len(light.get("attachments") or [])
            del light["attachments"]
        return light


def list_pending(include_done: bool = False) -> list[dict]:
    """Renvoie la liste des mails programmés (sans le body_html ni les
    attachments, pour rester léger côté frontend)."""
    with _lock:
        items = _read_all()
    out = []
    for it in items:
        if not include_done and it.get("status") != "pending":
            continue
        light = {k: v for k, v in it.items()
                 if k not in ("attachments", "body_html", "body")}
        light["body_preview"] = (it.get("body") or "")[:280]
        light["attachments_count"] = len(it.get("attachments") or [])
        out.append(light)
    # Tri : d'abord ceux à venir, par scheduled_at croissant
    out.sort(key=lambda x: x.get("scheduled_at", ""))
    return out


def cancel(mail_id: str) -> bool:
    """Annule un mail programmé (s'il est encore pending)."""
    with _lock:
        items = _read_all()
        changed = False
        for it in items:
            if it.get("id") == mail_id and it.get("status") == "pending":
                it["status"] = "cancelled"
                it["cancelled_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                changed = True
                break
        if changed:
            _write_all(items)
        return changed


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        # Python 3.11+ supporte les Z aussi
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _send_now(entry: dict, get_account) -> tuple[bool, str | None]:
    """Envoie un mail via SMTP. Renvoie (ok, error_msg).

    `get_account` est une fonction qui prend account_id et renvoie le
    dict du compte (smtp_host, smtp_user, smtp_password, from_email,
    from_name). Permet de découpler de l'Api singleton.
    """
    try:
        acc = get_account(entry.get("account_id") or "primary") or {}
        smtp_host = acc.get("smtp_host", "")
        smtp_port = int(acc.get("smtp_port") or 587)
        smtp_user = acc.get("smtp_user", "")
        smtp_password = acc.get("smtp_password", "")
        from_email = acc.get("from_email", "")
        from_name = acc.get("from_name", "") or from_email
        for k, v in (("smtp_host", smtp_host), ("smtp_user", smtp_user),
                     ("smtp_password", smtp_password), ("from_email", from_email)):
            if not v:
                return False, f"Config SMTP incomplète (manque {k})"

        msg = EmailMessage()
        msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
        msg["To"] = entry.get("to") or ""
        msg["Subject"] = entry.get("subject") or ""
        msg["Date"] = formatdate(localtime=True)
        domain = from_email.split("@", 1)[1] if "@" in from_email else "triskell-studio.fr"
        msg["Message-ID"] = make_msgid(domain=domain)
        msg["Reply-To"] = from_email
        in_reply_to = (entry.get("in_reply_to") or "").strip()
        if in_reply_to:
            irt = in_reply_to if in_reply_to.startswith("<") else f"<{in_reply_to}>"
            msg["In-Reply-To"] = irt
            msg["References"] = irt

        body = entry.get("body") or " "
        body_html = entry.get("body_html") or ""
        msg.set_content(body)
        if body_html:
            msg.add_alternative(body_html, subtype="html")

        # Pièces jointes (même logique que mail_send dans api.py)
        attachments = entry.get("attachments") or []
        if attachments:
            inline_atts = [a for a in attachments
                           if isinstance(a, dict) and a.get("inline") and a.get("cid")]
            other_atts = [a for a in attachments
                          if isinstance(a, dict) and not (a.get("inline") and a.get("cid"))]
            if inline_atts and body_html:
                html_part = None
                try:
                    for part in msg.iter_parts():
                        if part.get_content_type() == "text/html":
                            html_part = part
                            break
                except Exception:
                    html_part = None
                if html_part is not None:
                    for att in inline_atts:
                        try:
                            data = base64.b64decode(att.get("content_b64") or "")
                        except Exception:
                            continue
                        if not data:
                            continue
                        ctype = (att.get("content_type") or "image/png")
                        maintype, _, subtype = ctype.partition("/")
                        if not subtype:
                            maintype, subtype = "image", "png"
                        html_part.add_related(
                            data, maintype=maintype, subtype=subtype,
                            cid=f"<{att.get('cid')}>",
                            filename=att.get("filename") or "image",
                        )
            for att in other_atts:
                try:
                    data = base64.b64decode(att.get("content_b64") or "")
                except Exception:
                    continue
                if not data:
                    continue
                ctype = (att.get("content_type") or "application/octet-stream")
                maintype, _, subtype = ctype.partition("/")
                if not subtype:
                    maintype, subtype = "application", "octet-stream"
                msg.add_attachment(
                    data, maintype=maintype, subtype=subtype,
                    filename=att.get("filename") or "fichier",
                )

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
        return True, None
    except Exception as exc:
        logger.exception("send scheduled mail failed")
        return False, f"{type(exc).__name__}: {exc}"


def _tick(get_account) -> int:
    """Un tour de boucle : check les mails à envoyer et les envoie.
    Renvoie le nombre de mails envoyés ce tour."""
    sent = 0
    now = datetime.now(timezone.utc)
    with _lock:
        items = _read_all()
    changed = False
    for it in items:
        if it.get("status") != "pending":
            continue
        sched = _parse_dt(it.get("scheduled_at") or "")
        if sched is None:
            continue
        if sched.tzinfo is None:
            sched = sched.replace(tzinfo=timezone.utc)
        if sched > now:
            continue
        ok, err = _send_now(it, get_account)
        if ok:
            it["status"] = "sent"
            it["sent_at"] = now.isoformat(timespec="seconds")
            sent += 1
        else:
            it["status"] = "failed"
            it["error"] = err
            it["failed_at"] = now.isoformat(timespec="seconds")
        changed = True
    if changed:
        with _lock:
            _write_all(items)
    return sent


def start_worker(app_state, get_account_resolver=None):
    """Lance le thread background. Idempotent.

    `get_account_resolver` : fonction qui prend account_id et renvoie le
    dict du compte. Par défaut, on utilise shared_secrets.get_account_by_id.
    """
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return

    if get_account_resolver is None:
        try:
            from . import shared_secrets
            from ..web.api import Api  # pour accéder à _supabase()

            def get_account(account_id: str):
                # Fait son propre client Supabase à chaque appel (cheap)
                try:
                    api = Api()
                    api._app_state = app_state
                    client = api._supabase()
                    return shared_secrets.get_account_by_id(
                        account_id, client=client, app_state=app_state)
                except Exception as exc:
                    logger.debug("get_account: %s", exc)
                    return None
        except Exception:
            def get_account(account_id: str):
                return None
    else:
        get_account = get_account_resolver

    def loop():
        logger.info("scheduled_mail_runner: thread démarré (poll %ds)",
                    POLL_INTERVAL_SECONDS)
        while True:
            try:
                _tick(get_account)
            except Exception as exc:
                logger.exception("scheduled_mail_runner tick error: %s", exc)
            time.sleep(POLL_INTERVAL_SECONDS)

    _worker_thread = threading.Thread(
        target=loop, name="scheduled_mail_runner", daemon=True)
    _worker_thread.start()
