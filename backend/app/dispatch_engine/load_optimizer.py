from app.dispatch_engine.constraints import LoadRangeConstraint
from app.dispatch_engine.models import EngineDemand, EngineVehicle, LoadedDemand
from app.domain.enums import DeliveryPriority

PRIORITY_WEIGHT = {
    DeliveryPriority.URGENT: 300,
    DeliveryPriority.HIGH: 200,
    DeliveryPriority.NORMAL: 100,
}


class LoadOptimizer:
    """First-fit decreasing loader for whole, non-splittable demand records."""

    def __init__(self) -> None:
        self.load_constraint = LoadRangeConstraint()

    def build_load(
        self,
        vehicle: EngineVehicle,
        demands: list[EngineDemand],
        stop_at_minimum: bool = False,
    ) -> tuple[LoadedDemand, ...]:
        selected: list[LoadedDemand] = []
        total = vehicle.min_load * 0

        for demand in sorted(
            demands,
            key=lambda item: (-PRIORITY_WEIGHT[item.priority], -item.quantity, item.id),
        ):
            proposed_total = total + demand.quantity
            if self.load_constraint.does_not_exceed_maximum(
                vehicle, proposed_total
            ):
                selected.append(
                    LoadedDemand(demand=demand, quantity=demand.quantity)
                )
                total = proposed_total
                if stop_at_minimum and total >= vehicle.min_load:
                    break

        if not self.load_constraint.is_dispatchable(vehicle, total):
            return ()
        return tuple(selected)
