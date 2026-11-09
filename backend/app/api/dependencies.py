from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.infrastructure.database.session import get_db

DbSession = Annotated[Session, Depends(get_db)]

