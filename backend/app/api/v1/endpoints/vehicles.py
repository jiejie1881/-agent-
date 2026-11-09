from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import DbSession
from app.api.auth_dependencies import CurrentUser
from app.schemas.vehicle import VehicleCreate, VehicleResponse, VehicleUpdate
from app.services.vehicle_service import VehicleService

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("", response_model=list[VehicleResponse])
def list_vehicles(
    db: DbSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(None,max_length=100),
    is_active: bool | None = None,
    operating_status: str | None = Query(None,pattern=r'^(ACTIVE|MAINTENANCE|RETIRED)$'),
    vehicle_type_id: int | None = Query(None,gt=0),
):
    from app.models.vehicle import Vehicle
    return VehicleService(db).search_page(Vehicle,offset,limit,q,is_active,{'operating_status':operating_status,'vehicle_type_id':vehicle_type_id})


@router.get("/{vehicle_id}", response_model=VehicleResponse)
def get_vehicle(vehicle_id: int, db: DbSession):
    return VehicleService(db).get(vehicle_id)


@router.post("", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
def create_vehicle(data: VehicleCreate, db: DbSession, actor: CurrentUser):
    return VehicleService(db).with_audit(actor,'MASTER_DATA_CREATED','Vehicle',changes=data.model_dump()).create(data, actor)


@router.patch("/{vehicle_id}", response_model=VehicleResponse)
def update_vehicle(vehicle_id: int, data: VehicleUpdate, db: DbSession, actor: CurrentUser):
    return VehicleService(db).with_audit(actor,'MASTER_DATA_UPDATED','Vehicle',vehicle_id,data.model_dump(exclude_unset=True)).update(vehicle_id, data, actor)


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vehicle(vehicle_id: int, db: DbSession, actor: CurrentUser) -> Response:
    VehicleService(db).with_audit(actor,'MASTER_DATA_DELETED','Vehicle',vehicle_id).delete(vehicle_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

