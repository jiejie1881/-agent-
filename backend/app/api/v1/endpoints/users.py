from fastapi import APIRouter, Depends, Query, status

from app.api.auth_dependencies import CurrentUser, require_admin
from app.api.dependencies import DbSession
from app.schemas.auth import UserCreate, UserResponse, UserUpdate
from app.services.user_service import UserService

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[UserResponse])
def list_users(
    db: DbSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
):
    return UserService(db).list(offset, limit)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, current_user: CurrentUser, db: DbSession):
    return UserService(db).create(data, current_user)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int, data: UserUpdate, current_user: CurrentUser, db: DbSession
):
    return UserService(db).update(user_id, data, current_user)
