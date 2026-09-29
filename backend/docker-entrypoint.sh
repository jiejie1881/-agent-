#!/bin/sh
set -eu

echo "Waiting for database..."
python - <<'PY'
import time

from sqlalchemy import create_engine, text

from app.core.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
for attempt in range(1, 31):
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("Database is ready.")
        break
    except Exception as exc:
        if attempt == 30:
            raise SystemExit(f"Database did not become ready: {exc}") from exc
        print(f"Database unavailable (attempt {attempt}/30); retrying...")
        time.sleep(2)
engine.dispose()
PY

echo "Applying database migrations..."
python -m alembic upgrade head

echo "Starting backend..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
