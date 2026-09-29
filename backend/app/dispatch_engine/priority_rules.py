from collections import Counter

from app.dispatch_engine.models import EngineVehicle
from app.domain.enums import DeliveryPeriod, VehicleTypeCode


class PriorityRules:
    minimum_trip_targets = {
        VehicleTypeCode.FOUR_METER: 1,
        VehicleTypeCode.BIG_VAN: 1,
        VehicleTypeCode.SMALL_VAN: 2,
    }
    target_priority = {
        VehicleTypeCode.BIG_VAN: 0,
        VehicleTypeCode.SMALL_VAN: 1,
        VehicleTypeCode.FOUR_METER: 2,
    }
    normal_priority = {
        VehicleTypeCode.FOUR_METER: 0,
        VehicleTypeCode.BIG_VAN: 1,
        VehicleTypeCode.SMALL_VAN: 2,
    }

    def needs_minimum_trip(
        self,
        vehicle: EngineVehicle,
        period: DeliveryPeriod,
        trip_counts: Counter[tuple[DeliveryPeriod, VehicleTypeCode]],
    ) -> bool:
        code = vehicle.vehicle_type_code
        return (
            trip_counts[(period, code)] < self.minimum_trip_targets[code]
        )

    def vehicle_sort_key(
        self,
        vehicle: EngineVehicle,
        period: DeliveryPeriod,
        trip_counts: Counter[tuple[DeliveryPeriod, VehicleTypeCode]],
        vehicle_trip_counts: Counter[tuple[int, DeliveryPeriod]],
    ) -> tuple[int, int, int]:
        code = vehicle.vehicle_type_code
        target_rank = self._target_rank(code, period, trip_counts)
        return (
            target_rank,
            vehicle_trip_counts[(vehicle.id, period)],
            vehicle.id,
        )

    def _target_rank(
        self,
        code: VehicleTypeCode,
        period: DeliveryPeriod,
        trip_counts: Counter[tuple[DeliveryPeriod, VehicleTypeCode]],
    ) -> int:
        unmet_codes = {
            vehicle_type_code
            for vehicle_type_code, target in self.minimum_trip_targets.items()
            if trip_counts[(period, vehicle_type_code)] < target
        }
        if code in unmet_codes:
            return self.target_priority[code]
        if unmet_codes:
            return len(self.target_priority)
        return self.normal_priority[code]
