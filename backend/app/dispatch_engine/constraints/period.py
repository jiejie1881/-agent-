from app.dispatch_engine.models import EngineDemand
from app.domain.enums import DeliveryPeriod


class DemandPeriodConstraint:
    def is_satisfied(
        self, demand: EngineDemand, period: DeliveryPeriod
    ) -> bool:
        return demand.period == period

