from dataclasses import dataclass

from app.domain.constraints import (
    LoadConstraint,
    PeriodConstraint,
    RouteConstraint,
    TerrainConstraint,
    VehicleAvailableConstraint,
)
from app.domain.constraints.base import (
    ConstraintResult,
    DispatchConstraint,
    DispatchValidationContext,
)

class OperatingConstraint:
    name = 'OperatingConstraint'

    def validate(self, context):
        for valid,code,message in ((context.vehicle_active,'VEHICLE_INACTIVE','车辆或车型当前不可运营'),
            (context.store_active,'STORE_INACTIVE','门店已停用'),(context.route_active,'ROUTE_INACTIVE','线路已停用'),
            (context.vehicle_route_allowed,'VEHICLE_ROUTE_NOT_ALLOWED','线路不在该车辆可运行范围')):
            if not valid:return ConstraintResult(self.name,False,message,code)
        return ConstraintResult(self.name,True)


DEFAULT_CONSTRAINTS: tuple[DispatchConstraint, ...] = (
    OperatingConstraint(),
    VehicleAvailableConstraint(),
    PeriodConstraint(),
    TerrainConstraint(),
    RouteConstraint(),
    LoadConstraint(),
)


@dataclass(frozen=True)
class DispatchValidationResult:
    is_valid: bool
    constraint_results: list[ConstraintResult]

    @property
    def failure_reasons(self) -> list[str]:
        return [
            result.reason
            for result in self.constraint_results
            if not result.passed and result.reason is not None
        ]


def validate_dispatch(
    context: DispatchValidationContext,
    constraints: tuple[DispatchConstraint, ...] = DEFAULT_CONSTRAINTS,
) -> DispatchValidationResult:
    results = [constraint.validate(context) for constraint in constraints]
    return DispatchValidationResult(
        is_valid=all(result.passed for result in results),
        constraint_results=results,
    )

