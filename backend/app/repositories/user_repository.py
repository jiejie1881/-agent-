from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, User)

    def get_by_username(self, username: str) -> User | None:
        return self.session.scalar(select(User).where(User.username == username))

    def list(self, offset: int = 0, limit: int = 100) -> list[User]:
        return list(
            self.session.scalars(
                select(User).order_by(User.id).offset(offset).limit(limit)
            )
        )
