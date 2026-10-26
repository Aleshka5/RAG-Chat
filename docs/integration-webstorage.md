# Интеграция с WebStorage (HomeCloud)

**Статус:** контракт US-11…US-13. Реализация — ветки `cursor/us11-office-documents-7c4a`, `cursor/us12-shared-bucket-9e2b`, `cursor/us13-rekey-3f81`.
**Истории:** [US-11, US-12, US-13](user-stories.md).
**Вторая сторона:** `WebStorage/docs/epics/storage-indexing/init.md` (E-SIDX).

Документ фиксирует контракт между HomeCloud (далее storage) и RAG-чатом: кто кого вызывает, в каком бакете лежат байты, какие типы идут в какие коллекции, что происходит при переименовании и удалении. Он не заменяет [api.md](api.md), [data-models.md](data-models.md) и [processing.md](processing.md): там остаются общие правила, здесь — только отличия, которые вносит интеграция.

## 1. Что индексируется

| Раздел storage | PDF | DOCX | XLSX | JPEG, PNG, WebP, GIF | HEIC, HEIF |
|----------------|-----|------|------|----------------------|------------|
| Files | `documents` | `documents` | `documents` | `images` | превью JPEG |
| Photos | — | — | — | `images` | превью JPEG |
| Shared, Resumes, Generated | не индексируется | | | | |
| Private | не индексируется никогда: байты зашифрованы AES-256-GCM, ключ живёт в Redis и RAG его не получает | | | | |

Коллекции — существующие, без новых: `documents` для текста, `images` для одного вектора на изображение. `QDRANT_COLLECTION` и `QDRANT_IMAGES_COLLECTION` не меняются, размерность остаётся 768.

`images` становится общей: в ней лежат точки и файлов, загруженных в RAG, и картинок storage. Разделяет их `user_id` в payload, как и раньше.

## 2. Один бакет

Storage и RAG читают один и тот же бакет MinIO `storage` (Common MinIO). `S3_BUCKET` у file-collector, processor и deletion-worker меняется с `documents` на `storage`. Другие процессы эту переменную не читают. RAG бакет не создаёт.

Ключи разведены по префиксам:

| Владелец | Ключ | Кто удаляет байты |
|----------|------|-------------------|
| RAG | `rag/files/{user_id}/{file_id}/{safe_name}` | RAG |
| Storage, Files | `users/{user_id}/files/{relative_path}` | storage |
| Storage, Photos | `users/{user_id}/photos/originals/{id}{ext}`, `users/{user_id}/photos/previews/{id}_thumb.jpg` | storage |
| Storage, архив | `users/{user_id}/…{ext}.zst` | storage |

`users/…` и `_meta/backups/…` — чужие для RAG объекты. RAG их только читает, и только те, что ему назвали в манифесте.

Старые объекты RAG, уже лежащие в `files/{user_id}/{file_id}/…`, остаются читаемыми: префикс `rag/` действует для новых записей, проверка владельца принимает оба вида.

## 3. Кто кого вызывает

Вызывает storage. RAG ничего не опрашивает и не ходит в storage.

```
storage app:8000
  → http://rag-edge:8080      (сеть rag_edge, external)
       /api/files/documents    → file-collector
       /api/files/images       → file-collector
       /api/files/{id}         → file-collector
       /api/files/{id}/object  → file-collector
       /api/chats/image-search → chat
```

- `app` storage подключается к сети `rag_edge` как к external. В `rag_internal` он не входит: там MongoDB, Qdrant и RabbitMQ.
- Заголовки: `X-Auth-User-Id` — UUID владельца файла (`sub`), `X-Request-Id` — по желанию. Cookie и `Authorization` не отправляются. `X-Auth-Role` не отправляется: `BLOCKED` у storage отсекается у себя.
- `rag-edge` не проверяет личность, поэтому членство в `rag_edge` — доверенное. Новых членов в этой сети, кроме gateway и storage, быть не должно.
- Таймаут на вызов — 10 секунд. Регистрация не должна задерживать ответ storage на загрузку: storage делает её фоновой задачей.

## 4. Манифест регистрации

`POST /api/files/documents` и `POST /api/files/images` (JSON-манифест) получают новое необязательное поле `origin`.

```json
{
  "s3_key": "users/91a0b1c2-3d4e-4f50-8617-18293a4b5c6d/files/Отчёт.docx",
  "file_name": "Отчёт.docx",
  "content_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "file_size": 12345,
  "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "origin": "storage"
}
```

| Поле | Правило |
|------|---------|
| `origin` | `rag` или `storage`. Нет поля — `rag`. |
| `s3_key` | `origin=rag`: как раньше, `files/…` или `rag/files/{uuid}/…`, этот UUID обязан совпасть с `X-Auth-User-Id`. `origin=storage`: `users/{user_id}/…`, этот `user_id` обязан совпасть с `X-Auth-User-Id`, иначе `404 object_not_found`. |
| `content_type` | `POST /api/files/documents` принимает `application/pdf`, `…wordprocessingml.document`, `…spreadsheetml.sheet`. Остальное — `415`. `POST /api/files/images` не меняется. |
| `content_sha256` | Байты заново не хешируются. Дедупликация active-файла по `(user_id, content_sha256)` и по `(user_id, s3_key)` сохраняется; storage обязан трактовать `409 duplicate_file` как «уже зарегистрировано», если `details.file_id` совпадает с его сохранённым `rag_file_id`. |

`origin=storage` пишется в документ `files` новым полем `object_owner` (`rag` \| `storage`) и в payload Qdrant не попадает.

## 5. Конвейеры

| `content_type` | Коллекция | Что делает Processor |
|----------------|-----------|----------------------|
| `application/pdf` | `documents` | без изменений: страницы, OCR, чанки |
| `…wordprocessingml.document` | `documents` | единицы docx, без OCR, чанки |
| `…spreadsheetml.sheet` | `documents` | единицы xlsx, без OCR, чанки |
| `image/jpeg`, `image/png`, `image/webp`, `image/gif` | `images` | без изменений: одна точка `{file_id}:0` |

Чанкинг, эмбеддинг, идентификаторы точек, удаление хвоста и переходы статусов у docx/xlsx те же, что у PDF.

## 6. Word и Excel: единицы вместо страниц

У docx и xlsx нет страниц. Вместо номера страницы вводится **единица** — то, на что можно сослаться в ответе.

| Тип | Единица | `unit_label` |
|-----|---------|--------------|
| PDF | страница | нет (клиент показывает «стр. N») |
| DOCX | блок от заголовка (стиль `Heading 1…3`) до следующего заголовка; документ без заголовков — одна единица | текст заголовка, без заголовка — `Раздел N` |
| XLSX | лист с хотя бы одной непустой ячейкой | имя листа |

Правила:

- Текст docx — абзацы в порядке документа, затем таблицы построчно, ячейки через ` | `. Форматирование, сноски, колонтитулы и комментарии отбрасываются.
- Текст xlsx — значения ячеек построчно, через табуляцию, без формул (пишется вычисленное значение, если оно сохранено в файле). Пустые строки и листы схлопываются.
- `page_number` и `page_end` в payload остаются целыми: это порядковый номер единицы с 1. Новое поле payload `unit_label` (keyword) заполняется только у docx/xlsx. `source` всегда `text`.
- `page_count` в карточке файла — число единиц. `progress.pages_done` / `pages_total` — счётчики единиц. Отдельных полей не вводится.
- `file_pages` хранит текст единицы, `page_number` — её номер. Схема не меняется.
- Элемент `sources` в ответе API получает необязательное поле `unit_label`. Есть — клиент показывает его вместо «стр. N». Нет — прежний вид.
- Ни одна единица не дала текста → `no_extractable_text`. Файл не открывается как OOXML → новый код `corrupt_document`.

## 7. Re-key

Переименование или перемещение в storage меняет `s3_key`, содержимое — нет. Новый маршрут:

`PUT /api/files/{file_id}/object`

```json
{ "s3_key": "users/…/files/Новая папка/Отчёт.docx", "file_size": 12345, "content_sha256": "0123…" }
```

1. Файл этого пользователя, статус `ready`, `error` или `processing`. Иначе `404` / `409 file_busy`.
2. `content_sha256` обязан совпасть с сохранённым. Иначе `409` `content_changed`: изменилось содержимое, это не переименование.
3. `HEAD` нового ключа, размер сверяется с `file_size`. Нет объекта — `404 object_not_found`. `origin=storage` требует префикс `users/{user_id}/…`.
4. Записывается новый `s3_key`, сбрасываются `checkpoint.chunks_done=0`, `chunks_total=null`, `page_count=null`. `file_pages` не удаляются: байты те же.
5. Публикуется `doc.process` с новым ключом, ответ `202` и карточка файла.

`ready → processing` — единственный новый переход статуса, и разрешён он только этому маршруту. Вместе со сменой ключа пишется `checkpoint.reindex=true`. Старые точки не удаляются перед переиндексацией: идентификаторы чанков стабильны, upsert перезаписывает их на месте. Поиск документов и изображений оставляет файл, пока статус `processing` и `checkpoint.reindex` истинен. Processor снимает флаг при переходе в `ready`. Окна, когда файл пропадает из поиска, нет.

## 8. Удаление

`DELETE /api/files/{file_id}` для `origin=storage` снимает документ `files`, точки `documents` и `images`, строки `file_pages` и переводит запись в `deleted`. **Байты в бакете не трогаются**: объект принадлежит storage, и повторная регистрация того же `s3_key` после `deleted` разрешена частичными индексами.

Deletion Worker для `object_owner=storage` пропускает шаг удаления объекта MinIO. `GET /content` продолжает отдавать байты по `s3_key`, пока запись жива.

## 9. Ошибки

К существующей таблице [api.md](api.md) добавляются:

| HTTP | `code` | Когда |
|------|--------|--------|
| 409 | `content_changed` | `PUT /api/files/{file_id}/object`: `content_sha256` не совпал с сохранённым |
| 415 | `unsupported_media_type` | Тот же код, что раньше; теперь покрывает и `.doc`, `.xls`, `.pptx`, `.csv`, присланные как `content_type` |
| 200 | — | Ошибки конвейера видны в карточке: `error=corrupt_document`, `no_extractable_text`, `unsupported_image`, `image_too_large` |

Коды `error` файла получают `corrupt_document`. Остальные коды прежние.

## 10. Идемпотентность и повторы

- Повторная регистрация одного и того же `s3_key` активным файлом — `409 duplicate_file`. Storage считает это успехом, если `details.file_id` равен его `rag_file_id`.
- Повторный `PUT …/object` с тем же ключом и тем же хешем — `202`, повторная переиндексация тех же байтов, идентификаторы точек те же.
- Повторный `DELETE` при `deleting` — `409 file_busy`; при `deleted` — `404`. Storage трактует оба как «векторов нет».
- Сбой RAG (сеть, `503`, `504`) на регистрации: storage повторяет вызов по своей политике. RAG со своей стороны ничего не доотправляет.

## 11. Что не входит

- Обратный вызов из RAG в storage, вебхуки, отдельная очередь для storage-файлов.
- Раздел Shared: общий доступ в RAG не моделируется, поиск фильтруется только по `user_id`.
- Индексация `meta.yaml`, `statuses.yaml`, `Keys/keys.yaml` и любых `.yaml`/`.json`.
- Чат по файлам storage через фронтенд RAG: источники указывают на `file_id` RAG, а не на объект storage; переход по ним открывает `/api/files/{file_id}/content` RAG. Открытие файла в storage-UI — отдельная история.
- Изменение модели эмбеддинга и переиндексация: смена `EMBEDDING_MODEL` по-прежнему требует пересоздания обеих коллекций.
