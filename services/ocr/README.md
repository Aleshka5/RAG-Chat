# OCR

Внутренний сервис распознавания одной страницы. Контракт — `docs/openapi-internal.yaml`, поведение — `docs/internal-services.md`. Сервис слушает только сеть `rag_internal`. Порт на хост не публикуется.

## Модель

`OCR_MODEL=surya-ocr-2`.

Движок: **Surya OCR 2** через **llama.cpp**, одна модель на английский и русский.

При старте процесса, до открытия порта, скачиваются `surya-2.gguf` и `surya-2-mmproj.gguf` из `datalab-to/surya-ocr-2-gguf` и поднимается `llama-server` на `127.0.0.1:8092`. Этот порт в сеть `rag_internal` не публикуется. Число потоков и потолок памяти llama-server не задаются. Рассуждение модели выключено (`--reasoning off`): иначе Qwen3.5 пишет `<think>` до конца бюджета страницы. Повторяющийся хвост останавливает генерацию сразу, слот освобождается, и страница не ждёт `OCR_TIMEOUT`.

Пока llama-server не здоров, процесс не слушает `OCR_PORT`, и проверка готовности не проходит. `GET /health` после старта уже означает, что модель загружена. Если загрузка не удалась, процесс завершается. GPU не требуется. Цель образа по умолчанию — `cpu` (пин-бинарник). Цель `cuda` ставит тот же сервис на `ghcr.io/ggml-org/llama.cpp:server-cuda12`; её собирает `make up-gpu`. Контракт от этого не меняется.

Режим работы задаёт `OCR_LLAMA_NGL` — значение флага `-ngl` у llama-server: `-1` или `999` кладут все слои на GPU, `0` оставляет чистый CPU, промежуточное N выгружает часть слоёв. Один и тот же образ годится для обоих режимов, пересборка не нужна. По умолчанию `999`, как и раньше, поэтому существующие развёртывания не меняются; для CPU-цели задайте `OCR_LLAMA_NGL=0`.

Страницу из PDF сервис не рендерит. Ожидается PNG, который собрал Processor. Другой декодируемый растр принимается. Неразобранное тело — `400` `validation_error`.

Пустой `text` — успешный `200`, не ошибка.

## HTTP

`POST /ocr`, `multipart/form-data`, поле `image`.

```json
{
  "text": "распознанный текст",
  "confidence": 0.92,
  "processing_time_ms": 340
}
```

`confidence` — число от 0 до 1 или `null`, если движок не отдал оценку. `processing_time_ms` — время работы движка, целое ≥ 0.

Бюджет разбора — `OCR_TIMEOUT` секунд (120). По истечении сервис отвечает `504`:

```json
{"error": {"code": "upstream_timeout", "message": "OCR timed out"}}
```

`GET /health` → `{"status":"ok"}`.

Необязательный заголовок `X-Request-Id` (UUID) возвращается в ответе. Если его нет или он не UUID, сервис подставляет новый UUID.

## Переменные

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `OCR_PORT` | `8090` | Порт внутри сети. |
| `OCR_MODEL` | `surya-ocr-2` | Surya OCR 2. Другое значение не даёт процессу стартовать. |
| `OCR_TIMEOUT` | `120` | Секунды на один разбор. |
| `OCR_LLAMA_URL` | `http://127.0.0.1:8092` | llama-server внутри контейнера. |
| `OCR_LLAMA_NGL` | `999` | Слоёв на GPU: `-1`/`999` — все, `0` — CPU. Допустимо `-1..999`. |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error`. |

Неверное значение пишется в лог только именем переменной.

## Запуск

Из каталога `services/ocr`:

```bash
uv sync
uv run python -m ocr_service
```

Образ (порт наружу не пробрасывается):

```bash
podman build -f Dockerfile --target cpu -t ocr .
podman build -f Dockerfile --target cuda -t ocr:cuda .
```

## Тесты

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest
```

Тесты подставляют фальшивый читатель страницы и не скачивают веса. Боевой вход `python -m ocr_service` поднимает `llama-server` с `surya-2.gguf` и `surya-2-mmproj.gguf`.
