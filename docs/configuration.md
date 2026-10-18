# Конфигурация

Имена общие для всех процессов, которым переменная нужна. Секреты не имеют значений по умолчанию. Сервис, которому не хватает обязательной переменной, не стартует и пишет в лог имя переменной без её значения.

## Общие

| Переменная | Кто | По умолчанию | Смысл |
|------------|-----|--------------|--------|
| `MONGODB_URI` | file-collector, processor, deletion, chat | нет | URI, включая имя базы. |
| `S3_ENDPOINT` | file-collector, processor, deletion | нет | URL MinIO. |
| `S3_ACCESS_KEY` | те же | нет | |
| `S3_SECRET_KEY` | те же | нет | |
| `S3_BUCKET` | те же | `documents` | |
| `S3_REGION` | те же | `us-east-1` | Для MinIO значение формальное, но клиент его требует. |
| `QDRANT_URL` | processor, deletion, chat | нет | Например `http://qdrant:6333`. |
| `QDRANT_COLLECTION` | те же | `documents` | |
| `RABBITMQ_URL` | file-collector, processor, deletion | нет | AMQP URI. |
| `RABBITMQ_EXCHANGE` | те же | `doc_events` | |
| `RABBITMQ_DLX` | те же | `doc_events_dlq` | |
| `EMBEDDING_URL` | processor, chat | нет | Базовый URL без пути, например `http://embedding:8091`. |
| `OCR_URL` | processor | нет | Например `http://ocr:8090`. |
| `LOG_LEVEL` | все | `info` | `debug`, `info`, `warning`, `error`. |

## File Collector

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `FILE_COLLECTOR_PORT` | `8081` | |
| `MAX_UPLOAD_BYTES` | `52428800` | 50 МиБ. |

## Processor

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `PROCESSOR_CONCURRENCY` | `1` | Число каналов с `prefetch=1`. |
| `CHUNK_TOKENS` | `512` | Не выше `EMBEDDING_MAX_TOKENS` и не выше локального окна модели (1024). |
| `CHUNK_OVERLAP_TOKENS` | `51` | Меньше `CHUNK_TOKENS`, около 10%. |
| `MAX_PROCESS_ATTEMPTS` | `8` | Сколько доставок одного сообщения можно начать, не дойдя до `ready`. |
| `MIN_EXTRACTED_CHARS` | `50` | Страница короче или равна порогу идёт в OCR. |
| `OCR_RENDER_DPI` | `300` | |
| `OCR_TIMEOUT` | `30` | Секунды на один запрос страницы. |
| `OCR_MAX_ATTEMPTS` | `3` | |
| `EMBEDDING_TIMEOUT` | `30` | Секунды на одну пачку. |
| `EMBEDDING_BATCH_SIZE` | `16` | Совпадает с лимитом Embedding. |
| `EMBEDDING_DIM` | `768` | |
| `EMBEDDING_MAX_TOKENS` | `1024` | Тот же потолок, что у сервиса Embedding. |
| `QDRANT_UPSERT_BATCH` | `64` | |
| `STALE_PROCESSING_SECONDS` | `900` | После этого DELETE может забрать `processing`. |
| `SWEEP_INTERVAL_SECONDS` | `60` | |
| `UPLOAD_REQUEUE_AFTER_SECONDS` | `120` | Возраст записи `error=enqueue_failed`, после которого sweeper публикует сообщение. |

`CHUNK_TOKENS` не больше `EMBEDDING_MAX_TOKENS`, перекрытие меньше окна. Иначе процесс не стартует.

## Deletion Worker

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `DELETION_CONCURRENCY` | `1` | |
| `STALE_PROCESSING_SECONDS` | `900` | Тот же смысл, что у Processor. Значения в обоих процессах должны совпадать. |
| `SWEEP_INTERVAL_SECONDS` | `60` | |
| `DELETE_REQUEUE_AFTER_SECONDS` | `120` | |

## Chat

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `CHAT_PORT` | `8082` | |
| `LLM_BASE_URL` | нет | Без завершающего слэша, уже включает `/v1`, если так устроен endpoint. |
| `LLM_API_KEY` | нет | |
| `LLM_MODEL` | нет | Имя модели на стороне провайдера. |
| `LLM_TEMPERATURE` | `0.2` | |
| `LLM_TIMEOUT_SECONDS` | `60` | И на первый байт, и на весь поток. |
| `RAG_TOP_K` | `5` | Больше 0, не больше 50. |
| `RAG_MIN_SCORE` | `0` | `0` выключает отсечение. |
| `RAG_CONTEXT_MESSAGES` | `10` | Сколько прошлых сообщений попадает в промпт. |
| `EMBEDDING_TIMEOUT` | `10` | |
| `EMBEDDING_DIM` | `768` | Длина вектора вопроса. Иная длина — ошибка запроса, не поиск. |
| `EMBEDDING_MAX_TOKENS` | `1024` | Потолок вопроса вместе с префиксом. |

## OCR

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `OCR_PORT` | `8090` | |
| `OCR_MODEL` | `paddleocr_multilingual` | PP-OCRv4, `en` + `ru`. |
| `OCR_TIMEOUT` | `30` | Серверный бюджет разбора. |

## Embedding

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `EMBEDDING_PORT` | `8091` | |
| `EMBEDDING_MODEL` | `google/embeddinggemma-2` | Текстовый контур, без энкодеров изображения и звука. |
| `EMBEDDING_DIM` | `768` | Полная размерность. Усечение Matryoshka в MVP не используется. |
| `EMBEDDING_MAX_TOKENS` | `1024` | После префикса запроса или документа. Контекст модели — 8192. |
| `EMBEDDING_BATCH_SIZE` | `16` | Верхняя граница `texts` на CPU. |
| `EMBEDDING_TIMEOUT` | `30` | Секунды на одну пачку. |

## Gateway

Своих переменных в этом репозитории нет. Существующий gateway направляет:

| Внешний путь | Куда |
|--------------|------|
| `/api/files` | File Collector |
| `/api/chats` | Chat |
| остальной UI | Frontend |

Он же выставляет `X-User-Id` и не пропускает запрос к этим префиксам без установленного пользователя.
