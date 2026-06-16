"""Listes noires (DNSBL) du domaine d'envoi — vérification HONNÊTE.

Pourquoi ce module n'utilise PAS une simple requête publique
------------------------------------------------------------
Spamhaus, SURBL & co REFUSENT les requêtes qui passent par les gros résolveurs
publics (Cloudflare, Google) : ils répondent alors « 127.255.255.254 » (requête
bloquée) quelle que soit la réalité. Si on interprétait ça naïvement, on
afficherait « pas sur liste noire » à tort — exactement la fausse affirmation
qu'on bannit.

La méthode fiable et gratuite : le **DQS Spamhaus** (Data Query Service). Jordan
crée un compte gratuit, récupère une clé personnelle, et on interroge alors
`<domaine>.<clé>.dbl.dq.spamhaus.net`. Avec la clé, la réponse est vraie quel
que soit le résolveur. Sans clé → on ne ment pas : on affiche « à activer ».

On vérifie le DOMAINE (liste DBL), pas l'IP d'envoi : l'IP appartient à IONOS
ou Google (mutualisée), donc la tester renseignerait sur l'hébergeur, pas sur
nous. Le domaine, lui, est bien le nôtre.

La lecture du code de réponse (127.0.1.x = signalé, 127.255.255.x = clé en
défaut, NXDOMAIN = propre) est PURE et testée sans réseau (interpret_dbl).
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

DOH_ENDPOINTS = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
)
DQS_ZONE = "dbl.dq.spamhaus.net"   # liste des domaines (Domain Block List)

# Codes retour DBL (127.0.1.x) → motif en français clair.
_DBL_CATEGORIES = {
    "127.0.1.2": "domaine de spam",
    "127.0.1.4": "hameçonnage (phishing)",
    "127.0.1.5": "logiciel malveillant",
    "127.0.1.6": "réseau de machines infectées (botnet)",
    "127.0.1.102": "domaine légitime détourné par des spammeurs",
    "127.0.1.103": "redirecteur détourné",
    "127.0.1.104": "domaine légitime détourné (hameçonnage)",
    "127.0.1.105": "domaine légitime détourné (malware)",
    "127.0.1.106": "domaine légitime détourné (botnet)",
}
# Codes « ce n'est PAS un signalement » : la clé/le service est en défaut.
_DBL_ERRORS = {
    "127.255.255.252": "requête mal formée",
    "127.255.255.253": "configuration incorrecte",
    "127.255.255.254": "requête refusée (clé absente ou résolveur public)",
    "127.255.255.255": "trop de requêtes (quota dépassé)",
}


def interpret_dbl(status: int, ips: list[str]) -> dict:
    """Lecture PURE de la réponse DNS d'une liste noire de domaines.

    Renvoie {state, detail} où state ∈ {listed, clean, inconclusive} :
    - listed       : le domaine est réellement signalé (avec le motif) ;
    - clean        : le domaine n'est sur AUCUNE des listes vérifiées ;
    - inconclusive : impossible de conclure (clé en défaut, réseau, code inconnu)
                     → on n'affirme RIEN.
    """
    # NXDOMAIN (3) = pas dans la liste = propre.
    if status == 3:
        return {"state": "clean", "detail": "pas sur la liste des domaines signalés"}
    if status != 0:
        return {"state": "inconclusive",
                "detail": f"réponse DNS inattendue (code {status})"}
    ips = [str(i).strip() for i in (ips or []) if str(i).strip()]
    if not ips:
        # NOERROR sans réponse = pas de signalement.
        return {"state": "clean", "detail": "aucun signalement"}
    # Codes d'erreur du service (clé) → surtout pas « propre » ni « signalé ».
    for ip in ips:
        if ip in _DBL_ERRORS:
            return {"state": "inconclusive",
                    "detail": "Spamhaus : " + _DBL_ERRORS[ip]}
    # Codes de signalement réels.
    motifs = [_DBL_CATEGORIES.get(ip) for ip in ips if ip.startswith("127.0.1.")]
    motifs = [m for m in motifs if m]
    if motifs:
        return {"state": "listed", "detail": "signalé — " + ", ".join(motifs)}
    if any(ip.startswith("127.0.1.") for ip in ips):
        return {"state": "listed", "detail": "signalé par Spamhaus"}
    return {"state": "inconclusive",
            "detail": "réponse non reconnue (" + ", ".join(ips) + ")"}


def _doh_a(name: str, timeout: float = 6.0) -> Optional[tuple[int, list[str]]]:
    """Résout un enregistrement A via DNS-over-HTTPS. Renvoie (status, [ip]),
    ou None si le réseau a échoué (à distinguer d'un NXDOMAIN propre)."""
    import requests
    for endpoint in DOH_ENDPOINTS:
        try:
            r = requests.get(endpoint, params={"name": name, "type": "A"},
                             headers={"accept": "application/dns-json"},
                             timeout=timeout)
            if r.status_code != 200:
                continue
            data = r.json() or {}
            status = int(data.get("Status", -1))
            ips = [(a.get("data") or "").strip()
                   for a in (data.get("Answer") or [])
                   if a.get("type") == 1]   # type 1 = A
            return status, [i for i in ips if i]
        except Exception as exc:
            logger.debug("DoH A %s via %s : %s", name, endpoint, exc)
    return None


def check_domain(domain: str, dqs_key: str) -> dict:
    """Vérifie si un domaine est sur la liste noire des domaines (Spamhaus DBL)
    via le DQS (clé personnelle). Réseau.

    Renvoie {ok, state, detail, source}. Sans clé → state 'unconfigured'
    (« à activer »), jamais une fausse affirmation."""
    domain = (domain or "").strip().lower().lstrip("@")
    key = (dqs_key or "").strip()
    if not domain or "." not in domain:
        return {"ok": False, "state": "inconclusive", "detail": "domaine invalide"}
    if not key:
        return {"ok": True, "state": "unconfigured",
                "detail": "clé Spamhaus gratuite non configurée",
                "source": "spamhaus_dbl"}
    query = f"{domain}.{key}.{DQS_ZONE}"
    res = _doh_a(query)
    if res is None:
        return {"ok": True, "state": "inconclusive",
                "detail": "service de liste noire injoignable",
                "source": "spamhaus_dbl"}
    status, ips = res
    out = interpret_dbl(status, ips)
    out.update({"ok": True, "source": "spamhaus_dbl"})
    return out
