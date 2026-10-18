# Frontend

Клиент RAG-чата: список PDF, чат с потоком ответа и предпросмотр страницы. Контракт — [`docs/frontend.md`](../docs/frontend.md), форма HTTP — [`docs/openapi.yaml`](../docs/openapi.yaml).

Стек: Vite, React, TypeScript, Tailwind CSS, Zustand, PDF.js. Сборка статики отдаётся nginx на порту **3000**.

## Маршруты

| Путь | Экран |
|------|--------|
| `/files` | Список, загрузка и удаление |
| `/chat` | Список чатов |
| `/chat/:chatId` | История и вопрос |
| `/files/:fileId?page=N` | Страница PDF |

`/` ведёт на `/files`.

Запросы только same-origin и относительные: `/api/files`, `/api/chats`. Байты PDF — `GET /api/files/{file_id}/content`. Номер страницы в API не передаётся, presigned URL нет, ответ не вставляется в iframe. Cookie сеанса уходит с `credentials: "include"`. Клиент не ставит `Authorization`, `X-User-Id` и `X-Auth-*`.

`401` с телом gateway `{"error":"unauthorized"}` уводит браузер на `{PUBLIC_ORIGIN}/auth?return_to=`. `403` `{"error":"blocked"}` или код RAG `forbidden` показывает, что доступ закрыт, и запрос не повторяется.

Пока на загруженной странице списка есть `uploaded`, `processing` или `deleting`, список запрашивается каждые 5 секунд. История чата читается с сервера при открытии страницы.

## Команды

```bash
npm ci
npm test
npm run build
npm run dev
```

`npm run dev` проксирует `/api` на `http://127.0.0.1:8080` только для локального Vite. В собранном приложении этого адреса нет: снаружи запросы идут на тот же хост, что и страница.

## Образ

```bash
podman build -f frontend/Containerfile -t rag-frontend frontend
```

Контейнер слушает порт 3000 и отдаёт `dist`. Описание стенда — в [`docs/deployment.md`](../docs/deployment.md).

## Переменные

| Переменная | Смысл |
|------------|--------|
| `VITE_PUBLIC_ORIGIN` | Происхождение страницы входа, без завершающего слэша. Пустое значение — текущий origin. Пример: `https://filenkov.store`. |

Переменная подставляется при `npm run build`.
