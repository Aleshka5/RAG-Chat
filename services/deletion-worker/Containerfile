FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# The service pins rag-common at ../../packages/rag-common, so the image mirrors the
# repository layout under /app: /app/services/deletion-worker sits beside
# /app/packages/rag-common. Build context is the repository root.
WORKDIR /app/services/deletion-worker

COPY packages/rag-common/pyproject.toml /app/packages/rag-common/pyproject.toml
COPY packages/rag-common/src /app/packages/rag-common/src
COPY services/deletion-worker/pyproject.toml services/deletion-worker/uv.lock services/deletion-worker/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/deletion-worker/deletion_worker ./deletion_worker
RUN uv sync --frozen --no-dev

USER nobody
CMD ["/app/services/deletion-worker/.venv/bin/python", "-m", "deletion_worker"]
