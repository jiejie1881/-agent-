import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-with-at-least-32-characters"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.domain.enums import UserRole
from app.infrastructure.database.base import Base
from app.infrastructure.database.session import get_db
from app.main import app
from app.services.auth_service import AuthService


@pytest.fixture(autouse=True)
def isolated_upload_storage(tmp_path,monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(),'upload_root',str(tmp_path/'uploads'))
    monkeypatch.setattr(get_settings(),'agent_checkpoint_path',str(tmp_path/'agent/checkpoints.sqlite3'))
    monkeypatch.setattr(get_settings(),'rag_vector_store_dir',str(tmp_path/'rag'))


@pytest.fixture(autouse=True)
def isolated_model_budget(tmp_path_factory):
    """Keep synthetic budgets separate from each test's uploads and artifacts."""
    import time
    from app.core.model_budget import BudgetPolicy, ModelBudget, budget_context
    budget = ModelBudget(tmp_path_factory.mktemp("model-budget") / ModelBudget.FILENAME,
                         BudgetPolicy(100, 1000000, 10, max_inflight=4,
                                      max_input_bytes=1000000, max_output_tokens=8192))
    budget.initialize_new(expires_at=time.time() + 3600)
    with budget_context(budget):
        yield budget


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield testing_session
    finally:
        testing_session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def client(session: Session) -> TestClient:
    AuthService(session).create_user("test-admin", "AdminPass123!", UserRole.ADMIN)

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        login = test_client.post(
            "/api/v1/auth/login",
            json={"username": "test-admin", "password": "AdminPass123!"},
        )
        test_client.headers["Authorization"] = (
            f"Bearer {login.json()['access_token']}"
        )
        yield test_client
    app.dependency_overrides.clear()
