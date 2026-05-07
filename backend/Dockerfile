# Phase 7 — production image. Single-stage uv install + slim runtime.
# The Phase 0.6 fork is gone, so no graphrag/ bind-mount; PyPI graphrag
# arrives with the api workspace's pyproject.

FROM ghcr.io/astral-sh/uv:0.5-python3.12-bookworm-slim AS build

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY api/pyproject.toml api/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv .venv --no-python-downloads && \
    uv sync --no-dev --frozen --all-packages

FROM python:3.12-slim-bookworm

WORKDIR /app
COPY --from=build /app/.venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY api ./api
COPY scripts ./scripts
COPY data ./data

EXPOSE 8000

# Boot: alembic upgrade head (idempotent), then uvicorn. POSTGRES__*
# envs come from compose; STORAGE__DATA_DIR points at the named volume.
ENTRYPOINT ["/bin/sh", "-c", "cd /app/api/db && alembic upgrade head && cd /app && exec uvicorn api.__main__:app --host 0.0.0.0 --port 8000"]
