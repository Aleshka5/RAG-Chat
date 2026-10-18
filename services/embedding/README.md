# Embedding

Внутренний сервис векторов для RAG Chat. Слушает `POST /embed` и `GET /health` в сети `rag_internal`. Снаружи хоста порт не публикуется.

Норма: `docs/openapi-internal.yaml`, `docs/internal-services.md`, `docs/configuration.md`.

Модель в ответе — `google/embeddinggemma-2`. Вектор — 768 чисел после mean pooling и L2-нормализации. Усечения до 512, 256 или 128 нет.

Считает вектор `llama-server` из llama.cpp (архитектура `gemma-embedding2`) на `127.0.0.1:8092`. FastAPI на `EMBEDDING_PORT` (8091) клеит префикс и проверяет вектор. В сеть приложения виден только FastAPI. PyTorch и `model.safetensors` не используются. F16 и `mmproj` не загружаются.

Веса по умолчанию: `ggml-org/embeddinggemma-2-GGUF`, файл `embeddinggemma-2-Q8_0.gguf`. Токены считает `tokenizer.json` ревизии `google/embeddinggemma-2`, указанной в `.src_sha` этого GGUF (`914f7f89142e33e77833254d9c9b90c3cef7303b`). В счёт входят `<bos>` и `<eos>` из post-processor этого файла.

## Префиксы

Один `input_type` на пачку.

| `input_type` | Строка для модели |
|--------------|-------------------|
| `query` | `task: question answering \| query: {text}` |
| `document` | `title: {title} \| text: {text}` |

`title` — имя файла. Для `document` он обязателен, для `query` запрещён, в том числе пустой и `null`. Края `texts` и `title` снимаются; пустая строка после `strip` — `400 validation_error`. Сервис сам текст не обрезает: если после префикса токенов больше `EMBEDDING_MAX_TOKENS` (1024), ответ `400`.

Пачка — от 1 до `EMBEDDING_BATCH_SIZE` текстов. По умолчанию 16. Поле `model`, если передано, должно совпасть с `EMBEDDING_MODEL`.

`embeddings[i]` соответствует `texts[i]`. Длина не равна `EMBEDDING_DIM`, NaN, бесконечность или нулевая норма — `502 upstream_failed`. Если норма не 1, сервис нормализует сам. Таймаут пачки — `504 upstream_timeout`.

`GET /health` отвечает `200` и `{"status":"ok"}` только после загрузки GGUF. Неудачная загрузка останавливает процесс. Необязательный `X-Request-Id` (UUID) возвращается; иначе выдаётся новый UUID.

## Переменные

| Переменная | По умолчанию |
|------------|----------------|
| `EMBEDDING_PORT` | `8091` |
| `EMBEDDING_MODEL` | `google/embeddinggemma-2` |
| `EMBEDDING_GGUF` | `embeddinggemma-2-Q8_0.gguf` |
| `EMBEDDING_LLAMA_URL` | `http://127.0.0.1:8092` |
| `EMBEDDING_CONTEXT` | `2048` |
| `EMBEDDING_DIM` | `768` |
| `EMBEDDING_MAX_TOKENS` | `1024` |
| `EMBEDDING_BATCH_SIZE` | `16` |
| `EMBEDDING_TIMEOUT` | `30` |
| `LOG_LEVEL` | `info` |

`EMBEDDING_LLAMA_URL` остаётся на `127.0.0.1` или `localhost`. Неверное значение не даёт процессу стартовать: в лог пишется имя переменной, без значения. `EMBEDDING_CONTEXT`, `--batch-size` и `--ubatch-size` одинаковые. `--parallel` у llama-server равен 1. Бюджет памяти контейнера — около 2 ГиБ.

## Запуск и проверка

Зависимости ставит `uv`, не pip. `uv.lock` фиксирует версии. `requirements.txt` — тот же список для чтения.

```bash
cd services/embedding
uv sync --group dev
uv run ruff check
uv run ruff format --check
uv run pytest
```

Образ собирается Podman из `Containerfile` (тот же текст, что `Dockerfile`):

```bash
podman build -f services/embedding/Containerfile -t embedding services/embedding
```

В образе два процесса: `llama-server` только на `127.0.0.1:8092` и `python -m embedding` на 8091. Порт 8092 наружу не открывается, порт 8091 на хост compose не публикует. Первый запрос не ждёт загрузки весов: она заканчивается до готовности `/health`.

Тесты ходят в фиктивный энкодер и не скачивают GGUF. Боевой вход `python -m embedding` вызывает `load_model`: скачивание текстового Q8_0, запуск `llama-server --embeddings --pooling mean` и ожидание его `/health`.
