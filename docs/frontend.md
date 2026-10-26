# Контракт клиента

Клиент открывает `https://rag.filenkov.store`. Запросы same-origin, cookie `auth_access` уходит сама, если хост покрыт `COOKIE_DOMAIN`. Клиент не ставит `X-Auth-*`, `X-User-Id` и `Authorization`. Эти заголовки пишет Auth Gateway на пути к `rag-edge`.

Ответ `401` с телом gateway `{"error":"unauthorized"}` значит, что сеанса нет. Клиент уводит браузер на `{PUBLIC_ORIGIN}/auth?return_to=` с текущим URL. Конверт RAG `error.code` в этом ответе не разбирается. `403` с `{"error":"blocked"}` или с кодом RAG `forbidden` показывает «Access denied» и не повторяет запрос.

Клиент собирается Vite. UI — React, Tailwind CSS, Zustand, PDF.js. Другой сборщик не используется. Форму API это не меняет. Сервисы API сами CORS не настраивают: браузер ходит на тот же хост. Локальная проверка без Auth Gateway бьёт во внутренние порты с заголовком `X-Auth-User-Id` и не является формой продакшена.

## Файлы, маршрут `/files`

Список — `GET /api/files`. Строка: имя, размер, статус, число страниц, дата `created_at`. `page_count = null` показывается как «—». Это же значение у изображения и до открытия PDF.

Статусы:

| `status` | Подпись | Вид |
|----------|---------|-----|
| `uploaded` | Uploaded | жёлтый |
| `processing` | Processing… | синий, со спиннером. Если в карточке есть `progress.pages_total`, подпись «Processing… {pages_done} of {pages_total}» |
| `ready` | Ready | зелёный |
| `error` | Error | красный, подсказка по коду `error` |
| `deleting` | Deleting… | серый |

Подписи кодов `error`:

| Код | Подпись |
|-----|---------|
| `corrupt_pdf` | The file is damaged or is not a PDF |
| `corrupt_document` | The file is damaged or is not a Word or Excel document |
| `unsupported_image` | The image is damaged or is not a supported image |
| `image_too_large` | The image is larger than the allowed size |
| `storage_read_failed` | Could not read the file from storage |
| `embedding_failed` | Could not build the vectors |
| `index_write_failed` | Could not write the index |
| `metadata_update_failed` | Could not save the status |
| `no_extractable_text` | No text found in the document |
| `enqueue_failed` | Could not queue the file |
| `processing_attempts_exceeded` | Processing stopped several times and did not finish |

Пока в загруженной странице списка есть `uploaded`, `processing` или `deleting`, клиент повторяет `GET /api/files` каждые 5 секунд. Когда таких статусов нет, опрос останавливается. Удаление и загрузка не ждут окончания опроса: они сразу меняют локальный список и затем сверяются с ответом сервера.

Загрузка — выбор файла или перетаскивание, один файл за запрос. PDF уходит `POST /api/files`, изображение — `POST /api/files/images`; оба маршрута принимают `multipart/form-data` с полем `file`. Изображением клиент считает файл с типом `image/*` или с расширением `jpg`, `jpeg`, `png`, `webp`, `gif`; какой это тип на самом деле, решает сервер по сигнатуре. Ответ `409 duplicate_file` показывает «This file already exists». `413` показывает «The file is larger than the allowed size», `415` — «This file type is not supported». Форма по-прежнему не шлёт DOCX и XLSX: multipart отвечает `415`. Эти типы приходят манифестом от storage.

Строка с `content_type` `image/jpeg`, `image/png`, `image/webp` или `image/gif` не передаёт байты в PDF.js. Клиент забирает `GET /api/files/{file_id}/content` тем же same-origin запросом, что и остальные байты, и показывает кадр через object URL. PDF по-прежнему открывается в PDF.js.

Удаление спрашивает подтверждение и вызывает `DELETE`. `409 file_busy` показывает «Processing is still in progress or deletion has already started».

## Чат, маршрут `/chat`

Боковая колонка — `GET /api/chats`. Новый чат — `POST /api/chats`, затем переход в него.

Сообщения — `GET /api/chats/{chat_id}`. Отправка — `POST /api/chats/{chat_id}/messages` с `Accept: text/event-stream`.

В поле ввода есть переключатель режима. Подписи — `Documents` и `Images`. Выбран `Documents`: тело запроса не содержит `mode` либо содержит `mode` `documents`, экран прежний. `Images` отправляет `"mode": "images"`.

Порядок на экране:

1. Сразу показать вопрос пользователя как неотправленный до `meta`.
2. По `meta` запомнить `user_message_id`, `assistant_message_id` и карточки `sources`. Карточки видны до окончания текста.
3. Склеивать `delta.content` в ответ и рисовать его как Markdown.
4. По `done` ход считается сохранённым. Если `finish_reason` равен `retrieval_only`, текста ответа нет: над карточками источников постоянная подпись «The model is unavailable. Showing the passages that were found.»
5. По `error` или обрыву потока показать ошибку у хода и не считать его сохранённым. Повтор отправляет тот же текст новым запросом.

Та же подпись показывается после `GET`, если у сообщения ассистента `finish_reason` равен `retrieval_only`. Клиент не подставляет текст чанков в тело ответа: фрагменты остаются в карточках.

Карточка источника: имя файла, «Page N», действие «Open». Если у источника есть `unit_label`, вместо «Page N» показывается эта подпись. Если пользователь уже удалил файл, `GET /content` вернёт `404`; карточка остаётся, действие показывает «Preview unavailable».

Пустой ответ модели по контракту может быть фразой «Не найдено в документах.» Клиент не отличает её от обычного текста и не подменяет её своей строкой. Пустой `sources` просто не рисует карточек.

Режим `Images` карточки `sources` не рисует. Фразу дельты он показывает как текст ответа. Под ней — элементы `images`: имя файла, `score` и превью. Превью грузится с `content_path` тем же запросом байтов, что и `GET /content`, и показывается через object URL. `s3_url` клиент не открывает. После `GET` тот же массив `images` рисуется так же. Пустой массив оставляет только фразу «Не найдено изображений.» Ошибка загрузки кадра показывает «Preview unavailable», имя и оценку оставляет.

## Предпросмотр

Маршрут клиента: `/files/{file_id}?page={page_number}`.

Для `application/pdf` PDF.js загружает `GET /api/files/{file_id}/content` тем же same-origin запросом, что и остальной API, и открывает страницу `page`. Заголовок личности клиент к этому URL не приписывает. Номер страницы в API не передаётся. Ответ API не вставляется в iframe: Auth Gateway ставит `X-Frame-Options: DENY`.

Для изображения тот же маршрут показывает кадр через object URL и в PDF.js файл не передаёт. Параметр `page` на изображение не влияет.

У PDF `page` меньше 1 заменяется на 1. Если страниц меньше запрошенной, viewer остаётся на последней и не шлёт повторный запрос к API.
