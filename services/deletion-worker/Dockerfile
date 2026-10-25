FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# The lock pins rag-common at ../../packages/rag-common, which is /packages/rag-common
# when this project is copied to /app. Build context is the repository root.
COPY packages/rag-common/pyproject.toml /packages/rag-common/pyproject.toml
COPY packages/rag-common/src /packages/rag-common/src
COPY services/deletion-worker/pyproject.toml services/deletion-worker/uv.lock services/deletion-worker/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/deletion-worker/deletion_worker ./deletion_worker
RUN uv sync --frozen --no-dev

USER nobody
CMD ["/app/.venv/bin/python", "-m", "deletion_worker"]
