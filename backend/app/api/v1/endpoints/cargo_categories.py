from fastapi import APIRouter, Query, status

from app.api.dependencies import DbSession
from app.schemas.cargo_category import (
    CargoCategoryCreate,
    CargoCategoryResponse,
    CargoCategoryUpdate,
)
from app.services.cargo_category_service import CargoCategoryService

router = APIRouter(prefix="/cargo-categories", tags=["cargo-categories"])


@router.get("", response_model=list[CargoCategoryResponse])
def list_cargo_categories(
    db: DbSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
):
    return CargoCategoryService(db).list(offset, limit)


@router.get("/{category_id}", response_model=CargoCategoryResponse)
def get_cargo_category(category_id: int, db: DbSession):
    return CargoCategoryService(db).get(category_id)


@router.post("", response_model=CargoCategoryResponse, status_code=status.HTTP_201_CREATED)
def create_cargo_category(data: CargoCategoryCreate, db: DbSession):
    return CargoCategoryService(db).create(data)


@router.patch("/{category_id}", response_model=CargoCategoryResponse)
def update_cargo_category(
    category_id: int, data: CargoCategoryUpdate, db: DbSession
):
    return CargoCategoryService(db).update(category_id, data)


@router.delete("/{category_id}", response_model=CargoCategoryResponse)
def deactivate_cargo_category(category_id: int, db: DbSession):
    return CargoCategoryService(db).deactivate(category_id)
