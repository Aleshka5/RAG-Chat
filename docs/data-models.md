# Модели данных

База MongoDB задаётся путём в `MONGODB_URI` (по умолчанию база `rag`). Время хранится как BSON Date (UTC) и в API сериализуется как ISO-8601 с суффиксом `Z`. `_id` — внутренний ObjectId и в API не отдаётся.

Идентификаторы ресурсов (`file_id`, `chat_id`, `message_id`) — UUID версии 4, строкой в каноническом виде `8-4-4-4-12` в нижнем регистре. `user_id` — тот же формат, но это `sub` из `X-Auth-User-Id`; версию UUID выбирает User-Service, не RAG.

## Статусы файла

Закрытый набор: `uploaded`, `processing`, `ready`, `error`, `deleting`, `deleted`.

```mermaid
stateDiagram-v2
    [*] --> uploaded: запись после Put в MinIO
    uploaded --> processing: processor захватил сообщение
    error --> processing: повторная обработка
    processing --> processing: heartbeat updated_at
    processing --> ready: индекс записан
    processing --> error: неустранимая ошибка конвейера
    uploaded --> deleting: DELETE
    ready --> deleting: DELETE
    error --> deleting: DELETE
    processing --> deleting: DELETE только если updated_at старше порога
    deleting --> deleted: MinIO и Qdrant очищены
```

| Из | В | Кто | Условие |
|----|---|-----|---------|
| `uploaded`, `error`, `processing` | `processing` | Processor | Документ ещё не `deleting`, `deleted` или `ready`. При входе `error` обнуляется. |
| `processing` | `ready` | Processor | Запись всё ещё `processing`. У PDF пишутся `page_count` и `updated_at`. У изображения `page_count` остаётся `null`, пишется `updated_at`. |
| `processing` | `error` | Processor | Пишется код в `error`. |
| `uploaded`, `ready`, `error` | `deleting` | File Collector | Условное обновление. Иначе `409` или `404`. |
| `processing` | `deleting` | File Collector | Только если `updated_at` старше `STALE_PROCESSING_SECONDS`. |
| `deleting` | `deleted` | Deletion Worker | После успеха MinIO и Qdrant. |

Других переходов нет. `ready` не возвращается в `processing` обычным путём: повторное сообщение при `ready` подтверждается без работы.

## Коллекция `files`

| Поле | Тип | Правило |
|------|-----|---------|
| `file_id` | string | UUID v4, уникальный. |
| `user_id` | string | UUID из `X-Auth-User-Id` (JWT `sub`). |
| `file_name` | string | Имя, как его показал пользователь, после отсечения пути. До 255 символов. |
| `safe_name` | string | Имя внутри `s3_key`. |
| `file_size` | int | Размер в байтах, больше 0. |
| `content_type` | string | `application/pdf` либо `image/jpeg`, `image/png`, `image/webp`, `image/gif`. |
| `content_sha256` | string | SHA-256 байтов файла, 64 hex-символа в нижнем регистре. Для регистрации это строка манифеста: байты заново не хешируются. |
| `s3_key` | string | У multipart-загрузки: `files/{user_id}/{file_id}/{safe_name}`. У регистрации: ключ из запроса, объект не переименовывается. |
| `status` | string | Значение из закрытого набора. |
| `page_count` | int или null | Число страниц после успешного открытия PDF. До этого `null`. У изображения всегда `null`. |
| `error` | string или null | Код ошибки либо `null`. |
| `delete_claimed_at` | datetime или null | Внутреннее поле. `null`, пока Deletion Worker не начал обработку. В API не отдаётся. |
| `created_at` | datetime | Момент вставки. |
| `updated_at` | datetime | Каждое изменение статуса и heartbeat. |

Коды `error`:

| Код | Когда |
|-----|--------|
| `corrupt_pdf` | Файл не открывается как PDF. |
| `storage_read_failed` | MinIO не отдал объект. |
| `embedding_failed` | Embedding не ответил после повторов. |
| `index_write_failed` | Qdrant не принял запись или предварительное удаление точек. |
| `metadata_update_failed` | Финальное обновление MongoDB не выполнено. |
| `no_extractable_text` | После извлечения и OCR не осталось ни одного чанка. |
| `unsupported_image` | Байты изображения не опознаны, эмбеддер вернул `400` или вектор пуст. Сразу `error` и DLQ. |
| `image_too_large` | Изображение больше `EMBEDDING_MAX_IMAGE_BYTES` после декодирования. Сразу `error` и DLQ, эмбеддер не вызывается. |
| `enqueue_failed` | Публикация `doc.process` не подтвердилась. Повторно публикует только sweeper Processor. |
| `processing_attempts_exceeded` | Восемь доставок `doc.process` не довели файл до `ready`. |

`safe_name` multipart-загрузки PDF: взять базовое имя, оставить буквы Unicode, цифры и `._-`, остальные символы заменить на `_`, схлопнуть повторы `_`, обрезать до 200 символов, пустой результат заменить на `document.pdf`, расширение привести к `.pdf`. Регистрация документа и изображения это правило к `s3_key` и к расширению `file_name` не применяет. `file_name` регистрации — базовое имя из манифеста, до 255 символов.

Индексы, создаются идемпотентно при старте File Collector, Processor и Deletion Worker:

```javascript
db.files.createIndex({ file_id: 1 }, { unique: true })
db.files.createIndex({ user_id: 1, status: 1 })
db.files.createIndex({ user_id: 1, created_at: -1 })
db.files.createIndex(
  { user_id: 1, content_sha256: 1 },
  {
    unique: true,
    partialFilterExpression: {
      status: { $in: ["uploaded", "processing", "ready", "error", "deleting"] }
    }
  }
)
db.files.createIndex(
  { user_id: 1, s3_key: 1 },
  {
    unique: true,
    partialFilterExpression: {
      status: { $in: ["uploaded", "processing", "ready", "error", "deleting"] }
    }
  }
)
```

Частичные индексы разрешают заново загрузить тот же файл после `deleted`. Гонка двух одинаковых загрузок или двух регистраций одного хеша либо одного `s3_key` заканчивается ошибкой дубликата ключа у второй вставки; API отвечает `409 duplicate_file`. Ключ multipart уникален сам по себе. Индекс по `s3_key` ловит повторную регистрацию того же ключа.

В карточке файла нет `s3_key`, `safe_name`, `content_sha256`, `user_id` и сырого `checkpoint`. `content_type` в карточке есть всегда. Поиск изображений отдаёт `s3_key` и `s3_url` отдельно, не в карточке файла. Пока статус `processing`, в ответе PDF есть `progress`, собранный из контрольной точки. В остальных статусах и у изображения `progress` равен `null`.

```json
{
  "pages_done": 120,
  "pages_total": 400,
  "chunks_done": 30,
  "chunks_total": 80
}
```

`pages_total` известен после открытия PDF, до этого `null`. `chunks_total` известен после нарезки, до этого `null`.

### Контрольная точка на `files`

Внутренний объект `checkpoint`:

| Поле | Тип | Правило |
|------|-----|---------|
| `pages_done` | int | Сколько страниц уже есть в `file_pages`, с начала и без дыр. |
| `pages_total` | int или null | Число страниц PDF. |
| `chunks_done` | int | Сколько чанков уже записано в Qdrant. |
| `chunks_total` | int или null | Сколько чанков в текущей нарезке. |
| `process_attempts` | int | Сколько раз брали текущую публикацию сообщения. Новая публикация ставит 1. |
| `embedding_model` | string | Модель, под которую посчитаны чанки. |
| `chunk_tokens` | int | Окно, под которое посчитаны чанки. |
| `chunk_overlap` | int | Перекрытие той нарезки. |

Несовпадение модели или параметров нарезки с текущим процессом сбрасывает только векторную часть: точки файла удаляются, `chunks_done=0`, `chunks_total=null`. Страницы в `file_pages` остаются.

## Коллекция `file_pages`

Текст одной страницы. Отдельный документ на страницу, чтобы не упираться в лимит 16 МиБ у документа файла.

| Поле | Тип | Правило |
|------|-----|---------|
| `file_id` | string | |
| `user_id` | string | Тот же UUID, что в `files.user_id`. |
| `page_number` | int | С 1. |
| `text` | string | Пустая строка, если `origin=empty`. |
| `origin` | string | `text`, `ocr` или `empty`. |
| `updated_at` | datetime | |

Индекс, создают Processor и Deletion Worker:

```javascript
db.file_pages.createIndex({ file_id: 1, page_number: 1 }, { unique: true })
```

Записи живут до удаления файла. Поиск по ним не делается. В API коллекции нет.

## Коллекция `chats`

| Поле | Тип | Правило |
|------|-----|---------|
| `chat_id` | string | UUID v4, уникальный. |
| `user_id` | string | Владелец, тот же UUID, что в `files.user_id`. |
| `title` | string | До первого сообщения — `Новый чат`. Затем обрезка текста первого вопроса. |
| `created_at` | datetime | |
| `updated_at` | datetime | Обновляется при новом завершённом ходе. |

Заголовок из вопроса: схлопнуть пробельные символы в один пробел, обрезать края, взять не больше 80 символов. Если обрезка прошла внутри строки, последние три символа результата — `...`. Пустым вопрос не бывает: API отклоняет пустую строку раньше.

Индексы, создаёт Chat при старте:

```javascript
db.chats.createIndex({ chat_id: 1 }, { unique: true })
db.chats.createIndex({ user_id: 1, updated_at: -1 })
```

## Коллекция `messages`

| Поле | Тип | Правило |
|------|-----|---------|
| `message_id` | string | UUID v4, уникальный. |
| `chat_id` | string | |
| `user_id` | string | Тот же UUID владельца, чтобы выбирать сообщения без соединения с чатом. |
| `role` | string | `user` или `assistant`. |
| `content` | string | Текст сообщения. У ответа без LLM — пустая строка. |
| `sources` | array | Только у `assistant`. У `user` поля нет. У режима `images` массив пуст, как в `meta`. |
| `images` | array | Только у `assistant` режима `images`, включая пустой массив. У `user` и у режима `documents` поля нет. |
| `finish_reason` | string или поле отсутствует | Только у `assistant` и только со значением `retrieval_only`: ответ — найденные чанки, текста LLM нет. У обычного ответа и у `user` поля нет. |
| `created_at` | datetime | У пары одного хода время ответа строго больше времени вопроса. |

Элемент `sources`:

| Поле | Тип | Правило |
|------|-----|---------|
| `file_id` | string | |
| `file_name` | string | Имя на момент ответа. Позже файл может быть удалён, имя в сообщении не переписывается. |
| `page_number` | int | Страница с 1, первый токен чанка. |
| `chunk_index` | int | С 0 внутри документа. |
| `snippet` | string | Начало `text` чанка. Если текст длиннее 500 символов, в snippet попадают первые 497 символов и `...`. |
| `score` | number | Оценка Qdrant, cosine similarity, больше — ближе. |

Элемент `images`:

| Поле | Тип | Правило |
|------|-----|---------|
| `file_id` | string | |
| `file_name` | string | Имя на момент ответа. |
| `score` | number | Cosine similarity. |
| `content_path` | string | `/api/files/{file_id}/content`. |

`s3_key` и `s3_url` в сообщении чата не хранятся. `content` ответа — фраза `Найдено изображений: N.` или `Не найдено изображений.`

Индексы:

```javascript
db.messages.createIndex({ message_id: 1 }, { unique: true })
db.messages.createIndex({ chat_id: 1, created_at: 1 })
db.messages.createIndex({ user_id: 1, created_at: -1 })
```

Ход пишется только целиком: сначала документ `user`, затем `assistant`, затем `updated_at` чата. Если процесс упал между ними, при следующем чтении клиент может увидеть вопрос без ответа. Отдельной компенсации в MVP нет; повторный вопрос создаёт новый ход.

Коллекции настроек чата в MVP нет.

## Qdrant

Две коллекции. `documents` хранит чанки PDF. `images` (`QDRANT_IMAGES_COLLECTION`, по умолчанию `images`) хранит по одной точке на файл изображения. Обе создаёт Processor при старте, если коллекции ещё нет. Если коллекция есть, размерность вектора обязана совпасть с `EMBEDDING_DIM`. Иначе процесс не стартует. PDF в `images` не пишется. Изображение в `documents` не пишется.

Требуется Qdrant 1.11 или новее: флаг `is_tenant` появился в этой версии.

```python
client.create_collection(
    collection_name="documents",
    vectors_config=models.VectorParams(
        size=768,
        distance=models.Distance.COSINE,
    ),
    hnsw_config=models.HnswConfigDiff(
        payload_m=16,
        m=0,
    ),
)

client.create_payload_index(
    collection_name="documents",
    field_name="user_id",
    field_schema=models.KeywordIndexParams(
        type=models.KeywordIndexType.KEYWORD,
        is_tenant=True,
    ),
)

client.create_payload_index(
    collection_name="documents",
    field_name="document_id",
    field_schema=models.KeywordIndexParams(
        type=models.KeywordIndexType.KEYWORD,
    ),
)
```

`m=0` выключает общий граф. `payload_m=16` строит граф на каждого арендатора. Запрос без фильтра `user_id` по этой коллекции не выполняется: общий поиск по отключённому графу неполный.

### Идентификатор точки

```text
point_id = uuid5(namespace, "{file_id}:{chunk_index}")
```

`namespace` — UUID `a5b3c1d2-6e47-5f80-9c11-0d4e8f2a7b65`. Один и тот же чанк при повторе обработки получает тот же id и перезаписывается.

Перед upsert Processor удаляет все точки с этим `document_id` и `user_id`, затем пишет актуальный набор. Так сократившийся документ не оставляёт хвост старых чанков.

### Payload

| Поле | Тип | Правило |
|------|-----|---------|
| `text` | string | Текст чанка. |
| `document_id` | keyword | Равен `file_id`. |
| `user_id` | keyword | Арендатор. |
| `page_number` | integer | Страница первого токена, с 1. |
| `page_end` | integer | Страница последнего токена, с 1. |
| `file_name` | keyword | `file_name` на момент индексации. |
| `source` | keyword | `text` или `ocr`. |
| `chunk_index` | integer | С 0, без пропусков в записанном наборе. |
| `created_at` | string | ISO-8601, общее время индексации документа. |

`source = ocr`, если в окно попал хотя бы один токен со страницы, распознанной OCR. Иначе `text`.

### Поиск

```python
client.query_points(
    collection_name="documents",
    query=query_vector,
    query_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="user_id",
                match=models.MatchValue(value=user_id),
            )
        ]
    ),
    limit=top_k,
)
```

`top_k` берётся из `RAG_TOP_K`. Фильтра по конкретному файлу в MVP нет.

Если задан `RAG_MIN_SCORE` больше 0, точки с оценкой ниже порога отбрасываются. Порог сравнивается с cosine similarity, которую возвращает Qdrant.

### Удаление точек файла

```python
client.delete(
    collection_name="documents",
    points_selector=models.FilterSelector(
        filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="user_id",
                    match=models.MatchValue(value=user_id),
                ),
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=file_id),
                ),
            ]
        )
    ),
)
```

Успех операции при нуле удалённых точек — нормальный результат. Удаление файла вызывает этот фильтр и в `documents`, и в `images`. Коллекции `images` нет — это не ошибка, коллекция при удалении не создаётся.

### Коллекция `images`

Параметры те же: `size=768`, `distance=COSINE`, `hnsw_config` с `payload_m=16` и `m=0`. Payload-индексы те же: `user_id` с `is_tenant=true`, `document_id` типа keyword. Имя коллекции — `QDRANT_IMAGES_COLLECTION`. Запрос без фильтра `user_id` не выполняется.

Одна точка на файл. Id — та же формула `uuid5(namespace, "{file_id}:{chunk_index}")` с `chunk_index` 0, то есть имя `{file_id}:0`. Повтор обработки перезаписывает эту точку.

| Поле | Тип | Правило |
|------|-----|---------|
| `file_id` | keyword | UUID файла. |
| `document_id` | keyword | То же значение, что `file_id`. Удаление фильтрует по нему. |
| `user_id` | keyword | Арендатор. |
| `file_name` | keyword | Имя на момент индексации. |
| `s3_key` | keyword | Ключ объекта. |
| `s3_url` | keyword | `s3://{S3_BUCKET}/{s3_key}` без учётных данных. |
| `created_at` | string | ISO-8601, время индексации. |

Полей `text`, `page_number`, `page_end`, `chunk_index` и `source` нет.

Поиск изображений передаёт вектор текстового запроса (`input_type=query` у `POST /embed`) в `query_points` этой коллекции с фильтром `user_id`. Оценка — cosine similarity. В выдачу попадают только точки, чей файл в MongoDB принадлежит этому `user_id` и имеет статус `ready`.

## Объект в MinIO

Бакет — `S3_BUCKET` (по умолчанию `documents`). Один объект на файл, ключ `s3_key`. File Collector создаёт бакет при старте, если его нет.

Содержимое — исходные байты PDF или исходные байты изображения. Регистрация объект не копирует и не перекладывает. Производные изображения страниц PDF не сохраняются. У зарегистрированного файла ключ — тот, что передал вызывающий.
