# OCR

Внутренний сервис распознавания одной страницы. Контракт — `docs/openapi-internal.yaml`, поведение — `docs/internal-services.md`. Сервис слушает только сеть `rag_internal`. Порт на хост не публикуется.

## Модель

`OCR_MODEL=paddleocr_multilingual`.

Движок: **PaddleOCR PP-OCRv4**, языки **`en`** и **`ru`**.

При старте процесса, до открытия порта, загружаются оба контура PP-OCRv4:

| Язык | Вызов | Веса, которые выбирает PaddleOCR 2.10 для `ocr_version=PP-OCRv4` |
|------|--------|-------------------------------------------------------------------|
| `en` | `PaddleOCR(lang="en", ocr_version="PP-OCRv4")` | детекция `en_PP-OCRv3_det`, распознавание `en_PP-OCRv4_rec` |
| `ru` | `PaddleOCR(lang="ru", ocr_version="PP-OCRv4")` | детекция `Multilingual_PP-OCRv3_det`, распознавание `cyrillic_PP-OCRv3_rec` |

Классификатор угла — `ch_ppocr_mobile_v2.0_cls`. Отдельных весов PP-OCRv4 для кириллицы Paddle не публикует: русский в конфигурации PP-OCRv4 идёт моделью `cyrillic`. Английский распознаётся `en_PP-OCRv4_rec`.

Пока веса не в памяти, процесс не слушает порт, и проверка готовности не проходит. `GET /health` после старта уже означает, что модель загружена. Если загрузка не удалась, процесс завершается. GPU не требуется: инференс идёт на CPU. Контракт от этого не меняется.

Страницу из PDF сервис не рендерит. Ожидается PNG, который собрал Processor. Другой декодируемый растр принимается. Неразобранное тело — `400` `validation_error`.

Пустой `text` — успешный `200`, не ошибка.

## HTTP

`POST /ocr`, `multipart/form-data`, поле `image`.

```json
{
  "text": "распознанный текст",
  "confidence": 0.92,
  "processing_time_ms": 340
}
```

`confidence` — число от 0 до 1 или `null`, если движок не отдал оценку. `processing_time_ms` — время работы движка, целое ≥ 0.

Бюджет разбора — `OCR_TIMEOUT` секунд (30). По истечении сервис отвечает `504`:

```json
{"error": {"code": "upstream_timeout", "message": "OCR timed out"}}
```

`GET /health` → `{"status":"ok"}`.

Необязательный заголовок `X-Request-Id` (UUID) возвращается в ответе. Если его нет или он не UUID, сервис подставляет новый UUID.

## Переменные

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `OCR_PORT` | `8090` | Порт внутри сети. |
| `OCR_MODEL` | `paddleocr_multilingual` | PP-OCRv4, `en` + `ru`. Другое значение не даёт процессу стартовать. |
| `OCR_TIMEOUT` | `30` | Секунды на один разбор. |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error`. |

Неверное значение пишется в лог только именем переменной.

## Запуск

Из каталога `services/ocr`:

```bash
uv sync
uv run python -m ocr_service
```

Образ (порт наружу не пробрасывается):

```bash
podman build -f Dockerfile -t ocr .
```

## Тесты

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest
```

Тесты подставляют фальшивый движок и не скачивают веса. Боевой вход `python -m ocr_service` по-прежнему создаёт `PaddleMultilingualEngine` и вызывает `PaddleOCR` для `en` и `ru` с `ocr_version=PP-OCRv4`.
