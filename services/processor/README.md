# Processor

Воркер очереди `doc.process`. Читает PDF из MinIO, достаёт текст через PyMuPDF, для страниц без текстового слоя вызывает OCR, режет текст токенизатором EmbeddingGemma 2, считает эмбеддинги пачками и пишет точки в Qdrant.

Норма алгоритма — `docs/processing.md`, `docs/messaging.md`, `docs/data-models.md`. Этот каталог ей следует.

## Запуск

Процесс без HTTP-порта. Обязательные переменные: `MONGODB_URI`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `QDRANT_URL`, `RABBITMQ_URL`, `EMBEDDING_URL`, `OCR_URL`. Нет переменной — процесс не стартует и пишет в лог только её имя.

```bash
uv sync --all-groups
uv run python -m processor
```

Образ: `Containerfile` (тот же текст, что `Dockerfile`), сборка `podman build -f Containerfile`. Зависимости ставит `uv` из `uv.lock`. `requirements.txt` — экспорт тех же пакетов, канон — `uv.lock`.

На канале consumer **prefetch=1**. `PROCESSOR_CONCURRENCY` (по умолчанию 1) — число таких каналов, а не размер prefetch.

## Конвейер

1. Сообщение с неизвестной `schema_version` или битым JSON — `nack` без requeue. Чужой `user_id` или `s3_key` — то же, статус файла не меняется.
2. `ready`, `deleting`, `deleted` — `ack`, без MinIO и Qdrant.
3. `uploaded`, `error`, `processing` — условный переход в `processing` (`error=null`). Доставка без `redelivered` ставит `checkpoint.process_attempts=1`, повторная увеличивает счётчик. Значение больше `MAX_PROCESS_ATTEMPTS` (8) — `error=processing_attempts_exceeded` и dead-letter.
4. PDF открывается PyMuPDF. Не открылся — `error=corrupt_pdf`, документ остаётся в `files`. `page_count` и `checkpoint.pages_total` пишутся сразу после открытия.
5. Страница, которая уже есть в `file_pages`, не рендерится и в OCR не отправляется. Иначе `page.get_text("text")`: длиннее `MIN_EXTRACTED_CHARS` — `origin=text`, иначе PNG при `OCR_RENDER_DPI` и `POST /ocr`. Пустой текст OCR — `origin=empty`, это успех. `checkpoint.pages_done` двигается через `$max` и не уменьшается.
6. Чанки — скользящее окно `CHUNK_TOKENS` / `CHUNK_OVERLAP_TOKENS` по токенам `tokenizer.json` модели `EMBEDDING_MODEL` (ревизия GGUF `914f7f89142e33e77833254d9c9b90c3cef7303b`). В точку кладётся сырой текст, без префикса `title`.
7. Эмбеддинг: `POST /embed`, `input_type=document`, `title` — `file_name` из MongoDB, пачка не больше `EMBEDDING_BATCH_SIZE` (16). Дальше upsert в Qdrant, id `uuid5(a5b3c1d2-6e47-5f80-9c11-0d4e8f2a7b65, "{file_id}:{chunk_index}")`, фильтр арендатора `user_id`.
8. Когда `chunks_done == chunks_total`, хвост `chunk_index >= chunks_total` удаляется. Условный переход `processing → ready`. Если файл уже ушёл из `processing`, новые точки не пишутся, точки файла удаляются, сообщение `ack`.
9. MinIO, OCR, Embedding, Qdrant и MongoDB после коротких повторов шага — временный сбой: статус остаётся `processing`, пауза `min(60, 2^process_attempts)` секунд, `nack(requeue=true)`. На 8-й неудачной доставке тот же сбой постоянный: `embedding_failed`, `index_write_failed` или `storage_read_failed`, затем `nack` без requeue, и брокер кладёт сообщение в `doc.processing.dead`. В рабочую очередь оно не подтверждается.
10. При старте и далее раз в `SWEEP_INTERVAL_SECONDS` sweeper публикует новый `doc.process` только для `error=enqueue_failed` старше `UPLOAD_REQUEUE_AFTER_SECONDS`.

Топология RabbitMQ объявляется идемпотентно: `doc_events`, `doc_events_dlq`, очереди `doc.processing`, `doc.deletion`, `doc.processing.dead`, `doc.deletion.dead`.

## Тесты

```bash
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
```

OCR, Embedding и Qdrant в тестах подменяются. Реальные HTTP-клиенты проверяются через `httpx.MockTransport`. GPU не нужен.
