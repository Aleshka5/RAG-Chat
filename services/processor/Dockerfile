FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TOKENIZER_JSON=/app/tokenizer/tokenizer.json

# The service pins rag-common at ../../packages/rag-common, so the image mirrors the
# repository layout under /app: /app/services/processor sits beside
# /app/packages/rag-common. Build context is the repository root.
WORKDIR /app/services/processor

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin processor

COPY packages/rag-common/pyproject.toml /app/packages/rag-common/pyproject.toml
COPY packages/rag-common/src /app/packages/rag-common/src
COPY services/processor/pyproject.toml services/processor/uv.lock services/processor/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/processor/src ./src
RUN uv sync --frozen --no-dev \
    && mkdir -p /app/tokenizer \
    && /app/services/processor/.venv/bin/python -c "from huggingface_hub import hf_hub_download; import shutil; p=hf_hub_download('google/embeddinggemma-2','tokenizer.json',revision='914f7f89142e33e77833254d9c9b90c3cef7303b'); shutil.copy(p,'/app/tokenizer/tokenizer.json')" \
    && chown -R processor:processor /app

USER processor
CMD ["/app/services/processor/.venv/bin/python", "-m", "processor"]
