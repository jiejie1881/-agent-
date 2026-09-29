from datetime import date

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import DbSession
from app.schemas.route import (
    RouteCreate,
    RouteResponse,
    RouteTerrainCreate,
    RouteTerrainResponse,
    RouteTerrainUpdate,
    RouteUpdate,
)
from app.services.route_service import RouteService, RouteTerrainService

router = APIRouter(prefix="/routes", tags=["routes"])


@router.get("", response_model=list[RouteResponse])
def list_routes(
    db: DbSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    return RouteService(db).list(offset, limit)


@router.get("/{route_id}", response_model=RouteResponse)
def get_route(route_id: int, db: DbSession):
    return RouteService(db).get(route_id)


@router.post("", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
def create_route(data: RouteCreate, db: DbSession):
    return RouteService(db).create(data)


@router.patch("/{route_id}", response_model=RouteResponse)
def update_route(route_id: int, data: RouteUpdate, db: DbSession):
    return RouteService(db).update(route_id, data)


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_route(route_id: int, db: DbSession) -> Response:
    RouteService(db).delete(route_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{route_id}/terrain-configs", response_model=list[RouteTerrainResponse]
)
def list_route_terrain_configs(route_id: int, db: DbSession):
    return RouteTerrainService(db).list(route_id)


@router.post(
    "/{route_id}/terrain-configs",
    response_model=RouteTerrainResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_route_terrain_config(
    route_id: int, data: RouteTerrainCreate, db: DbSession
):
    return RouteTerrainService(db).create(route_id, data)


@router.get("/{route_id}/effective-terrain", response_model=RouteTerrainResponse)
def get_effective_route_terrain(
    route_id: int, db: DbSession, on_date: date = Query()
):
    return RouteTerrainService(db).get_effective(route_id, on_date)


@router.patch(
    "/{route_id}/terrain-configs/{config_id}",
    response_model=RouteTerrainResponse,
)
def update_route_terrain_config(
    route_id: int,
    config_id: int,
    data: RouteTerrainUpdate,
    db: DbSession,
):
    return RouteTerrainService(db).update(route_id, config_id, data)


@router.delete(
    "/{route_id}/terrain-configs/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_route_terrain_config(
    route_id: int, config_id: int, db: DbSession
) -> Response:
    RouteTerrainService(db).delete(route_id, config_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
