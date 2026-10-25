# Embedding

Внутренний сервис векторов для RAG Chat. Слушает `POST /embed`, `POST /embed/image` и `GET /health` в сети `rag_internal`. Снаружи хоста порт не публикуется.

Норма: `docs/openapi-internal.yaml`, `docs/internal-services.md`, `docs/configuration.md`.

Модель в ответе — `google/embeddinggemma-2`. Вектор — 768 чисел после mean pooling и L2-нормализации. Усечения до 512, 256 или 128 нет.

Считает вектор `llama-server` из llama.cpp (архитектура `gemma-embedding2`) на `127.0.0.1:8092`. FastAPI на `EMBEDDING_PORT` (8091) клеит префикс и проверяет вектор. В сеть приложения виден только FastAPI. PyTorch и `model.safetensors` не используются. F16 не загружается. Проектор изображения `mmproj-embeddinggemma-2-Q8_0.gguf` (`EMBEDDING_MMPROJ`) передаётся в `llama-server` флагом `--mmproj`. Отдельный аудиопроектор не загружается.

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

## Изображения

`POST /embed/image` считает вектор картинки в то же пространство 768. Тело — `images`, массив base64 от 1 до `EMBEDDING_MAX_IMAGES` (4). Необязательный `model` такой же, как у `/embed`. Поля `texts`, `input_type` и `title` дают `400 validation_error`: у картинки нет префикса задачи.

Контейнер берётся только из сигнатуры: JPEG (`FF D8 FF`), PNG (`89 50 4E 47 0D 0A 1A 0A`), GIF (`GIF87a` / `GIF89a`), WebP (`RIFF` и `WEBP` на смещении 8). Другое, битый base64 и декодированный размер больше `EMBEDDING_MAX_IMAGE_BYTES` (10485760) — `400`, поле `images`. Сигнатура принята, а llama-server не декодировал файл, ответил ошибкой или проектор изображения не загружен — `502 upstream_failed`. Таймаут — `504 upstream_timeout`. `POST /embed` и `GET /health` при отсутствии проектора остаются доступны. Если переданы несколько из `texts`, `input_type`, `title`, `details.fields` называет каждое.

В `POST /v1/embeddings` уходит пачка без текста. У каждого элемента `input` один блок `content` с частью `image_url` и data-URI `data:image/<тип>;base64,<base64>`. Рядом `encoding_format` равен `float`. Ответ тот же, что у `/embed`: `embeddings[i]` соответствует `images[i]`, та же L2-проекция.

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
| `EMBEDDING_MAX_IMAGES` | `4` |
| `EMBEDDING_MAX_IMAGE_BYTES` | `10485760` |
| `EMBEDDING_MMPROJ` | `mmproj-embeddinggemma-2-Q8_0.gguf` |
| `EMBEDDING_TIMEOUT` | `30` |
| `EMBEDDING_LLAMA_NGL` | `999` |
| `LOG_LEVEL` | `info` |

`EMBEDDING_LLAMA_NGL` уходит в `llama-server` как `-ngl`: сколько слоёв модели считать на GPU. `999` (по умолчанию) — все слои, `-1` — то же самое в терминах llama.cpp, `0` — только CPU. Допустимый диапазон `-1..999`, иное значение не даёт процессу стартовать. На CPU-сборке образа флаг ничего не меняет: бинарник без CUDA его игнорирует.

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

Образ собирается Podman из `Containerfile` (тот же текст, что `Dockerfile`). В файле два target'а: `cpu` (он же `default`, сборка без `--target`) и `cuda`:

```bash
# CPU, по умолчанию
podman build -f services/embedding/Containerfile -t embedding services/embedding
# GPU: тот же сервис на ghcr.io/ggml-org/llama.cpp:server-cuda12
podman build -f services/embedding/Containerfile --target cuda -t embedding:gpu services/embedding
```

В `cuda`-сборке `llama-server` и библиотеки ggml из `/app` базового образа переносятся в `/opt/llama` (там же остаются `libcudart` и `libcublas` из CUDA runtime), `LLAMA_ARG_HOST`/`LLAMA_ARG_PORT` перекрываются на `127.0.0.1:8092`, Python ставится системный (`UV_PYTHON=python3`). Слои на GPU задаёт `EMBEDDING_LLAMA_NGL`.

В образе два процесса: `llama-server` только на `127.0.0.1:8092` и `python -m embedding` на 8091. Порт 8092 наружу не открывается, порт 8091 на хост compose не публикует. Первый запрос не ждёт загрузки весов: она заканчивается до готовности `/health`.

Тесты ходят в фиктивный энкодер и не скачивают GGUF. Боевой вход `python -m embedding` вызывает `load_model`: скачивание текстового Q8_0 и `mmproj-embeddinggemma-2-Q8_0.gguf`, запуск `llama-server --embeddings --pooling mean --mmproj` и ожидание его `/health`. Нет файла проектора — процесс не останавливается, `POST /embed/image` отвечает `502`.
