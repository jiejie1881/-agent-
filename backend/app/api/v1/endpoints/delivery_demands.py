from datetime import date

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import DbSession
from app.api.auth_dependencies import CurrentUser
from app.domain.enums import DeliveryPeriod
from app.schemas.delivery_demand import (
    DeliveryDemandCreate,
    DeliveryDemandResponse,
    DeliveryDemandUpdate,
)
from app.services.delivery_demand_service import DeliveryDemandService

router = APIRouter(prefix="/delivery-demands", tags=["delivery-demands"])


@router.get("", response_model=list[DeliveryDemandResponse])
def list_delivery_demands(
    db: DbSession,
    demand_date: date | None = Query(default=None, alias="date"),
    store_id: int | None = Query(default=None, gt=0),
    period: DeliveryPeriod | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    return DeliveryDemandService(db).list(
        demand_date, store_id, period, offset, limit
    )


@router.get("/{demand_id}", response_model=DeliveryDemandResponse)
def get_delivery_demand(demand_id: int, db: DbSession):
    return DeliveryDemandService(db).get(demand_id)


@router.post(
    "", response_model=DeliveryDemandResponse, status_code=status.HTTP_201_CREATED
)
def create_delivery_demand(
    data: DeliveryDemandCreate, current_user: CurrentUser, db: DbSession
):
    return DeliveryDemandService(db).create(data, current_user)


@router.patch("/{demand_id}", response_model=DeliveryDemandResponse)
def update_delivery_demand(
    demand_id: int,
    data: DeliveryDemandUpdate,
    current_user: CurrentUser,
    db: DbSession,
):
    return DeliveryDemandService(db).update(demand_id, data, current_user)


@router.post("/{demand_id}/cancel", response_model=DeliveryDemandResponse)
def cancel_delivery_demand(demand_id: int, db: DbSession):
    return DeliveryDemandService(db).cancel(demand_id)


@router.delete("/{demand_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_delivery_demand(demand_id: int, db: DbSession) -> Response:
    DeliveryDemandService(db).delete(demand_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
