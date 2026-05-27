"""
Validation et nettoyage des emails.
Règle absolue : aucun email n'est jamais inventé. On extrait uniquement ce qui
est littéralement présent dans le HTML d'une page web visitée.
"""

import re
from typing import Iterable, Set


# Regex pour extraire les emails d'un texte HTML brut.
# Suit le format RFC simplifié et capture les caractères valides courants.
EMAIL_EXTRACT_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)

# Regex stricte pour valider qu'une chaîne EST un email correct.
EMAIL_STRICT_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
)

# Préfixes (partie avant le @) à exclure : adresses techniques, automatiques,
# qui ne mènent jamais à un humain commercial.
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
}

# Domaines techniques à exclure (services SaaS, exemples, services tiers).
JUNK_DOMAINS = {
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
    "sentry-next.wixpress.com",
}

# Domaines de messageries personnelles grand public.
# Exclus par défaut, mais peuvent être réinclus via une option.
PERSONAL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "yahoo.fr",
    "ymail.com",
    "hotmail.com",
    "hotmail.fr",
    "outlook.com",
    "outlook.fr",
    "live.com",
    "live.fr",
    "msn.com",
    "orange.fr",
    "free.fr",
    "sfr.fr",
    "laposte.net",
    "wanadoo.fr",
    "neuf.fr",
    "bbox.fr",
    "alice.fr",
    "club-internet.fr",
    "aliceadsl.fr",
    "numericable.fr",
    "9online.fr",
    "voila.fr",
    "tiscali.fr",
    "noos.fr",
    "cegetel.net",
    "icloud.com",
    "me.com",
    "mac.com",
    "aol.com",
    "aol.fr",
    "protonmail.com",
    "proton.me",
    "tutanota.com",
    "gmx.com",
    "gmx.fr",
    "mailo.com",
    "zoho.com",
}

# Extensions de fichiers qui apparaissent parfois après un @ dans le HTML
# (faux positifs comme "image@2x.png", "logo@2x.jpg").
FAKE_EMAIL_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".bmp",
    ".pdf",
    ".css",
    ".js",
)


def extract_emails_from_text(text: str) -> Set[str]:
    """
    Extrait tous les emails bruts d'un texte (HTML, page Web).
    Aucune génération : seules les chaînes littéralement présentes sont retenues.
    """
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

    # Filtre faux positifs (ex: "icon@2x.png" capturé par le regex large).
    if any(email.endswith(suf) for suf in FAKE_EMAIL_SUFFIXES):
        return False

    local, _, domain = email.partition("@")

    # Préfixe poubelle.
    if local in JUNK_PREFIXES:
        return False

    # Domaine technique poubelle.
    if domain in JUNK_DOMAINS:
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
