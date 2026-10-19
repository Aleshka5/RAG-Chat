# Поставка и локальный запуск

## Процессы, которые входят в систему

| Образ | Порт внутри сети | Роль |
|-------|------------------|------|
| `rag-edge` | 8080 | единственный вход с `rag_edge` |
| `file-collector` | 8081 | HTTP |
| `processor` | нет | consumer |
| `deletion-worker` | нет | consumer |
| `chat` | 8082 | HTTP |
| `ocr` | 8090 | внутренний HTTP |
| `embedding` | 8091 | внутренний HTTP |
| `frontend` | 3000 | статический UI |

Код всех этих образов лежит в одном репозитории. Стенд запускается Podman: `podman compose -f docker-compose.yml` из корня репозитория, вход через `make up`. Auth Gateway в этот compose не входит. Наружу из RAG смотрит только `rag-edge` в сети `rag_edge`. Для локальной проверки без gateway клиент бьёт во внутренний сервис и сам передаёт `X-Auth-User-Id`. Продакшен так не выставляется. Подробности — в [gateway.md](gateway.md).

Контейнер `embedding` внутри себя запускает `llama-server` на `127.0.0.1:8092` и FastAPI на 8091. В compose это один сервис, не два.

Инфраструктура локального стенда: MinIO, MongoDB 7, Qdrant ≥ 1.11, RabbitMQ 3 с management-плагином.

## Кто что создаёт при старте

| Ресурс | Кто |
|--------|-----|
| Бакет MinIO | File Collector |
| Индексы `files` | File Collector, Processor, Deletion Worker |
| Индекс `file_pages` | Processor, Deletion Worker |
| Индексы `chats` и `messages` | Chat |
| Коллекция Qdrant и payload-индексы | Processor |
| Топология RabbitMQ | File Collector, Processor, Deletion Worker |
| Веса OCR и Embedding | соответствующие процессы до готовности |

Повторный старт не пересоздаёт коллекцию и не удаляет данные.

## Локальный compose

Ниже состав стенда, тот же, что в корневом `docker-compose.yml`. Это не второй манифест: `make up` и `podman compose -f docker-compose.yml` читают тот файл. Секреты подставляются снаружи. У MinIO текущих образов задаются `MINIO_ROOT_USER` и `MINIO_ROOT_PASSWORD`, команда `server /data --console-address ":9001"`.

Порты на хост не публикуются. Имена сетей заданы явно, чтобы Auth Gateway мог подключиться к `rag_edge` как к external, не завися от имени проекта compose. `rag-edge` входит в обе сети: с `rag_edge` его видит gateway, по `rag_internal` он ходит к File Collector, Chat и frontend. Остальные контейнеры только в `rag_internal`.

Если `LLM_BASE_URL` — имя на уже существующей `llm_network` (`http://litellm-proxy-server:4000`), контейнер `chat` дополнительно подключают к этой external-сети. К `auth_network` не подключается никто.

```yaml
networks:
  rag_internal:
    name: rag_internal
  rag_edge:
    name: rag_edge
  llm_network:
    name: llm_network
    external: true

services:
  rag-edge:
    build: ./services/rag-edge
    networks: [rag_internal, rag_edge]
    restart: unless-stopped
    depends_on: [file-collector, chat, frontend]
    environment:
      RAG_EDGE_PORT: "8080"
      MAX_UPLOAD_BYTES: "524288000"
      FILE_COLLECTOR_URL: http://file-collector:8081
      CHAT_URL: http://chat:8082
      FRONTEND_URL: http://frontend:3000

  file-collector:
    build: ./services/file-collector
    networks: [rag_internal]
    restart: unless-stopped
    depends_on: [mongo, minio, rabbitmq]
    environment:
      FILE_COLLECTOR_PORT: "8081"
      MAX_UPLOAD_BYTES: "524288000"
      S3_ENDPOINT: http://minio:9000
      S3_ACCESS_KEY: ${S3_ACCESS_KEY}
      S3_SECRET_KEY: ${S3_SECRET_KEY}
      S3_BUCKET: documents
      MONGODB_URI: mongodb://mongo:27017/rag
      RABBITMQ_URL: amqp://rabbit:5672/

  processor:
    build: ./services/processor
    networks: [rag_internal]
    restart: unless-stopped
    depends_on: [mongo, minio, qdrant, ocr, embedding, rabbitmq]
    environment:
      S3_ENDPOINT: http://minio:9000
      S3_ACCESS_KEY: ${S3_ACCESS_KEY}
      S3_SECRET_KEY: ${S3_SECRET_KEY}
      MONGODB_URI: mongodb://mongo:27017/rag
      QDRANT_URL: http://qdrant:6333
      OCR_URL: http://ocr:8090
      EMBEDDING_URL: http://embedding:8091
      RABBITMQ_URL: amqp://rabbit:5672/
      PROCESSOR_CONCURRENCY: "1"

  deletion-worker:
    build: ./services/deletion-worker
    networks: [rag_internal]
    restart: unless-stopped
    depends_on: [mongo, minio, qdrant, rabbitmq]
    environment:
      S3_ENDPOINT: http://minio:9000
      S3_ACCESS_KEY: ${S3_ACCESS_KEY}
      S3_SECRET_KEY: ${S3_SECRET_KEY}
      MONGODB_URI: mongodb://mongo:27017/rag
      QDRANT_URL: http://qdrant:6333
      RABBITMQ_URL: amqp://rabbit:5672/
      DELETION_CONCURRENCY: "1"

  chat:
    build: ./services/chat
    networks: [rag_internal, llm_network]
    restart: unless-stopped
    depends_on: [mongo, qdrant, embedding]
    environment:
      CHAT_PORT: "8082"
      MONGODB_URI: mongodb://mongo:27017/rag
      QDRANT_URL: http://qdrant:6333
      EMBEDDING_URL: http://embedding:8091
      LLM_BASE_URL: ${LLM_BASE_URL}
      LLM_API_KEY: ${LLM_API_KEY}
      LLM_MODEL: ${LLM_MODEL}

  ocr:
    build: ./services/ocr
    networks: [rag_internal]
    restart: unless-stopped

  embedding:
    build: ./services/embedding
    networks: [rag_internal]
    restart: unless-stopped

  frontend:
    build: ./frontend
    networks: [rag_internal]
    restart: unless-stopped

  minio:
    image: minio/minio
    networks: [rag_internal]
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${S3_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${S3_SECRET_KEY}
    volumes: ["minio-data:/data"]

  mongo:
    image: mongo:7
    networks: [rag_internal]
    restart: unless-stopped
    volumes: ["mongo-data:/data/db"]

  qdrant:
    image: qdrant/qdrant:v1.13.4
    networks: [rag_internal]
    restart: unless-stopped
    volumes: ["qdrant-data:/qdrant/storage"]

  rabbitmq:
    image: rabbitmq:3-management
    restart: unless-stopped
    networks: [rag_internal]
    volumes: ["rabbit-data:/var/lib/rabbitmq"]

volumes:
  minio-data:
  mongo-data:
  qdrant-data:
  rabbit-data:
```

Чтобы вызвать File Collector или Chat с хоста без gateway, порт этого сервиса публикуют временно и передают `X-Auth-User-Id`. В состав стенда по умолчанию такая публикация не входит.

Реплик processor и deletion-worker в MVP — одна. Вторая реплика допустима: захват статуса и стабильные id точек не требуют глобального лока. `prefetch` остаётся 1 на канал.

## Ручной возврат из DLQ

1. Прочитать сообщение из `doc.processing.dead` или `doc.deletion.dead`.
2. Взять исходное JSON-тело. Заголовок `x-death` не переносить и в тело не вставлять.
3. Устранить причину (доступность хранилища, битый PDF, неверная схема).
4. Опубликовать тело в `doc_events` с routing key `doc.process` или `doc.delete`, `delivery_mode=2`, новый `message_id` можно оставить прежним.
5. Подтвердить копию в dead-очереди только после confirm рабочей публикации.

Битый PDF после replay снова уйдёт в DLQ со статусом `error`. Его путь — удаление через API, а не бесконечный replay.

## Проверка стенда

1. `GET /health` у rag-edge, file-collector, chat, ocr, embedding. На публичном хосте тот же путь отвечает edge и не требует cookie.
2. Загрузка небольшого текстового PDF с заголовком `X-Auth-User-Id` заканчивается статусом `ready`. Тот же запрос только с `X-User-Id` даёт `401`.
3. Вопрос по фразе из PDF возвращает `meta.sources` с нужным `file_id` и страницей.
4. `GET /content` этого файла отдаёт байты PDF.
5. `DELETE` переводит файл в `deleting`, затем в `deleted`; список его больше не показывает; точки с этим `document_id` в Qdrant отсутствуют; объект в бакете отсутствует.
6. Повторная публикация того же `doc.delete` подтверждается и не меняет результат.
