FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

# The service pins rag-common at ../../packages/rag-common, so the image mirrors the
# repository layout under /app: /app/services/file-collector sits beside
# /app/packages/rag-common. Build context is the repository root.
WORKDIR /app/services/file-collector

COPY packages/rag-common/pyproject.toml /app/packages/rag-common/pyproject.toml
COPY packages/rag-common/src /app/packages/rag-common/src
COPY services/file-collector/pyproject.toml services/file-collector/uv.lock services/file-collector/README.md ./
COPY services/file-collector/file_collector ./file_collector

RUN uv sync --frozen --no-dev --no-cache \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

ENV PYTHONUNBUFFERED=1 \
    FILE_COLLECTOR_PORT=8081

EXPOSE 8081

CMD ["/app/services/file-collector/.venv/bin/python", "-m", "file_collector"]
