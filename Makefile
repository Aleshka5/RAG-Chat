.PHONY: config up up-cpu-only up-gpu down lint test test-common

# up / up-cpu-only build the ocr image target `cpu` (docker-compose.yml).
# up-gpu layers docker-compose.gpu.yml: target `cuda` and the GPU reservation.
# See services/ocr/Dockerfile.

config:
	podman compose config

up up-cpu-only:
	podman compose up --build -d

# Requires a GPU and the NVIDIA driver. The override builds the cuda target
# and reserves the device for ocr.
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
