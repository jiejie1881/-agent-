import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-with-at-least-32-characters"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401, E402
from app.infrastructure.database.base import Base
from app.infrastructure.database.session import get_db
from app.main import app
from app.domain.enums import UserRole
from app.services.auth_service import AuthService
from app.models.cargo_category import CargoCategory


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)()
    testing_session.add_all(
        [
            CargoCategory(code="NORMAL", name="常温商品"),
            CargoCategory(code="FRESH", name="生鲜"),
            CargoCategory(code="FROZEN", name="冷冻品"),
            CargoCategory(code="BULK", name="大宗货物"),
        ]
    )
    testing_session.commit()
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
