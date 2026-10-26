# File Collector

HTTP-сервис приёма PDF. Порт по умолчанию — `8081`.

Контракт: [docs/openapi.yaml](../../docs/openapi.yaml), [docs/api.md](../../docs/api.md), [docs/data-models.md](../../docs/data-models.md), [docs/messaging.md](../../docs/messaging.md). Образ собирается из `Containerfile` через `podman build`. `Dockerfile` повторяет тот же текст. Зависимости ставятся через `uv` и зафиксированы в `uv.lock`. `requirements.txt` — экспорт этого замка, не способ установки.

## Переменные

Обязательные, без значений по умолчанию: `MONGODB_URI`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `RABBITMQ_URL`.

| Переменная | По умолчанию |
|------------|----------------|
| `FILE_COLLECTOR_PORT` | `8081` |
| `MAX_UPLOAD_BYTES` | `524288000` (500 МиБ) |
| `S3_BUCKET` | `storage` |
| `S3_REGION` | `us-east-1` |
| `RABBITMQ_EXCHANGE` | `doc_events` |
| `RABBITMQ_DLX` | `doc_events_dlq` |
| `STALE_PROCESSING_SECONDS` | `900` |
| `LOG_LEVEL` | `info` |

При старте сервис создаёт бакет, индексы коллекции `files` и топологию RabbitMQ. Повторный старт данные не удаляет.

## Маршруты

| Метод | Путь | Ответ |
|-------|------|--------|
| `GET` | `/health` | `{"status":"ok"}` без проверки зависимостей и без `X-Auth-User-Id` |
| `POST` | `/api/files` | `202` карточка файла, публикация `doc.process` |
| `GET` | `/api/files` | список своих файлов без `deleted` |
| `GET` | `/api/files/{file_id}` | карточка; чужой и `deleted` — `404` |
| `GET` | `/api/files/{file_id}/content` | байты PDF; чужой, `deleted` и `deleting` — `404` |
| `DELETE` | `/api/files/{file_id}` | `202` и `doc.delete`; свежий `processing` — `409` |

Пользователь берётся только из `X-Auth-User-Id`. `X-User-Id` не аутентифицирует. `X-Auth-Role: BLOCKED` — `403`.

## Локально

```bash
cd services/file-collector
uv sync --all-groups
uv run ruff check
uv run ruff format --check
uv run pytest
```

Тесты ходят в FastAPI через подставные MongoDB, MinIO и RabbitMQ и не требуют стенда.
