FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TOKENIZER_JSON=/app/tokenizer/tokenizer.json

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin processor

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev \
    && mkdir -p /app/tokenizer \
    && /app/.venv/bin/python -c "from huggingface_hub import hf_hub_download; import shutil; p=hf_hub_download('google/embeddinggemma-2','tokenizer.json',revision='914f7f89142e33e77833254d9c9b90c3cef7303b'); shutil.copy(p,'/app/tokenizer/tokenizer.json')" \
    && chown -R processor:processor /app

USER processor
CMD ["uv", "run", "--no-dev", "--frozen", "python", "-m", "processor"]
