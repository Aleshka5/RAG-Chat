# Подключение к Auth Gateway

Auth Gateway уже стоит на краю `filenkov.store`. Этот репозиторий его не реализует и не поднимает второй публичный вход. Caddy по-прежнему только завершает TLS. RAG-чат — ещё один upstream за тем же gateway.

Норматив сети и заголовков — этот файл. Поведение `/api/files` и `/api/chats` остаётся в [api.md](api.md).

## Что RAG принимает за личность

Gateway для нового хоста с `role_field: global_role` подставляет четыре заголовка и **не** подставляет `X-User-Id`. `X-User-Id` у этого gateway есть только у storage и у прокси к User-Service. RAG его не читает и не доверяет ему, даже если заголовок каким-то образом пришёл.

Перед проксированием gateway сам стирает клиентские `X-Auth-*`, `X-User-Id` и `X-Storage-Role`.

| Заголовок | Кто | Как использует RAG |
|-----------|-----|--------------------|
| `X-Auth-User-Id` | JWT `sub`, UUID пользователя в User-Service | Единственный `user_id`. Обязателен на всех маршрутах File Collector и Chat, кроме `GET /health`. |
| `X-Auth-Email` | JWT `email` | Не читается в MVP. |
| `X-Auth-Name` | JWT `username` | Не читается в MVP. |
| `X-Auth-Role` | JWT `global_role` | Если значение `BLOCKED`, ответ `403` и код `forbidden`. Остальные роли проходят: доступ к RAG есть у любого действительного сеанса. |

Идентификатор хранится как UUID в каноническом виде `8-4-4-4-12`, в нижнем регистре. Версию UUID RAG не выбирает: это `sub` из User-Service.

Нет заголовка или это не UUID — `401`, код `unauthenticated`. Cookie, `Authorization` и JWT RAG не проверяет и по ним пользователя не восстанавливает. Gateway может переслать cookie; для RAG это шум.

`GET /health` заголовок личности не требует. Это и внутренние проверки file-collector, chat, OCR и Embedding, и публичный `GET /health` на крае RAG.

## Край, который видит gateway

Снаружи один хост и один upstream. Внутри сети RAG путь разбирает процесс `rag-edge`. Gateway не знает про File Collector и Chat по отдельности.

| Путь на хосте | Куда ведёт `rag-edge` |
|---------------|------------------------|
| `GET /health` | Ответ самого edge: `{"status":"ok"}`. В MongoDB и очередь не ходит. |
| `/api/files` и `/api/files/*` | File Collector |
| `/api/chats` и `/api/chats/*` | Chat |
| всё остальное | Frontend |

Тело загрузки edge пропускает целиком до `MAX_UPLOAD_BYTES` (по умолчанию 500 МиБ) и не ставит меньший предел. Ответ `413` даёт File Collector. Поток `text/event-stream` edge не буферизует: байты чата уходят клиенту по мере прихода от Chat.

Публичного порта у edge нет. Контейнер состоит в `rag_edge` и в `rag_internal`; с хоста его порт не открыт.

## Сети

Две сети, обе создаёт compose RAG.

| Сеть | Кто в ней | Кто снаружи |
|------|-----------|-------------|
| `rag_internal` | edge, frontend, file-collector, chat, processor, deletion-worker, OCR, embedding, MinIO, MongoDB, Qdrant, RabbitMQ | Никто. Сеть не external. |
| `rag_edge` | только контейнер `rag-edge` | Auth Gateway. Для него сеть external. |

Имена сетей зафиксированы: `rag_internal` и `rag_edge`. Compose Auth подключает **только процесс gateway** к `rag_edge` как к external-сети с этим именем. К `rag_internal` он не подключается и имена `mongo`, `qdrant`, `minio`, `file-collector` оттуда не видит. Порты RAG на хост не публикуются. RAG не входит в `auth_network`.

Порядок: сначала compose RAG, чтобы сеть `rag_edge` и контейнер `rag-edge` существовали, затем пересоздать gateway Auth, чтобы он к сети присоединился. В Caddy для `rag.filenkov.store` — один `reverse_proxy localhost:8083` и тот же набор заголовков, что у остальных продуктовых хостов. Отдельных `handle` по `/api` нет.

Если Chat ходит в LiteLLM по имени `litellm-proxy-server`, к external `llm_network` присоединяется только контейнер `chat`. Это не сеть края и не повод пускать gateway в `rag_internal`.

OCR и Embedding по-прежнему без проверки пользователя. Их закрывает `rag_internal`, а не заголовок.

## Запись, которую добавляют в gateway

Это правка чужого `deploy/gateway.yaml` и compose Auth, не код этого репозитория. Хост — `rag.filenkov.store`. Имя должно попадать в домен cookie `COOKIE_DOMAIN`, иначе браузер не пришлёт `auth_access`, и gateway сочтёт запрос анонимным. Список хостов в том же YAML задаёт `aud` JWT, поэтому хост добавляется до того, как пользователи пойдут на новый адрес. Старый access-токен без этого `aud` обновится штатным `POST /api/refresh` на gateway.

```yaml
upstreams:
  rag: "http://rag-edge:8080"

hosts:
  rag.filenkov.store:
    role_field: global_role
    timeouts:
      proxy: 5m
    routes:
      - match: /health
        upstream: rag
        auth: public
      - match: /*
        upstream: rag
        auth: session
```

`role_field: global_role` — как у messenger: четыре `X-Auth-*`, без вызова User-Service и без `X-User-Id`. `inject_access_jwt` не ставится: JWT на RAG не уходит.

`timeouts.proxy: 5m` — таймаут заголовка ответа. Загрузка PDF и чат до первого байта потока укладываются в него с запасом относительно `LLM_TIMEOUT_SECONDS`. Тело потока после заголовков этим таймаутом не режется.

Политика `auth: session` на catch-all. Анонимную HTML-навигацию gateway сам уводит `302` на `{public_origin}/auth?return_to=`. Запрос с префиксом `/api/`, с `Accept: application/json` или с `X-Requested-With` без сеанса gateway режет `401` и телом `{"error":"unauthorized"}`. Это тело gateway, не конверт RAG. До File Collector и Chat такой запрос не доходит.

`BLOCKED` и `rejected_cache` gateway останавливает `403` `{"error":"blocked"}` до RAG. Проверка `X-Auth-Role == BLOCKED` внутри RAG — второй рубеж, если заголовок всё же пришёл.

Лимит gateway `requests_per_minute` (в конфигурации по умолчанию 180 на IP) действует и на этот хост. Отдельного лимита в RAG в MVP нет.

Заголовки безопасности gateway, включая `X-Frame-Options: DENY`, стоят и на проксированных ответах. Предпросмотр PDF делается через PDF.js запросом байтов, не через iframe на URL API.

Свой `GET /healthz` у RAG нет. У gateway `GET /healthz` отвечает он сам, до маршрутизации по хосту. Публичная проверка RAG — `GET /health`.

## Что менять в Auth не нужно

Не нужен новый `role_field`, вызов User-Service за ролью RAG и заголовок `X-User-Id`. Не нужен `auth: admin`: чат доступен любому пользователю с действительным access JWT, не только `ADMIN`. Не нужна публикация порта RAG рядом с Caddy: снаружи по-прежнему один `reverse_proxy` на gateway, плюс server block Caddy на `rag.filenkov.store` тем же способом, что у storage и messenger.
