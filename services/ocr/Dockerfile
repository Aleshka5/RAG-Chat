# Internal OCR service. Listens on OCR_PORT (8090) inside the container network.
# The port is not published on the host; compose attaches the container to rag_internal.
# llama-server listens on 127.0.0.1:8092 and is not exposed.
#
# Two targets. Buildah skips stages the target does not use, so `cpu` does not
# pull the CUDA image:
#   cpu  — pinned b11721 binary on python:3.12-slim-bookworm.
#          `make up` / `make up-cpu-only`. A build without --target
#          is this same image (stage `default`).
#   cuda — this service installed on the local
#          ghcr.io/ggml-org/llama.cpp:server-cuda12 image (CUDA 12.8 runtime).
#          `make up-gpu`. libcudart and libcublas stay in that image;
#          llama-server and the ggml libraries are moved to /opt/llama.

# ---------------------------------------------------------------------------
# cpu: pinned CPU binary.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS llama-cpu

ARG LLAMA_CPP_VERSION=b11721
ARG LLAMA_CPP_SHA256=68c7a4dfb6a53e607b73c00c839bfc81c55141cd0a7697c0252e634190647c2f

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /tmp/llama.tar.gz \
        "https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_CPP_VERSION}/llama-${LLAMA_CPP_VERSION}-bin-ubuntu-x64.tar.gz" \
    && echo "${LLAMA_CPP_SHA256}  /tmp/llama.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/llama.tar.gz -C /opt \
    && mv "/opt/llama-${LLAMA_CPP_VERSION}" /opt/llama \
    && rm /tmp/llama.tar.gz

FROM python:3.12-slim-bookworm AS cpu

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin ocr \
    && mkdir -p /var/cache/huggingface \
    && chown ocr:ocr /var/cache/huggingface

COPY --from=llama-cpu /opt/llama /opt/llama
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

WORKDIR /app
# No thread count and no memory ceiling. llama.cpp takes the cores it is given.
# OCR_TIMEOUT is not baked in: compose and the process default (120) must win.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:/opt/llama:${PATH}" \
    HOME=/home/ocr \
    HF_HOME=/var/cache/huggingface \
    HF_HUB_CACHE=/var/cache/huggingface/hub \
    OCR_PORT=8090 \
    OCR_MODEL=surya-ocr-2 \
    OCR_LLAMA_URL=http://127.0.0.1:8092 \
    LOG_LEVEL=info \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && chown -R ocr:ocr /app /home/ocr

EXPOSE 8090

# Weights download at process start. The port opens only after llama-server is healthy.
# Podman's default OCI format drops HEALTHCHECK; `podman build --format docker` keeps it.
HEALTHCHECK --interval=30s --timeout=5s --start-period=900s --retries=3 \
    CMD python -c "import os, urllib.request; p=os.environ.get('OCR_PORT','8090'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=4)"

ENTRYPOINT ["/entrypoint.sh"]

# ---------------------------------------------------------------------------
# cuda: Python service on the CUDA runtime image. Selected with --target cuda.
#
# server-cuda12 is nvidia/cuda 12.8 on Ubuntu 24.04. llama-server and libggml*.so
# live in /app; libcudart and libcublas stay in the CUDA runtime paths, so the
# binary is moved rather than copied onto Debian. The base image sets
# LLAMA_ARG_HOST=0.0.0.0 and LLAMA_ARG_PORT=8080, which llama.cpp would apply.
# Python 3.12 is not in the runtime image.
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
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin ocr \
    && mkdir -p /var/cache/huggingface \
    && chown ocr:ocr /var/cache/huggingface

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

WORKDIR /app
# Keep the CUDA library path from the base image and add the ggml libraries.
# Clear the image's 0.0.0.0:8080 defaults so llama-server stays on 127.0.0.1:8092.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON=python3 \
    PATH="/app/.venv/bin:/opt/llama:${PATH}" \
    LD_LIBRARY_PATH=/opt/llama:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64 \
    LLAMA_ARG_HOST=127.0.0.1 \
    LLAMA_ARG_PORT=8092 \
    HOME=/home/ocr \
    HF_HOME=/var/cache/huggingface \
    HF_HUB_CACHE=/var/cache/huggingface/hub \
    OCR_PORT=8090 \
    OCR_MODEL=surya-ocr-2 \
    OCR_LLAMA_URL=http://127.0.0.1:8092 \
    LOG_LEVEL=info \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && chown -R ocr:ocr /app /home/ocr

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=900s --retries=3 \
    CMD python -c "import os, urllib.request; p=os.environ.get('OCR_PORT','8090'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=4)"

# Replaces the base image entrypoint (/app/llama-server); those files now live in /opt/llama.
ENTRYPOINT ["/entrypoint.sh"]

# `podman build` without --target builds this stage and skips cuda.
FROM cpu AS default
