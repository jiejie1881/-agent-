from app.dispatch_engine.models import EngineRoute, EngineVehicle


class VehicleTerrainConstraint:
    def is_satisfied(
        self,
        vehicle: EngineVehicle,
        route: EngineRoute,
        permissions: set[tuple[int, int]],
    ) -> bool:
        return (vehicle.vehicle_type_id, route.terrain_id) in permissions

