# Internal embedding image.
# Build: podman build -f Containerfile -t embedding .
# FastAPI listens on 8091 inside the container network. Do not publish it on the host.
# llama-server listens on 127.0.0.1:8092 and is not exposed.
#
# Two targets. Buildah skips stages the target does not use, so `cpu` does not
# pull the CUDA image:
#   cpu  — pinned b11721 CPU binary on python:3.12-slim-bookworm. A build
#          without --target is this same image (stage `default`).
#   cuda — this service installed on ghcr.io/ggml-org/llama.cpp:server-cuda12
#          (CUDA 12.8 runtime). libcudart and libcublas stay in that image;
#          llama-server and the ggml libraries are moved to /opt/llama.
# Both targets pass `-ngl $EMBEDDING_LLAMA_NGL` (default 999 = every layer on
# the GPU, -1 is the upstream synonym). A CPU-only build ignores the flag.

# ---------------------------------------------------------------------------
# cpu: pinned CPU binary. Default target.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS cpu

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
    EMBEDDING_MMPROJ=mmproj-embeddinggemma-2-Q8_0.gguf \
    EMBEDDING_LLAMA_URL=http://127.0.0.1:8092 \
    EMBEDDING_CONTEXT=2048 \
    EMBEDDING_DIM=768 \
    EMBEDDING_MAX_TOKENS=1024 \
    EMBEDDING_BATCH_SIZE=16 \
    EMBEDDING_MAX_IMAGES=4 \
    EMBEDDING_MAX_IMAGE_BYTES=10485760 \
    EMBEDDING_TIMEOUT=30 \
    LOG_LEVEL=info

EXPOSE 8091

USER embedding
CMD ["python", "-m", "embedding"]

# ---------------------------------------------------------------------------
# cuda: Python service on the CUDA runtime image. Selected with --target cuda.
#
# server-cuda12 is nvidia/cuda 12.8 on Ubuntu 24.04. llama-server and the ggml
# libraries live in /app; libcudart and libcublas stay in the CUDA runtime
# paths, so the binaries are moved rather than copied onto Debian. The base
# image sets LLAMA_ARG_HOST=0.0.0.0 and LLAMA_ARG_PORT=8080, which llama.cpp
# would apply as defaults, and it has no Python. Its inherited ENTRYPOINT
# (/app/llama-server), HEALTHCHECK (:8080) and EXPOSE 8080 are neutralised
# below; the stale EXPOSE cannot be removed, only overridden by 8091.
# ---------------------------------------------------------------------------
FROM ghcr.io/ggml-org/llama.cpp:server-cuda12 AS cuda

RUN mkdir -p /opt/llama \
    && cp -aL /app/. /opt/llama/ \
    && chmod -R a+rX /opt/llama \
    && rm -rf /app \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates libgomp1 python3 util-linux \
    && python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else "python3 must be 3.12")' \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --home-dir /home/embedding --uid 10001 --shell /usr/sbin/nologin embedding \
    && mkdir -p /var/cache/huggingface \
    && chown embedding:embedding /var/cache/huggingface

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

WORKDIR /app

# Keep the CUDA library path from the base image and add the ggml libraries.
# Clear the image's 0.0.0.0:8080 defaults so llama-server stays on 127.0.0.1:8092.
# UV_PYTHON pins the venv to the system interpreter; a uv-managed copy would
# land under /root/.local and break for the unprivileged user. It must be set
# before `uv sync` runs, so this block precedes the COPY/RUN below.
ENV UV_PYTHON=python3 \
    PATH="/app/.venv/bin:/opt/llama:${PATH}" \
    LD_LIBRARY_PATH=/opt/llama:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64 \
    LLAMA_ARG_HOST=127.0.0.1 \
    LLAMA_ARG_PORT=8092 \
    HOME=/home/embedding \
    HF_HOME=/var/cache/huggingface \
    HF_HUB_CACHE=/var/cache/huggingface/hub \
    EMBEDDING_PORT=8091 \
    EMBEDDING_MODEL=google/embeddinggemma-2 \
    EMBEDDING_GGUF=embeddinggemma-2-Q8_0.gguf \
    EMBEDDING_MMPROJ=mmproj-embeddinggemma-2-Q8_0.gguf \
    EMBEDDING_LLAMA_URL=http://127.0.0.1:8092 \
    EMBEDDING_CONTEXT=2048 \
    EMBEDDING_DIM=768 \
    EMBEDDING_MAX_TOKENS=1024 \
    EMBEDDING_BATCH_SIZE=16 \
    EMBEDDING_MAX_IMAGES=4 \
    EMBEDDING_MAX_IMAGE_BYTES=10485760 \
    EMBEDDING_TIMEOUT=30 \
    LOG_LEVEL=info

COPY pyproject.toml uv.lock README.md ./
COPY embedding ./embedding

RUN uv sync --frozen --no-dev --no-cache \
    && chown -R embedding:embedding /app

EXPOSE 8091

# The base image probes localhost:8080, where nothing listens here.
HEALTHCHECK NONE

USER embedding
# The base image entrypoint is /app/llama-server (now in /opt/llama and started
# by the loader with -ngl). Reset it so CMD, identical to the cpu stage, runs.
ENTRYPOINT []
CMD ["python", "-m", "embedding"]

# `podman build` without --target builds this stage and skips cuda.
FROM cpu AS default
