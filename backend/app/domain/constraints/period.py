from app.domain.constraints.base import ConstraintResult, DispatchValidationContext


class PeriodConstraint:
    name = "PeriodConstraint"

    def validate(self, context: DispatchValidationContext) -> ConstraintResult:
        if context.demand_period != context.dispatch_period:
            return ConstraintResult(
                constraint=self.name,
                passed=False,
                reason=(
                    f"配送需求时段为{context.demand_period.value}，"
                    f"不能安排到{context.dispatch_period.value}"
                ),
                code="PERIOD_MISMATCH",
            )
        return ConstraintResult(constraint=self.name, passed=True)
