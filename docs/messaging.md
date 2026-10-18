# Сообщения RabbitMQ

## Топология

Объявляют идемпотентно все, кто публикует или читает: File Collector, Processor, Deletion Worker.

| Объект | Параметры |
|--------|-----------|
| Exchange `doc_events` | `direct`, durable |
| Exchange `doc_events_dlq` | `direct`, durable |
| Queue `doc.processing` | durable |
| Queue `doc.deletion` | durable |
| Queue `doc.processing.dead` | durable |
| Queue `doc.deletion.dead` | durable |

Аргументы рабочих очередей:

| Очередь | `x-dead-letter-exchange` | `x-dead-letter-routing-key` |
|---------|--------------------------|-----------------------------|
| `doc.processing` | `doc_events_dlq` | `doc.processing.dead` |
| `doc.deletion` | `doc_events_dlq` | `doc.deletion.dead` |

Привязки:

| Очередь | Exchange | Routing key |
|---------|----------|-------------|
| `doc.processing` | `doc_events` | `doc.process` |
| `doc.deletion` | `doc_events` | `doc.delete` |
| `doc.processing.dead` | `doc_events_dlq` | `doc.processing.dead` |
| `doc.deletion.dead` | `doc_events_dlq` | `doc.deletion.dead` |

Приоритетов у очередей нет.

Оба consumer вызывают `basic_qos(prefetch_count=1)` на своём канале до `basic_consume`. Один канал — одно неподтверждённое сообщение. `PROCESSOR_CONCURRENCY` и `DELETION_CONCURRENCY` задают число таких каналов в процессе. В MVP оба значения равны 1.

## Публикация

- `content_type`: `application/json`
- `content_encoding`: `utf-8`
- `delivery_mode`: `2`
- `message_id`: тот же UUID, что в теле
- `timestamp`: Unix-время публикации
- `app_id`: `file-collector`, `processor` или `deletion-worker`
- заголовок `x-request-id`, если он известен

Публикация ждёт confirm. Отказ confirm — ошибка публикации, а не успех.

Тело — JSON-объект. Поле `x-death` в тело не кладётся. При попадании в DLQ брокер сам дописывает заголовок `x-death`.

Повторов на уровне брокера нет: consumer делает `basic_nack(requeue=false)`. Сообщение оказывается в соответствующей dead-очереди. Возврат в работу — ручная перепубликация исходного тела в `doc_events` с прежним routing key. Заголовки `x-death` при перепубликации не копируются.

## `doc.process`

Отправитель: File Collector, либо sweeper внутри Processor.

```json
{
  "schema_version": 1,
  "message_type": "doc.process",
  "message_id": "f0c1d2e3-4a5b-4c6d-8e7f-8091a2b3c4d5",
  "file_id": "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
  "user_id": "91a0b1c2-3d4e-4f50-8617-18293a4b5c6d",
  "s3_key": "files/91a0b1c2-3d4e-4f50-8617-18293a4b5c6d/6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f/Otchet.pdf",
  "file_name": "Отчёт.pdf",
  "content_type": "application/pdf",
  "created_at": "2026-10-18T20:00:00Z"
}
```

| Поле | Правило |
|------|---------|
| `schema_version` | Целое `1`. Другая версия — `nack` без requeue и лог. Статус файла не менять наугад. |
| `message_type` | Строго `doc.process`. |
| `message_id` | UUID, для логов. На идемпотентность не влияет. |
| `file_id`, `user_id` | Обязательные UUID. |
| `s3_key` | Непустая строка. Processor читает объект только по этому ключу и только если документ MongoDB с тем же `file_id` содержит тот же `s3_key` и тот же `user_id`. Иначе сообщение отклоняется в DLQ. |
| `file_name` | Отображаемое имя для payload Qdrant, если оно совпадает с документом. При расхождении побеждает `file_name` из MongoDB. |
| `content_type` | `application/pdf`. |
| `created_at` | Время постановки сообщения. |

`ack` — после согласованного завершения: либо файл `ready` и точки записаны, либо обработка сознательно пропущена (`ready`, `deleting`, `deleted`), либо статус уже записан как `error` и сообщение уходит в DLQ отдельным `nack`. Нельзя подтверждать сообщение, если статус остался `processing` из-за сбоя.

Временный сбой обработки — исключение из правила «сразу в DLQ». Контрольная точка уже сохранена, статус остаётся `processing`. Worker выдерживает паузу `min(60, 2^process_attempts)` секунд и делает `nack(requeue=true)`. После `MAX_PROCESS_ATTEMPTS` тот же сбой становится постоянным: пишется `error`, `nack` без requeue. Подробности в [processing.md](processing.md).

Исключение — сбой записи самого статуса `error`: сообщение всё равно уходит в DLQ, в логе причина `metadata_update_failed`. Такой файл остаётся `processing` и снимается правилом устаревшего heartbeat.

## `doc.delete`

Отправитель: File Collector, либо sweeper внутри Deletion Worker.

```json
{
  "schema_version": 1,
  "message_type": "doc.delete",
  "message_id": "aabbccdd-1122-4333-8444-556677889900",
  "file_id": "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
  "user_id": "91a0b1c2-3d4e-4f50-8617-18293a4b5c6d",
  "s3_key": "files/91a0b1c2-3d4e-4f50-8617-18293a4b5c6d/6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f/Otchet.pdf",
  "created_at": "2026-10-18T20:05:00Z"
}
```

Перед удалением объекта worker сверяет `s3_key` с документом. Если в документе другой ключ, в DLQ: чужой ключ из сообщения не удаляется.

`ack` — когда объект отсутствует или удалён, точки Qdrant и документы `file_pages` удалены, в MongoDB статус `deleted`. Отсутствие объекта, точек и страниц — успешные шаги.

Если документа в MongoDB уже нет, worker всё равно удаляет `s3_key` из сообщения и точки по паре `user_id` + `file_id`, затем подтверждает сообщение.

Если статус `processing` и `updated_at` не старше порога, сообщение уходит в DLQ без requeue. Горячего повтора нет. После зависания файл удаляется новым запросом DELETE, когда heartbeat устарел.

## Sweeper

Processor не реже чем раз в `SWEEP_INTERVAL_SECONDS` и один раз при старте ищет документы `status=error` и `error=enqueue_failed`, у которых `updated_at` старше `UPLOAD_REQUEUE_AFTER_SECONDS`. Для каждого публикует новый `doc.process`. Другие коды `error` sweeper не трогает: битый PDF не должен возвращаться в очередь сам.

Deletion Worker так же ищет `status=deleting`, где `delete_claimed_at` равно `null` и `updated_at` старше `DELETE_REQUEUE_AFTER_SECONDS`, и публикует `doc.delete`. Уже захваченное удаление в рабочую очередь повторно не ставится: незакрытое сообщение вернёт брокер, а окончательно отклонённое лежит в DLQ.

Повторная публикация безопасна: конвейеры идемпотентны. Новый `message_id` на каждый такой publish — норма.

## Что сознательно не входит в топологию

Отдельной очереди повторов с TTL нет. Паузу перед повторной доставкой `doc.process` держит сам Processor, затем `nack(requeue=true)`. Разбор DLQ делает человек по runbook из [deployment.md](deployment.md).
