from app.domain.exceptions import BusinessError


class AgentModelError(BusinessError):
    """Safe model-layer error that never exposes provider internals."""


class AgentModelConfigurationError(AgentModelError):
    def __init__(self, message: str = "Agent模型配置不完整") -> None:
        super().__init__(
            message,
            status_code=503,
            code="AGENT_MODEL_CONFIGURATION_ERROR",
        )


class AgentModelTimeoutError(AgentModelError):
    def __init__(self) -> None:
        super().__init__(
            "Agent模型请求超时",
            status_code=504,
            code="AGENT_MODEL_TIMEOUT",
        )


class AgentModelConnectionError(AgentModelError):
    def __init__(self) -> None:
        super().__init__(
            "无法连接Agent模型服务",
            status_code=503,
            code="AGENT_MODEL_CONNECTION_ERROR",
        )


class AgentModelResponseError(AgentModelError):
    def __init__(self, message: str = "Agent模型返回了无法解析的响应") -> None:
        super().__init__(
            message,
            status_code=502,
            code="AGENT_MODEL_RESPONSE_ERROR",
        )


class AgentToolError(BusinessError):
    """Safe error raised by Agent tool infrastructure."""


def _safe_tool_name(name: object) -> str:
    if not isinstance(name, str):
        return "<invalid>"
    normalized = name.strip()
    return normalized[:100] if normalized else "<empty>"


class AgentToolNotFoundError(AgentToolError):
    def __init__(self, name: object) -> None:
        super().__init__(
            f"Agent工具未注册：{_safe_tool_name(name)}",
            status_code=400,
            code="AGENT_TOOL_NOT_FOUND",
        )


class AgentToolArgumentsError(AgentToolError):
    def __init__(self, name: object) -> None:
        super().__init__(
            f"Agent工具参数不合法：{_safe_tool_name(name)}",
            status_code=400,
            code="AGENT_TOOL_ARGUMENTS_ERROR",
        )


class AgentToolRegistrationError(AgentToolError):
    def __init__(self, name: object) -> None:
        super().__init__(
            f"Agent工具名称重复：{_safe_tool_name(name)}",
            status_code=500,
            code="AGENT_TOOL_REGISTRATION_ERROR",
        )


class AgentToolExecutionError(AgentToolError):
    def __init__(
        self,
        name: object,
        message: str | None = None,
        *,
        status_code: int = 500,
    ) -> None:
        safe_message = message or "工具执行失败，请稍后重试"
        super().__init__(
            f"Agent工具执行失败（{_safe_tool_name(name)}）：{safe_message}",
            status_code=status_code,
            code="AGENT_TOOL_EXECUTION_ERROR",
        )


class AgentMaxToolCallsError(BusinessError):
    def __init__(self, limit: int) -> None:
        super().__init__(
            f"单次Agent请求最多允许执行{limit}个工具调用",
            status_code=400,
            code="AGENT_MAX_TOOL_CALLS_EXCEEDED",
        )
