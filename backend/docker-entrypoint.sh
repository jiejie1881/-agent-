#!/bin/sh
set -eu

echo "Waiting for database..."
python - <<'PY'
import time

from sqlalchemy import create_engine, text

from app.core.config import get_settings

database_url = get_settings().database_url
options = {"pool_pre_ping": True}
if database_url.startswith("mysql"):
    options.update(connect_args={"connect_timeout": 3, "read_timeout": 5, "write_timeout": 5}, pool_timeout=3)
engine = create_engine(database_url, **options)
for attempt in range(1, 31):
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("Database is ready.")
        break
    except Exception as exc:
        if attempt == 30:
            raise SystemExit("Database did not become ready within 30 attempts") from None
        print(f"Database unavailable (attempt {attempt}/30); retrying...")
        time.sleep(2)
engine.dispose()
PY

case "${RUN_MIGRATIONS:-true}" in
  true) echo "Applying database migrations..."; python -m alembic upgrade head ;;
  false) echo "Migrations are managed by the separate release step." ;;
  *) echo "RUN_MIGRATIONS must be true or false" >&2; exit 1 ;;
esac

echo "Starting backend..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log
