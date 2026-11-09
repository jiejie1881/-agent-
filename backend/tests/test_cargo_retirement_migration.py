from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.models.cargo_category import CargoCategory
from app.models.delivery_demand import DeliveryDemand
from app.models.store import Store


def migrated_database(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    url = f"sqlite+pysqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(database_url=url))
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("path_separator", "os")
    command.upgrade(config, "20261009_23")
    engine = sa.create_engine(url)
    with engine.begin() as connection:
        connection.execute(sa.insert(CargoCategory.__table__).values(id=999, code="OLD", name="历史分类"))
        connection.execute(sa.insert(Store.__table__).values(id=1, code="OLD", name="历史门店"))
        connection.execute(sa.insert(DeliveryDemand.__table__).values(
            id=1, date=date(2026, 10, 9), store_id=1, period="MORNING", quantity=100,
            status="COMPLETED", cargo_category_id=999, requires_temperature_control=True,
            min_temperature=-20, max_temperature=-18,
        ))
    return config, engine


def test_migration_preserves_archived_data_and_safe_downgrade(tmp_path, monkeypatch):
    config, engine = migrated_database(tmp_path, monkeypatch)
    try:
        command.upgrade(config, "20261010_24")
        column = next(c for c in sa.inspect(engine).get_columns("delivery_demands") if c["name"] == "cargo_category_id")
        assert column["nullable"]
        with engine.connect() as connection:
            row = connection.execute(sa.text("SELECT cargo_category_id, quantity, status, min_temperature FROM delivery_demands WHERE id=1")).one()
            assert tuple(row) == (999, 100, "COMPLETED", -20)
            assert connection.execute(sa.text("SELECT COUNT(*) FROM cargo_categories WHERE code='OLD'")).scalar() == 1
        command.downgrade(config, "20261009_23")
        column = next(c for c in sa.inspect(engine).get_columns("delivery_demands") if c["name"] == "cargo_category_id")
        assert not column["nullable"]
    finally:
        engine.dispose()


def test_downgrade_refuses_to_discard_unclassified_demands(tmp_path, monkeypatch):
    config, engine = migrated_database(tmp_path, monkeypatch)
    try:
        command.upgrade(config, "20261010_24")
        with engine.begin() as connection:
            connection.execute(sa.insert(DeliveryDemand.__table__).values(
                id=2, date=date(2026, 10, 10), store_id=1, period="MORNING", quantity=50, status="PENDING",
            ))
        with pytest.raises(RuntimeError, match="unclassified demands exist"):
            command.downgrade(config, "20261009_23")
        with engine.connect() as connection:
            assert connection.execute(sa.text("SELECT COUNT(*) FROM delivery_demands")).scalar() == 2
            assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == "20261010_24"
    finally:
        engine.dispose()
