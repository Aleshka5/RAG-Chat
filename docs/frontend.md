# Контракт клиента

Клиент открывает `https://rag.filenkov.store`. Запросы same-origin, cookie `auth_access` уходит сама, если хост покрыт `COOKIE_DOMAIN`. Клиент не ставит `X-Auth-*`, `X-User-Id` и `Authorization`. Эти заголовки пишет Auth Gateway на пути к `rag-edge`.

Ответ `401` с телом gateway `{"error":"unauthorized"}` значит, что сеанса нет. Клиент уводит браузер на `{PUBLIC_ORIGIN}/auth?return_to=` с текущим URL. Конверт RAG `error.code` в этом ответе не разбирается. `403` с `{"error":"blocked"}` или с кодом RAG `forbidden` показывает «Access denied» и не повторяет запрос.

Клиент собирается Vite. UI — React, Tailwind CSS, Zustand, PDF.js. Другой сборщик не используется. Форму API это не меняет. Сервисы API сами CORS не настраивают: браузер ходит на тот же хост. Локальная проверка без Auth Gateway бьёт во внутренние порты с заголовком `X-Auth-User-Id` и не является формой продакшена.

## Файлы, маршрут `/files`

Список — `GET /api/files`. Строка: имя, размер, статус, число страниц, дата `created_at`. `page_count = null` показывается как «—».

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
| `storage_read_failed` | Could not read the file from storage |
| `embedding_failed` | Could not build the vectors |
| `index_write_failed` | Could not write the index |
| `metadata_update_failed` | Could not save the status |
| `no_extractable_text` | No text found in the document |
| `enqueue_failed` | Could not queue the file |
| `processing_attempts_exceeded` | Processing stopped several times and did not finish |

Пока в загруженной странице списка есть `uploaded`, `processing` или `deleting`, клиент повторяет `GET /api/files` каждые 5 секунд. Когда таких статусов нет, опрос останавливается. Удаление и загрузка не ждут окончания опроса: они сразу меняют локальный список и затем сверяются с ответом сервера.

Загрузка — выбор файла или перетаскивание, один файл за запрос, `POST /api/files`. Ответ `409 duplicate_file` показывает «This document already exists». `413` и `415` показываются отдельно от общего сбоя.

Удаление спрашивает подтверждение и вызывает `DELETE`. `409 file_busy` показывает «Processing is still in progress or deletion has already started».

## Чат, маршрут `/chat`

Боковая колонка — `GET /api/chats`. Новый чат — `POST /api/chats`, затем переход в него.

Сообщения — `GET /api/chats/{chat_id}`. Отправка — `POST /api/chats/{chat_id}/messages` с `Accept: text/event-stream`.

Порядок на экране:

1. Сразу показать вопрос пользователя как неотправленный до `meta`.
2. По `meta` запомнить `user_message_id`, `assistant_message_id` и карточки `sources`. Карточки видны до окончания текста.
3. Склеивать `delta.content` в ответ и рисовать его как Markdown.
4. По `done` ход считается сохранённым. Если `finish_reason` равен `retrieval_only`, текста ответа нет: над карточками источников постоянная подпись «The model is unavailable. Showing the passages that were found.»
5. По `error` или обрыву потока показать ошибку у хода и не считать его сохранённым. Повтор отправляет тот же текст новым запросом.

Та же подпись показывается после `GET`, если у сообщения ассистента `finish_reason` равен `retrieval_only`. Клиент не подставляет текст чанков в тело ответа: фрагменты остаются в карточках.

Карточка источника: имя файла, «Page N», действие «Open». Если пользователь уже удалил файл, `GET /content` вернёт `404`; карточка остаётся, действие показывает «Preview unavailable».

Пустой ответ модели по контракту может быть фразой «Не найдено в документах.» Клиент не отличает её от обычного текста и не подменяет её своей строкой. Пустой `sources` просто не рисует карточек.

## Предпросмотр

Маршрут клиента: `/files/{file_id}?page={page_number}`.

PDF.js загружает `GET /api/files/{file_id}/content` тем же same-origin запросом, что и остальной API, и открывает страницу `page`. Заголовок личности клиент к этому URL не приписывает. Номер страницы в API не передаётся. Ответ API не вставляется в iframe: Auth Gateway ставит `X-Frame-Options: DENY`.

`page` меньше 1 заменяется на 1. Если страниц меньше запрошенной, viewer остаётся на последней и не шлёт повторный запрос к API.
