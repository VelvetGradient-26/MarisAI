# syntax=docker/dockerfile:1

# ---- Stage 1: builder ----
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app/backend

# Copy lockfile + project metadata first so dependency install is cached
# separately from application source changes.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
RUN uv sync --frozen --no-dev

# ---- Stage 2: runtime ----
FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser

WORKDIR /app/backend

COPY --from=builder /app/backend /app/backend

# settings.PREDICTIONS_DIR (app/core/config.py) defaults to
# Path(__file__).resolve().parents[3] / "machine_learning" / "exports" —
# i.e. it expects machine_learning/ as a SIBLING of backend/. Preserving
# that layout here means the existing default resolves correctly with no
# code change and no PREDICTIONS_DIR override needed.
COPY machine_learning/exports /app/machine_learning/exports

ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    FORECAST_GRID_REFRESH_ON_BOOT=false

COPY backend/docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

ENTRYPOINT ["entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
