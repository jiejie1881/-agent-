from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import DbSession
from app.api.auth_dependencies import CurrentUser
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
def create_terrain(data: TerrainCreate, db: DbSession, actor: CurrentUser):
    return TerrainService(db).with_audit(actor,'MASTER_DATA_CREATED','Terrain',changes=data.model_dump()).create(data)


@router.patch("/{terrain_id}", response_model=TerrainResponse)
def update_terrain(terrain_id: int, data: TerrainUpdate, db: DbSession, actor: CurrentUser):
    return TerrainService(db).with_audit(actor,'MASTER_DATA_UPDATED','Terrain',terrain_id,data.model_dump(exclude_unset=True)).update(terrain_id, data)


@router.delete("/{terrain_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_terrain(terrain_id: int, db: DbSession, actor: CurrentUser) -> Response:
    TerrainService(db).with_audit(actor,'MASTER_DATA_DELETED','Terrain',terrain_id).delete(terrain_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

