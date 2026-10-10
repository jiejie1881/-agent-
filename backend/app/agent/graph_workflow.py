"""StateGraph owns routing, tool rounds and the durable human approval pause."""
from typing import TypedDict
from uuid import uuid4
from langchain_core.tools import StructuredTool
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app.agent.chat_types import AgentChatResult, AgentPendingActionSnapshot
from app.agent.exceptions import AgentMaxToolCallsError, AgentModelResponseError
from app.agent.model_types import AgentMessageRole, AgentModelMessage
from app.agent.tool_execution import AgentToolResult
from app.domain.exceptions import NotFoundError, AgentPendingActionError
from app.agent.graph_store import AgentGraphStore


class AgentState(TypedDict, total=False):
    user_id: int
    conversation_id: int | None
    messages: list[dict]
    calls: list[dict]
    content: str
    count: int
    used: list[str]
    pending: list[dict]
    write_signature: list[str] | None
    decision: str
    execution: dict


class AgentWorkflow:
    def __init__(self, service, context, store):
        self.service, self.context, self.store = service, context, store

    def graph(self, saver):
        graph = StateGraph(AgentState)
        graph.add_node('model', self.model)
        graph.add_node('tools', self.tools)
        graph.add_node('approval', self.approval)
        graph.add_node('execute', self.execute)
        graph.add_edge(START, 'model')
        graph.add_conditional_edges('model', lambda state: 'tools' if state.get('calls') else ('approval' if state.get('pending') else END))
        graph.add_edge('tools', 'model')
        graph.add_edge('approval', 'execute')
        graph.add_edge('execute', END)
        return graph.compile(checkpointer=saver)

    def owned(self, state):
        if state['user_id'] != self.context.current_user.id or state.get('conversation_id') != self.context.conversation_id:
            raise NotFoundError('Agent执行状态不存在')

    async def model(self, state):
        self.owned(state)
        response = await self.service.model_client.chat(
            [AgentModelMessage.model_validate(item) for item in state['messages']],
            self.service.tool_registry.to_openai_tools())
        if not response.has_tool_calls and (response.content is None or not response.content.strip()):
            raise AgentModelResponseError('Agent模型未返回最终回答')
        message = AgentModelMessage(role=AgentMessageRole.ASSISTANT, content=response.content, tool_calls=response.tool_calls)
        return {'messages': [*state['messages'], message.model_dump(mode='json')],
                'calls': [call.model_dump(mode='json') for call in response.tool_calls], 'content': response.content or ''}

    async def tools(self, state):
        self.owned(state)
        calls = state['calls']
        if sum(self.service.tool_registry.get(call['name']).requires_confirmation for call in calls) > 1:
            raise AgentModelResponseError('单次请求只能生成一个待确认写操作')
        count, used, pending = state['count'], list(state['used']), list(state['pending'])
        signature, messages = state.get('write_signature'), list(state['messages'])
        for call in calls:
            if count >= self.service.max_tool_calls:
                raise AgentMaxToolCallsError(self.service.max_tool_calls)
            args = self.service.tool_registry.validate_arguments(call['name'], call['arguments'])
            definition = self.service.tool_registry.get(call['name'])
            count += 1
            if definition.requires_confirmation:
                if self.service.pending_action_service is None:
                    raise AgentModelResponseError('Agent写操作确认服务未配置')
                next_signature = [call['name'], args.model_dump_json()]
                if signature is not None and next_signature != signature:
                    raise AgentModelResponseError('单次请求只能生成一个待确认写操作')
                if not pending:
                    action = self.service.pending_action_service.create(definition, args, self.context)
                    pending.append(self.service.pending_action_service.snapshot(action).model_dump(mode='json'))
                    signature = next_signature
                action = pending[0]
                result = AgentToolResult.from_data(call['name'], {'status': 'confirmation_required', 'action_id': action['id'], 'summary': action['summary'], 'expires_at': action['expires_at']})
            else:
                async def execute_read(**kwargs):
                    return await self.service.executor_registry.execute(call['name'], kwargs, self.context)
                tool = StructuredTool.from_function(name=definition.name, description=definition.description,
                                                     args_schema=definition.arguments_schema, coroutine=execute_read)
                result = await tool.ainvoke(call['arguments'])
            used.append(call['name'])
            messages.append(AgentModelMessage(role=AgentMessageRole.TOOL, tool_call_id=call['id'], content=result.to_json()).model_dump(mode='json'))
        return {'messages': messages, 'count': count, 'used': used, 'pending': pending, 'write_signature': signature, 'calls': []}

    def approval(self, state):
        self.owned(state)
        action = state['pending'][0]
        decision = interrupt({'action_id': action['id'], 'summary': action['summary'], 'requires_confirmation': True})
        if decision not in ('confirm', 'cancel'):
            raise AgentModelResponseError('非法的人工审批指令')
        return {'decision': decision}

    async def execute(self, state):
        self.owned(state)
        action_id = state['pending'][0]['id']
        service = self.service.pending_action_service
        if state['decision'] == 'confirm':
            action, result = await service.confirm(self.context.conversation_id, action_id, self.context.current_user)
            data = result.data
        else:
            action = service.cancel(self.context.conversation_id, action_id, self.context.current_user)
            data = {'status': 'cancelled'}
        return {'pending': [service.snapshot(action).model_dump(mode='json')], 'execution': data}

    async def chat(self, user_message, history):
        initial = AgentState(user_id=self.context.current_user.id, conversation_id=self.context.conversation_id,
            messages=[AgentModelMessage(role=AgentMessageRole.SYSTEM, content=self.service.system_prompt).model_dump(mode='json'),
                      *[item.model_dump(mode='json') for item in history],
                      AgentModelMessage(role=AgentMessageRole.USER, content=user_message).model_dump(mode='json')],
            count=0, used=[], pending=[], write_signature=None, calls=[])
        thread = f'u{self.context.current_user.id}:c{self.context.conversation_id}:r{uuid4()}'
        config = {'configurable': {'thread_id': thread}, 'recursion_limit': self.service.max_tool_calls * 3 + 8}
        async with AsyncSqliteSaver.from_conn_string(str(self.store.path)) as saver:
            state = await self.graph(saver).ainvoke(initial, config)
        for action in state['pending']:
            self.store.register(action['id'], self.context.current_user.id, self.context.conversation_id, thread)
        return AgentChatResult(content=state['content'], tool_calls_count=state['count'], used_tools=tuple(state['used']),
                               pending_actions=tuple(AgentPendingActionSnapshot.model_validate(action) for action in state['pending']))

    async def resume(self, action_id, decision):
        thread = self.store.find(action_id, self.context.current_user.id, self.context.conversation_id)
        if thread is None:
            return None  # Legacy PendingActions remain valid and use the same business service.
        config = {'configurable': {'thread_id': thread}}
        async with AsyncSqliteSaver.from_conn_string(str(self.store.path)) as saver:
            graph = self.graph(saver)
            snapshot = await graph.aget_state(config)
            self.owned(snapshot.values)
            actual = self.service.pending_action_service._get_owned(
                action_id, self.context.conversation_id, self.context.current_user.id, for_update=True)
            # IDs may be reused after a separate test DB/backup restore. Do not
            # attach an unrelated older checkpoint to a newly created action.
            created_at = self.service.pending_action_service.snapshot(actual).model_dump(mode='json')['created_at']
            if snapshot.values['pending'][0]['created_at'] != created_at:
                return None
            if snapshot.values['pending'][0]['id'] != action_id or not snapshot.next:
                raise AgentPendingActionError('AGENT_ACTION_NOT_PENDING', '待确认操作已经处理')
            if 'execute' in snapshot.next:
                # An execution error can leave approval consumed. Honour the
                # latest explicit decision rather than replaying an old confirm.
                await graph.aupdate_state(config, {'decision': decision}, as_node='approval')
                state = await graph.ainvoke(None, config)
            else:
                state = await graph.ainvoke(Command(resume=decision), config)
        return state['execution']
