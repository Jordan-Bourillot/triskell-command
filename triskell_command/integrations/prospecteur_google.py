"""Prospecteur Google Places — découvre des entreprises locales via l'API
Google Places (Text Search v1) puis tente d'extraire leurs mails publics en
scrapant leur site web.

Adapté depuis le programme desktop `prospecteur-google/main.py` (Tkinter). On
réutilise l'architecture "hunt en arrière-plan" déjà en place pour le
Chasseur PME et le Chasseur Créateur : chaque recherche tourne dans un
thread daemon, persiste son état en JSON, et l'UI poll toutes les 2 secondes.

Pourquoi c'est utile :
  - Beaucoup d'entreprises locales sont sur Google Maps mais n'ont pas de
    site web → cibles idéales Triskell (vendre un site).
  - Pour celles qui en ont un, on récupère leur mail public en scrapant les
    pages habituelles (home, contact, mentions légales, à propos).

L'utilisateur peut filtrer pour ne garder que les entreprises SANS site web
(prospects "site neuf à vendre").
"""
from __future__ import annotations

import csv
import json
import logging
import os
import random
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

logger = logging.getLogger(__name__)


PROSP_DIR = Path.home() / ".triskell-command" / "prospecteur_google"
HUNTS_DIR = PROSP_DIR / "hunts"
EXPORTS_DIR = PROSP_DIR / "exports"

# SÉCURITÉ : plus de clé Google Places en dur dans le code (l'ancienne a
# fuité dans l'historique git → à révoquer côté Google). La clé vient du
# payload, de la variable d'env GOOGLE_PLACES_API_KEY, ou des Réglages.

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELDS = (
    "places.displayName,places.formattedAddress,"
    "places.internationalPhoneNumber,places.websiteUri,"
    "places.businessStatus,nextPageToken"
)

EMAIL_REGEX = r"[\w\.\-+]+@[\w\.\-]+\.\w+"

UA_WEB = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# Codes ISO acceptés pour le filtre francophone. "ALL" = on itère sur les
# principaux pays francophones (FR, BE, CH, CA, LU, MC) et on dédoublonne.
FRANCOPHONE_COUNTRIES = {
    "FR", "BE", "CH", "CA", "LU", "MC",
    "MA", "DZ", "TN", "SN", "CI",
}

# Itération "tous francophones" : on couvre les principaux marchés où Triskell
# vend ses sites. Les pays du Maghreb / Afrique francophone sont volontairement
# exclus de la boucle ALL pour ne pas exploser le quota Places.
ALL_FRANCOPHONE_ITER = ["FR", "BE", "CH", "CA", "LU", "MC"]


def _normalize_pays(pays: str | None) -> str:
    """Renvoie un code ISO valide en majuscules, ou 'FR' par défaut."""
    code = (pays or "FR").strip().upper()
    if code == "ALL":
        return "ALL"
    if code not in FRANCOPHONE_COUNTRIES:
        return "FR"
    return code

# Mails techniques / faux positifs à jeter
EMAIL_BLACKLIST = [
    "@example.", "noreply", "no-reply", "@wix.com", "@sentry",
    "@wordpress", "godaddy", "domain.com", "@sentry.io",
    "@cloudfront", ".png", ".jpg", "@google.", "@gstatic",
    "@bootstrapcdn", "@jquery", "@w3.org",
]


def ensure_dirs() -> None:
    HUNTS_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _get_api_key(payload_key: str | None = None) -> str:
    """Résout la clé Google Places : payload > env > Réglages. Vide si aucune."""
    if payload_key and payload_key.strip():
        return payload_key.strip()
    env_key = (os.environ.get("GOOGLE_PLACES_API_KEY") or "").strip()
    if env_key:
        return env_key
    try:
        import json as _json
        p = Path.home() / ".triskell-command" / "settings.json"
        if p.exists():
            d = _json.loads(p.read_text(encoding="utf-8"))
            key = (((d.get("ai") or {}).get("api_keys") or {})
                   .get("google_places") or "").strip()
            if key:
                return key
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------
@dataclass
class GoogleProspect:
    """Une entreprise trouvée via Google Places."""
    name: str
    address: str = ""
    phone: str = ""
    website: str = ""
    email: str = ""               # mail principal trouvé sur le site
    emails_extra: list[str] = field(default_factory=list)
    has_website: bool = False
    status: str = ""              # OPERATIONAL / CLOSED_TEMPORARILY / etc.

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProspectHunt:
    id: str
    label: str
    created_at: str
    status: str = "pending"   # pending / searching / enriching / done / error
    progress: int = 0          # 0-100
    log: list[str] = field(default_factory=list)
    filters: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    prospects: list[dict] = field(default_factory=list)
    error: str = ""

    @property
    def path(self) -> Path:
        return HUNTS_DIR / f"{self.id}.json"

    def save(self) -> None:
        ensure_dirs()
        self.path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Copie de secours cloud quand la chasse atteint un état final
        if self.status in ("done", "error"):
            try:
                from .hunt_cloud_backup import mirror_hunt
                mirror_hunt("prospecteur_google", asdict(self))
            except Exception:
                pass

    @classmethod
    def load(cls, hunt_id: str) -> "ProspectHunt | None":
        p = HUNTS_DIR / f"{hunt_id}.json"
        if not p.exists():
            return None
        try:
            from .hunt_zombies import reconcile_hunt_file
            data = reconcile_hunt_file(p, is_running=is_running(hunt_id))
            if not data:
                return None
            return cls(**data)
        except Exception as exc:
            logger.warning("prospect hunt.load failed %s: %s", hunt_id, exc)
            return None


# ---------------------------------------------------------------------------
# Helpers scraping site
# ---------------------------------------------------------------------------
def _scrape_site_for_emails(url: str) -> set[str]:
    """Scrape les pages habituelles d'un site pour en extraire des mails."""
    emails: set[str] = set()
    if not url:
        return emails
    if not url.startswith("http"):
        url = "https://" + url
    base = url.rstrip("/")
    pages = [
        url,
        f"{base}/contact",
        f"{base}/contact.html",
        f"{base}/contact.php",
        f"{base}/a-propos",
        f"{base}/about",
        f"{base}/mentions-legales",
    ]
    # Filtre central anti-fausses-adresses de triskell_core (même protection
    # qu'Obélisk et le Chasseur Créateur). Fallback : blacklist locale seule.
    # + has_mail_record : on ne garde QUE les adresses dont le domaine peut
    #   vraiment recevoir du courrier (enregistrement MX/A). Une adresse sur
    #   un domaine mort rebondirait et abîmerait la réputation d'envoi —
    #   demande explicite de Jordan (13/06/2026). Cache MX en mémoire process.
    try:
        from triskell_core.prospect.enrichers.email_filter import (
            clean_email, has_mail_record,
        )
    except ImportError:
        clean_email = None
        has_mail_record = None
    for page in pages:
        try:
            r = requests.get(page, headers=UA_WEB, timeout=8)
            if r.status_code == 200:
                for em in re.findall(EMAIL_REGEX, r.text):
                    em_low = em.lower()
                    if clean_email is not None:
                        em_low = clean_email(em_low) or ""
                        if not em_low:
                            continue
                    if any(b in em_low for b in EMAIL_BLACKLIST):
                        continue
                    # Vérif délivrabilité : domaine capable de recevoir du mail.
                    if has_mail_record is not None and "@" in em_low:
                        domain = em_low.split("@", 1)[1]
                        if not has_mail_record(domain):
                            continue
                    emails.add(em_low)
        except Exception:
            pass
        time.sleep(random.uniform(0.3, 0.6))
    return emails


# ---------------------------------------------------------------------------
# Orchestration : run, threads, list, export
# ---------------------------------------------------------------------------
_RUNNING: dict[str, threading.Thread] = {}


def is_running(hunt_id: str) -> bool:
    t = _RUNNING.get(hunt_id)
    return bool(t and t.is_alive())


def list_hunts(limit: int = 20) -> list[dict]:
    """Liste les chasses, en requalifiant les zombies (serveur redémarré)."""
    ensure_dirs()
    from .hunt_zombies import reconcile_hunt_file
    items: list[dict] = []
    for p in HUNTS_DIR.glob("*.json"):
        try:
            running = is_running(p.stem)
            data = reconcile_hunt_file(p, is_running=running)
            if not data:
                continue
            items.append({
                "id": data.get("id"),
                "label": data.get("label"),
                "created_at": data.get("created_at"),
                "status": data.get("status"),
                "progress": data.get("progress"),
                "error": data.get("error") or "",
                "stats": data.get("stats") or {},
                "filters": data.get("filters") or {},
                "running": running,
                "prospects_count": len(data.get("prospects") or []),
            })
        except Exception:
            continue
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items[:limit]


def _build_label(metier: str, zone: str, only_no_site: bool) -> str:
    m = (metier or "").strip() or "tous métiers"
    z = (zone or "").strip() or "France"
    suffix = "  ·  sans site" if only_no_site else ""
    return f"{m} — {z}{suffix}"


def start_hunt(metier: str, zone: str, num_results: int = 60,
               only_no_site: bool = False,
               api_key: str | None = None,
               pays: str = "FR",
               progress_cb: Callable[[ProspectHunt], None] | None = None,
               ) -> ProspectHunt:
    """Lance une chasse Google Places en arrière-plan.

    `pays` : code ISO francophone (FR par défaut). "ALL" itère sur les
    principaux pays francophones et dédoublonne les résultats.
    """
    ensure_dirs()
    if not metier or not metier.strip():
        raise ValueError("Indique un métier ou un type d'entreprise.")
    if not zone or not zone.strip():
        raise ValueError("Indique une zone géographique.")
    if not _get_api_key(api_key):
        raise ValueError(
            "Clé Google Places manquante. Ajoute-la dans Réglages → IA & "
            "clés (champ google_places), ou en variable d'environnement "
            "GOOGLE_PLACES_API_KEY sur le serveur."
        )
    if num_results <= 0:
        num_results = 60
    if num_results > 200:
        num_results = 200
    pays = _normalize_pays(pays)

    hunt_id = uuid.uuid4().hex[:12]
    hunt = ProspectHunt(
        id=hunt_id,
        label=_build_label(metier, zone, only_no_site),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        status="pending",
        progress=0,
        filters={
            "metier": metier, "zone": zone,
            "num_results": num_results, "only_no_site": only_no_site,
            "pays": pays,
        },
    )
    hunt.save()

    def _thread():
        try:
            _run_hunt(hunt, metier=metier, zone=zone,
                      num_results=num_results, only_no_site=only_no_site,
                      api_key=_get_api_key(api_key), pays=pays,
                      progress_cb=progress_cb)
            hunt.status = "done"
            hunt.progress = 100
            hunt.save()
        except Exception as exc:
            logger.exception("prospect hunt %s crashed", hunt.id)
            hunt.status = "error"
            hunt.error = str(exc)
            hunt.save()

    t = threading.Thread(target=_thread, daemon=True,
                         name=f"prospecteur-{hunt_id}")
    _RUNNING[hunt_id] = t
    t.start()
    return hunt


def _fetch_places(region_code: str, metier: str, zone: str, num_results: int,
                  api_key: str, log: Callable[[str], None]) -> list[dict]:
    """Interroge l'API Places pour un seul `regionCode`. Renvoie la liste
    brute des places (max `num_results`).
    """
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": PLACES_FIELDS,
    }
    body: dict[str, Any] = {
        "textQuery": f"{metier} {zone}",
        "pageSize": 20,
        "languageCode": "fr",
        "regionCode": region_code,
    }

    places: list[dict] = []
    page_token: str | None = None
    while len(places) < num_results:
        if page_token:
            body["pageToken"] = page_token
        try:
            r = requests.post(PLACES_URL, headers=headers, json=body, timeout=15)
            if r.status_code != 200:
                log(f"⚠️ Erreur API {region_code} ({r.status_code}) : {r.text[:300]}")
                break
            data = r.json()
            batch = data.get("places", []) or []
            places.extend(batch)
            log(f"📄 [{region_code}] +{len(batch)} entreprise(s) (total {len(places)})")
            page_token = data.get("nextPageToken")
            if not page_token:
                break
            time.sleep(2)
        except Exception as exc:
            log(f"⚠️ Erreur réseau {region_code} : {exc}")
            break
    return places[:num_results]


# Champs minimaux pour une recherche « site d'UNE entreprise » : on ne
# demande QUE l'URL du site (+ le nom pour vérifier qu'on est sur la bonne
# boîte) → requête la moins chère possible côté facturation Places.
_SITE_LOOKUP_FIELDS = "places.displayName,places.websiteUri"


def lookup_site_for_company(name: str, city: str, api_key: str = "",
                            region_code: str = "FR") -> str:
    """Trouve le site web d'UNE entreprise via Google Places (UNE requête).

    Sert de filet pour Le Chasseur quand les moteurs gratuits (devinage de
    domaine, Mojeek, DuckDuckGo) ne trouvent rien — ce qui est le cas sur
    le serveur où ces moteurs sont bloqués.

    Renvoie l'URL du site (str) ou "" si rien / pas de clé / erreur.
    Best-effort : ne lève jamais.
    """
    key = (api_key or "").strip() or _get_api_key()
    q = " ".join(p for p in [(name or "").strip(), (city or "").strip()] if p)
    if not key or not q:
        return ""
    try:
        r = requests.post(
            PLACES_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": _SITE_LOOKUP_FIELDS,
            },
            json={"textQuery": q, "pageSize": 1, "languageCode": "fr",
                  "regionCode": region_code or "FR"},
            timeout=12,
        )
        if r.status_code != 200:
            return ""
        places = (r.json() or {}).get("places") or []
        if not places:
            return ""
        return (places[0].get("websiteUri") or "").strip()
    except Exception:
        return ""


def _run_hunt(hunt: ProspectHunt, metier: str, zone: str, num_results: int,
              only_no_site: bool, api_key: str, pays: str = "FR",
              progress_cb: Callable[[ProspectHunt], None] | None = None) -> None:
    def log(msg: str) -> None:
        hunt.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        if len(hunt.log) > 200:
            hunt.log = hunt.log[-200:]
        hunt.save()
        if progress_cb:
            try: progress_cb(hunt)
            except Exception: pass

    hunt.status = "searching"
    hunt.save()
    zone_label = "tous francophones" if pays == "ALL" else pays
    log(f"🔎 Recherche Google Places : '{metier}' à '{zone}' — {zone_label} (max {num_results})")

    all_places: list[dict] = []
    seen_ids: set[str] = set()
    if pays == "ALL":
        # On répartit le quota num_results sur les pays itérés.
        per_country = max(num_results // len(ALL_FRANCOPHONE_ITER), 10)
        for rc in ALL_FRANCOPHONE_ITER:
            if len(all_places) >= num_results:
                break
            batch = _fetch_places(rc, metier, zone, per_country, api_key, log)
            for pl in batch:
                key = pl.get("id") or (
                    (pl.get("displayName") or {}).get("text", "") +
                    "|" + (pl.get("formattedAddress") or "")
                )
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                all_places.append(pl)
                if len(all_places) >= num_results:
                    break
    else:
        all_places = _fetch_places(pays, metier, zone, num_results, api_key, log)

    all_places = all_places[:num_results]
    hunt.stats["candidats"] = len(all_places)
    log(f"✅ {len(all_places)} entreprise(s) à analyser.")

    # ----- Phase enrichissement : scraping mails -----
    hunt.status = "enriching"
    hunt.save()
    results: list[GoogleProspect] = []
    total = max(len(all_places), 1)

    for i, place in enumerate(all_places):
        name = (place.get("displayName") or {}).get("text") or "Inconnu"
        address = place.get("formattedAddress", "") or ""
        phone = place.get("internationalPhoneNumber", "") or ""
        website = place.get("websiteUri", "") or ""
        status = place.get("businessStatus", "") or ""

        log(f"--- {i+1}/{len(all_places)} : {name}")
        log(f"  📍 {address}")
        if phone:
            log(f"  📞 {phone}")

        emails: list[str] = []
        if website:
            log(f"  🌐 {website}")
            found = _scrape_site_for_emails(website)
            emails = sorted(found)
            if emails:
                log(f"  📧 {len(emails)} mail(s) : {', '.join(emails[:3])}")
            else:
                log("  📧 aucun mail trouvé sur le site")
        else:
            log("  ⚠️ Pas de site web → cible Triskell idéale")

        prospect = GoogleProspect(
            name=name, address=address, phone=phone, website=website,
            email=emails[0] if emails else "",
            emails_extra=emails[1:] if len(emails) > 1 else [],
            has_website=bool(website),
            status=status,
        )
        results.append(prospect)

        # Si only_no_site, on ne garde que celles sans site dans la sortie,
        # mais on continue à logger toutes les boîtes pour la transparence.
        retained = ([p for p in results if not p.has_website]
                    if only_no_site else results)

        hunt.prospects = [p.to_dict() for p in retained]
        hunt.progress = int((i + 1) / total * 100)
        hunt.stats["traites"] = i + 1
        hunt.stats["retenus"] = len(retained)
        hunt.stats["avec_mail"] = sum(1 for p in retained if p.email)
        hunt.stats["sans_site"] = sum(1 for p in results if not p.has_website)
        hunt.save()
        if progress_cb:
            try: progress_cb(hunt)
            except Exception: pass

        time.sleep(random.uniform(0.3, 0.8))

    no_site = sum(1 for p in results if not p.has_website)
    log(f"🎉 Terminé — {len(results)} entreprise(s) analysées · {no_site} sans site web")


def export_csv(hunt_id: str) -> dict:
    h = ProspectHunt.load(hunt_id)
    if not h:
        return {"ok": False, "error": "chasse introuvable"}
    ensure_dirs()
    out = EXPORTS_DIR / f"prospects_google_{h.id}.csv"
    rows = h.prospects or []
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "Nom", "Adresse", "Téléphone", "Site web",
            "Email principal", "Emails secondaires",
            "A un site ?", "Statut",
        ])
        for p in rows:
            w.writerow([
                p.get("name", ""),
                p.get("address", ""),
                p.get("phone", ""),
                p.get("website", ""),
                p.get("email", ""),
                "; ".join(p.get("emails_extra", []) or []),
                "oui" if p.get("has_website") else "NON",
                p.get("status", ""),
            ])
    return {"ok": True, "path": str(out), "rows": len(rows)}


def export_xlsx(hunt_id: str) -> dict:
    """Exporte les entreprises d'une recherche en fichier Excel (.xlsx)."""
    h = ProspectHunt.load(hunt_id)
    if not h:
        return {"ok": False, "error": "chasse introuvable"}
    ensure_dirs()
    out = EXPORTS_DIR / f"prospects_google_{h.id}.xlsx"
    rows = h.prospects or []
    try:
        from .hunt_exports import write_xlsx
        n = write_xlsx(
            out, sheet_title="Entreprises",
            headers=["Nom", "Adresse", "Téléphone", "Site web",
                     "Email principal", "Emails secondaires",
                     "A un site ?", "Statut"],
            rows=([p.get("name", ""), p.get("address", ""),
                   p.get("phone", ""), p.get("website", ""),
                   p.get("email", ""),
                   "; ".join(p.get("emails_extra", []) or []),
                   "oui" if p.get("has_website") else "NON",
                   p.get("status", "")] for p in rows),
            widths=[28, 38, 18, 32, 28, 28, 12, 18],
            # Met en évidence (fond ambre) les boîtes SANS site
            highlight=[not p.get("has_website") for p in rows],
        )
    except ImportError:
        return {"ok": False,
                "error": "openpyxl manquant — `pip install openpyxl`"}
    return {"ok": True, "path": str(out), "rows": n}


def delete_hunt(hunt_id: str) -> dict:
    h = ProspectHunt.load(hunt_id)
    if not h:
        return {"ok": False, "error": "chasse introuvable"}
    try:
        h.path.unlink(missing_ok=True)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


def push_to_prospects(hunt_id: str) -> dict:
    """Pousse les prospects d'une chasse Google vers la base partagée
    (table `prospects`), là où l'Auto-Pilote et la vue "Tous les prospects"
    travaillent. Même mécanique que Le Chasseur (upsert dédoublonné).

    Seuls les prospects AVEC email sont poussés : sans mail, ni
    l'Auto-Pilote ni les campagnes ne peuvent rien en faire.

    Renvoie {ok, backend, pushed, created, merged, total}.
    """
    h = ProspectHunt.load(hunt_id)
    if not h:
        return {"ok": False, "error": "chasse introuvable"}
    if not h.prospects:
        return {"ok": False, "error": "aucun prospect à pousser"}

    try:
        from triskell_core.prospect.core.crm import get_crm
        from triskell_core.prospect.core.prospect import (
            Prospect as CoreProspect, Source,
        )
    except ImportError as exc:
        return {"ok": False, "error":
                f"triskell_core absent — impossible de pousser ({exc})"}

    try:
        crm = get_crm()
    except Exception as exc:
        return {"ok": False, "error": f"connexion CRM impossible : {exc}"}
    backend = "remote" if crm.__class__.__name__ == "RemoteCRM" else "local"

    metier = (h.filters or {}).get("metier") or ""
    zone = (h.filters or {}).get("zone") or ""

    # Contrôle qualité AVANT versement (emails fabriqués, noms fantômes,
    # doublons internes) — le rapport remonte jusqu'à la mission.
    from .data_quality import filter_for_push
    clean_prospects, quality = filter_for_push(
        h.prospects, email_key="email", name_key="name")

    core_prospects: list[CoreProspect] = []
    for p in clean_prospects:
        email = (p.get("email") or "").strip()
        if not email:
            continue
        all_emails = [email] + [e for e in (p.get("emails_extra") or []) if e]
        emails_meta = [{
            "email": e,
            "source": "maps",
            "source_id": "",
            "url": (p.get("website") or "").strip(),
            "context": "site web trouvé via fiche Google Maps",
            "found_at": "",
        } for e in all_emails]
        tags = ["prospecteur_google"]
        if not p.get("has_website"):
            tags.append("sans_site")
        cp = CoreProspect(
            name=(p.get("name") or "").strip(),
            emails=all_emails,
            emails_meta=emails_meta,
            phones=[p.get("phone")] if p.get("phone") else [],
            website=(p.get("website") or "").strip(),
            address=(p.get("address") or "").strip(),
            country="FR",
            industry=metier,
            language="fr",
            tags=tags,
            notes=f"Trouvé via Prospecteur Google ({metier or 'tous métiers'}"
                  f" — {zone or 'France'})",
            sources=[Source(
                name="maps",
                source_id="",
                url=(p.get("website") or "").strip(),
            )],
            status="new",
        )
        core_prospects.append(cp)

    if not core_prospects:
        return {"ok": False, "error":
                "aucun prospect avec mail à pousser (mail requis)"}

    try:
        result = crm.upsert_many(core_prospects)
        if hasattr(crm, "save"):
            try: crm.save()
            except Exception: pass
        return {
            "ok": True,
            "backend":  backend,
            "created":  int(result.get("created") or 0),
            "merged":   int(result.get("merged") or 0),
            "total":    int(result.get("total") or 0),
            "pushed":   len(core_prospects),
            "quality":  quality,
        }
    except Exception as exc:
        return {"ok": False, "error": f"upsert échoué : {exc}"}
