from fastapi import APIRouter, Depends

from app.api.auth_dependencies import enforce_rbac
from app.api.v1.endpoints import business_imports, exception_cases
from app.api.v1.endpoints import knowledge

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
    daily_exceptions,
    driver_scheduling,
    driver_leave,
    ai_operations,
    enterprise,
    delivery_proofs,
)

api_router = APIRouter(dependencies=[Depends(enforce_rbac)])
api_router.include_router(knowledge.router)
api_router.include_router(business_imports.router)
api_router.include_router(exception_cases.router)
api_router.include_router(agent.router)
from app.api.v1.endpoints import agent_stream
api_router.include_router(agent_stream.router)
from app.api.v1.endpoints import agent_memory
api_router.include_router(agent_memory.router)
api_router.include_router(auto_dispatch.router)
api_router.include_router(terrains.router)
api_router.include_router(routes.router)
api_router.include_router(stores.router)
api_router.include_router(vehicle_types.router)
api_router.include_router(vehicles.router)
api_router.include_router(vehicle_attendances.router)
api_router.include_router(ai_operations.router)
api_router.include_router(enterprise.router)
api_router.include_router(delivery_demands.router)
api_router.include_router(dispatch_validations.router)
api_router.include_router(dispatch_plans.router)
api_router.include_router(daily_exceptions.router)
api_router.include_router(driver_scheduling.router)
api_router.include_router(driver_leave.router)
api_router.include_router(users.router)
api_router.include_router(audit_logs.router)
api_router.include_router(delivery_proofs.router)
