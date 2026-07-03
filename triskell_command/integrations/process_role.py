"""Rôle du process — source unique pour la séparation site/robots.

Un seul déploiement historique faisait tout (« all »). La variable
d'environnement TRISKELL_ROLE prépare la séparation en 2 conteneurs Coolify :

- « all »     (défaut, ou valeur inconnue) : web + robots — comportement
              historique. Le desktop n'a pas la variable → « all » aussi.
- « web »     : sert le site/l'API, AUCUN robot de fond… sauf ce qui est
              attaché à l'état LOCAL du serveur web (auto-pilote GEO,
              sauvegarde GEO) — voir owns_ui_state().
- « workers » : les robots de fond, sans vocation à servir le front.

Règles de partage (décidées le 03/07/2026) :
- Les robots qui travaillent sur la BASE PARTAGÉE (Supabase) vont côté
  « workers » : autopilot, drip, réponses, missions, pollers, chauffe…
- Ce qui travaille sur l'ÉTAT LOCAL du serveur web (AppState : données GEO)
  reste côté « web », sinon l'écran GEO et son robot divergent (split-brain).
- Le ménage disque tourne PARTOUT (chaque conteneur nettoie SON disque),
  mais la sauvegarde/restauration cloud du GEO ne se fait que là où vivent
  les vraies données GEO (owns_ui_state), pour ne jamais écraser la
  sauvegarde fraîche avec une copie périmée.
"""
from __future__ import annotations

import os

VALID_ROLES = ("all", "web", "workers")


def get_role() -> str:
    """Rôle du process, toujours valide (« all » par défaut)."""
    role = (os.environ.get("TRISKELL_ROLE") or "all").strip().lower()
    return role if role in VALID_ROLES else "all"


def runs_workers() -> bool:
    """Ce process fait-il tourner les robots de fond (base partagée) ?"""
    return get_role() in ("all", "workers")


def owns_ui_state() -> bool:
    """Ce process possède-t-il l'état local du serveur web (AppState) ?

    Vrai pour « all » et « web » : c'est là que vivent les données GEO et
    que l'écran les lit. Le conteneur « workers » ne doit ni faire tourner
    l'auto-pilote GEO ni toucher aux sauvegardes GEO.
    """
    return get_role() in ("all", "web")
