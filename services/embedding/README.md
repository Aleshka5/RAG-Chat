# Embedding

Внутренний сервис векторов для RAG Chat. Слушает `POST /embed`, `POST /embed/image` и `GET /health` в сети `rag_internal`. Снаружи хоста порт не публикуется.

Норма: `docs/openapi-internal.yaml`, `docs/internal-services.md`, `docs/configuration.md`.

Модель в ответе — `google/embeddinggemma-2`. Вектор — 768 чисел после mean pooling и L2-нормализации. Усечения до 512, 256 или 128 нет.

Считает вектор `llama-server` из llama.cpp (архитектура `gemma-embedding2`) на `127.0.0.1:8092`. FastAPI на `EMBEDDING_PORT` (8091) клеит текстовый префикс и проверяет вектор. В сеть приложения виден только FastAPI. PyTorch и `model.safetensors` не используются. F16-весов текста нет. Проектор изображения загружается, кодировщик звука — нет.

Веса по умолчанию: `ggml-org/embeddinggemma-2-GGUF`, файлы `embeddinggemma-2-Q8_0.gguf` и проектор `mmproj-embeddinggemma-2-Q8_0.gguf` (около 530 МиБ, переменная `EMBEDDING_MMPROJ`). Обе ревизии закреплены в `embedding/constants.py`. Токены считает `tokenizer.json` ревизии `google/embeddinggemma-2`, указанной в `.src_sha` этого GGUF (`914f7f89142e33e77833254d9c9b90c3cef7303b`). В счёт входят `<bos>` и `<eos>` из post-processor этого файла.

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

## Изображения

`POST /embed/image` принимает ту же модель и то же пространство, что `/embed`:

```json
{"images": ["<base64 PNG>", "<base64 JPEG>"]}
```

Ответ совпадает по форме с `/embed`: `embeddings[i]` для `images[i]`, `dimension` = 768. Текстовый вопрос сравнивается с картинкой напрямую, отдельной коллекции не нужно.

- Префикс не клеится: карточка модели требует передавать изображения, видео и звук без инструкции. Поэтому `texts`, `input_type` и `title` в этом запросе — `400`, а не тихий игнор.
- Формат определяется по первым байтам: PNG, JPEG, WebP, GIF. Заявленный клиентом Content-Type не читается.
- Одно изображение — не больше `EMBEDDING_MAX_IMAGE_BYTES` (10 МиБ) после декодирования, пачка — не больше `EMBEDDING_MAX_IMAGES` (4) штук.
- Бюджет токенов не проверяется: одно изображение занимает около 280 токенов контекста модели, и текстовая мера их не считает. Граница — число изображений.
- Битые байты, прошедшие проверку магии, дают `502 upstream_failed`: разбирает их llama-server.

Маркер изображения — не константа. Свежие сборки llama-server выдают на процесс случайный `media_marker` и публикуют его в `GET /props`; `LlamaEncoder` читает его один раз и кэширует. Захардкоженный `<__media__>` остаётся только запасным вариантом для сборки, которая маркер не публикует.

## Переменные

| Переменная | По умолчанию |
|------------|----------------|
| `EMBEDDING_PORT` | `8091` |
| `EMBEDDING_MODEL` | `google/embeddinggemma-2` |
| `EMBEDDING_MMPROJ` | `mmproj-embeddinggemma-2-Q8_0.gguf` |
| `EMBEDDING_GGUF` | `embeddinggemma-2-Q8_0.gguf` |
| `EMBEDDING_LLAMA_URL` | `http://127.0.0.1:8092` |
| `EMBEDDING_CONTEXT` | `2048` |
| `EMBEDDING_DIM` | `768` |
| `EMBEDDING_MAX_TOKENS` | `1024` |
| `EMBEDDING_BATCH_SIZE` | `16` |
| `EMBEDDING_MAX_IMAGES` | `4` |
| `EMBEDDING_MAX_IMAGE_BYTES` | `10485760` |
| `EMBEDDING_TIMEOUT` | `30` |
| `EMBEDDING_LLAMA_NGL` | `999` |
| `LOG_LEVEL` | `info` |

`EMBEDDING_LLAMA_NGL` уходит в `llama-server` как `-ngl`: сколько слоёв модели считать на GPU. `999` (по умолчанию) — все слои, `-1` — то же самое в терминах llama.cpp, `0` — только CPU. Допустимый диапазон `-1..999`, иное значение не даёт процессу стартовать. На CPU-сборке образа флаг ничего не меняет: бинарник без CUDA его игнорирует.

`EMBEDDING_LLAMA_URL` остаётся на `127.0.0.1` или `localhost`. Неверное значение не даёт процессу стартовать: в лог пишется имя переменной, без значения. `EMBEDDING_CONTEXT`, `--batch-size` и `--ubatch-size` одинаковые. `--parallel` у llama-server равен 1. Бюджет памяти контейнера — около 3 ГиБ: проектор добавляет примерно 740 МиБ видеопамяти или около 600 МиБ RSS на CPU, измерено на одном экземпляре модели.

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

Тесты ходят в фиктивный энкодер и не скачивают GGUF. Боевой вход `python -m embedding` вызывает `load_model`: скачивание текстового Q8_0, запуск `llama-server --embeddings --pooling mean` и ожидание его `/health`.
