# RAG-Chat

Чат по PDF-документам пользователя: загрузка, индексация, ответ со ссылкой на файл и страницу. US-10 дополнительно регистрирует изображения: они индексируются отдельной коллекцией и ищутся по текстовому запросу.

Нормативная спецификация — в [docs/README.md](docs/README.md). Правила разработки — в [AGENTS.md](AGENTS.md): один репозиторий, Podman, uv, Makefile, ruff, FastAPI и Vite.

Auth Gateway и модель LLM в этот репозиторий не входят: gateway уже есть и передаёт `X-Auth-User-Id`, LLM вызывается по OpenAI-совместимому URL. Эмбеддинги считает llama.cpp внутри контейнера `embedding`.

## Run

```bash
cp .env.example .env
docker compose up --build
```

Критерии приёмки — в [docs/mvp.md](docs/mvp.md).
