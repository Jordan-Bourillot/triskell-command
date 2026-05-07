"""Morning mailer — formate le digest morning_digest en mail HTML/texte
et l'envoie aux destinataires configurés via SMTP.

Usage :
- depuis un script CLI : `python -m triskell_command.integrations.morning_mailer`
- depuis Windows Task Scheduler à 8 h :
    schtasks /create /tn "Triskell Matinale" /tr "python -m triskell_command.integrations.morning_mailer" /sc daily /st 08:00

Si le SMTP n'est pas configuré dans shared_settings ou settings.json,
on ne fait rien (no-op silencieux + exit 0).

Destinataires : shared_settings 'morning_digest_recipients' (list de strings)
ou fallback à smtp_cfg.from_email (Jordan se l'envoie à lui-même).
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Setup imports robustes pour les deux modes : python -m OU script direct
HERE = Path(__file__).resolve()
PKG_ROOT = HERE.parent.parent.parent  # …/Triskell Command/
CORE_ROOT = PKG_ROOT.parent / "Triskell Core"
for p in (str(CORE_ROOT), str(PKG_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

logger = logging.getLogger(__name__)


def _client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None
    try:
        c = get_client()
    except SupabaseNotConfigured:
        return None
    if not c.is_authenticated:
        return None
    return c


def _resolve_smtp_config(client) -> Optional[dict]:
    sb = client.get_shared_setting("smtp_config", None)
    if sb and isinstance(sb, dict):
        host = (sb.get("smtp_host") or "").strip()
        user = (sb.get("smtp_user") or "").strip()
        password = sb.get("smtp_password") or ""
        from_email = sb.get("from_email") or ""
        if host and user and password and from_email:
            return {
                "smtp_host": host,
                "smtp_port": int(sb.get("smtp_port") or 587),
                "smtp_user": user,
                "smtp_password": password,
                "from_email": from_email,
                "from_name": sb.get("from_name") or "",
            }
    # Fallback : settings.json local
    try:
        from triskell_command.state import load_settings
        s = load_settings()
        out = (s or {}).get("outreach", {}) or {}
        host = (out.get("smtp_host") or "").strip()
        user = (out.get("smtp_user") or "").strip()
        password = out.get("smtp_password") or ""
        from_email = out.get("from_email") or ""
        if host and user and password and from_email:
            return {
                "smtp_host": host,
                "smtp_port": int(out.get("smtp_port") or 587),
                "smtp_user": user,
                "smtp_password": password,
                "from_email": from_email,
                "from_name": out.get("from_name") or "",
            }
    except Exception:
        pass
    return None


def _resolve_recipients(client, smtp_cfg: dict) -> list[str]:
    raw = client.get_shared_setting("morning_digest_recipients", []) or []
    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if str(x).strip()]
        if out:
            return out
    # Fallback : Jordan s'envoie le digest à lui-même
    return [smtp_cfg["from_email"]]


def render_digest_text(digest: dict) -> str:
    s = digest.get("sent", {}) or {}
    r = digest.get("replies", {}) or {}
    q = digest.get("queue", {}) or {}
    a = digest.get("alerts", {}) or {}
    rb = r.get("yesterday_breakdown", {}) or {}
    lines = [
        f"== Triskell — Matinale du {digest.get('today', '?')} ==",
        "",
        f"Hier ({digest.get('yesterday', '?')})",
        f"  Envoyés       : {s.get('yesterday', 0)}",
        f"  Réponses      : {r.get('yesterday_total', 0)}",
        f"   ↳ intéressés : {rb.get('interested', 0)}",
        f"   ↳ pas now    : {rb.get('not_now', 0)}",
        f"   ↳ refus      : {rb.get('no', 0)}",
        f"   ↳ unsub      : {rb.get('unsubscribe', 0)}",
        f"   ↳ à trier    : {rb.get('unknown', 0)}",
        "",
        "À traiter aujourd'hui",
        f"  Réponses positives à valider : {q.get('replies_unhandled_interested', 0)}",
        f"  Réponses non triées          : {max(0, q.get('replies_unhandled_total', 0) - q.get('replies_unhandled_interested', 0))}",
        f"  Drafts prospect en attente   : {q.get('drafts_prospect_pending', 0)}",
        f"  Drafts Convoi en attente     : {q.get('drafts_convoy_pending', 0)}",
        "",
        f"Aujourd'hui (en cours)",
        f"  Envoyés depuis 00:00 : {s.get('today', 0)}",
        f"  Réponses depuis 00:00: {r.get('today_total', 0)}",
        f"  7 derniers jours     : {s.get('last_7d', 0)} envoyés",
        "",
    ]
    n_failed_y = a.get("convoy_failed_yesterday", 0)
    n_failed_t = a.get("convoy_failed_today", 0)
    if n_failed_y or n_failed_t:
        lines.append("Anomalies")
        if n_failed_y:
            lines.append(f"  Convoi en échec hier : {n_failed_y}")
        if n_failed_t:
            lines.append(f"  Convoi en échec auj. : {n_failed_t}")
        lines.append("")
    lines.append("Ouvre Triskell Command → Matinale pour cliquer dessus.")
    return "\n".join(lines)


def render_digest_html(digest: dict) -> str:
    s = digest.get("sent", {}) or {}
    r = digest.get("replies", {}) or {}
    q = digest.get("queue", {}) or {}
    a = digest.get("alerts", {}) or {}
    rb = r.get("yesterday_breakdown", {}) or {}

    def kpi(label: str, value: Any, *, accent: str = "") -> str:
        col = "color: #16a34a;" if accent == "good" else (
            "color: #dc2626;" if accent == "bad" else "color: #1f2937;"
        )
        return (
            f"<td style='padding:14px;border:1px solid #e5e7eb;border-radius:6px;background:#fafafa;'>"
            f"<div style='font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;'>{label}</div>"
            f"<div style='font-size:28px;font-weight:700;{col}margin-top:2px;'>{value}</div>"
            f"</td>"
        )

    interested_y = rb.get("interested", 0)
    sent_y = s.get("yesterday", 0)
    replies_y = r.get("yesterday_total", 0)
    unsub_y = rb.get("unsubscribe", 0)

    return f"""
<html><body style="font-family: 'Inter', system-ui, sans-serif; color: #1f2937; max-width: 720px; margin: 0 auto; padding: 24px;">
  <div style="border-bottom: 2px solid #C9A032; padding-bottom: 12px; margin-bottom: 24px;">
    <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #6b7280;">Triskell · Matinale</div>
    <h1 style="margin: 4px 0 0 0; font-size: 28px; font-weight: 700;">{digest.get('today', '?')}</h1>
  </div>

  <h2 style="font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; color: #6b7280; margin: 0 0 12px 0;">Hier ({digest.get('yesterday', '?')})</h2>
  <table style="width: 100%; border-spacing: 8px; border-collapse: separate;">
    <tr>
      {kpi('Envoyés', sent_y)}
      {kpi('Réponses', replies_y)}
      {kpi('Intéressés', interested_y, accent='good' if interested_y > 0 else '')}
      {kpi('Désinscriptions', unsub_y, accent='bad' if unsub_y > 2 else '')}
    </tr>
  </table>

  <h2 style="font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; color: #6b7280; margin: 32px 0 12px 0;">À traiter</h2>
  <ul style="line-height: 1.7;">
    <li><strong>{q.get('replies_unhandled_interested', 0)}</strong> réponse(s) intéressée(s) à valider</li>
    <li><strong>{max(0, q.get('replies_unhandled_total', 0) - q.get('replies_unhandled_interested', 0))}</strong> autre(s) réponse(s) à trier</li>
    <li><strong>{q.get('drafts_prospect_pending', 0)}</strong> draft(s) prospect en attente</li>
    <li><strong>{q.get('drafts_convoy_pending', 0)}</strong> draft(s) Convoi en attente</li>
  </ul>

  {f'''<h2 style="font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; color: #dc2626; margin: 32px 0 12px 0;">Anomalies</h2>
  <ul style="line-height: 1.7; color: #dc2626;">
    {f"<li>{a.get('convoy_failed_yesterday', 0)} envoi(s) Convoi en échec hier</li>" if a.get('convoy_failed_yesterday') else ''}
    {f"<li>{a.get('convoy_failed_today', 0)} envoi(s) Convoi en échec aujourd'hui</li>" if a.get('convoy_failed_today') else ''}
  </ul>''' if (a.get('convoy_failed_yesterday') or a.get('convoy_failed_today')) else ''}

  <p style="color: #6b7280; font-size: 13px; margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb;">
    Ouvre Triskell Command → Matinale pour cliquer.
  </p>
</body></html>
"""


def send_morning_mail() -> dict:
    """Calcule le digest et l'envoie. Renvoie {sent, error}."""
    out = {"sent": 0, "error": ""}

    client = _client()
    if client is None:
        out["error"] = "supabase_unavailable"
        return out

    smtp_cfg = _resolve_smtp_config(client)
    if not smtp_cfg:
        out["error"] = "smtp_not_configured"
        return out

    try:
        from triskell_command.integrations import morning_digest
    except ImportError as exc:
        out["error"] = f"import_digest: {exc}"
        return out

    digest = morning_digest.compute_digest()
    if not digest.get("ok"):
        out["error"] = f"digest: {digest.get('error', 'unknown')}"
        return out

    text = render_digest_text(digest)
    html = render_digest_html(digest)
    subject = f"Triskell Matinale — {digest.get('today', datetime.now().date().isoformat())}"

    try:
        from email.message import EmailMessage
        from email.utils import formatdate, make_msgid
        import smtplib

        recipients = _resolve_recipients(client, smtp_cfg)
        for rcp in recipients:
            msg = EmailMessage()
            from_name = smtp_cfg.get("from_name", "")
            from_email = smtp_cfg["from_email"]
            msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
            msg["To"] = rcp
            msg["Subject"] = subject
            msg["Date"] = formatdate(localtime=True)
            domain = from_email.split("@", 1)[1]
            msg["Message-ID"] = make_msgid(domain=domain)
            msg.set_content(text)
            msg.add_alternative(html, subtype="html")

            host = smtp_cfg["smtp_host"]
            port = int(smtp_cfg["smtp_port"])
            user = smtp_cfg["smtp_user"]
            password = smtp_cfg["smtp_password"]
            if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=30) as s:
                    s.login(user, password)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=30) as s:
                    s.ehlo()
                    s.starttls()
                    s.ehlo()
                    s.login(user, password)
                    s.send_message(msg)
            out["sent"] += 1
    except Exception as exc:
        out["error"] = f"smtp: {exc}"
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)s | %(message)s")
    res = send_morning_mail()
    if res.get("sent"):
        logger.info("Matinale envoyée à %d destinataire(s).", res["sent"])
        return 0
    logger.warning("Matinale non envoyée : %s", res.get("error") or "?")
    # Exit 0 quand même — c'est un cron, on ne veut pas spammer les alertes
    # quand Supabase ou SMTP n'est pas configuré.
    return 0


if __name__ == "__main__":
    sys.exit(main())
