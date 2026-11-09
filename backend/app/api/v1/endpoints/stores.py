from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import DbSession
from app.api.auth_dependencies import CurrentUser
from app.schemas.store import (
    StoreCreate,
    StoreResponse,
    StoreRouteCreate,
    StoreRouteResponse,
    StoreUpdate,
)
from app.services.store_service import StoreRouteService, StoreService

router = APIRouter(prefix="/stores", tags=["stores"])


@router.get("", response_model=list[StoreResponse])
def list_stores(
    db: DbSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(None, max_length=100),
    is_active: bool | None = None,
    delivery_region: str | None = Query(None,max_length=100),
):
    from app.models.store import Store
    return StoreService(db).search_page(Store,offset,limit,q,is_active,{'delivery_region':delivery_region})


@router.get("/{store_id}", response_model=StoreResponse)
def get_store(store_id: int, db: DbSession):
    return StoreService(db).get(store_id)


@router.post("", response_model=StoreResponse, status_code=status.HTTP_201_CREATED)
def create_store(data: StoreCreate, db: DbSession, actor: CurrentUser):
    return StoreService(db).with_audit(actor,'MASTER_DATA_CREATED','Store',changes=data.model_dump()).create(data)


@router.patch("/{store_id}", response_model=StoreResponse)
def update_store(store_id: int, data: StoreUpdate, db: DbSession, actor: CurrentUser):
    return StoreService(db).with_audit(actor,'MASTER_DATA_UPDATED','Store',store_id,data.model_dump(exclude_unset=True)).update(store_id, data)


@router.delete("/{store_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_store(store_id: int, db: DbSession, actor: CurrentUser) -> Response:
    StoreService(db).with_audit(actor,'MASTER_DATA_DELETED','Store',store_id).delete(store_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{store_id}/routes", response_model=list[StoreRouteResponse])
def list_store_routes(store_id: int, db: DbSession):
    return StoreRouteService(db).list(store_id)


@router.post(
    "/{store_id}/routes",
    response_model=StoreRouteResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_store_route(store_id: int, data: StoreRouteCreate, db: DbSession, actor: CurrentUser):
    return StoreRouteService(db).with_audit(actor,'STORE_ROUTE_ADDED','Store',store_id,data.model_dump()).add(store_id, data.route_id)


@router.delete(
    "/{store_id}/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_store_route(store_id: int, route_id: int, db: DbSession, actor: CurrentUser) -> Response:
    StoreRouteService(db).with_audit(actor,'STORE_ROUTE_REMOVED','Store',store_id,{'route_id':route_id}).remove(store_id, route_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

