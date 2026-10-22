"""Pinned EmbeddingGemma 2 identities.

The GGUF revision is the commit of ``ggml-org/embeddinggemma-2-GGUF`` whose
``.src_sha`` names the Hugging Face tokenizer revision. Token counts must use
that tokenizer and no other.
"""

MODEL_ID = "google/embeddinggemma-2"
GGUF_REPO = "ggml-org/embeddinggemma-2-GGUF"
GGUF_REVISION = "bfcd298762cc34d0357ece5ebdd31791a3a374d8"
DEFAULT_GGUF = "embeddinggemma-2-Q8_0.gguf"
TOKENIZER_REPO = "google/embeddinggemma-2"
TOKENIZER_REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"
TOKENIZER_FILE = "tokenizer.json"

DEFAULT_PORT = 8091
DEFAULT_LLAMA_URL = "http://127.0.0.1:8092"
DEFAULT_CONTEXT = 2048
DEFAULT_DIMENSION = 768
DEFAULT_MAX_TOKENS = 1024
DEFAULT_BATCH_SIZE = 16
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_LOG_LEVEL = "info"

# Layers offloaded to the GPU. 999 exceeds any real layer count, so llama.cpp
# keeps every layer on the accelerator; -1 means the same thing upstream.
# The value is passed to llama-server as `-ngl` and is inert without a GPU build.
DEFAULT_NGL = 999
NGL_MINIMUM = -1
NGL_MAXIMUM = 999

# llama.cpp b11721 is the first release train that contains gemma-embedding2
# (PR 30054, merged 2026-10-06) and is current for this service image.
LLAMA_CPP_VERSION = "b11721"
LOAD_TIMEOUT_SECONDS = 300.0
UNIT_NORM_TOLERANCE = 1e-3
