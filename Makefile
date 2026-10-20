.PHONY: config up up-cpu-only up-gpu down lint test test-common

# CPU and GPU variants of the stand. The llama.cpp variant baked into the ocr
# image is selected by the compose file, not here:
#   up / up-cpu-only  -> docker-compose.yml (LLAMA_BUILD=cpu, the default)
#   up-gpu            -> docker-compose.yml + docker-compose.gpu.yml (LLAMA_BUILD=cuda)
# See services/ocr/Dockerfile for the two llama.cpp build stages.

config:
	podman compose config

up:
	podman compose up --build -d

# CPU build of the ocr service (default llama.cpp prebuilt binary).
up-cpu-only:
	podman compose up --build -d

# GPU build of the ocr service. Requires a GPU + NVIDIA driver on the host; the
# gpu override file builds the CUDA variant and reserves the device for ocr.
up-gpu:
	podman compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d

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
