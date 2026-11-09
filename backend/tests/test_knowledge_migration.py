"""Execute the draft ONLY against a brand-new in-memory synthetic SQLite."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

from app.infrastructure.database.base import Base


def migration(connection):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261027_29_knowledge_governance.py"
    spec = importlib.util.spec_from_file_location("synthetic_knowledge_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    return module


def test_draft_schema_matches_orm_and_empty_downgrade_is_reversible():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        module = migration(connection)
        assert module.down_revision == "20261015_28"
        module.upgrade()
        inspector = sa.inspect(connection)
        assert set(inspector.get_table_names()) == set(module.TABLES)
        for name in module.TABLES:
            actual = {c["name"]: c["nullable"] for c in inspector.get_columns(name)}
            assert actual == {c.name: c.nullable for c in Base.metadata.tables[name].columns}
        module.downgrade()
        assert sa.inspect(connection).get_table_names() == []
    engine.dispose()


def test_downgrade_refuses_to_drop_populated_governance_tables():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        module = migration(connection)
        module.upgrade()
        connection.execute(Base.metadata.tables["rag_knowledge_bases"].insert().values(name="synthetic only", created_by=1))
        with pytest.raises(RuntimeError, match="Refuse downgrade"):
            module.downgrade()
        assert set(module.TABLES) <= set(sa.inspect(connection).get_table_names())
    engine.dispose()
