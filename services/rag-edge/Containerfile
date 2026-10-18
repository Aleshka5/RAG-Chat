# rag-edge listens on 8080 inside the pod.
# Compose attaches this container to rag_edge (Auth Gateway) and rag_internal
# (file-collector, chat, frontend). The port is not published on the host.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY rag_edge ./rag_edge

RUN uv sync --frozen --no-dev \
    && chmod -R a+rX /app

USER nobody
EXPOSE 8080
CMD ["rag-edge"]
