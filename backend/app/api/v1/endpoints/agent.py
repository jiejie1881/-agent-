import logging
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Query, status

from app.agent.tool_execution import AgentToolContext
from app.api.agent_dependencies import (
    AgentConversationServiceDependency,
    AgentServiceDependency,
)
from app.api.auth_dependencies import CurrentUser
from app.domain.exceptions import BusinessError
from app.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentConversationChatResponse,
    AgentConversationDetailResponse,
    AgentConversationMessageResponse,
    AgentConversationSummaryResponse,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post(
    "/conversations",
    response_model=AgentConversationSummaryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建Agent会话",
)
def create_agent_conversation(
    current_user: CurrentUser,
    conversation_service: AgentConversationServiceDependency,
):
    return conversation_service.create(current_user.id)


@router.get(
    "/conversations",
    response_model=list[AgentConversationSummaryResponse],
    summary="查询当前用户的Agent会话",
)
def list_agent_conversations(
    current_user: CurrentUser,
    conversation_service: AgentConversationServiceDependency,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    return conversation_service.list(current_user.id, offset, limit)


@router.get(
    "/conversations/{conversation_id}",
    response_model=AgentConversationDetailResponse,
    summary="查询Agent会话详情",
)
def get_agent_conversation(
    conversation_id: int,
    current_user: CurrentUser,
    conversation_service: AgentConversationServiceDependency,
) -> AgentConversationDetailResponse:
    conversation, messages = conversation_service.get_detail(
        conversation_id, current_user.id
    )
    return AgentConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            AgentConversationMessageResponse.model_validate(message)
            for message in messages
        ],
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=AgentConversationChatResponse,
    summary="在Agent会话中发送消息",
    description=(
        "读取当前用户会话的最近历史，通过只读AI调度助手回答，"
        "成功后原子保存用户消息和助手最终回答。"
    ),
)
async def send_agent_conversation_message(
    conversation_id: int,
    data: AgentChatRequest,
    current_user: CurrentUser,
    agent_service: AgentServiceDependency,
    conversation_service: AgentConversationServiceDependency,
) -> AgentConversationChatResponse:
    request_id = str(uuid4())
    started_at = perf_counter()
    history = conversation_service.get_model_history(
        conversation_id, current_user.id
    )
    logger.info(
        "Agent conversation request started request_id=%s user_id=%s "
        "conversation_id=%s history_count=%s",
        request_id,
        current_user.id,
        conversation_id,
        len(history),
    )
    try:
        result = await agent_service.chat(
            data.message,
            AgentToolContext(
                current_user=current_user,
                request_id=request_id,
            ),
            history=history,
        )
        assistant_message = conversation_service.save_exchange(
            conversation_id,
            current_user.id,
            data.message,
            result.content,
        )
    except BusinessError as exc:
        logger.warning(
            "Agent conversation request failed request_id=%s user_id=%s "
            "conversation_id=%s code=%s elapsed_ms=%.2f",
            request_id,
            current_user.id,
            conversation_id,
            exc.code or "BUSINESS_ERROR",
            (perf_counter() - started_at) * 1000,
        )
        raise
    except Exception:
        logger.error(
            "Agent conversation request failed request_id=%s user_id=%s "
            "conversation_id=%s code=UNEXPECTED_ERROR elapsed_ms=%.2f",
            request_id,
            current_user.id,
            conversation_id,
            (perf_counter() - started_at) * 1000,
        )
        raise

    logger.info(
        "Agent conversation request succeeded request_id=%s user_id=%s "
        "conversation_id=%s tool_calls_count=%s used_tools=%s elapsed_ms=%.2f",
        request_id,
        current_user.id,
        conversation_id,
        result.tool_calls_count,
        ",".join(result.used_tools),
        (perf_counter() - started_at) * 1000,
    )
    return AgentConversationChatResponse(
        conversation_id=conversation_id,
        message=AgentConversationMessageResponse.model_validate(
            assistant_message
        ),
        tool_calls_count=result.tool_calls_count,
        used_tools=list(result.used_tools),
        request_id=request_id,
    )


@router.post(
    "/chat",
    response_model=AgentChatResponse,
    summary="使用只读物流调度助手",
    description=(
        "使用当前登录用户身份，通过只读AI调度助手查询物流业务信息。"
        "当前版本不会修改任何物流业务数据。"
    ),
)
async def chat_with_agent(
    data: AgentChatRequest,
    current_user: CurrentUser,
    agent_service: AgentServiceDependency,
) -> AgentChatResponse:
    request_id = str(uuid4())
    started_at = perf_counter()
    logger.info(
        "Agent request started request_id=%s user_id=%s",
        request_id,
        current_user.id,
    )
    try:
        result = await agent_service.chat(
            data.message,
            AgentToolContext(
                current_user=current_user,
                request_id=request_id,
            ),
        )
    except BusinessError as exc:
        logger.warning(
            "Agent request failed request_id=%s user_id=%s code=%s elapsed_ms=%.2f",
            request_id,
            current_user.id,
            exc.code or "BUSINESS_ERROR",
            (perf_counter() - started_at) * 1000,
        )
        raise
    except Exception:
        logger.error(
            "Agent request failed request_id=%s user_id=%s code=UNEXPECTED_ERROR "
            "elapsed_ms=%.2f",
            request_id,
            current_user.id,
            (perf_counter() - started_at) * 1000,
        )
        raise

    logger.info(
        "Agent request succeeded request_id=%s user_id=%s "
        "tool_calls_count=%s used_tools=%s elapsed_ms=%.2f",
        request_id,
        current_user.id,
        result.tool_calls_count,
        ",".join(result.used_tools),
        (perf_counter() - started_at) * 1000,
    )
    return AgentChatResponse(
        content=result.content,
        tool_calls_count=result.tool_calls_count,
        used_tools=list(result.used_tools),
        request_id=request_id,
    )
