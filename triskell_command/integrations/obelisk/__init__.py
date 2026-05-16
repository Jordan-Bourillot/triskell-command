"""Intégration Obelisk dans Triskell Command.

Obelisk était historiquement une app desktop standalone (Triskell\\trove,
ex-Le Dénicheur). Depuis le rebrand 2026-05-16 + la fusion dans Command,
toutes les fonctions vivent ici :

  - repo.py     : DAO Supabase (table public.prospects) + config par user
  - runner.py   : lance run_creators_pipeline en arrière-plan + suit la progression

L'app standalone reste utilisable (sync Supabase) mais Jordan utilise
désormais Triskell Command comme interface principale.
"""

from . import repo  # noqa: F401
