"""Helper centralisé pour logger un envoi de mail dans `email_history`.

Les pipelines de produit (Pixel Pros, Phare, …) envoient leurs mails
transactionnels directement via `smtp_sender.send_email`, qui ne touche
pas la table `email_history` (alimentée par l'API `mail_send`). Résultat :
ces envois n'apparaissent jamais dans la vue « Mails envoyés ».

`log_sent_pipeline_mail` est l'helper unique à appeler après un envoi
réussi pour rendre le mail visible dans la vue. Robuste : si le log
échoue, on ne propage pas l'erreur (l'envoi reste considéré comme
réussi côté pipeline).
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_BODY_HTML_MAX = 80_000


def _get_supabase():
    """Renvoie un client Supabase authentifié, ou None."""
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None
    try:
        c = get_client()
    except SupabaseNotConfigured:
        return None
    if not getattr(c, "is_authenticated", False):
        return None
    return c


def log_sent_pipeline_mail(
    *,
    to: str,
    subject: str,
    body: str,
    body_html: str = "",
    from_email: str = "",
    account_id: str = "",
    message_id: str = "",
    source: str = "",
    cc: Iterable[str] | None = None,
    bcc: Iterable[str] | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> bool:
    """Insère une ligne `kind='email_sent'` dans `email_history`.

    `source` identifie l'origine (`pixelpros_paid_mail`, `phare_alert`, …).
    Renvoie True si l'insertion a réussi.
    """
    c = _get_supabase()
    if c is None:
        return False
    try:
        sb = c.raw
        cc_list = list(cc) if cc else []
        bcc_list = list(bcc) if bcc else []
        to_list = [a.strip() for a in (to or "").split(",") if a.strip()]
        all_recipients: list[str] = []
        seen: set[str] = set()
        for addr in (to_list + cc_list + bcc_list):
            key = addr.strip().lower()
            if key and key not in seen:
                seen.add(key)
                all_recipients.append(addr.strip())
        if not all_recipients:
            all_recipients = [to]

        ws_id = None
        try:
            ws_id = c._current_workspace_id()
        except Exception:
            pass

        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        body_html_log = (body_html or "")[:_BODY_HTML_MAX]

        rows = []
        for recipient in all_recipients:
            extra_log: dict[str, Any] = {
                "to": recipient,
                "to_all": ", ".join(all_recipients),
                "recipients_count": len(all_recipients),
                "from": from_email,
                "account_id": account_id,
                "has_html": bool(body_html),
                "body_html": body_html_log,
                "attachments_meta": [],
                "attachments_count": 0,
                "inline_images_count": 0,
                "manual_reply": False,
                "in_reply_to": "",
                "source": source or "pipeline",
            }
            if extra_meta:
                # Merge sans écraser les clés clés (to, from, ...)
                for k, v in extra_meta.items():
                    extra_log.setdefault(k, v)
            row = {
                "kind": "email_sent",
                "ts": now_iso,
                "subject": (subject or "")[:200],
                "body": (body or "")[:5000],
                "message_id": message_id or "",
                "extra": extra_log,
                "created_by": getattr(c, "user_id", None),
            }
            if ws_id:
                row["workspace_id"] = ws_id
            rows.append(row)
        sb.table("email_history").insert(rows).execute()
        return True
    except Exception as exc:
        logger.warning("email_history_log.log_sent_pipeline_mail: %s", exc)
        return False
