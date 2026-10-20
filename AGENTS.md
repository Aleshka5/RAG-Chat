# Правила разработки

Перед правкой кода читать [docs/README.md](docs/README.md).

Один репозиторий. Frontend, HTTP-сервисы, воркеры, `rag-edge`, OCR, адаптер эмбеддингов, compose и спецификация живут здесь. Отдельный репозиторий под UI, эмбеддер или воркер не заводится. Auth Gateway и LLM в этот репозиторий не переносятся.

Норма поведения системы — каталог `docs/`. Этот файл задаёт, чем писать код. Поведение за пределами `docs/` не придумывается.

## Приоритет при расхождении

1. Для формы HTTP-запросов и ответов приоритет у `docs/openapi.yaml` и `docs/openapi-internal.yaml`.
2. Для побочных эффектов, статусов и алгоритмов приоритет у профильного документа (`docs/api.md`, `docs/processing.md`, `docs/messaging.md`, `docs/data-models.md`).
3. `docs/review.md` ничего не предписывает. Размер пачки эмбеддингов — 16, как в `docs/configuration.md` и `docs/openapi-internal.yaml`, не 32.

## Раскладка

```text
AGENTS.md
Makefile
docker-compose.yml      # стенд, контексты от корня репозитория
.env.example
packages/
  rag-common/           # пакет rag_common
services/
  file-collector/       # FastAPI
  processor/            # воркер очереди
  deletion-worker/      # воркер очереди
  chat/                 # FastAPI
  ocr/                  # FastAPI
  embedding/            # FastAPI, перед llama-server
  rag-edge/             # FastAPI
frontend/               # Vite
docs/
```

Общий Python-код лежит в `packages/rag-common`, не в соседнем репозитории и не копируется в сервисы.

## Ветки и владение каталогами

Ветка — `cursor/<имя>-cc69`. Каталоги историй не пересекаются. Карта — в [docs/user-stories.md](docs/user-stories.md).

| История | Ветка | Каталог |
|---------|--------|---------|
| US-0 | `cursor/scaffold-common-cc69` | `packages/rag-common`, compose, Makefile, этот файл |
| US-1 | `cursor/rag-edge-cc69` | `services/rag-edge` |
| US-2 | `cursor/file-collector-cc69` | `services/file-collector` |
| US-3 | `cursor/processor-cc69` | `services/processor` |
| US-4 | `cursor/deletion-worker-cc69` | `services/deletion-worker` |
| US-5 | `cursor/ocr-cc69` | `services/ocr` |
| US-6 | `cursor/embedding-cc69` | `services/embedding` |
| US-7 | `cursor/chat-cc69` | `services/chat` |
| US-8 | `cursor/frontend-cc69` | `frontend` |
| US-9 | `cursor/retrieval-only-2bef` | `services/chat`, `frontend`, нормативные абзацы сценария в `docs/` |

## Чем пользоваться

| Задача | Инструмент |
|--------|------------|
| Контейнеры и локальный стенд | `docker-compose.yml` в корне. Проверка — `make config` (`podman compose config`). Поднятие — `make up` (`podman compose up --build`). Пример в `docs/deployment.md` тот же по составу; `podman compose -f docker-compose.yml` читает этот файл. |
| Зависимости Python | `uv`. Зафиксированный `uv.lock` коммитится. `pip`, Poetry и PDM как способ установки не используются. |
| Команды разработки | Корневой `Makefile`. Агент и человек вызывают `make`, а не сырые команды стенда. |
| Версия Python | 3.12. |
| Стиль Python | `ruff check` и `ruff format`. Black, isort и flake8 рядом не ставятся. |
| HTTP на Python | FastAPI. Это file-collector, chat, ocr, embedding и rag-edge. |
| Воркеры | Тот же Python 3.12 и тот же `uv`, без HTTP-порта. |
| Frontend | Vite. UI — React, TypeScript, Tailwind CSS, Zustand, PDF.js. Сборщик другой не подключается. Зависимости frontend — npm, lockfile коммитится. |

Цели Makefile, которые остаются стабильными:

| Цель | Действие |
|------|----------|
| `make config` | `docker compose config` |
| `make lint` | `ruff check`, `ruff format --check`, проверка frontend, когда каталог уже есть. |
| `make test` | Тесты Python через `uv` и `npm test` во `frontend/`, когда каталог уже есть. |
| `make test-common` | `pytest` в `packages/rag-common`. |
| `make up` | `docker compose up --build` |
| `make down` | Остановить тот же стенд. |

Секреты в репозиторий и в логи не попадают. Порты приложения на хост compose не публикует: снаружи только путь через Auth Gateway, описанный в `docs/gateway.md`. OCR и Embedding порт на хост не публикуют.

## Эмбеддинги

Считать вектор через PyTorch в этом сервисе не нужно. Инференс текста — `llama-server` из llama.cpp внутри контейнера `embedding`. Сборка должна знать архитектуру `gemma-embedding2`. Контракт `POST /embed` остаётся на FastAPI: префиксы, размер пачки и проверка вектора. Processor и Chat к llama-server не ходят. Подробности — в `docs/internal-services.md`.

Веса float16 не загружать. Файл проектора изображения и звука не загружать.
