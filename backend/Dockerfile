FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY knowledge_base ./knowledge_base
COPY docker-entrypoint.sh ./docker-entrypoint.sh

RUN pip install --upgrade pip && pip install .

RUN groupadd --system app && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/uploads /app/rag_data \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["sh", "/app/docker-entrypoint.sh"]
