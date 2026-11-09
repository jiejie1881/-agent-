from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.database.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    def __init__(self, session: Session, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    def get(self, entity_id: int) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def list(self, offset: int = 0, limit: int = 20) -> list[ModelT]:
        statement = select(self.model).order_by(self.model.id).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        self.session.flush()
        self.session.refresh(entity)
        return entity

    def delete(self, entity: ModelT) -> None:
        self.session.delete(entity)
        self.session.flush()

