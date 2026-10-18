# Поставка и локальный запуск

## Процессы, которые входят в систему

| Образ | Порт | Роль |
|-------|------|------|
| `file-collector` | 8081 | HTTP |
| `processor` | нет | consumer |
| `deletion-worker` | нет | consumer |
| `chat` | 8082 | HTTP |
| `ocr` | 8090 | внутренний HTTP |
| `embedding` | 8091 | внутренний HTTP |
| `frontend` | 3000 | статический UI и dev-сервер |

Gateway в compose нет: он уже развёрнут снаружи. Для локальной проверки клиент ходит на порты сервисов напрямую и сам передаёт `X-User-Id`.

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

Ниже состав стенда, а не готовый манифест релиза. Секреты подставляются снаружи. У MinIO текущих образов задаются `MINIO_ROOT_USER` и `MINIO_ROOT_PASSWORD`, команда `server /data --console-address ":9001"`.

```yaml
services:
  file-collector:
    build: ./services/file-collector
    ports: ["8081:8081"]
    environment:
      FILE_COLLECTOR_PORT: "8081"
      S3_ENDPOINT: http://minio:9000
      S3_ACCESS_KEY: ${S3_ACCESS_KEY}
      S3_SECRET_KEY: ${S3_SECRET_KEY}
      S3_BUCKET: documents
      MONGODB_URI: mongodb://mongo:27017/rag
      RABBITMQ_URL: amqp://rabbit:5672/

  processor:
    build: ./services/processor
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
    ports: ["8082:8082"]
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
    ports: ["8090:8090"]

  embedding:
    build: ./services/embedding
    ports: ["8091:8091"]

  frontend:
    build: ./frontend
    ports: ["3000:3000"]

  minio:
    image: minio/minio
    ports: ["9000:9000", "9001:9001"]
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${S3_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${S3_SECRET_KEY}
    volumes: ["minio-data:/data"]

  mongo:
    image: mongo:7
    ports: ["27017:27017"]
    volumes: ["mongo-data:/data/db"]

  qdrant:
    image: qdrant/qdrant:v1.13.4
    ports: ["6333:6333"]
    volumes: ["qdrant-data:/qdrant/storage"]

  rabbitmq:
    image: rabbitmq:3-management
    ports: ["5672:5672", "15672:15672"]
    volumes: ["rabbit-data:/var/lib/rabbitmq"]

volumes:
  minio-data:
  mongo-data:
  qdrant-data:
  rabbit-data:
```

Порты OCR и Embedding на хосте нужны для отладки. В общем стенде их наружу не публикуют.

Реплик processor и deletion-worker в MVP — одна. Вторая реплика допустима: захват статуса и стабильные id точек не требуют глобального лока. `prefetch` остаётся 1 на канал.

## Ручной возврат из DLQ

1. Прочитать сообщение из `doc.processing.dead` или `doc.deletion.dead`.
2. Взять исходное JSON-тело. Заголовок `x-death` не переносить и в тело не вставлять.
3. Устранить причину (доступность хранилища, битый PDF, неверная схема).
4. Опубликовать тело в `doc_events` с routing key `doc.process` или `doc.delete`, `delivery_mode=2`, новый `message_id` можно оставить прежним.
5. Подтвердить копию в dead-очереди только после confirm рабочей публикации.

Битый PDF после replay снова уйдёт в DLQ со статусом `error`. Его путь — удаление через API, а не бесконечный replay.

## Проверка стенда

1. `GET /health` у file-collector, chat, ocr, embedding.
2. Загрузка небольшого текстового PDF с заголовком `X-User-Id` заканчивается статусом `ready`.
3. Вопрос по фразе из PDF возвращает `meta.sources` с нужным `file_id` и страницей.
4. `GET /content` этого файла отдаёт байты PDF.
5. `DELETE` переводит файл в `deleting`, затем в `deleted`; список его больше не показывает; точки с этим `document_id` в Qdrant отсутствуют; объект в бакете отсутствует.
6. Повторная публикация того же `doc.delete` подтверждается и не меняет результат.
