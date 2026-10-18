from __future__ import annotations

import os
from pathlib import Path

from tokenizers import Tokenizer

from processor.logging import get_logger

DEFAULT_EMBEDDING_MODEL = "google/embeddinggemma-2"
# ggml-org/embeddinggemma-2-GGUF .src_sha PRIMARY, the tokenizer revision of that GGUF.
TOKENIZER_REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"
TOKENIZER_REVISIONS = {DEFAULT_EMBEDDING_MODEL: TOKENIZER_REVISION}
BAKED_TOKENIZER = Path("/app/tokenizer/tokenizer.json")


class ModelTokenizer:
    """Token ids from ``tokenizer.json`` of ``EMBEDDING_MODEL``.

    Windows are content tokens (``add_special_tokens=False``). The embedding
    service applies the document prefix and the model sees special tokens on
    that prefixed string, not on each PDF page.
    """

    def __init__(self, tokenizer: Tokenizer) -> None:
        self._tokenizer = tokenizer

    def encode(self, text: str) -> list[int]:
        return list(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def decode(self, token_ids: list[int]) -> str:
        return self._tokenizer.decode(list(token_ids), skip_special_tokens=True)


def load_tokenizer(model: str) -> ModelTokenizer:
    path = resolve_tokenizer_file(model)
    get_logger().info(
        "loaded tokenizer",
        extra={"embedding_model": model, "tokenizer_file": path.name},
    )
    return ModelTokenizer(Tokenizer.from_file(str(path)))


def resolve_tokenizer_file(model: str) -> Path:
    override = os.environ.get("TOKENIZER_JSON")
    if override:
        path = Path(override)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    if model == DEFAULT_EMBEDDING_MODEL and BAKED_TOKENIZER.is_file():
        return BAKED_TOKENIZER
    from huggingface_hub import hf_hub_download

    downloaded = hf_hub_download(
        repo_id=model,
        filename="tokenizer.json",
        revision=TOKENIZER_REVISIONS.get(model),
    )
    return Path(downloaded)
