# Конфигурация

Имена общие для всех процессов, которым переменная нужна. Секреты не имеют значений по умолчанию. Сервис, которому не хватает обязательной переменной, не стартует и пишет в лог имя переменной без её значения.

## Общие

| Переменная | Кто | По умолчанию | Смысл |
|------------|-----|--------------|--------|
| `MONGODB_URI` | file-collector, processor, deletion, chat | нет | URI, включая имя базы. База RAG живёт в общей MongoDB из `common_network`: `mongodb://mongo:27017/rag`. |
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
| `MAX_UPLOAD_BYTES` | `524288000` | 500 МиБ. Больше этого File Collector отвечает `413` и в MinIO не пишет. |

## Processor

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `PROCESSOR_CONCURRENCY` | `1` | Число каналов с `prefetch=1`. |
| `CHUNK_TOKENS` | `512` | Не выше `EMBEDDING_MAX_TOKENS` и не выше локального окна модели (1024). |
| `CHUNK_OVERLAP_TOKENS` | `51` | Меньше `CHUNK_TOKENS`, около 10%. |
| `MAX_PROCESS_ATTEMPTS` | `8` | Сколько доставок одного сообщения можно начать, не дойдя до `ready`. |
| `MIN_EXTRACTED_CHARS` | `50` | Страница короче или равна порогу идёт в OCR. |
| `OCR_RENDER_DPI` | `300` | |
| `OCR_TIMEOUT` | `120` | Секунды на один запрос страницы. |
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
| `OCR_MODEL` | `surya-ocr-2` | Surya OCR 2, одна модель на `en` и `ru`. Другое значение не даёт процессу стартовать. |
| `OCR_TIMEOUT` | `120` | Серверный бюджет разбора одной страницы. |
| `OCR_LLAMA_URL` | `http://127.0.0.1:8092` | llama-server внутри контейнера. Наружу этот порт не публикуется. |
| `OCR_LLAMA_NGL` | `999` | Сколько слоёв уходит на GPU: `999`/`-1` — все, `0` — ни одного (чистый CPU), `N` — частично. Режим задаётся этой переменной, а не пересборкой образа. |
| `HF_TOKEN` | нет | Необязательный токен Hugging Face для скачивания весов. Пусто — анонимный доступ. |

## Embedding

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `EMBEDDING_PORT` | `8091` | |
| `EMBEDDING_MODEL` | `google/embeddinggemma-2` | Имя в ответе `/embed` и `/embed/image`. Кодировщик изображения загружается, кодировщик звука — нет. |
| `EMBEDDING_GGUF` | `embeddinggemma-2-Q8_0.gguf` | Текстовый файл из `ggml-org/embeddinggemma-2-GGUF`. Не F16 и не `mmproj`. |
| `EMBEDDING_MMPROJ` | `mmproj-embeddinggemma-2-Q8_0.gguf` | Проектор изображения из того же репозитория и ревизии. Имя обязано содержать `mmproj`, иначе процесс не стартует. |
| `EMBEDDING_LLAMA_URL` | `http://127.0.0.1:8092` | llama-server внутри контейнера. В `rag_internal` этот порт не публикуется. |
| `EMBEDDING_CONTEXT` | `2048` | Одинаковые `--ctx-size`, `--batch-size` и `--ubatch-size`. |
| `EMBEDDING_DIM` | `768` | Полная размерность. Усечение Matryoshka в MVP не используется. |
| `EMBEDDING_MAX_TOKENS` | `1024` | После префикса запроса или документа. Контекст модели — 8192. |
| `EMBEDDING_BATCH_SIZE` | `16` | Верхняя граница `texts` на CPU. |
| `EMBEDDING_MAX_IMAGES` | `4` | Верхняя граница `images` на `/embed/image`. Больше 64 не принимается. |
| `EMBEDDING_MAX_IMAGE_BYTES` | `10485760` | Размер одного изображения после декодирования, 10 МиБ. Больше 100 МиБ не принимается. |
| `EMBEDDING_TIMEOUT` | `30` | Секунды на одну пачку. |
| `EMBEDDING_LLAMA_NGL` | `999` | Сколько слоёв уходит на GPU: `999`/`-1` — все, `0` — чистый CPU. Один CUDA-образ обслуживает оба режима. |

## Край и Auth Gateway

Переменных Auth Gateway в этом репозитории нет. Хост, сети и заголовки — в [gateway.md](gateway.md).

| Переменная | Кто | По умолчанию | Смысл |
|------------|-----|--------------|--------|
| `RAG_EDGE_PORT` | rag-edge | `8080` | Слушает в `rag_internal` и `rag_edge`, на хост не публикуется. |
| `MAX_UPLOAD_BYTES` | rag-edge | `524288000` | То же значение, что у File Collector. Свой меньший предел тела edge не задаёт. |
| `FILE_COLLECTOR_URL` | rag-edge | `http://file-collector:8081` | Куда уходят `/api/files` и `/api/files/*`. |
| `CHAT_URL` | rag-edge | `http://chat:8082` | Куда уходят `/api/chats` и `/api/chats/*`. |
| `FRONTEND_URL` | rag-edge | `http://frontend:3000` | Куда уходит остальной путь, включая `GET /`. |
