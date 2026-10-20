# Internal OCR service. Listens on OCR_PORT (8090) inside the container network.
# The port is not published on the host; compose attaches the container to rag_internal.
#
# Multi-stage build. Two llama.cpp variants are prepared as stages and one is chosen
# at build time by the LLAMA_BUILD argument (default: cpu):
#   cpu  - CPU prebuilt binary, pinned to b11721. The default; `make up` / `up-cpu-only`.
#   cuda - GPU variant from the local ghcr.io/ggml-org/llama.cpp:server-cuda12 image
#          (CUDA 12.8, verified to see the GPU). `make up-gpu`.
#
# buildah (the podman-compose build backend) expands ARG in RUN but not reliably
# in COPY --from, so each variant stage normalises its payload to /src and the
# final stage copies both from the literal stage names and keeps only the one
# named by LLAMA_BUILD. The Python service is identical either way.

# ---------------------------------------------------------------------------
# Stage: llama-cpu - pinned CPU prebuilt binary.
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
    && rm /tmp/llama.tar.gz \
    && mkdir -p /src && cp -a /opt/llama/. /src/

# ---------------------------------------------------------------------------
# Stage: llama-cuda - local CUDA 12.8 build.
#
# Reached only for LLAMA_BUILD=cuda; it needs the image in the local store, so it
# works fully offline. CUDA runtime libs (libggml-cuda.so, libcudart) ship inside
# this image; the driver API (libcuda) comes from the host at container start via
# the compose GPU device reservation.
# ---------------------------------------------------------------------------
ARG LLAMA_BUILD=cpu
FROM ghcr.io/ggml-org/llama.cpp:server-cuda12 AS llama-cuda

RUN mkdir -p /src && cp -a /app/. /src/

# ---------------------------------------------------------------------------
# Final: the Python OCR service plus the selected llama.cpp variant.
#
# trixie (GLIBC 2.41), not bookworm (2.36): the cuda stage is an Ubuntu 24.04
# build whose libllama-*.so / libstdc++ need GLIBC 2.38. trixie satisfies both
# variants; bookworm would only satisfy the cpu build.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-trixie

ARG LLAMA_BUILD=cpu

# libgomp1 backs the CPU build's OpenMP runtime; the CUDA build is self-contained.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin ocr \
    && mkdir -p /var/cache/huggingface \
    && chown ocr:ocr /var/cache/huggingface

# Both variant payloads are copied from their literal stage names (no ARG in
# --from), then only the one selected by LLAMA_BUILD is kept in /opt/llama.
COPY --from=llama-cpu /src /llama-cpu
COPY --from=llama-cuda /src /llama-cuda
RUN mkdir -p /opt/llama \
    && case "${LLAMA_BUILD}" in \
        cuda) cp -a /llama-cuda/. /opt/llama/ ;; \
        *)    cp -a /llama-cpu/. /opt/llama/ ;; \
    esac \
    && rm -rf /llama-cpu /llama-cuda

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

WORKDIR /app
# No thread count and no memory ceiling. llama.cpp takes the cores it is given.
# LD_LIBRARY_PATH=/opt/llama lets the cuda build find its own .so siblings; it is
# a no-op for the cpu build. libcuda (driver) is injected by the host at container
# start, so no extra path is needed for the driver.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:/opt/llama:${PATH}" \
    LD_LIBRARY_PATH=/opt/llama \
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

USER ocr
EXPOSE 8090

# Weights download at process start. The port opens only after llama-server is healthy.
# Podman's default OCI format drops HEALTHCHECK; `podman build --format docker` keeps it.
HEALTHCHECK --interval=30s --timeout=5s --start-period=900s --retries=3 \
    CMD python -c "import os, urllib.request; p=os.environ.get('OCR_PORT','8090'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=4)"

CMD ["python", "-m", "ocr_service"]
