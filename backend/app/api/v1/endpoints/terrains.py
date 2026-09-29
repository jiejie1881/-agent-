from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import DbSession
from app.schemas.terrain import TerrainCreate, TerrainResponse, TerrainUpdate
from app.services.terrain_service import TerrainService

router = APIRouter(prefix="/terrains", tags=["terrains"])


@router.get("", response_model=list[TerrainResponse])
def list_terrains(
    db: DbSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    return TerrainService(db).list(offset, limit)


@router.get("/{terrain_id}", response_model=TerrainResponse)
def get_terrain(terrain_id: int, db: DbSession):
    return TerrainService(db).get(terrain_id)


@router.post("", response_model=TerrainResponse, status_code=status.HTTP_201_CREATED)
def create_terrain(data: TerrainCreate, db: DbSession):
    return TerrainService(db).create(data)


@router.patch("/{terrain_id}", response_model=TerrainResponse)
def update_terrain(terrain_id: int, data: TerrainUpdate, db: DbSession):
    return TerrainService(db).update(terrain_id, data)


@router.delete("/{terrain_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_terrain(terrain_id: int, db: DbSession) -> Response:
    TerrainService(db).delete(terrain_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

