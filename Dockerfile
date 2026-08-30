FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
RUN python -m pip install --upgrade pip && python -m pip install .

COPY scripts ./scripts
RUN mkdir -p /var/data && chown -R appuser:appuser /var/data /app
USER appuser

ENV DATABASE_PATH=/var/data/catalog.sqlite3 \
    SNAPSHOT_PATH=/var/data/shopify-snapshot.jsonl \
    PORT=10000

EXPOSE 10000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
