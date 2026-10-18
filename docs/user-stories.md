# Истории разработки

Как вошедший пользователь, я загружаю PDF, они индексируются (текстовый слой и OCR сканов), я задаю вопросы по готовым документам и получаю ответ потоком SSE с источниками на уровне страницы, открываю PDF на процитированной странице с того же origin и удаляю файлы и чаты. Данные арендаторов изолированы. Готово, когда выполнен каждый пункт [mvp.md](mvp.md).

Каталоги ниже не пересекаются. История не правит чужой каталог и норматив `docs/`, кроме этого файла у US-0. Ветка — `cursor/<имя>-cc69`.

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
> - [ ] Обрыв LLM не создаёт пару сообщений. Повторный вопрос после успеха создаёт второй ход.
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
