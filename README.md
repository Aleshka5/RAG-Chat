# RAG-Chat

Чат по PDF-документам пользователя: загрузка, индексация, ответ со ссылкой на файл и страницу.

Нормативная спецификация — в [docs/README.md](docs/README.md). Правила разработки — в [AGENTS.md](AGENTS.md): один репозиторий, Podman, uv, Makefile, ruff, FastAPI и Vite.

Auth Gateway и модель LLM в этот репозиторий не входят: gateway уже есть и передаёт `X-Auth-User-Id`, LLM вызывается по OpenAI-совместимому URL. Эмбеддинги считает llama.cpp внутри контейнера `embedding`.
