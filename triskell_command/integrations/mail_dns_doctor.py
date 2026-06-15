"""Docteur DNS délivrabilité — vérifie SPF / DKIM / DMARC du domaine d'envoi.

Pourquoi : la capacité à atteindre une boîte de réception repose sur trois
« tampons » DNS qui prouvent que le mail vient bien de chez nous :

  - SPF    : liste des serveurs autorisés à envoyer pour le domaine.
  - DKIM   : signature cryptographique posée par le serveur d'envoi.
  - DMARC  : la consigne donnée aux destinataires quand SPF/DKIM échouent.

Sans eux, Gmail/Yahoo classent de plus en plus en spam, voire refusent.
Ce module interroge le DNS via DNS-over-HTTPS (Cloudflare puis Google en
secours) — aucune dépendance nouvelle, la lib `requests` suffit.

La partie analyse est PURE (injectable/testable) ; la partie réseau est
isolée dans `_doh_txt`.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DOH_ENDPOINTS = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
)

# Sélecteurs DKIM les plus courants. « google » en premier : Google Workspace
# signe avec google._domainkey (nos domaines d'envoi de prospection) ; IONOS
# utilise s1-ionos / s2-ionos.
DKIM_SELECTORS = ("google", "s1-ionos", "s2-ionos", "default", "s1", "s2",
                  "mail", "k1", "selector1", "selector2")


def _doh_txt(name: str, timeout: float = 6.0) -> list[str]:
    """Résout les enregistrements TXT d'un nom via DNS-over-HTTPS."""
    import requests
    for endpoint in DOH_ENDPOINTS:
        try:
            r = requests.get(
                endpoint,
                params={"name": name, "type": "TXT"},
                headers={"accept": "application/dns-json"},
                timeout=timeout,
            )
            if r.status_code != 200:
                continue
            data = r.json() or {}
            out = []
            for ans in data.get("Answer") or []:
                txt = (ans.get("data") or "").strip()
                # Les TXT arrivent entre guillemets, parfois fragmentés
                txt = txt.replace('" "', "").strip('"')
                if txt:
                    out.append(txt)
            return out
        except Exception as exc:
            logger.debug("DoH %s pour %s : %s", endpoint, name, exc)
    return []


def _doh_any(name: str, rtype: str, timeout: float = 6.0) -> bool:
    """True si le nom a au moins un enregistrement du type donné."""
    import requests
    for endpoint in DOH_ENDPOINTS:
        try:
            r = requests.get(
                endpoint,
                params={"name": name, "type": rtype},
                headers={"accept": "application/dns-json"},
                timeout=timeout,
            )
            if r.status_code != 200:
                continue
            data = r.json() or {}
            if data.get("Answer"):
                return True
        except Exception as exc:
            logger.debug("DoH %s %s %s : %s", endpoint, rtype, name, exc)
    return False


def analyze_records(domain: str, *, spf_txts: list[str],
                    dmarc_txts: list[str],
                    dkim_found_selector: str | None,
                    has_mx: bool) -> dict:
    """Analyse PURE des enregistrements → verdicts en français clair."""
    checks: list[dict] = []

    spf = next((t for t in spf_txts if t.lower().startswith("v=spf1")), "")
    if spf:
        too_soft = " ?all" in spf or spf.rstrip().endswith("?all")
        checks.append({
            "id": "spf", "label": "SPF", "ok": True,
            "detail": spf[:120],
            "advice": ("Politique '?all' trop laxiste — préfère '~all'."
                       if too_soft else ""),
        })
    else:
        checks.append({
            "id": "spf", "label": "SPF", "ok": False,
            "detail": "aucun enregistrement v=spf1 trouvé",
            "advice": ("Ajoute un TXT SPF sur le domaine (chez IONOS : "
                       "inclure leur include officiel)."),
        })

    dmarc = next((t for t in dmarc_txts if t.lower().startswith("v=dmarc1")), "")
    if dmarc:
        weak = "p=none" in dmarc.lower()
        checks.append({
            "id": "dmarc", "label": "DMARC", "ok": True,
            "detail": dmarc[:120],
            "advice": ("p=none : passe à p=quarantine quand tout est stable."
                       if weak else ""),
        })
    else:
        checks.append({
            "id": "dmarc", "label": "DMARC", "ok": False,
            "detail": "aucun enregistrement _dmarc trouvé",
            "advice": ("Ajoute un TXT sur _dmarc." + domain +
                       " : v=DMARC1; p=none; rua=mailto:contact@" + domain),
        })

    if dkim_found_selector:
        checks.append({
            "id": "dkim", "label": "DKIM", "ok": True,
            "detail": f"signature trouvée (sélecteur {dkim_found_selector})",
            "advice": "",
        })
    else:
        checks.append({
            "id": "dkim", "label": "DKIM", "ok": False,
            "detail": "aucun sélecteur courant trouvé",
            "advice": ("Active DKIM chez l'hébergeur mail (IONOS : menu "
                       "E-mail → DKIM). NB : un sélecteur exotique peut "
                       "exister sans qu'on le détecte ici."),
        })

    checks.append({
        "id": "mx", "label": "Réception (MX)", "ok": has_mx,
        "detail": ("le domaine sait recevoir des mails" if has_mx
                   else "aucun enregistrement MX — les réponses ne peuvent "
                        "pas revenir !"),
        "advice": "" if has_mx else "Vérifie la zone DNS du domaine.",
    })

    score = sum(1 for c in checks if c["ok"])
    return {
        "ok": True,
        "domain": domain,
        "checks": checks,
        "score": f"{score}/{len(checks)}",
        "all_good": score == len(checks),
    }


def check_domain(domain: str,
                 txt_resolver: Optional[Callable] = None,
                 any_resolver: Optional[Callable] = None) -> dict:
    """Vérifie la délivrabilité DNS d'un domaine d'envoi."""
    domain = (domain or "").strip().lower().lstrip("@")
    if not domain or "." not in domain:
        return {"ok": False, "error": "domaine invalide"}
    txt = txt_resolver or _doh_txt
    has = any_resolver or _doh_any

    spf_txts = txt(domain)
    dmarc_txts = txt(f"_dmarc.{domain}")
    dkim_selector = None
    for sel in DKIM_SELECTORS:
        name = f"{sel}._domainkey.{domain}"
        # DKIM peut être un TXT direct ou un CNAME vers l'hébergeur
        if txt(name) or has(name, "CNAME"):
            dkim_selector = sel
            break
    has_mx = has(domain, "MX")

    return analyze_records(domain, spf_txts=spf_txts, dmarc_txts=dmarc_txts,
                           dkim_found_selector=dkim_selector, has_mx=has_mx)
