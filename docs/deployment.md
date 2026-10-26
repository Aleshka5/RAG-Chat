# Поставка и локальный запуск

## Процессы, которые входят в систему

| Образ | Порт внутри сети | Роль |
|-------|------------------|------|
| `rag-edge` | 8080 | единственный вход с `rag_edge` |
| `file-collector` | 8081 | HTTP |
| `processor` | нет | consumer |
| `deletion-worker` | нет | consumer |
| `chat` | 8082 | HTTP |
| `ocr` | 8090 | внутренний HTTP, в `models_network` под Switch-Service |
| `embedding` | 8091 | внутренний HTTP, в `models_network` под Switch-Service |
| `frontend` | 3000 | статический UI |

Код всех этих образов лежит в одном репозитории, но владельцев у контейнеров два. RAG-стек запускается Podman: `podman compose -f docker-compose.yml` из корня репозитория, вход через `make up`; в нём только `rag-edge`, `file-collector`, `processor`, `deletion-worker`, `chat`, `frontend`, Mongo и Qdrant. OCR, embedding, LLM и генерация изображений в этот compose не входят: их контейнеры создаёт и держит Switch-Service в общей сети `models_network` (см. `Switch-Service/docs/models-network.md`). Второго владельца у них нет намеренно — иначе reconciler Switch-Service и `podman compose up` перетирали бы состояние друг друга. Auth Gateway в этот compose не входит. Наружу из RAG смотрит только `rag-edge` в сети `rag_edge`. Для локальной проверки без gateway клиент бьёт во внутренний сервис и сам передаёт `X-Auth-User-Id`. Продакшен так не выставляется. Подробности — в [gateway.md](gateway.md).

Контейнер `embedding` внутри себя запускает `llama-server` на `127.0.0.1:8092` и FastAPI на 8091. Контейнер `ocr` так же запускает свой `llama-server` на `127.0.0.1:8092` и FastAPI на 8090. У Switch-Service каждый из них один контейнер, не два. Порт llama-server наружу контейнера не публикуется. У OCR нет потолка по потокам и памяти: llama.cpp занимает ядра, которые есть у процесса.

## GPU для OCR

Режим CPU/GPU больше не переключается compose-целью и не требует пересборки. Образ `ocr` собирается один раз, целью `cuda`: локальный `localhost/rag-chat_ocr:cuda` поверх `ghcr.io/ggml-org/llama.cpp:server-cuda12` (CUDA 12.8, Ubuntu 24.04). В этом образе уже лежат `llama-server`, библиотеки ggml и runtime CUDA (`libcudart`, `libcublas`). Цель `cpu` (пин-бинарник b11721 на `python:3.12-slim-bookworm`) остаётся в `services/ocr/Dockerfile` для сборки без GPU, но переключателем режима не является: один и тот же CUDA-образ работает в обоих режимах.

Режим выбирает `OCR_LLAMA_NGL` в каталоге Switch-Service: `0` — слои остаются на CPU, `999` — все слои уходят на GPU; для embedder то же самое делает `EMBEDDING_LLAMA_NGL`. Смена режима — это пересоздание контейнера Switch-Service (`.venv/bin/switch-service state ocr gpu`), а не пересборка образа. Собирает образ не этот стек: под именем из каталога (`localhost/rag-chat_ocr:cuda`) он должен уже лежать локально, иначе Switch-Service отвечает `IMAGE_MISSING`, а не собирает его сам.

GPU контейнеру отдаёт Switch-Service, тем же способом, каким его отдаёт хост: CDI-устройство `nvidia.com/gpu=all` (`nvidia-ctk cdi list`), как и эталонный `startup_qwen3.8_image_instance_podman.sh`. Драйвер (`libcuda`) приходит с хоста, runtime CUDA остаётся в образе `server-cuda12`. Кэш весов — том `rag-chat_ocr-model-cache` на `/var/cache/huggingface`: его создаёт podman при первом `create`, в compose он не объявляется, процесс пишет в него от пользователя `ocr`.

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `OCR_LLAMA_NGL` | по профилю каталога (`0` в `cpu`, `999` в `gpu`) | Сколько слоёв llama.cpp выносит на GPU. Задаётся в каталоге Switch-Service, не в этом репозитории. |
| `EMBEDDING_LLAMA_NGL` | по профилю каталога (`0` в `cpu`, `999` в `gpu`) | То же для embedder. |
| Память embedder, профиль `gpu` | 2304 МиБ VRAM и 1024 МиБ RAM | Заявка каталога Switch-Service. В compose этого репозитория контейнер embedding не описан. |
| Память embedder, профиль `cpu` | 1792 МиБ RAM | Заявка того же каталога. |
| `HF_TOKEN` | нет | Необязательный токен Hugging Face. Пусто — анонимное скачивание. |

Инфраструктура локального стенда: MinIO и RabbitMQ 3 (с management-плагином) общие, живут в `common_network` (см. `Common/docker-compose-common.yml`), куда RAG-сервисы подключаются как к external-сети. В составе RAG-стека остаются MongoDB 7 и Qdrant ≥ 1.13. Сеть `models_network` вместе с `ocr`, `embedding`, LLM и генерацией изображений для этого стека тоже external: и сеть, и контейнеры создаёт Switch-Service.

## Кто что создаёт при старте

| Ресурс | Кто |
|--------|-----|
| Бакет MinIO | File Collector |
| Индексы `files` | File Collector, Processor, Deletion Worker |
| Индекс `file_pages` | Processor, Deletion Worker |
| Индексы `chats` и `messages` | Chat |
| Коллекции Qdrant `documents` и `images` и их payload-индексы | Processor |
| Топология RabbitMQ | File Collector, Processor, Deletion Worker |
| Веса OCR и Embedding | Switch-Service: процессы `ocr` и `embedding` до готовности |

Повторный старт не пересоздаёт коллекцию и не удаляет данные.

## Локальный compose

Ниже состав стенда, тот же, что в корневом `docker-compose.yml`. Это не второй манифест: `make up` и `podman compose -f docker-compose.yml` читают тот файл. Секреты подставляются снаружи. MinIO и RabbitMQ здесь не описаны — они общие и берутся из `common_network` (см. `Common/docker-compose-common.yml`). OCR и embedding здесь тоже не описаны: их контейнеры держит Switch-Service, а этот стек только подключается к их сети `models_network` как к external.

Порты на хост не публикуются. Имена сетей заданы явно, чтобы Auth Gateway мог подключиться к `rag_edge` как к external, не завися от имени проекта compose. `rag-edge` входит в обе сети: с `rag_edge` его видит gateway, по `rag_internal` он ходит к File Collector, Chat и frontend. `file-collector`, `processor` и `deletion-worker` дополнительно входят в external-сеть `common_network`, где отвечают общие `minio` (S3) и `rabbit` (AMQP). `processor` и `chat` дополнительно входят в external-сеть `models_network`, где Switch-Service держит `ocr` и `embedding`; адреса в окружении от этого не меняются — `OCR_URL: http://ocr:8090` и `EMBEDDING_URL: http://embedding:8091` резолвятся по именам контейнеров в этой сети. Потребителей в `models_network` можно подключить и снаружи, скриптом Switch-Service (`make network`), но compose делает это сам при старте.

Если `LLM_BASE_URL` — имя на уже существующей `llm_network` (`http://litellm-proxy-server:4000`), контейнер `chat` дополнительно подключают к этой external-сети. К `auth_network` не подключается никто.

```yaml
networks:
  rag_internal:
    name: rag_internal
  rag_edge:
    name: rag_edge
  common_network:
    name: common_network
    external: true
  models_network:
    name: models_network
    external: true
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
    build:
      context: .
      dockerfile: services/file-collector/Dockerfile
    networks: [rag_internal, common_network]
    restart: unless-stopped
    depends_on: [mongo]
    environment:
      FILE_COLLECTOR_PORT: "8081"
      MAX_UPLOAD_BYTES: "524288000"
      S3_ENDPOINT: http://minio:9000
      S3_ACCESS_KEY: ${S3_ACCESS_KEY}
      S3_SECRET_KEY: ${S3_SECRET_KEY}
      S3_BUCKET: storage
      MONGODB_URI: mongodb://mongo:27017/rag
      RABBITMQ_URL: amqp://rabbit:5672/

  processor:
    build:
      context: .
      dockerfile: services/processor/Dockerfile
    networks: [rag_internal, common_network, models_network]
    restart: unless-stopped
    depends_on: [mongo, qdrant]
    environment:
      S3_ENDPOINT: http://minio:9000
      S3_ACCESS_KEY: ${S3_ACCESS_KEY}
      S3_SECRET_KEY: ${S3_SECRET_KEY}
      S3_BUCKET: storage
      MONGODB_URI: mongodb://mongo:27017/rag
      QDRANT_URL: http://qdrant:6333
      OCR_URL: http://ocr:8090
      OCR_TIMEOUT: ${OCR_TIMEOUT:-120}
      EMBEDDING_URL: http://embedding:8091
      RABBITMQ_URL: amqp://rabbit:5672/
      PROCESSOR_CONCURRENCY: "1"

  deletion-worker:
    build:
      context: .
      dockerfile: services/deletion-worker/Dockerfile
    networks: [rag_internal, common_network]
    restart: unless-stopped
    depends_on: [mongo, qdrant]
    environment:
      S3_ENDPOINT: http://minio:9000
      S3_ACCESS_KEY: ${S3_ACCESS_KEY}
      S3_SECRET_KEY: ${S3_SECRET_KEY}
      S3_BUCKET: storage
      MONGODB_URI: mongodb://mongo:27017/rag
      QDRANT_URL: http://qdrant:6333
      RABBITMQ_URL: amqp://rabbit:5672/
      DELETION_CONCURRENCY: "1"

  chat:
    build: ./services/chat
    networks: [rag_internal, llm_network, models_network]
    restart: unless-stopped
    depends_on: [mongo, qdrant]
    environment:
      CHAT_PORT: "8082"
      MONGODB_URI: mongodb://mongo:27017/rag
      QDRANT_URL: http://qdrant:6333
      EMBEDDING_URL: http://embedding:8091
      LLM_BASE_URL: ${LLM_BASE_URL}
      LLM_API_KEY: ${LLM_API_KEY}
      LLM_MODEL: ${LLM_MODEL}

  frontend:
    build: ./frontend
    networks: [rag_internal]
    restart: unless-stopped

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

volumes:
  mongo-data:
  qdrant-data:
```

Чтобы вызвать File Collector или Chat с хоста без gateway, порт этого сервиса публикуют временно и передают `X-Auth-User-Id`. В состав стенда по умолчанию такая публикация не входит.

Реплик processor и deletion-worker в MVP — одна. Вторая реплика допустима: захват статуса и стабильные id точек не требуют глобального лока. `prefetch` остаётся 1 на канал.

## Ручной возврат из DLQ

1. Прочитать сообщение из `doc.processing.dead` или `doc.deletion.dead`.
2. Взять исходное JSON-тело. Заголовок `x-death` не переносить и в тело не вставлять.
3. Устранить причину (доступность хранилища, битый PDF, неверная схема).
4. Опубликовать тело в `doc_events` с routing key `doc.process` или `doc.delete`, `delivery_mode=2`, новый `message_id` можно оставить прежним.
5. Подтвердить копию в dead-очереди только после confirm рабочей публикации.

Битый PDF после replay снова уйдёт в DLQ со статусом `error`. Его путь — удаление через API, а не бесконечный replay. Постоянно отвергнутое изображение (`unsupported_image`) ведёт себя так же.

## Проверка стенда

1. `GET /health` у rag-edge, file-collector, chat. Те же пути у `ocr` и `embedding` проверяются со стороны Switch-Service (`make network-status`): их health-порты опубликованы только на loopback (`127.0.0.1:18090`, `127.0.0.1:18091`). На публичном хосте тот же путь отвечает edge и не требует cookie.
2. Загрузка небольшого текстового PDF с заголовком `X-Auth-User-Id` заканчивается статусом `ready`. Тот же запрос только с `X-User-Id` даёт `401`.
3. Вопрос по фразе из PDF возвращает `meta.sources` с нужным `file_id` и страницей.
4. `GET /content` этого файла отдаёт байты PDF.
5. `DELETE` переводит файл в `deleting`, затем в `deleted`; список его больше не показывает; точки с этим `document_id` в Qdrant отсутствуют; объект в бакете отсутствует.
6. Повторная публикация того же `doc.delete` подтверждается и не меняет результат.
