"""Argus — récupération de mails d'entreprises françaises.

Outil de prospection B2B qui récupère des emails publics depuis Pages Jaunes,
Europages, OpenStreetMap, DuckDuckGo et les sites web des entreprises.

Toute la collecte tourne en thread daemon. L'UI poll l'état toutes les 2s.

Règle absolue : aucun email n'est inventé. Tous les mails exportés ont été
extraits littéralement du HTML d'une page web réellement visitée.
"""

from .runner import (
    start_session,
    pause_session,
    resume_session,
    stop_session,
    get_status,
    export_xlsx,
    set_reference_emails,
    is_running,
)

__all__ = [
    "start_session",
    "pause_session",
    "resume_session",
    "stop_session",
    "get_status",
    "export_xlsx",
    "set_reference_emails",
    "is_running",
]
