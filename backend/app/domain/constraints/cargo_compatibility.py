from app.domain.constraints.base import ConstraintResult, DispatchValidationContext


class CargoCompatibilityConstraint:
    name = "CargoCompatibilityConstraint"

    def validate(self, context: DispatchValidationContext) -> ConstraintResult:
        if not context.cargo_capability_exists or not context.cargo_allowed:
            return ConstraintResult(
                constraint=self.name,
                passed=False,
                reason=(
                    f"车辆车型{context.vehicle_type_name}不支持当前货物类型"
                    f"{context.cargo_category_name or context.cargo_category_id}"
                ),
                code="CARGO_NOT_ALLOWED",
            )
        return ConstraintResult(constraint=self.name, passed=True)
