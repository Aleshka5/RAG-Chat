.PHONY: config up down lint test test-common

# This stack starts the RAG services only. OCR, embedding, LLM and image
# generation are owned by Switch-Service in the shared network models_network
# (Switch-Service/docs/models-network.md): there is no compose CPU/GPU switch
# here. The ocr/embedding images are built once with the `cuda` target and the
# running mode is chosen by OCR_LLAMA_NGL / EMBEDDING_LLAMA_NGL in the
# Switch-Service catalog, not by a make target.

config:
	podman compose config

up:
	podman compose up --build -d

down:
	podman compose down

test-common:
	cd packages/rag-common && uv run pytest

lint:
	cd packages/rag-common && uv run ruff check .
	cd packages/rag-common && uv run ruff format --check .
	@if [ -f frontend/package.json ]; then npm --prefix frontend run lint --if-present; fi

test: test-common
	@if [ -f frontend/package.json ]; then npm test --prefix frontend; fi
