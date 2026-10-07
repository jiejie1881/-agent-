from app.domain.constraints.base import ConstraintResult, DispatchValidationContext


class TemperatureConstraint:
    name = "TemperatureConstraint"

    def validate(self, context: DispatchValidationContext) -> ConstraintResult:
        if not context.requires_temperature_control:
            return ConstraintResult(constraint=self.name, passed=True)
        if (
            context.demand_min_temperature is None
            or context.demand_max_temperature is None
            or context.vehicle_min_temperature is None
            or context.vehicle_max_temperature is None
            or context.vehicle_min_temperature > context.demand_min_temperature
            or context.vehicle_max_temperature < context.demand_max_temperature
        ):
            return ConstraintResult(
                constraint=self.name,
                passed=False,
                reason=(
                    "车辆温控范围"
                    f"{context.vehicle_min_temperature}℃~{context.vehicle_max_temperature}℃"
                    "无法满足需求"
                    f"{context.demand_min_temperature}℃~{context.demand_max_temperature}℃"
                ),
                code="TEMPERATURE_NOT_SUPPORTED",
            )
        return ConstraintResult(constraint=self.name, passed=True)
