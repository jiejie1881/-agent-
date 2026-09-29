from fastapi import APIRouter, Response, status

from app.api.auth_dependencies import CurrentUser
from app.api.dependencies import DbSession
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: DbSession):
    return AuthService(db).login(data.username, data.password)


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshTokenRequest, db: DbSession):
    return AuthService(db).refresh(data.refresh_token)


@router.get("/me", response_model=UserResponse)
def get_me(current_user: CurrentUser):
    return current_user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    data: ChangePasswordRequest, current_user: CurrentUser, db: DbSession
) -> Response:
    AuthService(db).change_password(
        current_user, data.current_password, data.new_password
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
