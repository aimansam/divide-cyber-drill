# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY services/api/pyproject.toml ./
RUN pip install --upgrade pip hatchling && \
    pip wheel --wheel-dir=/wheels \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.32.0" \
    "pydantic>=2.9.0" \
    "pydantic-settings>=2.6.0" \
    "sqlalchemy[asyncio]>=2.0.36" \
    "asyncpg>=0.30.0" \
    "alembic>=1.13.3" \
    "redis[hiredis]>=5.2.0" \
    "httpx>=0.27.2" \
    "proxmoxer>=2.2.0" \
    "requests>=2.32.3" \
    "pyyaml>=6.0.2" \
    "jsonschema>=4.18,<5" \
    "structlog>=24.4.0" \
    "tenacity>=9.0.0" \
    "prometheus-client>=0.21.0" \
    "psycopg2-binary>=2.9.9"

# --- runtime stage ---
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 divide

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels \
    fastapi uvicorn pydantic pydantic-settings \
    sqlalchemy asyncpg alembic redis httpx proxmoxer requests pyyaml \
    jsonschema structlog tenacity prometheus-client psycopg2-binary \
    && rm -rf /wheels /root/.cache

COPY services/api/app ./app
COPY services/api/scripts ./scripts
COPY services/api/alembic ./alembic
COPY services/api/alembic.ini ./alembic.ini
# JSON Schema is shared with the host. We bundle a copy at /app/schemas so
# the schema-sync service works inside the container without a host mount.
COPY schemas ./schemas
USER divide

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
