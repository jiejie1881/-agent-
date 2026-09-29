class BusinessError(Exception):
    def __init__(
        self, message: str, status_code: int = 400, code: str | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class NotFoundError(BusinessError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=404)


class ConflictError(BusinessError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=409)


class AuthenticationError(BusinessError):
    def __init__(self, message: str = "登录凭证无效或已过期") -> None:
        super().__init__(message, status_code=401, code="UNAUTHENTICATED")


class PermissionDeniedError(BusinessError):
    def __init__(self, message: str = "当前用户没有执行该操作的权限") -> None:
        super().__init__(message, status_code=403, code="FORBIDDEN")


class DispatchAdjustmentError(BusinessError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message, status_code=409, code=code)


class DispatchAdjustmentValidationError(DispatchAdjustmentError):
    """人工调整失败，保留首个错误兼容旧客户端并返回全部校验问题。"""

    def __init__(self, issues: list[dict[str, object]]) -> None:
        first = issues[0]
        super().__init__(str(first["code"]), str(first["message"]))
        self.issues = issues


class DemandLockedByDispatchError(BusinessError):
    def __init__(self, status: str) -> None:
        super().__init__(
            f"配送需求当前状态为{status}，核心业务字段已被派车流程锁定；"
            "如需修改，请先按业务规则撤回或取消关联派车方案，"
            "使需求恢复为PENDING后再重新派车",
            status_code=409,
            code="DEMAND_LOCKED_BY_DISPATCH",
        )


class DispatchPlanValidationError(BusinessError):
    def __init__(self, issues: list[dict[str, object]]) -> None:
        super().__init__(
            "派车方案发布前校验失败",
            status_code=409,
            code="DISPATCH_PLAN_VALIDATION_FAILED",
        )
        self.issues = issues
