from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.exceptions import ConflictError

T = TypeVar("T")


class BaseService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _commit(self, action: Callable[[], T], conflict_message: str) -> T:
        try:
            result = action()
            self.session.commit()
            return result
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(conflict_message) from exc

