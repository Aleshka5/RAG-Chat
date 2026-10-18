FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY file_collector ./file_collector

RUN uv sync --frozen --no-dev --no-cache \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

ENV PYTHONUNBUFFERED=1 \
    FILE_COLLECTOR_PORT=8081

EXPOSE 8081

CMD ["/app/.venv/bin/python", "-m", "file_collector"]
