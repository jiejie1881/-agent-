from decimal import Decimal

from app.domain.constraints.base import ConstraintResult, DispatchValidationContext


class LoadConstraint:
    name = "LoadConstraint"

    def validate(self, context: DispatchValidationContext) -> ConstraintResult:
        return self.validate_load(
            context.quantity, context.min_load, context.max_load
        )

    def validate_load(
        self, quantity: Decimal, min_load: Decimal, max_load: Decimal
    ) -> ConstraintResult:
        if min_load <= 0 or max_load <= 0 or min_load > max_load:
            return ConstraintResult(
                constraint=self.name,
                passed=False,
                reason=(
                    f"车辆类型载重参数无效：最低载重量{min_load}，"
                    f"最高载重量{max_load}"
                ),
                code="INVALID_VEHICLE_TYPE_LOAD_RANGE",
            )
        if quantity < min_load:
            return ConstraintResult(
                constraint=self.name,
                passed=False,
                reason=(
                    f"装载量{quantity}低于车辆类型最低载重量"
                    f"{min_load}"
                ),
                code="BELOW_MIN_LOAD",
            )
        if quantity > max_load:
            return ConstraintResult(
                constraint=self.name,
                passed=False,
                reason=(
                    f"装载量{quantity}超过车辆类型最高载重量"
                    f"{max_load}"
                ),
                code="OVERLOAD",
            )
        return ConstraintResult(constraint=self.name, passed=True)
