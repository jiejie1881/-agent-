from app.domain.constraints.base import ConstraintResult, DispatchValidationContext


class RouteConstraint:
    name = "RouteConstraint"

    def validate(self, context: DispatchValidationContext) -> ConstraintResult:
        if not context.store_belongs_to_route:
            return ConstraintResult(
                constraint=self.name,
                passed=False,
                reason="配送需求所属门店不属于所选线路",
                code="ROUTE_NOT_ALLOWED",
            )
        return ConstraintResult(constraint=self.name, passed=True)
