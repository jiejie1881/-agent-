from fastapi import APIRouter, Depends

from app.api.auth_dependencies import enforce_rbac

from app.api.v1.endpoints import (
    agent,
    auto_dispatch,
    delivery_demands,
    dispatch_validations,
    dispatch_plans,
    routes,
    stores,
    terrains,
    vehicle_attendances,
    vehicle_types,
    vehicles,
    users,
    audit_logs,
)

api_router = APIRouter(dependencies=[Depends(enforce_rbac)])
api_router.include_router(agent.router)
api_router.include_router(auto_dispatch.router)
api_router.include_router(terrains.router)
api_router.include_router(routes.router)
api_router.include_router(stores.router)
api_router.include_router(vehicle_types.router)
api_router.include_router(vehicles.router)
api_router.include_router(vehicle_attendances.router)
api_router.include_router(delivery_demands.router)
api_router.include_router(dispatch_validations.router)
api_router.include_router(dispatch_plans.router)
api_router.include_router(users.router)
api_router.include_router(audit_logs.router)
