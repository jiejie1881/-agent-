"""Verify metadata against the real historical migration chain, not create_all."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_migrated_database_matches_metadata(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{(tmp_path / 'migrated.sqlite3').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    try:
        command.upgrade(config, "head")
        command.check(config)
        engine = create_engine(url)
        try:
            inspector = inspect(engine)
            columns = {c["name"]: c for c in inspector.get_columns("delivery_demands")}
            assert columns["status"]["type"].length == 20
            assert columns["priority"]["type"].length == 20
            for table, column in (
                ("terrains", "code"), ("routes", "code"), ("stores", "code"),
                ("vehicle_types", "code"), ("vehicles", "code"),
                ("vehicles", "plate_number"), ("users", "username"),
            ):
                assert any(
                    item["column_names"] == [column]
                    for item in inspector.get_unique_constraints(table)
                ), (table, column)
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()
