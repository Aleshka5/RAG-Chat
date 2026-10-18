# Internal embedding image.
# Build: podman build -f Containerfile -t embedding .
# FastAPI listens on 8091 inside the container network. Do not publish it on the host.
# llama-server listens on 127.0.0.1:8092 and is not exposed.

FROM python:3.12-slim-bookworm

ARG LLAMA_CPP_VERSION=b11721
ARG LLAMA_CPP_SHA256=68c7a4dfb6a53e607b73c00c839bfc81c55141cd0a7697c0252e634190647c2f

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /tmp/llama.tar.gz \
        "https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_CPP_VERSION}/llama-${LLAMA_CPP_VERSION}-bin-ubuntu-x64.tar.gz" \
    && echo "${LLAMA_CPP_SHA256}  /tmp/llama.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/llama.tar.gz -C /opt \
    && mv "/opt/llama-${LLAMA_CPP_VERSION}" /opt/llama \
    && rm /tmp/llama.tar.gz \
    && useradd --system --create-home --home-dir /home/embedding --uid 10001 --shell /usr/sbin/nologin embedding \
    && mkdir -p /var/cache/huggingface \
    && chown embedding:embedding /var/cache/huggingface

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY embedding ./embedding

RUN uv sync --frozen --no-dev --no-cache \
    && chown -R embedding:embedding /app

ENV PATH="/app/.venv/bin:/opt/llama:${PATH}" \
    HOME=/home/embedding \
    HF_HOME=/var/cache/huggingface \
    HF_HUB_CACHE=/var/cache/huggingface/hub \
    EMBEDDING_PORT=8091 \
    EMBEDDING_MODEL=google/embeddinggemma-2 \
    EMBEDDING_GGUF=embeddinggemma-2-Q8_0.gguf \
    EMBEDDING_LLAMA_URL=http://127.0.0.1:8092 \
    EMBEDDING_CONTEXT=2048 \
    EMBEDDING_DIM=768 \
    EMBEDDING_MAX_TOKENS=1024 \
    EMBEDDING_BATCH_SIZE=16 \
    EMBEDDING_TIMEOUT=30 \
    LOG_LEVEL=info

EXPOSE 8091

USER embedding
CMD ["python", "-m", "embedding"]
