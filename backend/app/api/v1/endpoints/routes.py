from datetime import date

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import DbSession
from app.api.auth_dependencies import CurrentUser
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
    q: str | None = Query(None,max_length=100),
    is_active: bool | None = None,
):
    from app.models.route import Route
    return RouteService(db).search_page(Route,offset,limit,q,is_active)

@router.get('/{route_id}/stores')
def route_stores(route_id: int, db: DbSession):
    from sqlalchemy import select
    from app.models.store import Store, StoreRoute
    from app.schemas.store import StoreResponse
    RouteService(db).get(route_id)
    return [StoreResponse.model_validate(store,from_attributes=True) for store in db.scalars(select(Store).join(StoreRoute,Store.id==StoreRoute.store_id).where(StoreRoute.route_id==route_id).order_by(Store.id))]


@router.get("/{route_id}", response_model=RouteResponse)
def get_route(route_id: int, db: DbSession):
    return RouteService(db).get(route_id)


@router.post("", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
def create_route(data: RouteCreate, db: DbSession, actor: CurrentUser):
    return RouteService(db).with_audit(actor,'MASTER_DATA_CREATED','Route',changes=data.model_dump()).create(data)


@router.patch("/{route_id}", response_model=RouteResponse)
def update_route(route_id: int, data: RouteUpdate, db: DbSession, actor: CurrentUser):
    return RouteService(db).with_audit(actor,'MASTER_DATA_UPDATED','Route',route_id,data.model_dump(exclude_unset=True)).update(route_id, data)


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_route(route_id: int, db: DbSession, actor: CurrentUser) -> Response:
    RouteService(db).with_audit(actor,'MASTER_DATA_DELETED','Route',route_id).delete(route_id)
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
    route_id: int, data: RouteTerrainCreate, db: DbSession, actor: CurrentUser
):
    return RouteTerrainService(db).with_audit(actor,'ROUTE_TERRAIN_CREATED','Route',route_id,data.model_dump()).create(route_id, data)


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
    actor: CurrentUser,
):
    return RouteTerrainService(db).with_audit(actor,'ROUTE_TERRAIN_UPDATED','Route',route_id,{'config_id':config_id,**data.model_dump(exclude_unset=True)}).update(route_id, config_id, data)


@router.delete(
    "/{route_id}/terrain-configs/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_route_terrain_config(
    route_id: int, config_id: int, db: DbSession, actor: CurrentUser
) -> Response:
    RouteTerrainService(db).with_audit(actor,'ROUTE_TERRAIN_DELETED','Route',route_id,{'config_id':config_id}).delete(route_id, config_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
