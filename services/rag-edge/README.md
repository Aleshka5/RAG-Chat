# rag-edge

Единственный HTTP-вход RAG. Слушает порт `8080` и не публикует его на хост.

Контейнер подключается к двум сетям:

- `rag_edge` — единственный участник со стороны RAG. Auth Gateway подключается к этой сети как к external и проксирует на `http://rag-edge:8080`.
- `rag_internal` — отсюда edge ходит к `file-collector`, `chat` и `frontend`.

## Маршруты

| Путь | Куда |
|------|------|
| `GET /health` | Ответ самого edge: `{"status":"ok"}`. Без заголовка личности, без MongoDB и очереди. |
| `/api/files` и `/api/files/*` | `FILE_COLLECTOR_URL` |
| `/api/chats` и `/api/chats/*` | `CHAT_URL` |
| всё остальное | `FRONTEND_URL` |

Тело загрузки проходит целиком. Своего более жёсткого предела, чем `MAX_UPLOAD_BYTES`, у edge нет. `413` отвечает File Collector.

Ответ `text/event-stream` не буферизуется: байты чата отдаются по мере прихода от Chat. На такой ответ добавляется `X-Accel-Buffering: no`.

Вверх уходят `X-Auth-User-Id`, `X-Auth-Role` и `X-Request-Id`. Если `X-Request-Id` не пришёл или это не UUID, edge создаёт UUID, передаёт его upstream и возвращает в ответе.

## Переменные

| Переменная | По умолчанию |
|------------|----------------|
| `RAG_EDGE_PORT` | `8080` |
| `MAX_UPLOAD_BYTES` | `524288000` |
| `FILE_COLLECTOR_URL` | `http://file-collector:8081` |
| `CHAT_URL` | `http://chat:8082` |
| `FRONTEND_URL` | `http://frontend:3000` |
| `LOG_LEVEL` | `info` |

Имена хостов по умолчанию совпадают с именами сервисов compose. Неверное значение останавливает процесс: в лог пишется имя переменной, без значения. Логи — JSON, поле `service` равно `rag-edge`.

## Сборка

```sh
podman build -f Containerfile -t rag-edge .
```

`Dockerfile` совпадает с `Containerfile`.

## Проверка

```sh
uv run ruff check
uv run ruff format --check
uv run pytest
```

Тесты поднимают локальные заглушки и не требуют file-collector, chat и frontend.
