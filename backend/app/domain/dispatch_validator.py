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

DEFAULT_CONSTRAINTS: tuple[DispatchConstraint, ...] = (
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

