# Internal OCR service. Listens on OCR_PORT (8090) inside the container network.
# The port is not published on the host; compose attaches the container to rag_internal.
FROM python:3.12-slim-bookworm

# Paddle and OpenCV need these shared libraries at runtime.
# libgomp1 / libgfortran5: Paddle CPU inference.
# libgl1, libglib2.0-0, libsm6, libxext6, libxrender1: opencv-python.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgfortran5 \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin ocr

WORKDIR /app
# One core per process. PaddleOCR 2.10 otherwise calls
# set_cpu_math_library_num_threads(10). OMP_NUM_THREADS alone does not
# replace that call, and an unset OpenMP pool takes the host CPU count
# on the request thread. Concurrent pages are separate processes.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:${PATH}" \
    HOME=/home/ocr \
    OCR_PORT=8090 \
    OCR_MODEL=paddleocr_multilingual \
    OCR_TIMEOUT=30 \
    LOG_LEVEL=info \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && chown -R ocr:ocr /app /home/ocr

USER ocr
EXPOSE 8090

# Model download happens at process start. The process opens the port only after that.
# Podman's default OCI format drops HEALTHCHECK; `podman build --format docker` keeps it.
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
    CMD python -c "import os, urllib.request; p=os.environ.get('OCR_PORT','8090'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=4)"

CMD ["python", "-m", "ocr_service"]
