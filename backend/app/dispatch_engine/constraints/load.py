from decimal import Decimal

from app.dispatch_engine.models import EngineVehicle


class LoadRangeConstraint:
    def does_not_exceed_maximum(
        self, vehicle: EngineVehicle, quantity: Decimal
    ) -> bool:
        return quantity <= vehicle.max_load

    def is_dispatchable(self, vehicle: EngineVehicle, total_load: Decimal) -> bool:
        return vehicle.min_load <= total_load <= vehicle.max_load

