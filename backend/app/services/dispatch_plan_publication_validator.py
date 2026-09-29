from decimal import Decimal

from app.domain.constraints import LoadConstraint
from app.domain.enums import DeliveryDemandStatus
from app.domain.exceptions import BusinessError
from app.models.dispatch_plan import DispatchPlan
from app.schemas.dispatch_validation import DispatchValidationRequest
from app.services.dispatch_validation_service import DispatchValidationService


class DispatchPlanPublicationValidator:
    VALID_DEMAND_STATUSES = {
        DeliveryDemandStatus.PLANNED,
        DeliveryDemandStatus.PUBLISHED,
    }
    ORDER_SCOPED_CONSTRAINTS = {
        "VehicleAvailableConstraint",
        "TerrainConstraint",
    }

    def __init__(self, validation_service: DispatchValidationService) -> None:
        self.validation_service = validation_service
        self.load_constraint = LoadConstraint()

    def validate(self, plan: DispatchPlan) -> list[dict[str, object]]:
        issues: list[dict[str, object]] = []
        first_assignment: dict[int, int] = {}

        for order in sorted(plan.orders, key=lambda item: item.id):
            actual_load = sum(
                (detail.quantity for detail in order.details), Decimal("0")
            )
            self._validate_order_load(order, actual_load, issues)
            reported_order_issues: set[tuple[str | None, str | None]] = set()

            for detail in sorted(order.details, key=lambda item: item.id):
                demand = detail.delivery_demand
                previous_order_id = first_assignment.get(detail.delivery_demand_id)
                if previous_order_id is not None:
                    issues.append(
                        self._issue(
                            "DUPLICATE_DEMAND",
                            (
                                f"需求{detail.delivery_demand_id}同时分配在任务"
                                f"{previous_order_id}和任务{order.id}"
                            ),
                            order.id,
                            detail.delivery_demand_id,
                        )
                    )
                else:
                    first_assignment[detail.delivery_demand_id] = order.id

                if demand.date != plan.delivery_date:
                    issues.append(
                        self._issue(
                            "INVALID_DELIVERY_DEMAND_DATE",
                            (
                                f"需求{demand.id}配送日期{demand.date.isoformat()}"
                                f"与方案日期{plan.delivery_date.isoformat()}不一致"
                            ),
                            order.id,
                            demand.id,
                        )
                    )
                if demand.status not in self.VALID_DEMAND_STATUSES:
                    issues.append(
                        self._issue(
                            "INVALID_DELIVERY_DEMAND_STATUS",
                            f"需求{demand.id}当前状态{demand.status.value}不可发布",
                            order.id,
                            demand.id,
                        )
                    )

                try:
                    result = self.validation_service.validate_result(
                        DispatchValidationRequest(
                            vehicle_id=order.vehicle_id,
                            delivery_demand_id=demand.id,
                            route_id=order.route_id,
                            period=order.period,
                            quantity=actual_load,
                        )
                    )
                except BusinessError as exc:
                    issues.append(
                        self._issue(
                            "INVALID_DELIVERY_DEMAND_REFERENCE",
                            exc.message,
                            order.id,
                            demand.id,
                        )
                    )
                    continue

                for constraint_result in result.constraint_results:
                    if constraint_result.passed:
                        continue
                    if constraint_result.constraint == "LoadConstraint":
                        continue
                    issue_key = (
                        constraint_result.code,
                        constraint_result.reason,
                    )
                    if (
                        constraint_result.constraint
                        in self.ORDER_SCOPED_CONSTRAINTS
                        and issue_key in reported_order_issues
                    ):
                        continue
                    if constraint_result.constraint in self.ORDER_SCOPED_CONSTRAINTS:
                        reported_order_issues.add(issue_key)
                    issues.append(
                        self._issue(
                            constraint_result.code or "DISPATCH_CONSTRAINT_FAILED",
                            constraint_result.reason or "派车约束校验失败",
                            order.id,
                            demand.id,
                        )
                    )

        return issues

    def _validate_order_load(
        self,
        order,
        actual_load: Decimal,
        issues: list[dict[str, object]],
    ) -> None:
        if order.total_load != actual_load:
            issues.append(
                self._issue(
                    "TOTAL_LOAD_MISMATCH",
                    (
                        f"任务{order.id}记录总载重{order.total_load}"
                        f"与明细合计{actual_load}不一致"
                    ),
                    order.id,
                )
            )
        load_result = self.load_constraint.validate_load(
            actual_load,
            order.vehicle.vehicle_type.min_load,
            order.vehicle.vehicle_type.max_load,
        )
        if not load_result.passed:
            issues.append(
                self._issue(
                    load_result.code or "LOAD_CONSTRAINT_FAILED",
                    load_result.reason or "任务载重不合法",
                    order.id,
                )
            )

    @staticmethod
    def _issue(
        code: str,
        message: str,
        order_id: int,
        demand_id: int | None = None,
    ) -> dict[str, object]:
        issue: dict[str, object] = {
            "code": code,
            "message": message,
            "order_id": order_id,
        }
        if demand_id is not None:
            issue["delivery_demand_id"] = demand_id
        return issue
