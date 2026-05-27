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

# Deps système nécessaires (build tools pour packages C, git pour cloner triskell-core,
# + libs natives nécessaires à Chromium headless utilisé par Argus via Playwright).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libxml2-dev libxslt-dev \
    curl \
    # Chromium runtime deps (Playwright)
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 libwayland-client0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Clone triskell-core (sibling repo). Le SHA peut être pinné via build-arg si besoin.
ARG TRISKELL_CORE_REF=main
RUN git clone --depth=1 --branch ${TRISKELL_CORE_REF} \
    https://github.com/Jordan-Bourillot/triskell-core.git \
    /opt/triskell-core

# Note : pixel-studio (le builder Python + templates) est un repo privé.
# On NE le clone PAS au build (ça demanderait de passer GITHUB_TOKEN en build arg
# et de le baker dans l'image). On le clone au runtime depuis pixelpros_repo.py,
# dans le volume persistant /data/pixel-studio, en utilisant l'env GITHUB_TOKEN.

# Install requirements en premier (cache layer optimisé : ne re-build pas les deps
# si seul le code app change). Note : requirements-http.txt inclut maintenant
# chevron (Mustache renderer) pour que le builder pixel-studio tourne sans
# install supplémentaire.
COPY requirements-http.txt ./
RUN pip install -r requirements-http.txt

# Argus utilise Playwright pour scraper Pages Jaunes / Europages.
# IMPORTANT : on place Chromium dans un chemin partagé indépendant de $HOME,
# parce que $HOME sera remappé sur /data (volume Coolify) au runtime — un
# install dans ~/.cache/ms-playwright serait perdu au redéploiement.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers
RUN python -m playwright install chromium --with-deps || \
    python -m playwright install chromium

# Copie le code app (.dockerignore exclut .git, .venv, node_modules, etc.)
COPY . .

# triskell_core importable
ENV PYTHONPATH="/opt/triskell-core:/app"

# Volume persistant pour les fichiers app utilisateur (auth Supabase, settings, etc.)
# /data sera monté par Coolify, mappé à $HOME pour que ~/.triskell-command pointe ici.
ENV HOME=/data
RUN mkdir -p /data
VOLUME ["/data"]

# Indique au builder Pixel Pros où cloner son repo (volume persistant).
ENV PIXEL_PROS_REPO_PATH=/data/pixel-studio

# Identité git par défaut pour les commits automatiques du builder Pixel Pros.
RUN git config --global user.email "robot@pixel-pros.fr" \
 && git config --global user.name "Pixel Pros Robot"

# Healthcheck simple : ping /api/_health
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8765/api/_health || exit 1

EXPOSE 8765

# Lance le serveur HTTP, écoute sur toutes les interfaces (0.0.0.0)
# pour que Coolify/Docker network puisse le router.
CMD ["python", "run_http.py", "--host", "0.0.0.0", "--port", "8765"]
