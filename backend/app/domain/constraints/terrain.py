from app.domain.constraints.base import ConstraintResult, DispatchValidationContext


class TerrainConstraint:
    name = "TerrainConstraint"

    def validate(self, context: DispatchValidationContext) -> ConstraintResult:
        if not context.terrain_configured:
            return ConstraintResult(
                constraint=self.name,
                passed=False,
                reason="所选线路在配送日期没有生效的地形配置",
                code="TERRAIN_NOT_CONFIGURED",
            )
        if not context.terrain_allowed:
            return ConstraintResult(
                constraint=self.name,
                passed=False,
                reason=(
                    f"车辆类型{context.vehicle_type_name}不允许进入"
                    f"{context.terrain_name}地形"
                ),
                code="TERRAIN_NOT_ALLOWED",
            )
        return ConstraintResult(constraint=self.name, passed=True)
