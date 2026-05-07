"""Kits de livraison — un kit par produit Triskell.

Chaque kit définit ce qui se passe quand un client achète :
  - Mail de bienvenue (sujet + corps + livrables intégrés)
  - Liste de livrables (URLs de téléchargement, codes d'accès, fichiers)
  - Mails de suivi (J+3 onboarding, J+14 astuce, etc.)

Stockage : un fichier JSON local + miroir Supabase (table `shared_settings`
clé `delivery_kits`) pour synchro multi-poste. Le local fait foi en cas de
conflit (Jordan édite localement, sync vers Supabase au save).

Format d'un kit :
{
  "pack-electricien-pro": {
    "product_name": "Pack Électricien Pro",
    "welcome": {
      "subject": "Bienvenue dans le Pack Électricien Pro 🔌",
      "body": "Bonjour {client_name},\\n\\nMerci pour ta confiance.\\n\\n"
              "Voici tes accès :\\n{deliverables_list}\\n\\n{signature}",
      "deliverables": [
        {"label": "Télécharger le pack (ZIP)", "url": "https://..."},
        {"label": "Espace client", "url": "https://billing.stripe.com/..."}
      ]
    },
    "follow_ups": [
      {"days": 3, "subject": "Comment ça se passe ?",
       "body": "Bonjour {client_name},\\n\\nJ+3 dans..."},
      {"days": 14, "subject": "Une astuce pour aller plus loin",
       "body": "Salut {client_name},\\n\\nDans..."}
    ]
  }
}

Variables disponibles dans subject/body : {client_name}, {product_name},
{deliverables_list}, {signature}.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Storage paths
# ---------------------------------------------------------------------------
KITS_FILE = Path.home() / ".triskell-command" / "delivery_kits.json"
SHARED_KEY = "delivery_kits"


# ---------------------------------------------------------------------------
# Kits par défaut (pré-remplis pour les produits Triskell connus, à adapter
# par Jordan via l'éditeur)
# ---------------------------------------------------------------------------
DEFAULT_KITS: dict[str, dict[str, Any]] = {
    "pack-electricien-pro": {
        "product_name": "Pack Électricien Pro",
        "welcome": {
            "subject": "Bienvenue dans le Pack Électricien Pro",
            "body": (
                "Bonjour {client_name},\n\n"
                "Merci pour ta confiance — bienvenue dans le Pack Électricien Pro.\n\n"
                "Voici tout ce que tu reçois :\n"
                "{deliverables_list}\n\n"
                "Si tu as la moindre question, réponds simplement à ce mail.\n\n"
                "À très vite,\n{signature}"
            ),
            "deliverables": [],   # Jordan remplit avec les vraies URLs
        },
        "follow_ups": [
            {
                "days": 3,
                "subject": "Tout va bien avec le Pack ?",
                "body": (
                    "Bonjour {client_name},\n\n"
                    "Trois jours après la livraison du Pack Électricien Pro : "
                    "tout se passe comme prévu ?\n\n"
                    "Si tu bloques quelque part, dis-le moi, je te débloque.\n\n"
                    "{signature}"
                ),
            },
            {
                "days": 14,
                "subject": "Une astuce pour aller plus loin",
                "body": (
                    "Salut {client_name},\n\n"
                    "Petite astuce que beaucoup oublient avec le Pack : "
                    "(à compléter par Jordan).\n\n"
                    "{signature}"
                ),
            },
            {
                "days": 30,
                "subject": "Un mois après — ton avis compte",
                "body": (
                    "Bonjour {client_name},\n\n"
                    "Un mois après la livraison du Pack Électricien Pro, "
                    "j'aimerais avoir ton retour franc.\n\n"
                    "Si l'outil t'a aidé, tu pourrais me déposer un avis "
                    "rapide ici (2 minutes max) — ça m'aide énormément à "
                    "faire connaître Triskell aux autres pros :\n"
                    "(lien Trustpilot/G2 à compléter par Jordan)\n\n"
                    "Si quelque chose ne va pas, réponds-moi directement, je "
                    "te recontacte sous 24h.\n\n"
                    "Merci d'avance,\n{signature}"
                ),
            },
        ],
    },
    "studio-pdf": {
        "product_name": "Studio PDF",
        "welcome": {
            "subject": "Studio PDF est à toi",
            "body": (
                "Bonjour {client_name},\n\n"
                "Bienvenue dans Studio PDF.\n\n"
                "Pour démarrer :\n{deliverables_list}\n\n"
                "{signature}"
            ),
            "deliverables": [],
        },
        "follow_ups": [
            {"days": 3, "subject": "Studio PDF — premier essai ?",
             "body": "Bonjour {client_name},\n\n(à compléter)\n\n{signature}"},
            {"days": 30, "subject": "Un mois avec Studio PDF — ton avis ?",
             "body": (
                "Bonjour {client_name},\n\n"
                "Un mois avec Studio PDF — qu'est-ce que ça donne ?\n\n"
                "Si tu as 2 minutes, j'apprécierais ton avis ici :\n"
                "(lien à compléter)\n\n"
                "Sinon, dis-moi ce qui pourrait aller mieux — j'écoute.\n\n"
                "{signature}"
             )},
        ],
    },
    "obelisk": {
        "product_name": "Obelisk",
        "welcome": {
            "subject": "Bienvenue dans Obelisk",
            "body": (
                "Bonjour {client_name},\n\n"
                "Merci pour ton achat d'Obelisk.\n\n"
                "Tes accès :\n{deliverables_list}\n\n"
                "Bonne chasse aux créateurs.\n\n"
                "{signature}"
            ),
            "deliverables": [],
        },
        "follow_ups": [
            {"days": 7, "subject": "Obelisk — première semaine",
             "body": "Bonjour {client_name},\n\n(à compléter)\n\n{signature}"},
            {"days": 30, "subject": "Obelisk — un mois après, ton retour ?",
             "body": (
                "Bonjour {client_name},\n\n"
                "Un mois avec Obelisk — combien de bonnes pioches ?\n\n"
                "Si l'outil t'a aidé, un petit avis me ferait gagner "
                "beaucoup de temps de prospection :\n"
                "(lien à compléter)\n\n"
                "Sinon, dis-moi ce qui manque — j'ajoute.\n\n"
                "{signature}"
             )},
        ],
    },
    # Kit générique utilisé si le produit acheté n'a pas de kit dédié
    "_default": {
        "product_name": "votre commande Triskell",
        "welcome": {
            "subject": "Merci pour ta commande",
            "body": (
                "Bonjour {client_name},\n\n"
                "Merci pour ton achat.\n\n"
                "Voici tes accès :\n{deliverables_list}\n\n"
                "Si tu as la moindre question, réponds à ce mail.\n\n"
                "{signature}"
            ),
            "deliverables": [],
        },
        "follow_ups": [
            {"days": 30, "subject": "Un mois après — comment ça va ?",
             "body": (
                "Bonjour {client_name},\n\n"
                "Un mois après ta commande chez Triskell : tout va bien ?\n\n"
                "Si tu as 2 minutes pour me laisser un avis, ça m'aide "
                "énormément :\n(lien à compléter)\n\n"
                "Sinon, dis-moi ce qui pourrait aller mieux.\n\n"
                "{signature}"
             )},
        ],
    },
}


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------
def _ensure_dir() -> None:
    KITS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_kits(client=None) -> dict[str, dict[str, Any]]:
    """Charge les kits. Local en priorité (édité par Jordan), Supabase en
    fallback (sync multi-poste). Si rien, retourne DEFAULT_KITS."""
    # 1) Local
    if KITS_FILE.exists():
        try:
            data = json.loads(KITS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                # Garantit la présence du _default
                if "_default" not in data:
                    data["_default"] = DEFAULT_KITS["_default"]
                return data
        except Exception as exc:
            logger.warning("delivery_kits load local: %s", exc)
    # 2) Supabase
    if client is not None:
        try:
            raw = client.get_shared_setting(SHARED_KEY, {}) or {}
            if isinstance(raw, str):
                raw = json.loads(raw)
            if isinstance(raw, dict) and raw:
                if "_default" not in raw:
                    raw["_default"] = DEFAULT_KITS["_default"]
                return raw
        except Exception as exc:
            logger.debug("delivery_kits load supabase: %s", exc)
    # 3) Default
    return _deep_copy(DEFAULT_KITS)


def save_kits(kits: dict[str, dict[str, Any]], client=None) -> None:
    """Sauve local + miroir Supabase si dispo."""
    _ensure_dir()
    KITS_FILE.write_text(
        json.dumps(kits, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if client is not None:
        try:
            client.set_shared_setting(SHARED_KEY, kits)
        except Exception as exc:
            logger.debug("delivery_kits save supabase: %s", exc)


def get_kit(product_key: str, client=None) -> dict[str, Any]:
    """Renvoie le kit du produit, ou le kit _default si pas trouvé."""
    kits = load_kits(client)
    if not product_key:
        return kits.get("_default") or DEFAULT_KITS["_default"]
    kit = kits.get(product_key)
    if kit:
        return kit
    return kits.get("_default") or DEFAULT_KITS["_default"]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_welcome(
    product_key: str,
    *,
    client_name: str,
    signature: str = "",
    extra_vars: Optional[dict] = None,
    client=None,
) -> dict[str, Any]:
    """Renvoie {subject, body, deliverables} prêt à envoyer pour le welcome."""
    kit = get_kit(product_key, client=client)
    welcome = kit.get("welcome") or {}
    deliverables = welcome.get("deliverables") or []
    deliverables_list = _format_deliverables(deliverables)
    vars_dict = {
        "client_name": client_name or "vous",
        "product_name": kit.get("product_name") or product_key or "votre commande",
        "deliverables_list": deliverables_list,
        "signature": signature or "",
        **(extra_vars or {}),
    }
    return {
        "subject":      _safe_format(welcome.get("subject", ""), vars_dict),
        "body":         _safe_format(welcome.get("body", ""), vars_dict),
        "deliverables": deliverables,
    }


def render_follow_up(
    product_key: str,
    follow_up_index: int,
    *,
    client_name: str,
    signature: str = "",
    extra_vars: Optional[dict] = None,
    client=None,
) -> Optional[dict[str, Any]]:
    """Renvoie {subject, body, days} pour un follow-up à l'index donné, ou None."""
    kit = get_kit(product_key, client=client)
    fus = kit.get("follow_ups") or []
    if follow_up_index < 0 or follow_up_index >= len(fus):
        return None
    fu = fus[follow_up_index]
    vars_dict = {
        "client_name": client_name or "vous",
        "product_name": kit.get("product_name") or product_key or "votre commande",
        "deliverables_list": _format_deliverables(
            (kit.get("welcome") or {}).get("deliverables") or []),
        "signature": signature or "",
        **(extra_vars or {}),
    }
    return {
        "subject": _safe_format(fu.get("subject", ""), vars_dict),
        "body":    _safe_format(fu.get("body", ""), vars_dict),
        "days":    int(fu.get("days") or 0),
    }


def list_follow_ups(product_key: str, client=None) -> list[dict[str, Any]]:
    """Renvoie la liste brute des follow-ups d'un produit (pour scheduling)."""
    kit = get_kit(product_key, client=client)
    return list(kit.get("follow_ups") or [])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _format_deliverables(items: list[dict]) -> str:
    """Formate la liste des livrables en bullet-list lisible dans un mail."""
    if not items:
        return "(à venir — Jordan te recontactera avec les liens)"
    lines = []
    for it in items:
        label = (it.get("label") or "Lien").strip()
        url = (it.get("url") or "").strip()
        if url:
            lines.append(f"  • {label} : {url}")
        else:
            lines.append(f"  • {label}")
    return "\n".join(lines)


def _safe_format(template: str, vars_dict: dict) -> str:
    """Format avec tolérance : variable manquante = laissée telle quelle."""
    try:
        return template.format(**vars_dict)
    except (KeyError, IndexError):
        # Fallback : remplace ce qu'on peut, laisse le reste
        out = template
        for k, v in vars_dict.items():
            out = out.replace("{" + k + "}", str(v))
        return out


def _deep_copy(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: _deep_copy(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_deep_copy(x) for x in d]
    return d
