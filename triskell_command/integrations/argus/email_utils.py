"""
Validation et nettoyage des emails.
Règle absolue : aucun email n'est jamais inventé. On extrait uniquement ce qui
est littéralement présent dans le HTML d'une page web visitée.
"""

import re
from typing import Iterable, Set


# Regex pour extraire les emails d'un texte HTML brut.
EMAIL_EXTRACT_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)

# Regex stricte pour valider qu'une chaîne EST un email correct.
EMAIL_STRICT_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
)

# Préfixes exacts à exclure : adresses techniques/automatiques.
# Match exact sur la partie locale (avant @).
JUNK_PREFIXES = {
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "postmaster",
    "mailer-daemon",
    "abuse",
    "admin",
    "administrator",
    "webmaster",
    "hostmaster",
    "dpo",
    "rgpd",
    "privacy",
    "contact-form",
    "wordpress",
    "newsletter",
    "test",
    "example",
    "user",
    "support-noreply",
    "commissioner",      # autorités de protection des données
    "compliance",
    "datenschutz",       # "protection des données" en allemand
    "customercare",      # service client générique
    "customer.care",
    "customer-care",
    "customer.success",
    "customer-success",
}

# Mots-clés à chercher DANS le préfixe (match partiel).
# Si l'un de ces mots apparaît dans la partie locale, on rejette.
# Ex: "data.privacy@..." ou "marketing-privacy@..." → bloqués via "privacy".
JUNK_PREFIX_KEYWORDS = (
    "data.privacy",
    "data-privacy",
    "data_privacy",
    "rgpd",
    "gdpr",
    "datenschutz",
    "no-reply",
    "noreply",
    "mailer-daemon",
)

# Domaines techniques à exclure (match EXACT).
JUNK_DOMAINS_EXACT = {
    "sentry.io",
    "wixpress.com",
    "example.com",
    "example.org",
    "example.fr",
    "example.net",
    "domain.com",
    "domain.fr",
    "yourdomain.com",
    "yoursite.com",
    "test.com",
    "email.com",
    "mail.com",
    "googlegroups.com",
    "wordpress.com",
    # Services SaaS B2B qu'on croise dans les mentions légales.
    "virtualminds.com",
    "visable.com",
    "hubspot.com",
    "salesforce.com",
    "mailchimp.com",
    "sendgrid.net",
    "intercom.io",
    "zendesk.com",
}

# Suffixes de domaines à exclure (match `endswith`).
# Permet de matcher tous les sous-domaines (`o123.ingest.sentry.io`) et toutes
# les institutions gouvernementales / européennes / autorités RGPD.
JUNK_DOMAIN_SUFFIXES = (
    # Sentry et ses variantes
    ".sentry.io",
    ".ingest.sentry.io",
    ".ingest.us.sentry.io",
    ".wixpress.com",
    # Institutions européennes
    ".europa.eu",
    # Sites gouvernementaux internationaux
    ".gouv.fr",
    ".gov.fr",
    ".gov.uk",
    ".gov.be",
    ".gov.cy",
    ".gov.pl",
    ".gov.lv",
    ".gov.mt",
    ".gov.gr",
    ".gov.es",
    ".gov.pt",
    ".gov.it",
    ".gov.ie",
    ".gov.lt",
    ".gov.sk",
    ".gov.si",
    ".gov.hr",
    ".gov.hu",
    ".gov.ro",
    ".gov.bg",
    ".gov.ee",
    # Spécifiques nationaux (autorités RGPD européennes)
    ".gv.at",          # Autriche
    ".bund.de",        # Allemagne fédérale
    ".datenschutz-bayern.de",
    ".datenschutz-berlin.de",
    ".datenschutz-hamburg.de",
)

# Autorités de protection des données européennes (CNIL & équivalents).
# Elles apparaissent dans les mentions légales de la plupart des sites EU.
GDPR_AUTHORITIES = {
    "cnil.fr",                  # France
    "apd-gba.be",               # Belgique
    "dpa.gr",                   # Grèce
    "datatilsynet.dk",          # Danemark
    "datatilsynet.no",          # Norvège
    "dsb.gv.at",                # Autriche
    "uodo.gov.pl",              # Pologne
    "edps.europa.eu",           # Contrôleur européen
    "edpb.europa.eu",           # Comité européen
    "cnpd.pt",                  # Portugal
    "cnpd.lu",                  # Luxembourg
    "ip-rs.si",                 # Slovénie
    "idpc.org.mt",              # Malte
    "imy.se",                   # Suède
    "llv.li",                   # Liechtenstein
    "aki.ee",                   # Estonie
    "dataprotection.ie",        # Irlande
    "dataprotection.gov.cy",    # Chypre
    "aepd.es",                  # Espagne
    "cpdp.bg",                  # Bulgarie
    "datenschutz-bayern.de",    # Bavière
    "datenschutz.bremen.de",
    "datenschutz-mv.de",
    "dvi.gov.lv",               # Lettonie
    "uoou.cz",                  # Tchéquie
    "bfdi.bund.de",             # Allemagne fédérale
    "ico.org.uk",               # UK
    "garanteprivacy.it",        # Italie
    "azop.hr",                  # Croatie
    "azlp.ba",                  # Bosnie-Herzégovine
    "datainspektorius.lt",      # Lituanie (ancien)
    "vdai.lrv.lt",              # Lituanie
    "ovd.cnam.lu",
    "personuvernd.is",          # Islande
    "dziennikinternetowy.pl",
}

# Plateformes/agrégateurs B2B qu'on scrape DÉJÀ : leurs propres emails de
# service client ne sont pas des prospects.
SCRAPER_OWN_DOMAINS = {
    "europages.com",
    "europages.fr",
    "pagesjaunes.fr",
    "solocal.com",
    "hellopro.fr",
    "pappers.fr",
}

# Domaines de messageries personnelles grand public.
PERSONAL_DOMAINS = {
    "gmail.com", "googlemail.com",
    "yahoo.com", "yahoo.fr", "ymail.com",
    "hotmail.com", "hotmail.fr",
    "outlook.com", "outlook.fr",
    "live.com", "live.fr", "msn.com",
    "orange.fr", "free.fr", "sfr.fr", "laposte.net",
    "wanadoo.fr", "neuf.fr", "bbox.fr",
    "alice.fr", "club-internet.fr", "aliceadsl.fr",
    "numericable.fr", "9online.fr", "voila.fr",
    "tiscali.fr", "noos.fr", "cegetel.net",
    "icloud.com", "me.com", "mac.com",
    "aol.com", "aol.fr",
    "protonmail.com", "proton.me", "tutanota.com",
    "gmx.com", "gmx.fr", "mailo.com", "zoho.com",
}

# Extensions de fichiers qui apparaissent parfois après un @ dans le HTML.
FAKE_EMAIL_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp",
    ".pdf", ".css", ".js",
)

# Regex pour repérer un préfixe qui ressemble à un hash hexa long
# (typique des emails techniques de tracking type Sentry, Cloudflare, etc.).
HEX_HASH_RE = re.compile(r"^[a-f0-9]{24,}$")


def extract_emails_from_text(text: str) -> Set[str]:
    """Extrait tous les emails bruts d'un texte (HTML, page Web)."""
    if not text:
        return set()
    raw = EMAIL_EXTRACT_RE.findall(text)
    return {e.strip().lower() for e in raw}


def is_valid_email(email: str, include_personal: bool = False) -> bool:
    """
    Vérifie qu'un email est syntaxiquement valide et n'est pas une adresse poubelle.

    - include_personal=False (défaut) : rejette gmail/yahoo/orange/etc.
    - include_personal=True : accepte aussi les domaines persos.
    """
    if not email:
        return False

    email = email.strip().lower()

    # Format strict.
    if not EMAIL_STRICT_RE.match(email):
        return False

    # Faux positifs type "icon@2x.png".
    if any(email.endswith(suf) for suf in FAKE_EMAIL_SUFFIXES):
        return False

    local, _, domain = email.partition("@")

    # Préfixe exact poubelle.
    if local in JUNK_PREFIXES:
        return False

    # Préfixe qui CONTIENT un mot-clé technique.
    for kw in JUNK_PREFIX_KEYWORDS:
        if kw in local:
            return False

    # Préfixe qui ressemble à un hash hexa long (tracking auto-généré).
    if HEX_HASH_RE.match(local):
        return False

    # Domaine technique exact.
    if domain in JUNK_DOMAINS_EXACT:
        return False

    # Domaine autorité RGPD européenne.
    if domain in GDPR_AUTHORITIES:
        return False

    # Domaine d'un agrégateur qu'on scrape (Europages, Pages Jaunes, etc.).
    if domain in SCRAPER_OWN_DOMAINS:
        return False

    # Domaine ou sous-domaine listé dans les suffixes (.sentry.io, .gov.fr…).
    for suf in JUNK_DOMAIN_SUFFIXES:
        if domain == suf.lstrip(".") or domain.endswith(suf):
            return False

    # Domaine perso (sauf si l'utilisateur veut les inclure).
    if not include_personal and domain in PERSONAL_DOMAINS:
        return False

    # Limites de longueur raisonnables.
    if len(email) > 254 or len(local) > 64:
        return False

    return True


def filter_valid_emails(
    emails: Iterable[str], include_personal: bool = False
) -> Set[str]:
    """Filtre un ensemble d'emails pour ne garder que les valides."""
    return {e for e in emails if is_valid_email(e, include_personal)}
