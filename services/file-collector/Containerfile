FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

WORKDIR /app

# The lock pins rag-common at ../../packages/rag-common, which is /packages/rag-common
# when this project is copied to /app. Build context is the repository root.
COPY packages/rag-common/pyproject.toml /packages/rag-common/pyproject.toml
COPY packages/rag-common/src /packages/rag-common/src
COPY services/file-collector/pyproject.toml services/file-collector/uv.lock services/file-collector/README.md ./
COPY services/file-collector/file_collector ./file_collector

RUN uv sync --frozen --no-dev --no-cache \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

ENV PYTHONUNBUFFERED=1 \
    FILE_COLLECTOR_PORT=8081

EXPOSE 8081

CMD ["/app/.venv/bin/python", "-m", "file_collector"]
