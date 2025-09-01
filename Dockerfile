# -------- Base --------
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Config padrão do Streamlit (pode ser sobrescrito por env/.env)
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_PORT=8505 \
    STREAMLIT_BROWSER_GATHERUSAGESTATS=false

# Dependências do sistema (adicione outras se seu app precisar)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Usuário não-root
RUN groupadd -r app && useradd -r -g app -d /app app
WORKDIR /app

# -------- Depêndencias Python (cache-friendly) --------
# Se usar requirements.txt/requirements-dev.txt, eles serão usados para cache.
COPY requirements*.txt /app/
RUN if [ -f "requirements.txt" ]; then pip install -r requirements.txt; fi \
 && if [ -f "requirements-dev.txt" ]; then pip install -r requirements-dev.txt; fi

# -------- Código --------
COPY . /app
RUN chown -R app:app /app
USER app

# Exponha a porta configurada
EXPOSE 8505

# Healthcheck simples (Streamlit responde em /_stcore/health)
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://localhost:${STREAMLIT_SERVER_PORT}/_stcore/health" || exit 1

# Comando padrão (docker-compose pode sobrescrever com `command:`)
CMD ["streamlit", "run", "src/app.py", "--server.port", "8505", "--server.headless", "true"]
