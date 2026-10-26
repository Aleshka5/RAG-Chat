# Истории разработки

Как вошедший пользователь, я загружаю PDF, они индексируются (текстовый слой и OCR сканов), я задаю вопросы по готовым документам и получаю ответ потоком SSE с источниками на уровне страницы, открываю PDF на процитированной странице с того же origin и удаляю файлы и чаты. Данные арендаторов изолированы. Готово, когда выполнен каждый пункт [mvp.md](mvp.md).

Каталоги ниже не пересекаются. История не правит чужой каталог и норматив `docs/`, кроме этого файла у US-0. Ветка — `cursor/<имя>-cc69`.

US-11…US-13 добавляют второй источник файлов: HomeCloud (WebStorage) кладёт свои PDF, DOCX, XLSX и изображения в те же коллекции `documents` и `images`. Контракт между системами — [integration-webstorage.md](integration-webstorage.md).

| История | Ветка | Каталог |
|---------|--------|---------|
| US-0 | `cursor/scaffold-common-cc69` | `packages/rag-common/**`, `docker-compose.yml`, `.env.example`, `Makefile`, `AGENTS.md`, `docs/user-stories.md`, секция Run в `README.md` |
| US-1 | `cursor/rag-edge-cc69` | `services/rag-edge/**` |
| US-2 | `cursor/file-collector-cc69` | `services/file-collector/**` |
| US-3 | `cursor/processor-cc69` | `services/processor/**` |
| US-4 | `cursor/deletion-worker-cc69` | `services/deletion-worker/**` |
| US-5 | `cursor/ocr-cc69` | `services/ocr/**` |
| US-6 | `cursor/embedding-cc69` | `services/embedding/**` |
| US-7 | `cursor/chat-cc69` | `services/chat/**` |
| US-8 | `cursor/frontend-cc69` | `frontend/**` |
| US-9 | `cursor/retrieval-only-2bef` | `services/chat/**`, `frontend/**`, нормативные абзацы этого сценария в `docs/` |
| US-10 | `cursor/us10-image-search-ea6f` | `services/embedding/**`, `services/file-collector/**`, `services/processor/**`, `services/deletion-worker/**`, `services/chat/**`, `services/rag-edge/**`, `frontend/**`, `packages/rag-common/**`, нормативные абзацы этого сценария в `docs/` |
| US-11 | `cursor/us11-office-documents-7c4a` | `services/processor/**`, `services/file-collector/**`, `services/chat/**`, `frontend/**`, `packages/rag-common/**`, нормативные абзацы этого сценария в `docs/` |
| US-12 | `cursor/us12-shared-bucket-9e2b` | `services/file-collector/**`, `services/processor/**`, `services/deletion-worker/**`, `docker-compose.yml`, `.env.example`, нормативные абзацы этого сценария в `docs/` |
| US-13 | `cursor/us13-rekey-3f81` | `services/file-collector/**`, `services/processor/**`, `services/chat/**`, нормативные абзацы этого сценария в `docs/` |

Общий код — пакет `rag_common`. Сервисы не копируют конверт ошибки, проверку `X-Auth-User-Id`, топологию RabbitMQ, индексы MongoDB и формулу id точки.

## US-0. Общий пакет и стенд

Ветка `cursor/scaffold-common-cc69`.

Приёмка, цитаты из mvp.md, раздел «Стенд»:

> - [ ] `make up` (`podman compose`) поднимает инфраструктуру и процессы приложения без отдельной разработки gateway.
> - [ ] OCR и Embedding не торчат в публичную сеть стенда, кроме явной локальной отладки.
> - [ ] Секреты не записаны в репозиторий.

`make up` в этом репозитории запускает `docker compose up --build` по корневому `docker-compose.yml`: пример в deployment.md задаёт контексты сборки от корня. Тот же файл читает `podman compose -f docker-compose.yml`. Auth Gateway в compose нет. Порты OCR и Embedding на хост не публикуются.

## US-1. rag-edge

Ветка `cursor/rag-edge-cc69`. Каталог `services/rag-edge/**`.

Приёмка:

> - [ ] Анонимный `GET /api/files` через хост gateway не доходит до RAG и возвращает `401` `{"error":"unauthorized"}`. `GET /health` на том же хосте публичен.

Edge — единственный процесс в `rag_edge`. `GET /health` отвечает сам edge: `{"status":"ok"}`. `/api/files` уходит в File Collector, `/api/chats` — в Chat, остальное — во frontend. Тело загрузки до `MAX_UPLOAD_BYTES` не режется меньшим пределом. Поток SSE не буферизуется.

## US-2. File Collector

Ветка `cursor/file-collector-cc69`. Каталог `services/file-collector/**`.

Приёмка:

> - [ ] Файл больше `MAX_UPLOAD_BYTES` отклоняется с `413` и не появляется в списке. По умолчанию это 500 МиБ.
> - [ ] Файл не с сигнатурой `%PDF` отклоняется с `415`.
> - [ ] Повторная загрузка тех же байтов тем же пользователем даёт `409` и `details.file_id` первого файла.
> - [ ] После `deleted` те же байты загружаются снова.
> - [ ] Список не показывает `deleted` и не показывает файлы другого `X-Auth-User-Id`.
> - [ ] Запрос без `X-Auth-User-Id` к File Collector или Chat даёт `401`. Заголовок `X-User-Id` сам по себе пользователя не задаёт.
> - [ ] `GET /content` чужого или удалённого файла — `404`. Своего `ready` — байты PDF.
> - [ ] `DELETE` во время свежего `processing` возвращает `409`. После `ready` удаление доходит до `deleted`.

Последний пункт общий с US-4: `409` и постановка `doc.delete` — File Collector, статус `deleted` — Deletion Worker.

## US-3. Processor

Ветка `cursor/processor-cc69`. Каталог `services/processor/**`.

Приёмка:

> - [ ] PDF с текстовым слоем доходит от `uploaded` до `ready`, в карточке верный `page_count`.
> - [ ] Остановка Processor после нескольких страниц многостраничного PDF не начинает OCR сначала: после нового запуска те же страницы не уходят в OCR повторно, файл доходит до `ready`.
> - [ ] Пока идёт обработка, `progress.pages_done` не уменьшается.
> - [ ] Повреждённый файл получает `error=corrupt_pdf` и остаётся в списке.
> - [ ] На канале consumer `prefetch=1`.
> - [ ] Сбой записи в Qdrant переводит файл в `error` и оставляет сообщение в `doc.processing.dead`, а не в рабочей очереди.

`prefetch=1` также у Deletion Worker (US-4). Константа — `rag_common`.

## US-4. Deletion Worker

Ветка `cursor/deletion-worker-cc69`. Каталог `services/deletion-worker/**`.

Приёмка:

> - [ ] На канале consumer `prefetch=1`.
> - [ ] `DELETE` во время свежего `processing` возвращает `409`. После `ready` удаление доходит до `deleted`.
> - [ ] После `deleted` нет объекта в MinIO и нет точек с этим `document_id` и `user_id`.
> - [ ] Повтор того же `doc.delete` завершается `ack` и не меняет состояние.
> - [ ] Падение worker после удаления объекта и до `deleted` лечится повторной доставкой: статус становится `deleted`, второй объект не требуется.

`409` на свежем `processing` отдаёт File Collector (US-2). Worker доводит `deleting` до `deleted`.

## US-5. OCR

Ветка `cursor/ocr-cc69`. Каталог `services/ocr/**`.

Приёмка:

> - [ ] Скан без текстового слоя доходит до `ready`, а ответ чата содержит фразу со скана.

Страницу в OCR отправляет Processor. Фразу в ответе показывает Chat (US-7). Этот сервис распознаёт одну страницу и не публикует порт на хост.

## US-6. Embedding

Ветка `cursor/embedding-cc69`. Каталог `services/embedding/**`.

Приёмка стенда, без которой сервис нельзя считать закрытым:

> - [ ] OCR и Embedding не торчат в публичную сеть стенда, кроме явной локальной отладки.

Размер пачки — `EMBEDDING_BATCH_SIZE` `16` из configuration.md. `review.md` размер не задаёт. Вектор считает llama-server внутри того же контейнера; Processor и Chat ходят только в FastAPI `POST /embed`.

Без этого сервиса не проходят пункты US-3 (файл доходит до `ready`) и US-7 (SSE с источниками). Сквозная проверка остаётся у тех историй.

## US-7. Chat

Ветка `cursor/chat-cc69`. Каталог `services/chat/**`.

Приёмка:

> - [ ] Запрос без `X-Auth-User-Id` к File Collector или Chat даёт `401`. Заголовок `X-User-Id` сам по себе пользователя не задаёт.
> - [ ] Вопрос по единственному готовому файлу возвращает SSE: сначала `meta` с непустым `sources`, затем `delta`, затем `done`.
> - [ ] В источнике верные `file_id`, `file_name` и страница, на которой лежит фраза.
> - [ ] Поиск не возвращает чанки другого пользователя. Это проверяется двумя `X-Auth-User-Id` и общим набором слов в разных PDF.
> - [ ] Вопрос при нуле готовых файлов не вызывает LLM и возвращает «Не найдено в документах.»
> - [ ] Обрыв LLM после уже отправленного текста не создаёт пару сообщений. HTTP 4xx провайдера, кроме 429, тоже не создаёт пару. Повторный вопрос после успеха создаёт следующий ход.
> - [ ] `GET` чата после `done` содержит оба сообщения и те же `sources`.
> - [ ] `DELETE` чата удаляет сообщения и не удаляет файл.
> - [ ] Первый вопрос заменяет заголовок «Новый чат».

Проверка `X-Auth-User-Id` — та же, что у File Collector, через `rag_common`.

## US-8. Frontend

Ветка `cursor/frontend-cc69`. Каталог `frontend/**`.

Приёмка:

> - [ ] Экран файлов опрашивает список, пока есть незавершённые статусы, и показывает подпись кода ошибки.
> - [ ] Под ответом есть карточка источника. Переход открывает PDF на указанной странице через `GET /content`, без presigned URL.
> - [ ] История чатов сохраняется между перезагрузкой страницы.

Клиент — React, Vite, TypeScript, Tailwind CSS, Zustand, PDF.js. Заголовки личности не ставит.

## US-9. Ответ без LLM

Ветка `cursor/retrieval-only-2bef`. Каталоги `services/chat/**` и `frontend/**`, плюс нормативные абзацы этого сценария в `docs/api.md`, `docs/openapi.yaml`, `docs/architecture.md`, `docs/data-models.md`, `docs/frontend.md`, `docs/mvp.md` и в этом файле.

Приёмка:

> - [ ] Если источники найдены, а провайдер LLM недоступен до первого текстового токена, SSE содержит `meta` с этими источниками, не содержит `delta` и завершается `done` с `finish_reason` `retrieval_only`.
> - [ ] Ход сохраняется. `content` ответа — пустая строка. У сообщения ассистента есть `finish_reason` `retrieval_only`. `GET` чата возвращает те же источники.
> - [ ] Недоступность — таймаут, сетевая ошибка, HTTP 429 или HTTP 5xx после одного повтора. HTTP 4xx кроме 429 по-прежнему не сохраняет ход.
> - [ ] Если текстовый токен уже ушёл клиенту, обрыв остаётся событием `error` и ход не пишется.
> - [ ] Клиент показывает «Модель недоступна. Показаны найденные фрагменты.» и карточки источников, в том числе после перезагрузки.

Ноль готовых файлов по-прежнему не вызывает LLM и возвращает «Не найдено в документах.» Это US-7.

## US-10. Поиск изображений

Ветка `cursor/us10-image-search-ea6f`. Каталоги `services/embedding/**`, `services/file-collector/**`, `services/processor/**`, `services/deletion-worker/**`, `services/chat/**`, `services/rag-edge/**`, `frontend/**`, `packages/rag-common/**`, плюс нормативные абзацы этого сценария в `docs/api.md`, `docs/openapi.yaml`, `docs/openapi-internal.yaml`, `docs/processing.md`, `docs/data-models.md`, `docs/messaging.md`, `docs/configuration.md`, `docs/internal-services.md`, `docs/architecture.md`, `docs/frontend.md`, `docs/gateway.md`, `docs/mvp.md`, `docs/deployment.md`, `docs/README.md` и в этом файле. Эти каталоги пересекаются с US-1…US-9: история меняет в них только регистрацию и поиск изображений.

Два конвейера. PDF остаётся на OCR и коллекции `documents`. Изображение — один вектор в коллекции `images`, без OCR и без страниц. Word и обычный текст в эту историю не входят: `POST /api/files/documents` и multipart `POST /api/files` отвечают на них `415`.

Приёмка:

> - [ ] `POST /embed/image` принимает пачку base64 PNG, JPEG, WebP или GIF и возвращает L2-векторы 768 в том же пространстве, что `POST /embed`. Поля `texts`, `input_type` и `title`, пустая пачка, чужая модель, не-base64, чужой контейнер и размер больше `EMBEDDING_MAX_IMAGE_BYTES` дают `400` `validation_error`. `502` — если контейнер опознан, а llama-server его не разобрал. `504` — по `EMBEDDING_TIMEOUT`.
> - [ ] llama-server загружает `EMBEDDING_MMPROJ` флагом `--mmproj`. Веса float16 и проектор звука не загружаются. Без проектора изображения `POST /embed/image` отвечает `502`. `POST /embed` и `GET /health` прежние, `EMBEDDING_DIM` остаётся 768.
> - [ ] `POST /api/files/documents` с `content_type` `application/pdf` ставит `doc.process` и отвечает `202` карточкой файла с `content_type`. Word, `text/plain` и любой другой тип — `415`. Multipart `POST /api/files` по-прежнему принимает только PDF по сигнатуре `%PDF`.
> - [ ] `POST /api/files/images` принимает `image/jpeg`, `image/png`, `image/webp`, `image/gif`. Байты не копируются и хеш не пересчитывается. Нет объекта или ключ `files/{uuid}/...` чужого пользователя — `404` `object_not_found`. Активный дубликат по `content_sha256` или `s3_key` — `409` `duplicate_file` и второе сообщение не ставится. У изображения `page_count` равен `null`.
> - [ ] Processor поднимает коллекцию `images` так же, как `documents`. Готовое изображение — одна точка `{file_id}:0` в `images`, без строк `file_pages` и без OCR. Постоянный отказ байтов, `400` эмбеддера или пустой вектор переводят файл в `error` и сообщение в DLQ. `502` и `504` идут по прежней политике повторов и затем в DLQ.
> - [ ] Удаление файла снимает точки и в `documents`, и в `images`. Отсутствующая коллекция `images` удаление не останавливает.
> - [ ] `GET /api/chats/image-search` ищет вектор вопроса из `POST /embed` (`input_type=query`) по коллекции `images` и отдаёт только `ready` файлы этого пользователя по убыванию `score`. Повтор страницы до истечения `IMAGE_SEARCH_CACHE_TTL_SECONDS` эмбеддер не вызывает.
> - [ ] `POST /api/chats/{chat_id}/messages` с `mode=images` не вызывает LLM. В `meta` есть `images` и `sources: []`. При попаданиях одна дельта `Найдено изображений: N.` и `finish_reason` `stop`. При пустом поиске дельта `Не найдено изображений.` и пустой `images`. `GET` чата возвращает сохранённый массив. `mode=documents` и отсутствие `mode` не меняют прежний ход. Неизвестный `mode` — `400`.
> - [ ] В чате есть переключатель режима, по умолчанию документы. Режим изображений рисует превью по `content_path` тем же запросом байтов, что и файл, через object URL, вместе с именем и `score`. Карточка и предпросмотр изображения не идут в PDF.js. PDF открывается как раньше.
> - [ ] `GET /api/chats/image-search` остаётся на префиксе `/api/chats`, `POST /api/files/documents` и `POST /api/files/images` — на префиксе `/api/files`. Edge отдаёт эти пути в Chat и File Collector.

## US-11. Word и Excel в `documents`

Ветка `cursor/us11-office-documents-7c4a`. Каталоги `services/processor/**`, `services/file-collector/**`, `services/chat/**`, `frontend/**`, `packages/rag-common/**`, нормативные абзацы этого сценария в `docs/`.

Контракт интеграции — [integration-webstorage.md](integration-webstorage.md), раздел 6. Второй файл в тот же конвейер: docx и xlsx — это текст без страниц, поэтому вместо страницы вводится единица, на которую ссылается ответ.

Приёмка:

> - [ ] `POST /api/files/documents` с `content_type` `application/vnd.openxmlformats-officedocument.wordprocessingml.document` или `…spreadsheetml.sheet` ставит `doc.process` и отвечает `202` карточкой файла. `.doc`, `.xls`, `.pptx`, `.csv`, `text/plain` по-прежнему `415 unsupported_media_type`. Multipart `POST /api/files` остаётся только PDF.
> - [ ] Processor разбирает docx без OCR: абзацы в порядке документа, затем таблицы построчно через ` | `. Единица — блок от заголовка `Heading 1…3` до следующего заголовка; документ без заголовков — одна единица. `unit_label` — текст заголовка, без него `Раздел N`.
> - [ ] Processor разбирает xlsx без OCR: единица — лист с хотя бы одной непустой ячейкой, текст — значения ячеек построчно через табуляцию, формулы не пишутся. `unit_label` — имя листа.
> - [ ] `page_count` в карточке равен числу единиц, `checkpoint.pages_total` тому же числу, `progress.pages_done` растёт без дыр. `file_pages` пишется по номеру единицы, схема не меняется. `page_count` не равен числу страниц печати, и это не ошибка.
> - [ ] Payload Qdrant получает `unit_label` (keyword) только у docx и xlsx. Остальные поля прежние, `source` всегда `text`.
> - [ ] `sources` в `meta`, в `GET /api/chats/{chat_id}` и в `openapi.yaml` получает необязательное `unit_label`. Есть значение — фронтенд показывает его вместо «стр. N»; нет — прежний вид для PDF.
> - [ ] Файл, не открывающийся как OOXML, получает `error=corrupt_document`, сообщение уходит в DLQ. Файл без текста получает `no_extractable_text`. Повторная доставка при `ready` по-прежнему подтверждается без работы.
> - [ ] Возобновление после падения работает как у PDF: `pages_done` не уменьшается, повтор не разбирает готовые единицы заново.
> - [ ] Смена `CHUNK_TOKENS`, `CHUNK_OVERLAP_TOKENS` или `EMBEDDING_MODEL` сбрасывает только векторную часть: точки файла удаляются, единицы в `file_pages` остаются.

## US-12. Один бакет с WebStorage и внешние объекты

Ветка `cursor/us12-shared-bucket-9e2b`. Каталоги `services/file-collector/**`, `services/processor/**`, `services/deletion-worker/**`, корневой `docker-compose.yml`, `.env.example`, нормативные абзацы этого сценария в `docs/`.

Контракт — [integration-webstorage.md](integration-webstorage.md), разделы 2–4 и 8. Бакет `documents` перестаёт существовать: storage и RAG читают один бакет `storage`, а байты, загруженные самим RAG, уезжают под префикс `rag/`.

Приёмка:

> - [ ] `S3_BUCKET` по умолчанию `storage`. Новые объекты RAG пишутся по ключу `rag/files/{user_id}/{file_id}/{safe_name}`. Старые `files/{user_id}/…` остаются читаемыми и удаляемыми, переноса объектов нет.
> - [ ] Манифест `POST /api/files/documents` и `POST /api/files/images` принимает необязательное `origin`: `rag` или `storage`. Нет поля — `rag`. Иное значение — `400 validation_error` с полем `origin`.
> - [ ] `origin=storage` требует ключ `users/{user_id}/…`; этот `user_id` обязан совпасть с `X-Auth-User-Id`, иначе `404 object_not_found`. Ключ `rag/files/{uuid}/…` или `files/{uuid}/…` с чужим UUID — тоже `404`.
> - [ ] Документ `files` получает поле `object_owner` (`rag` \| `storage`). В API-карточку оно не попадает.
> - [ ] Deletion Worker для `object_owner=storage` **не удаляет объект в бакете**: только точки `documents` и `images`, строки `file_pages` и запись `files`. Повторная регистрация того же `s3_key` после `deleted` проходит.
> - [ ] Для `object_owner=rag` удаление объекта остаётся прежним. Отсутствие объекта — по-прежнему успех.
> - [ ] `s3_url` в payload изображения равен `s3://storage/{s3_key}` и не содержит учётных данных.
> - [ ] Processor читает объект по `s3_key` из манифеста: `users/…` и `rag/…` одинаково, если `user_id`, `s3_key` и `content_type` в сообщении совпадают с документом. Иначе `nack` без requeue.
> - [ ] `GET /api/files/{file_id}/content` отдаёт байты объекта storage по сохранённому `content_type`. Файл из storage, зарегистрированный изображением, в режиме `images` и в `image-search` находится наравне с файлами RAG.
> - [ ] `docker-compose.yml` не создаёт бакет `documents`; бакет `storage` создаётся storage-стеком и здесь не трогается. `_meta/`, `users/`, `shared/` RAG не пишет и не удаляет.
> - [ ] Тест на совпадение имён: два пользователя с одинаковым `file_name` и одинаковыми байтами дают два разных `s3_key`, дедупликация по `(user_id, content_sha256)` работает внутри одного пользователя.

## US-13. Re-key: переименование и перемещение

Ветка `cursor/us13-rekey-3f81`. Каталоги `services/file-collector/**`, `services/processor/**`, `services/chat/**`, нормативные абзацы этого сценария в `docs/`. Поиск оставляет файл видимым, пока `checkpoint.reindex` истинен: иначе статус `processing` прятал бы старые точки.

Контракт — [integration-webstorage.md](integration-webstorage.md), раздел 7. В storage переименование и перемещение меняют `s3_key`, содержимое остаётся тем же; повторная регистрация дала бы `409 duplicate_file`, а удаление с последующей регистрацией открывает окно, в котором файл не находится.

Приёмка:

> - [ ] `PUT /api/files/{file_id}/object` с `{s3_key, file_size, content_sha256}` отвечает `202` и карточкой файла; статус на время переиндексации — `processing`.
> - [ ] `content_sha256` не совпал с сохранённым — `409 content_changed`, ничего не меняется. `file_size` не совпал с `HEAD` объекта — `400 validation_error`, поле `file_size`.
> - [ ] Нет объекта по новому ключу — `404 object_not_found`. `origin=storage` требует префикс `users/{user_id}/…` своего пользователя.
> - [ ] Чужой файл, `deleted` и `deleting` — `404`. Свежий `processing` — `409 file_busy`.
> - [ ] `s3_key` заменяется, `checkpoint.chunks_done=0`, `chunks_total=null`, `page_count=null`. `file_pages` не удаляются.
> - [ ] Публикуется `doc.process` с новым ключом. Точки не удаляются до переиндексации: идентификаторы чанков стабильны, upsert перезаписывает их на месте. Между вызовом и `ready` старые точки продолжают находиться поиском.
> - [ ] `ready → processing` разрешён только этому маршруту. Остальные пути по-прежнему не возвращают `ready` в `processing`.
> - [ ] Повторный `PUT` с теми же `s3_key` и хешем идемпотентен: `202`, повторная переиндексация тех же байтов, тот же набор идентификаторов точек.
> - [ ] `ready` после переиндексации: `GET /api/files/{file_id}` отдаёт новый `s3_key` в `image-search` (`s3_key`, `s3_url`), для PDF — прежний `page_count`.
> - [ ] Изменилось содержимое, а не имя — storage шлёт `DELETE`, ждёт `deleted` и регистрирует файл заново. Этот путь описан в [integration-webstorage.md](integration-webstorage.md) и в RAG нового не требует.
