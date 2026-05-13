"""Envoi mensuel automatique des rapports SEO clients (Le Phare).

DESTINATION FINALE :
    Triskell\\triskell-command\\triskell_command\\integrations\\phare\\client_report_sender.py

LIVRÉ depuis la session PC secondaire 2026-05-11 (PC principal en panne).
Quand le PC principal est de retour, déposer ce fichier à l'emplacement
ci-dessus et lancer la migration de scheduler (voir scheduler_patch.md
dans le même dossier de session).

Pipeline :
  1. Liste les clients en cadence `auto_mensuel` (table phare_clients).
  2. Filtre ceux dont le site est encore actif.
  3. Skip ceux déjà servis ce mois civil (idempotence sur
     `last_report_sent_at`).
  4. Génère le rapport via client_report.generate_for_client.
  5. Envoie le PDF en pièce jointe via l'API Resend, corps HTML = email_html
     produit par client_report.
  6. Sur succès : repo.mark_report_sent(client_id, pdf_path).
  7. Sur échec : retry max 3 avec backoff exponentiel (5s, 30s, 2min),
     log warning, alerte Discord si échec final.

Sujet : "[RankUs Studio] Votre rapport SEO de {mois} {année}".

Expéditeur Resend : `from` configurable via
shared_settings.phare_config.client_report_from (défaut
"Triskell Studio <rapports@rankus-studio.fr>"). Tant que le domaine
rankus-studio.fr n'est pas validé chez Resend, fallback sur
"Triskell Studio <onboarding@resend.dev>" + log d'alerte.

Variables de config attendues (shared_settings.phare_config) :
  - resend_api_key                : str, clé API Resend
  - client_report_from            : str, expéditeur (fallback fourni)
  - client_report_reply_to        : str, optionnel, ex "jordan@triskell-studio.fr"
  - client_report_discord_webhook : str, optionnel, alerte Discord sur échec final
  - client_report_dry_run         : bool, optionnel, simule sans envoyer

Usage CLI :
    python -m triskell_command.integrations.phare.client_report_sender
        [--dry-run] [--client-id <uuid>] [--month YYYY-MM]
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

from . import client_report, repo

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"
DEFAULT_FROM = "Triskell Studio <onboarding@resend.dev>"
RETRY_DELAYS_SECONDS = (5, 30, 120)


# =====================================================================
# Helpers
# =====================================================================
def _french_month(d: date) -> str:
    months = ["janvier", "février", "mars", "avril", "mai", "juin",
              "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    return f"{months[d.month - 1]} {d.year}"


def _previous_month_first_day(today: Optional[date] = None) -> date:
    today = today or date.today()
    first_this_month = today.replace(day=1)
    return (first_this_month - timedelta(days=1)).replace(day=1)


def _already_sent_this_month(client: dict, target_month: date) -> bool:
    """True si `last_report_sent_at` du client tombe dans le mois cible
    ou plus tard. Garantit l'idempotence si le worker est relancé.
    """
    last = client.get("last_report_sent_at")
    if not last:
        return False
    try:
        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except Exception:
        return False
    return dt.date() >= target_month


def _post_discord(webhook_url: str, content: str) -> None:
    """Best-effort, ne casse jamais."""
    if not webhook_url:
        return
    try:
        requests.post(webhook_url, json={"content": content}, timeout=8)
    except Exception as exc:
        logger.debug("discord webhook failed: %s", exc)


# =====================================================================
# Resend API call
# =====================================================================
def _send_via_resend(
    *,
    api_key: str,
    sender: str,
    to: str,
    subject: str,
    html: str,
    pdf_path: Path,
    pdf_filename: str,
    reply_to: str = "",
) -> dict:
    """Appelle l'API Resend POST /emails avec PDF en pièce jointe.

    Retourne le payload de réponse (incluant `id`). Lève en cas d'erreur HTTP.
    """
    payload = {
        "from": sender,
        "to": [to],
        "subject": subject,
        "html": html,
        "attachments": [{
            "filename": pdf_filename,
            "content": base64.b64encode(pdf_path.read_bytes()).decode("ascii"),
        }],
    }
    if reply_to:
        payload["reply_to"] = reply_to

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.post(RESEND_ENDPOINT, headers=headers,
                         data=json.dumps(payload), timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Resend {resp.status_code}: {resp.text[:400]}")
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


# =====================================================================
# Single-client send (with retries)
# =====================================================================
def send_for_client(
    client: dict,
    *,
    target_month: date,
    cfg: dict,
    app_state=None,
    dry_run: bool = False,
) -> dict:
    """Génère + envoie le rapport pour UN client.

    Retourne un dict de statut : {ok, client_id, status, attempts, error,
    resend_id, pdf_path, dry_run}.
    """
    site_id = client.get("site_id")
    client_id = client.get("id")
    contact_email = (client.get("contact_email") or "").strip()
    contact_name = client.get("contact_name") or ""

    result_base = {
        "client_id": client_id,
        "contact_email": contact_email,
        "contact_name": contact_name,
        "target_month": target_month.isoformat(),
        "attempts": 0,
        "dry_run": dry_run,
    }

    if not contact_email:
        return {**result_base, "ok": False, "status": "skipped",
                "error": "contact_email manquant"}

    # Site actif ?
    site = repo.get_site(site_id) if site_id else None
    if not site or not site.get("is_active", True):
        return {**result_base, "ok": False, "status": "skipped",
                "error": "site inactif ou introuvable"}

    # Génération du rapport (HTML + PDF + email_html)
    gen = client_report.generate_for_client(
        site_id=site_id, client_id=client_id,
        target_month=target_month, app_state=app_state,
    )
    if not gen.get("ok"):
        return {**result_base, "ok": False, "status": "generation_failed",
                "error": gen.get("error") or "génération échouée"}

    pdf_path_str = gen.get("pdf_path")
    if not pdf_path_str:
        return {**result_base, "ok": False, "status": "no_pdf",
                "error": "PDF non généré (WeasyPrint indisponible ?)"}

    pdf_path = Path(pdf_path_str)
    if not pdf_path.exists():
        return {**result_base, "ok": False, "status": "no_pdf",
                "error": f"PDF introuvable à {pdf_path}"}

    subject = (f"[RankUs Studio] Votre rapport SEO de "
               f"{_french_month(target_month)}")
    site_name_slug = (site.get("name") or site.get("domain") or "site")\
        .replace(" ", "-").lower()
    pdf_filename = (f"rapport-seo-{site_name_slug}-"
                    f"{target_month.strftime('%Y-%m')}.pdf")

    if dry_run or cfg.get("client_report_dry_run"):
        logger.info("[DRY-RUN] %s → %s (%s, %d bytes)",
                    contact_email, subject, pdf_filename,
                    pdf_path.stat().st_size)
        return {**result_base, "ok": True, "status": "dry_run",
                "pdf_path": str(pdf_path)}

    api_key = (cfg.get("resend_api_key") or "").strip()
    if not api_key:
        return {**result_base, "ok": False, "status": "no_api_key",
                "error": "resend_api_key absente de phare_config"}

    sender = (cfg.get("client_report_from") or DEFAULT_FROM).strip()
    reply_to = (cfg.get("client_report_reply_to") or "").strip()

    # Envoi avec retry
    last_error = ""
    for attempt in range(1, len(RETRY_DELAYS_SECONDS) + 1 + 1):
        result_base["attempts"] = attempt
        try:
            resend_resp = _send_via_resend(
                api_key=api_key, sender=sender, to=contact_email,
                subject=subject, html=gen.get("email_html") or "",
                pdf_path=pdf_path, pdf_filename=pdf_filename,
                reply_to=reply_to,
            )
            resend_id = resend_resp.get("id", "")
            repo.mark_report_sent(client_id, str(pdf_path))
            logger.info("Rapport envoyé à %s (resend_id=%s, attempt=%d)",
                        contact_email, resend_id, attempt)
            return {**result_base, "ok": True, "status": "sent",
                    "resend_id": resend_id, "pdf_path": str(pdf_path)}
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Envoi rapport client %s tentative %d échouée : %s",
                           client_id, attempt, exc)
            if attempt - 1 < len(RETRY_DELAYS_SECONDS):
                time.sleep(RETRY_DELAYS_SECONDS[attempt - 1])

    # Échec final
    webhook = cfg.get("client_report_discord_webhook") or ""
    if webhook:
        _post_discord(
            webhook,
            f":rotating_light: Rapport SEO non envoyé à {contact_email} "
            f"({contact_name}) après {result_base['attempts']} tentatives.\n"
            f"Erreur : `{last_error[:300]}`"
        )
    return {**result_base, "ok": False, "status": "send_failed",
            "error": last_error, "pdf_path": str(pdf_path)}


# =====================================================================
# Batch entry point
# =====================================================================
def send_pending_reports(
    app_state=None,
    *,
    target_month: Optional[date] = None,
    only_client_id: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Boucle sur tous les clients `auto_mensuel` et envoie les rapports
    du mois cible (défaut : mois précédent).

    Idempotent : si `last_report_sent_at` >= target_month, le client est
    skippé.

    Retourne un récap : {sent, skipped, failed, results: [...]}
    """
    target_month = target_month or _previous_month_first_day()
    cfg = repo.get_config() or {}

    if only_client_id:
        sb = repo._sb()
        clients = []
        if sb is not None:
            try:
                clients = (sb.table("phare_clients").select("*")
                           .eq("id", only_client_id).limit(1)
                           .execute().data) or []
            except Exception as exc:
                logger.warning("client_report_sender: lookup client failed: %s", exc)
    else:
        clients = repo.list_clients_with_cadence("auto_mensuel")

    results = []
    sent = skipped = failed = 0

    for client in clients:
        if not only_client_id and _already_sent_this_month(client, target_month):
            results.append({
                "client_id": client.get("id"),
                "contact_email": client.get("contact_email"),
                "ok": True, "status": "already_sent",
                "target_month": target_month.isoformat(),
            })
            skipped += 1
            continue

        r = send_for_client(client, target_month=target_month, cfg=cfg,
                            app_state=app_state, dry_run=dry_run)
        results.append(r)
        if r.get("ok") and r.get("status") in ("sent", "dry_run"):
            sent += 1
        elif r.get("status") == "skipped":
            skipped += 1
        else:
            failed += 1

    summary = {
        "ok": failed == 0,
        "target_month": target_month.isoformat(),
        "total": len(clients),
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "results": results,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
    }
    logger.info("client_report_sender summary: %s sent / %s skipped / %s failed "
                "(month=%s, dry_run=%s)",
                sent, skipped, failed, target_month.isoformat(), dry_run)
    return summary


# =====================================================================
# CLI
# =====================================================================
def _parse_month(s: str) -> date:
    return datetime.strptime(s, "%Y-%m").date().replace(day=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Simule sans appeler Resend.")
    parser.add_argument("--client-id", default=None,
                        help="Limite l'envoi à un seul client (UUID).")
    parser.add_argument("--month", default=None, type=_parse_month,
                        help="Mois cible YYYY-MM (défaut : mois précédent).")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    summary = send_pending_reports(
        target_month=args.month,
        only_client_id=args.client_id,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
