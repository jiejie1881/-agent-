from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import DbSession
from app.schemas.vehicle import (
    VehicleTypeCreate,
    VehicleTypeResponse,
    VehicleTypeTerrainPermissionCreate,
    VehicleTypeTerrainPermissionResponse,
    VehicleTypeUpdate,
    VehicleTypeCargoCapabilityReplace,
    VehicleTypeCargoCapabilityResponse,
)
from app.services.vehicle_service import (
    VehicleTypeService,
    VehicleTypeTerrainPermissionService,
    VehicleTypeCargoCapabilityService,
)

router = APIRouter(prefix="/vehicle-types", tags=["vehicle-types"])


@router.get("", response_model=list[VehicleTypeResponse])
def list_vehicle_types(
    db: DbSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    return VehicleTypeService(db).list(offset, limit)


@router.get("/{vehicle_type_id}", response_model=VehicleTypeResponse)
def get_vehicle_type(vehicle_type_id: int, db: DbSession):
    return VehicleTypeService(db).get(vehicle_type_id)


@router.post(
    "", response_model=VehicleTypeResponse, status_code=status.HTTP_201_CREATED
)
def create_vehicle_type(data: VehicleTypeCreate, db: DbSession):
    return VehicleTypeService(db).create(data)


@router.patch("/{vehicle_type_id}", response_model=VehicleTypeResponse)
def update_vehicle_type(
    vehicle_type_id: int, data: VehicleTypeUpdate, db: DbSession
):
    return VehicleTypeService(db).update(vehicle_type_id, data)


@router.delete("/{vehicle_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vehicle_type(vehicle_type_id: int, db: DbSession) -> Response:
    VehicleTypeService(db).delete(vehicle_type_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{vehicle_type_id}/terrain-permissions",
    response_model=list[VehicleTypeTerrainPermissionResponse],
)
def list_terrain_permissions(vehicle_type_id: int, db: DbSession):
    return VehicleTypeTerrainPermissionService(db).list(vehicle_type_id)


@router.post(
    "/{vehicle_type_id}/terrain-permissions",
    response_model=VehicleTypeTerrainPermissionResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_terrain_permission(
    vehicle_type_id: int,
    data: VehicleTypeTerrainPermissionCreate,
    db: DbSession,
):
    return VehicleTypeTerrainPermissionService(db).add(
        vehicle_type_id, data.terrain_id
    )


@router.delete(
    "/{vehicle_type_id}/terrain-permissions/{terrain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_terrain_permission(
    vehicle_type_id: int, terrain_id: int, db: DbSession
) -> Response:
    VehicleTypeTerrainPermissionService(db).remove(vehicle_type_id, terrain_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{vehicle_type_id}/cargo-capabilities",
    response_model=list[VehicleTypeCargoCapabilityResponse],
)
def list_cargo_capabilities(vehicle_type_id: int, db: DbSession):
    return VehicleTypeCargoCapabilityService(db).list(vehicle_type_id)


@router.put(
    "/{vehicle_type_id}/cargo-capabilities",
    response_model=list[VehicleTypeCargoCapabilityResponse],
)
def replace_cargo_capabilities(
    vehicle_type_id: int,
    data: VehicleTypeCargoCapabilityReplace,
    db: DbSession,
):
    return VehicleTypeCargoCapabilityService(db).replace(vehicle_type_id, data)
