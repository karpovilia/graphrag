FROM uv:0.5-python3.11 AS build

COPY pyproject.toml uv.lock ./


RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=graphrag,target=graphrag \
    --mount=type=bind,source=api/pyproject.toml,target=api/pyproject.toml \
    uv venv .venv --relocatable --no-python-downloads && \
    uv sync --no-dev --no-editable --frozen --all-packages


FROM python:3.11-slim-bookworm

COPY --from=build .venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY api api
COPY graphrag graphrag
COPY data data

ARG APP_VERSION
ARG COMMIT_SHORT
ENV APP_VERSION=$APP_VERSION
RUN export APP_VERSION=$APP_VERSION && \
    export COMMIT=$COMMIT_SHORT

ENTRYPOINT ["python3", "api", "--host=0.0.0.0"]
