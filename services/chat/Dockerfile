FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    TOKENIZER_JSON=/app/tokenizer/tokenizer.json

WORKDIR /app

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin chat

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY tokenizer/tokenizer.json /app/tokenizer/tokenizer.json
RUN chown -R chat:chat /app

USER chat

EXPOSE 8082

CMD ["python", "-m", "chat"]
