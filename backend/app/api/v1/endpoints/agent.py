import logging
from datetime import date
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Header, Query, Response, status

from app.agent.tool_execution import AgentToolContext
from app.api.agent_dependencies import (
    AgentConversationServiceDependency,
    AgentPendingActionServiceDependency,
    AgentServiceDependency,
)
from app.api.auth_dependencies import CurrentUser
from app.api.dependencies import DbSession
from app.api.shadow_dispatch_dependencies import ShadowDispatchDependency
from app.domain.exceptions import BusinessError, PermissionDeniedError
from app.domain.permissions import Permission, has_permission
from app.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentConversationChatResponse,
    AgentConversationDetailResponse,
    AgentConversationMessageResponse,
    AgentConversationSummaryResponse,
    AgentPendingActionExecutionResponse,
)
from app.schemas.agent_dispatch import (
    AgentDraftAcceptanceRequest, AgentDraftAcceptanceResponse,
    ShadowDispatchRequest, ShadowDispatchResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get('/conversations/{conversation_id}/executions', summary='查询本人会话的任务执行步骤')
def get_agent_executions(conversation_id: int, current_user: CurrentUser,
                         conversation_service: AgentConversationServiceDependency,
                         agent_service: AgentServiceDependency, response: Response):
    conversation_service.get_owned(conversation_id,current_user.id)
    response.headers['Cache-Control']='no-store'
    return agent_service.execution_reports(current_user,conversation_id)


@router.post('/conversations/{conversation_id}/executions/{execution_id}/resume', summary='从本人持久化检查点恢复任务')
async def resume_agent_execution(conversation_id: int,execution_id: str,current_user: CurrentUser,
                                 conversation_service: AgentConversationServiceDependency,
                                 agent_service: AgentServiceDependency,response: Response):
    conversation_service.get_owned(conversation_id,current_user.id)
    response.headers['Cache-Control']='no-store'
    return await agent_service.resume_execution(conversation_id,execution_id,current_user)


@router.post('/conversations/{conversation_id}/executions/{execution_id}/cancel',summary='请求取消本人正在执行的任务')
def cancel_agent_execution(conversation_id:int,execution_id:str,current_user:CurrentUser,
                           conversation_service:AgentConversationServiceDependency,
                           agent_service:AgentServiceDependency,response:Response):
    conversation_service.get_owned(conversation_id,current_user.id)
    requested=agent_service.graph_store.request_cancellation(execution_id,current_user.id,conversation_id)
    response.headers['Cache-Control']='no-store'
    return {'execution_id':execution_id,'cancellation_requested':requested,
            'status':'CANCEL_REQUESTED' if requested else agent_service.graph_store.execution(execution_id,current_user.id,conversation_id)['status'],
            'cleanup_confirmed':False}


@router.get("/dispatch/shadow/context", summary="预览真实业务影子快照，不调用模型")
def get_shadow_context(delivery_date: date, current_user: CurrentUser, db: DbSession, response: Response):
    from app.core.config import get_settings
    from app.services.dispatch_context_service import DispatchContextService

    if not current_user.is_active or not has_permission(current_user.role, Permission.DISPATCH_WRITE):
        raise PermissionDeniedError()
    response.headers["Cache-Control"] = "no-store"
    if not get_settings().agent_dispatch_shadow_enabled:
        return {"enabled": False, "reason_code": "SHADOW_DISABLED", "context": None}
    context = DispatchContextService(db).load(delivery_date)
    # Never return resource_records: they are internal fingerprint inputs.
    return {"enabled": True, "reason_code": None, "context": context.model_dump(
        mode="json", include={"delivery_date", "snapshot_version", "demands", "stores",
                              "vehicles", "routes", "shifts", "terrain_permissions"})}


@router.post("/dispatch/shadow", summary="只读Agent影子派车，不保存或发布")
async def run_shadow_dispatch(
    request: ShadowDispatchRequest,
    current_user: CurrentUser,
    workflow: ShadowDispatchDependency,
) -> ShadowDispatchResult:
    if workflow.settings.agent_dispatch_shadow_enabled and not request.authorize_external:
        raise PermissionDeniedError("需先确认将该日期的必要业务数据发送至已配置模型")
    result = await workflow.run(request, current_user)
    settings = workflow.settings
    if settings.agent_draft_accept_enabled and has_permission(current_user.role, Permission.AGENT_DRAFT_ACCEPT) and result.status == "SUCCESS":
        from app.services.agent_dispatch_receipt import issue_receipt

        result = result.model_copy(update={"acceptance_receipt": issue_receipt(result, current_user, settings)})
    return result


@router.post("/dispatch/accept-draft", response_model=AgentDraftAcceptanceResponse,
             status_code=status.HTTP_201_CREATED, summary="采纳已校验 Agent 候选为正式草稿")
def accept_agent_draft(request: AgentDraftAcceptanceRequest, current_user: CurrentUser,
                       db: DbSession, idempotency_key: str = Header(alias="Idempotency-Key")):
    from app.core.config import get_settings
    from app.services.agent_dispatch_acceptance_service import AgentDispatchAcceptanceService

    return AgentDispatchAcceptanceService(db.get_bind(), get_settings()).accept(
        request.candidate, request.acceptance_receipt, idempotency_key,
        request.confirmed, current_user.id)


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
    pending_action_service: AgentPendingActionServiceDependency,
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
        pending_actions=[
            pending_action_service.snapshot(action)
            for action in pending_action_service.list_owned(
                conversation_id, current_user.id
            )
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
                conversation_id=conversation_id,
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
        pending_actions=list(result.pending_actions),
        execution=getattr(result,'execution',None),
    )


@router.post(
    "/conversations/{conversation_id}/pending-actions/{action_id}/confirm",
    response_model=AgentPendingActionExecutionResponse,
    summary="确认并执行Agent待确认操作",
)
async def confirm_agent_pending_action(
    conversation_id: int,
    action_id: int,
    current_user: CurrentUser,
    pending_action_service: AgentPendingActionServiceDependency,
    agent_service: AgentServiceDependency,
) -> AgentPendingActionExecutionResponse:
    resumed = await agent_service.resume_action(conversation_id, action_id, current_user, 'confirm')
    if resumed is not None:
        action = pending_action_service._get_owned(action_id, conversation_id, current_user.id, for_update=False)
        return AgentPendingActionExecutionResponse(action=pending_action_service.snapshot(action), result=resumed)
    action, result = await pending_action_service.confirm(
        conversation_id, action_id, current_user
    )
    return AgentPendingActionExecutionResponse(
        action=pending_action_service.snapshot(action),
        result=result.data,
    )


@router.post(
    "/conversations/{conversation_id}/pending-actions/{action_id}/cancel",
    response_model=AgentPendingActionExecutionResponse,
    summary="取消Agent待确认操作",
)
async def cancel_agent_pending_action(
    conversation_id: int,
    action_id: int,
    current_user: CurrentUser,
    pending_action_service: AgentPendingActionServiceDependency,
    agent_service: AgentServiceDependency,
) -> AgentPendingActionExecutionResponse:
    resumed = await agent_service.resume_action(conversation_id, action_id, current_user, 'cancel')
    if resumed is not None:
        action = pending_action_service._get_owned(action_id, conversation_id, current_user.id, for_update=False)
        return AgentPendingActionExecutionResponse(action=pending_action_service.snapshot(action), result=resumed)
    action = pending_action_service.cancel(conversation_id, action_id, current_user)
    return AgentPendingActionExecutionResponse(
        action=pending_action_service.snapshot(action),
        result={"status": "cancelled"},
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
        execution=getattr(result,'execution',None),
    )
