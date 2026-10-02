FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/users.db

WORKDIR /app

# Сначала зависимости: этот слой кэшируется и не пересобирается при правке api.py
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api.py .

# Запуск не от root: папка для базы принадлежит обычному пользователю
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)" || exit 1

# Один процесс с несколькими потоками: список активных пользователей хранится в памяти процесса
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "api:app"]