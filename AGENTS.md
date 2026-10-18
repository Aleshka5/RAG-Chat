# Правила разработки

Один репозиторий. Frontend, HTTP-сервисы, воркеры, `rag-edge`, OCR, адаптер эмбеддингов, compose и спецификация живут здесь. Отдельный репозиторий под UI, эмбеддер или воркер не заводится. Auth Gateway и LLM в этот репозиторий не переносятся.

Норма поведения системы — каталог `docs/`. Этот файл задаёт, чем писать код. Если расходятся форма HTTP и текст, побеждает `docs/openapi.yaml` и `docs/openapi-internal.yaml`.

## Раскладка

```text
AGENTS.md
Makefile
pyproject.toml          # uv workspace
uv.lock
services/
  file-collector/       # FastAPI
  processor/            # воркер очереди
  deletion-worker/      # воркер очереди
  chat/                 # FastAPI
  ocr/                  # FastAPI
  embedding/            # FastAPI, перед llama-server
  rag-edge/             # FastAPI
frontend/               # Vite
deploy/                 # Containerfile и podman compose
docs/
```

Общий Python-код, если он появится, лежит в workspace-пакете внутри этого дерева, не в соседнем репозитории.

## Чем пользоваться

| Задача | Инструмент |
|--------|------------|
| Контейнеры и локальный стенд | Podman. Команда — `podman compose`, файл — `deploy/compose.yaml`. Docker CLI и `docker compose` не используются. |
| Образ | `Containerfile`, сборка через `podman build`. |
| Зависимости Python | `uv`. Зафиксированный `uv.lock` коммитится. `pip`, Poetry и PDM как способ установки не используются. |
| Команды разработки | Корневой `Makefile`. Агент и человек вызывают `make`, а не сырые команды стенда. |
| Стиль Python | `ruff check` и `ruff format`. Black, isort и flake8 рядом не ставятся. |
| HTTP на Python | FastAPI. Это file-collector, chat, ocr, embedding и rag-edge. |
| Воркеры | Тот же Python и тот же `uv`, без HTTP-порта. |
| Frontend | Vite. UI — React, Tailwind CSS, Zustand, PDF.js. Сборщик другой не подключается. Зависимости frontend — npm, lockfile коммитится. |

Цели Makefile, которые остаются стабильными:

| Цель | Действие |
|------|----------|
| `make lint` | `ruff check`, `ruff format --check`, проверка frontend. |
| `make test` | Тесты Python через `uv` и `npm test` во `frontend/`. |
| `make up` | `podman compose` из `deploy/compose.yaml`. |
| `make down` | Остановить тот же стенд. |

Секреты в репозиторий и в логи не попадают. Порты приложения на хост compose не публикует: снаружи только путь через Auth Gateway, описанный в `docs/gateway.md`.

## Эмбеддинги

Считать вектор через PyTorch в этом сервисе не нужно. Инференс текста — `llama-server` из llama.cpp внутри контейнера `embedding`. Сборка должна знать архитектуру `gemma-embedding2`. Контракт `POST /embed` остаётся на FastAPI: префиксы, размер пачки и проверка вектора. Processor и Chat к llama-server не ходят. Подробности — в `docs/internal-services.md`.

Веса float16 не загружать. Файл проектора изображения и звука не загружать.
