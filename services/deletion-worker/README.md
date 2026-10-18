# deletion-worker

Consumer очереди `doc.delete`. Снимает объект PDF, точки Qdrant и страницы, затем ставит в MongoDB статус `deleted`.

Порядок одного сообщения фиксирован:

1. Разобрать тело. Битый JSON, чужая `schema_version` или неверный `doc.delete` — `nack` без requeue.
2. Если статус уже `deleted` — `ack`, хранилища не трогать.
3. Если документа нет — удалить объект по `s3_key` из сообщения, точки по паре `user_id` + `document_id` и `file_pages`, затем `ack`.
4. Свежий `processing` (heartbeat не старше `STALE_PROCESSING_SECONDS`) — `nack` без requeue.
5. Чужой `s3_key` или чужой `user_id` — `nack` без requeue, байты не удалять.
6. Если статус ещё не `deleting`, условно перевести его из `uploaded`, `ready`, `error` или устаревшего `processing`. Проигравшая гонка перечитывает документ и выбирает ветку заново.
7. Записать `delete_claimed_at`, если поле пустое. Пока отметки нет, объект и точки не удаляются. Три неудачные записи сдвигают `updated_at` и уводят сообщение в DLQ.
8. Удалить объект MinIO. Отсутствие ключа — успех.
9. Удалить точки Qdrant с фильтром `user_id` и `document_id` (`file_id`). Ноль точек — успех.
10. Удалить документы `file_pages` этого `file_id`. Ноль страниц — успех.
11. Условно перевести `deleting` → `deleted` и только потом `ack`.

Повтор того же `doc.delete` после `deleted` подтверждается и состояние не меняет. Падение после удаления объекта и до `deleted` оставляет `deleting`; следующая доставка дочищает хранилища и ставит `deleted`. Отдельный объект для ремонта не нужен.

Сбой MinIO, Qdrant или `file_pages` после трёх попыток и сбой финальной записи MongoDB после одной дополнительной попытки — `nack(requeue=false)`. Статус остаётся `deleting`. Неподтверждённое сообщение брокер отдаст снова, только если процесс умер до `ack`/`nack`.

При старте процесс идемпотентно объявляет топологию `doc_events` и один раз проходит sweeper: `status=deleting`, `delete_claimed_at=null`, `updated_at` старше `DELETE_REQUEUE_AFTER_SECONDS`. Дальше sweeper повторяется не реже `SWEEP_INTERVAL_SECONDS`. На каждом канале `basic_qos(prefetch_count=1)` до `basic_consume`. Число каналов — `DELETION_CONCURRENCY`.

## Переменные

Обязательные, без значения по умолчанию: `MONGODB_URI`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `QDRANT_URL`, `RABBITMQ_URL`. В лог попадает имя отсутствующей переменной, не её значение.

| Переменная | По умолчанию |
|------------|----------------|
| `S3_BUCKET` | `documents` |
| `S3_REGION` | `us-east-1` |
| `QDRANT_COLLECTION` | `documents` |
| `RABBITMQ_EXCHANGE` | `doc_events` |
| `RABBITMQ_DLX` | `doc_events_dlq` |
| `LOG_LEVEL` | `info` |
| `DELETION_CONCURRENCY` | `1` |
| `STALE_PROCESSING_SECONDS` | `900` |
| `SWEEP_INTERVAL_SECONDS` | `60` |
| `DELETE_REQUEUE_AFTER_SECONDS` | `120` |

`MONGODB_URI` включает имя базы. Логи — JSON, поле `service` равно `deletion-worker`.

## Запуск и проверка

Зависимости ставит `uv` из `uv.lock`. `requirements.txt` — тот же набор сторонних пакетов без локального проекта.

```bash
cd services/deletion-worker
uv sync --group dev
uv run pytest
uv run ruff check
uv run ruff format --check
uv run python -m deletion_worker
```

Образ: `Containerfile` (Podman) и идентичный `Dockerfile`. Сборка из этого каталога, команда процесса — `python -m deletion_worker`. Порта нет.
