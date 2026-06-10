"""Contrôle qualité des prospects — rien de faux n'entre dans la base.

Toute fournée de prospects passe ici AVANT d'être versée dans la base
partagée. On écarte :

  - les fiches SANS email (inutilisables pour la prospection),
  - les emails invalides ou fabriqués (filtre central de triskell_core :
    fragments d'URL, domaines plateforme/factices, préfixe www., etc.),
  - les noms fantômes (test, demo, asdf, lorem…),
  - les doublons À L'INTÉRIEUR de la fournée (même email deux fois).

Le rapport renvoyé dit exactement ce qui a été gardé et pourquoi le
reste a sauté — affiché tel quel dans la mission. Les doublons contre
la base elle-même sont gérés plus loin par l'upsert dédoublonné + les
verrous SQL (jamais deux fois le même email, jamais un client).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Noms qui sentent la donnée de test / le placeholder, pas un vrai prospect.
PLACEHOLDER_NAME_PATTERNS = re.compile(
    r"^\s*(test|tests|demo|démo|exemple|example|sample|asdf+|azerty|qwerty|"
    r"lorem(\s+ipsum)?|todo|xxx+|aaa+|n/?a|null|none|inconnu|unknown|"
    r"sans\s+nom)\s*$",
    re.IGNORECASE,
)


def _clean_email(email: str) -> str | None:
    """Valide/normalise un email via le filtre central. Fallback minimal
    (syntaxe seule) si triskell_core est absent."""
    e = (email or "").strip().lower()
    if not e or "@" not in e:
        return None
    try:
        from triskell_core.prospect.enrichers.email_filter import clean_email
        return clean_email(e)
    except ImportError:
        return e if re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", e) else None


def validate_prospect(p: dict, *, email_key: str = "email",
                      name_key: str = "nom") -> dict:
    """Vérifie UNE fiche. Renvoie {ok, email, issues: [codes]}.

    Codes d'écart : no_email | bad_email | placeholder_name
    (une fiche au nom fantôme mais email valide est gardée si le nom
    est le SEUL souci d'un champ non-bloquant ? Non — nom fantôme =
    donnée fabriquée, on écarte : on ne démarche pas « M. Test ».)
    """
    issues: list[str] = []
    raw_email = (p.get(email_key) or "").strip()
    email = _clean_email(raw_email) if raw_email else None
    if not raw_email:
        issues.append("no_email")
    elif not email:
        issues.append("bad_email")
    name = (p.get(name_key) or p.get("name") or "").strip()
    if name and PLACEHOLDER_NAME_PATTERNS.match(name):
        issues.append("placeholder_name")
    return {"ok": not issues, "email": email, "issues": issues}


def filter_for_push(prospects: list[dict], *, email_key: str = "email",
                    name_key: str = "nom") -> tuple[list[dict], dict]:
    """Filtre une fournée avant versement. Renvoie (gardés, rapport).

    Le rapport : {total, kept, dropped: {no_email, bad_email,
    placeholder_name, duplicate_in_batch}, samples_dropped: [..5 max]}.
    """
    report = {
        "total": len(prospects or []),
        "kept": 0,
        "dropped": {"no_email": 0, "bad_email": 0,
                    "placeholder_name": 0, "duplicate_in_batch": 0},
        "samples_dropped": [],
    }
    kept: list[dict] = []
    seen_emails: set[str] = set()
    for p in (prospects or []):
        v = validate_prospect(p, email_key=email_key, name_key=name_key)
        if not v["ok"]:
            for code in v["issues"]:
                if code in report["dropped"]:
                    report["dropped"][code] += 1
            if len(report["samples_dropped"]) < 5:
                report["samples_dropped"].append({
                    "nom": (p.get(name_key) or p.get("name") or "")[:60],
                    "email": (p.get(email_key) or "")[:80],
                    "raison": v["issues"][0],
                })
            continue
        if v["email"] in seen_emails:
            report["dropped"]["duplicate_in_batch"] += 1
            continue
        seen_emails.add(v["email"])
        kept.append(p)
    report["kept"] = len(kept)
    return kept, report


REASON_LABELS_FR = {
    "no_email": "sans email",
    "bad_email": "email invalide/fabriqué",
    "placeholder_name": "nom fantôme (test/démo…)",
    "duplicate_in_batch": "doublon dans la fournée",
}


def report_to_french(report: dict) -> str:
    """Résumé humain du rapport, pour les missions et les journaux."""
    if not report:
        return ""
    d = report.get("dropped") or {}
    parts = [f"{report.get('kept', 0)}/{report.get('total', 0)} gardés"]
    for code, n in d.items():
        if n:
            parts.append(f"{n} {REASON_LABELS_FR.get(code, code)}")
    return " · ".join(parts)
