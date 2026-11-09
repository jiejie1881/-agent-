from app.domain.constraints.base import ConstraintResult, DispatchValidationContext


class VehicleAvailableConstraint:
    name = "VehicleAvailableConstraint"

    def validate(self, context: DispatchValidationContext) -> ConstraintResult:
        if not context.attendance_exists:
            return ConstraintResult(
                constraint=self.name,
                passed=False,
                reason=f"车辆在{context.dispatch_date.isoformat()}没有出勤记录",
                code="VEHICLE_NOT_AVAILABLE",
            )
        if not context.vehicle_available:
            return ConstraintResult(
                constraint=self.name,
                passed=False,
                reason=f"车辆在{context.dispatch_date.isoformat()}未出勤",
                code="VEHICLE_NOT_AVAILABLE",
            )
        return ConstraintResult(constraint=self.name, passed=True)
