# Triskell Command — image Docker pour le serveur HTTP (mode prod public).
# Hostable derrière Coolify / Caprover / docker run direct.
#
# Architecture :
# - Base : python:3.12-slim
# - Clone triskell-core (sibling repo public sur GitHub) au moment du build
# - Installe les deps HTTP (requirements-http.txt, plus light que desktop)
# - Le code app est dans /app, triskell-core dans /opt/triskell-core
# - Volume persistant /data → mappé à $HOME pour que ~/.triskell-command
#   (auth.json, settings.json, users.json) survive aux redéploiements
# - Expose 8765 (port serveur HTTP, voir run_http.py)
# - Variables sensibles (SESSION_SECRET, *_PASSWORD_HASH, ANTHROPIC_API_KEY,
#   SUPABASE_*, VAPID_*) à injecter via env Coolify (NE PAS les mettre ici).

FROM python:3.12-slim

# Évite les .pyc + bufferise stdout (logs en temps réel)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Deps système nécessaires (build tools pour packages C, git pour cloner triskell-core)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libxml2-dev libxslt-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Clone triskell-core (sibling repo). Le SHA peut être pinné via build-arg si besoin.
ARG TRISKELL_CORE_REF=main
RUN git clone --depth=1 --branch ${TRISKELL_CORE_REF} \
    https://github.com/Jordan-Bourillot/triskell-core.git \
    /opt/triskell-core

# Install requirements en premier (cache layer optimisé : ne re-build pas les deps
# si seul le code app change)
COPY requirements-http.txt ./
RUN pip install -r requirements-http.txt

# Copie le code app (.dockerignore exclut .git, .venv, node_modules, etc.)
COPY . .

# triskell_core importable
ENV PYTHONPATH="/opt/triskell-core:/app"

# Volume persistant pour les fichiers app utilisateur (auth Supabase, settings, etc.)
# /data sera monté par Coolify, mappé à $HOME pour que ~/.triskell-command pointe ici.
ENV HOME=/data
RUN mkdir -p /data
VOLUME ["/data"]

# Healthcheck simple : ping /api/_health
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8765/api/_health || exit 1

EXPOSE 8765

# Lance le serveur HTTP, écoute sur toutes les interfaces (0.0.0.0)
# pour que Coolify/Docker network puisse le router.
CMD ["python", "run_http.py", "--host", "0.0.0.0", "--port", "8765"]
