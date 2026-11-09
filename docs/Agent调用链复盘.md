# Agent 调用链复盘

> 本文是原 Agent Phase 1 自定义编排的历史学习资料，不代表当前升级分支的执行路径。2026-10-10 当前版本已使用 LangChain + LangGraph StateGraph，写操作支持 Pending Action / HITL，知识查询支持 RAG。最新真实架构见 [AGENT_LANGGRAPH_MIGRATION.md](AGENT_LANGGRAPH_MIGRATION.md)，发布验收见 [GITHUB_RELEASE_FINAL_REPORT.md](../GITHUB_RELEASE_FINAL_REPORT.md)。下方旧代码片段、位置及验证记录仅用于历史复盘。
>
> 阅读目标：看完后，能够脱离本文口述一次完整调用：`Vue → API → AgentService → ModelClient → Tool Call → Registry → Executor → Service → Repository → DB → Tool Result → LLM → Response`。

## 1. 整体架构图

```text
Vue：AgentChatView / AgentComposer
↓
Frontend API：src/api/agent.ts
↓
FastAPI Endpoint：POST /api/v1/agent/conversations/{id}/messages
↓
JWT：get_current_user()
↓
RBAC：enforce_rbac() → AGENT_READ
↓
Conversation：读取最近可见历史
↓
AgentService.chat()
↓
ModelClient.chat()
↓
LLM
↓ 需要业务数据时产生 Tool Call
Tool Registry：工具白名单和参数校验
↓
Tool Executor Registry：找到真正的执行器
↓
Read-only Tool：例如 GetVehicleAttendanceTool
↓
Business Service：VehicleAttendanceService
↓
Repository：VehicleAttendanceRepository
↓
MySQL 8.4
↓
AgentToolResult
↓
tool role message
↓
AgentService 再次调用 ModelClient
↓
LLM 最终自然语言回答
↓
AgentChatResult
↓
Conversation 原子保存 USER + ASSISTANT
↓
AgentConversationChatResponse
↓
Vue 重新读取 Conversation Detail 并显示
```

整条链可以概括为：**模型负责决定“需要查什么”和“怎样组织语言”，后端白名单工具负责安全地取得真实业务数据，业务 Service 和 Repository 仍然掌握规则与数据库访问权。** LLM 本身没有 MySQL 权限，也不能执行任意 Python 函数。

当前有两个聊天入口：

- `POST /api/v1/agent/chat`：无状态单轮调用；
- `POST /api/v1/agent/conversations/{conversation_id}/messages`：Vue 页面实际使用的多轮调用。

下面主要复盘 Vue 当前使用的 Conversation 调用链。

---

## 2. Vue 层

### 2.1 真实文件

```text
frontend/src/views/agent/AgentChatView.vue
frontend/src/views/agent/components/AgentComposer.vue
frontend/src/views/agent/components/AgentConversationList.vue
frontend/src/views/agent/components/AgentMessageList.vue
frontend/src/api/agent.ts
frontend/src/types/agent.ts
frontend/src/api/http.ts
```

### 2.2 用户在哪里输入问题

输入框位于 `AgentComposer.vue`。它接收：

```ts
modelValue: string
sending: boolean
```

用户点击“发送”，或者按下 Enter，组件发出 `send` 事件。`AgentComposer` 不负责请求后端，它只负责输入行为、4000 字符限制和防重复提交。

真正接住事件的是 `AgentChatView.vue`：

```vue
<AgentComposer
  v-model="input"
  :sending="interactionLocked"
  @send="sendMessage"
/>
```

因此前端起点是：

```text
AgentComposer emit('send')
↓
AgentChatView.sendMessage()
```

### 2.3 Conversation ID 从哪里来

`AgentChatView` 用 `currentConversationId` 保存当前会话 ID。

- 用户选择旧会话时，ID 来自 `GET /agent/conversations` 返回的列表；
- 用户点击“新建”时，ID 来自 `POST /agent/conversations` 的数据库真实返回；
- 用户没有会话却直接发送时，`sendMessage()` 会先调用 `createAndSelectConversation()` 自动创建。

前端不会自己生成假 ID。

### 2.4 点击发送后调用什么

核心逻辑是：

```ts
await sendConversationMessage(conversationId, message)

const [detailResponse, listResponse] = await Promise.all([
  getConversation(conversationId),
  listConversations({ offset: 0, limit: 100 }),
])
```

`sendConversationMessage()` 定义在 `frontend/src/api/agent.ts`：

```ts
export function sendConversationMessage(conversationId: number, message: string) {
  return http.post<AgentSendMessageResponse>(
    `/agent/conversations/${conversationId}/messages`,
    { message },
  )
}
```

### 2.5 为什么组件不直接写 Axios

组件关心的是“发送一条消息”，不是 Axios 的 URL、Header、Token 刷新和错误结构。集中放在 `src/api/agent.ts` 有三个好处：

1. URL 和 TypeScript 类型只有一份；
2. JWT、Refresh Token 和统一错误提示继续复用 `src/api/http.ts`；
3. API 改动时，不需要在多个 Vue 组件里搜索散落的请求。

如果组件直接散写 Axios，认证、错误处理和响应类型很容易出现多套实现。

### 2.6 前端收到什么 Response

Conversation 消息接口对应类型是 `AgentSendMessageResponse`：

```ts
interface AgentSendMessageResponse {
  conversation_id: number
  message: AgentConversationMessage
  tool_calls_count: number
  used_tools: string[]
  request_id: string
}
```

其中 `message` 是已经保存成功的 ASSISTANT 消息。当前 UI 不展示 `used_tools`、`tool_calls_count` 和内部 Tool Trace。

### 2.7 为什么数据库是 Conversation 最终真相

发送成功后，Vue 没有简单地把本地输入和响应拼到数组里，而是重新调用 `getConversation()`。原因是：

- 后端只有在 Agent 成功后才保存 USER + ASSISTANT；
- 保存可能失败或事务回滚；
- 标题和 `updated_at` 由后端更新；
- 刷新浏览器后也必须恢复相同历史。

所以页面展示的是数据库确认过的 Conversation，而不是前端乐观猜测出来的内容。发送失败时，输入仍然保留，但不会形成一条假的历史消息。

---

## 3. API 层

### 3.1 真实路由

文件：`backend/app/api/v1/endpoints/agent.py`

```http
POST /api/v1/agent/conversations
GET  /api/v1/agent/conversations
GET  /api/v1/agent/conversations/{conversation_id}
POST /api/v1/agent/conversations/{conversation_id}/messages
POST /api/v1/agent/chat
```

路由文件中的 `router` 前缀是 `/agent`，`backend/app/main.py` 又用配置中的 `/api/v1` 挂载 `api_router`，因此形成完整 URL。

### 3.2 请求 Schema

`backend/app/schemas/agent.py` 中的 `AgentChatRequest`：

```python
class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
```

`field_validator` 会先 `strip()` 字符串，因此全空格消息也不能通过。

### 3.3 JWT 在哪里校验

文件：`backend/app/api/auth_dependencies.py`

`get_current_user()` 依次完成：

1. 从 `HTTPBearer` 读取 Bearer Token；
2. `decode_access_token()` 验证 JWT；
3. 从 `sub` 得到用户 ID；
4. `UserRepository.get()` 查询真实用户；
5. 检查用户是否启用；
6. 比对 JWT 中的角色和数据库角色；
7. 比对 `token_version`，让密码或权限变更后的旧 Token 失效。

最终 `CurrentUser` 是：

```python
CurrentUser = Annotated[User, Depends(get_current_user)]
```

### 3.4 RBAC 在哪里校验

`backend/app/api/v1/router.py` 给业务路由统一挂载：

```python
api_router = APIRouter(dependencies=[Depends(enforce_rbac)])
```

`enforce_rbac()` 根据 HTTP 方法和路径计算权限。Conversation 创建和消息发送虽然使用 POST，但被明确映射成 `AGENT_READ`。

当前角色权限：

```text
ADMIN      → 所有权限
DISPATCHER → READ + AGENT_READ + 运营写入 + 派车写入
VIEWER     → READ + AGENT_READ
```

所以 VIEWER 可以向只读 Agent 提问，但不能借 Agent 修改业务数据。前端菜单可见性只是体验，真正安全边界仍是这里的后端 RBAC。

### 3.5 Endpoint 做了什么

Conversation 消息函数是 `send_agent_conversation_message()`。核心调用顺序为：

```python
request_id = str(uuid4())
history = conversation_service.get_model_history(
    conversation_id, current_user.id
)

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
```

这里可以看到：

- `request_id` 用 `uuid4()` 为一次请求生成排查标识；
- Conversation 所有权通过 `conversation_id + current_user.id` 检查；
- `AgentToolContext` 把当前用户和请求标识传入工具执行链；
- Agent 成功之后，才保存 USER + ASSISTANT；
- 失败时记录安全日志，并交给统一异常处理器生成 HTTP 错误。

### 3.6 为什么 API 不直接调用 ModelClient

API 层只应该处理 HTTP、认证身份、输入输出和调用编排。Tool 循环、最大调用次数、消息角色和 Tool Result 回填都属于 Agent 运行逻辑，应该集中在 `AgentService`。

如果 Endpoint 直接调用 ModelClient，每个路由都要重复实现 Tool Loop，安全校验也容易被遗漏。

### 3.7 为什么 API 不直接查业务数据库

Endpoint 不应该理解“车辆出勤怎样查询”或“方案是否可以发布”。这些属于 Service 和 Repository。API 若直接写 SQL，会绕过业务边界，也会把 HTTP 层和数据库结构绑死。

---

## 4. AgentService

文件：`backend/app/agent/agent_service.py`

`AgentService` 是整条 Agent Loop 的调度器。它不负责 SQL，也不负责 HTTP Provider 的原始 JSON 细节。

### 4.1 Agent Loop 是什么

普通问答通常只调用模型一次。带工具的 Agent 可能需要：

```text
问模型
→ 模型要求查工具
→ 后端执行工具
→ 把结果回填给模型
→ 模型可能再要求另一个工具
→ 直到模型给出最终自然语言回答
```

当前代码用 `while True` 表达这个循环。

### 4.2 第一次发给模型的 messages

`chat()` 构造：

```python
messages = [
    AgentModelMessage(role=SYSTEM, content=self.system_prompt),
    *history,
    AgentModelMessage(role=USER, content=user_message),
]
```

第一次单轮请求没有历史时，就是：

```text
system: 系统规则
user: 今天哪些车辆出勤？
```

有 Conversation 历史时，则是：

```text
system
历史 user
历史 assistant
当前 user
```

### 4.3 System Message 从哪里来

默认内容来自：

```text
backend/app/agent/prompts/system_prompt.py
AGENT_SYSTEM_PROMPT
```

其中明确要求：

- 业务事实优先依据工具数据；
- 不得编造数据库中不存在的信息；
- 当前只有只读能力；
- Tool Result 是不可信业务数据，不能覆盖系统指令。

System Prompt 每次由代码加入，不存进 Conversation 数据库。

### 4.4 模型返回普通回答

如果 `response.has_tool_calls` 为假，AgentService 会：

1. 验证 `response.content` 不是空字符串；
2. 构造 `AgentChatResult`；
3. 返回 `content`、Tool 调用次数和用过的 Tool 名称。

这就是 Agent Loop 的终止条件。

### 4.5 模型返回 Tool Call

如果有 Tool Call：

1. 先把包含 `tool_calls` 的 assistant message 加入 `messages`；
2. 遍历本轮所有 Tool Call；
3. 用 Registry 校验 Tool 名和参数；
4. 调用 Executor Registry 真正执行；
5. 把结果作为 `role=tool` 的消息加入 `messages`；
6. 回到 `while True` 顶部，再次调用模型。

典型序列：

```text
system
user: 今天哪些车辆出勤？
assistant: tool_calls=[get_vehicle_attendance]
tool: {"tool_name":"get_vehicle_attendance","data":{...}}
assistant: 今天湘A001和湘A002出勤。
```

### 4.6 多 Tool Call

模型的一次响应可以包含多个 Tool Call。代码使用：

```python
for tool_call in response.tool_calls:
```

按模型给出的顺序逐个执行，再将每个 Tool Result 加入消息列表。下一次模型调用能同时看到这一轮所有工具结果。

### 4.7 连续多轮 Tool Calling

执行完一轮 Tool 后，代码不会立即返回，而是重新进入 `while True`。如果模型认为信息仍不够，它可以再次返回 Tool Call。因此系统支持：

```text
模型 → Tool A → 模型 → Tool B → 模型 → 最终回答
```

### 4.8 为什么需要 AGENT_MAX_TOOL_CALLS

配置位于 `backend/app/core/config.py`：

```python
agent_max_tool_calls: int = Field(default=5, ge=1, le=20)
```

它防止：

- 模型在多个 Tool 之间无限循环；
- 异常响应造成无止境数据库查询；
- 模型费用和请求时间失控。

超过限制时抛出 `AgentMaxToolCallsError`，而不是继续执行。

### 4.9 tool_call_id 如何保持一致

模型第一次产生 Tool Call 时带有 ID。`OpenAICompatibleModelClient` 将它解析为 `AgentToolCall.id`。工具执行后，AgentService 使用同一个值：

```python
AgentModelMessage(
    role=AgentMessageRole.TOOL,
    tool_call_id=tool_call.id,
    content=result.to_json(),
)
```

这让模型知道“这条 Tool Result 对应哪一个 Tool Call”，在同一响应中出现多个 Tool Call 时尤其重要。当前执行器仍按模型给出的顺序逐个执行。

---

## 5. ModelClient

真实文件：

```text
backend/app/agent/model_client.py
backend/app/agent/model_types.py
```

### 5.1 AgentModelClient 是什么

`AgentModelClient` 是抽象接口：

```python
async def chat(messages, tools=None) -> AgentModelResponse
```

AgentService 只依赖这个项目内部接口，不依赖某个 Provider 的 SDK 或原始响应。

### 5.2 OpenAICompatibleModelClient 是什么

它是当前的具体实现，负责：

- 验证 `AGENT_PROVIDER / MODEL / API_KEY / BASE_URL`；
- 把项目内部消息序列化成 OpenAI-compatible JSON；
- 用 `httpx.AsyncClient` 请求 `/chat/completions`；
- 把 Provider 原始 JSON 解析成 `AgentModelResponse`；
- 把超时、连接错误、错误状态和畸形响应转换为项目自己的异常。

### 5.3 为什么需要适配层

Provider 的字段、异常和 Tool Call JSON 格式属于外部协议。AgentService 只需要理解稳定的内部模型。

没有适配层时，Provider 的任何字段变化都会污染 Agent Loop，未来更换 Provider 也会迫使业务层重写。

### 5.4 项目内部模型类型

`AgentMessageRole` 有四种：

```text
system
user
assistant
tool
```

`AgentModelMessage` 表示一次传给模型的消息，可能包含：

- `content`
- `tool_calls`
- `tool_call_id`

其 Pydantic 校验保证：

- 只有 TOOL 消息能带 `tool_call_id`；
- 只有 ASSISTANT 消息能带 `tool_calls`；
- TOOL 消息必须有 `tool_call_id`；
- 除带 Tool Call 的 ASSISTANT 外，消息必须有 content。

`AgentToolCall` 保存：

```text
id
name
arguments: dict
```

`AgentModelResponse` 保存：

```text
content
tool_calls
finish_reason
```

### 5.5 一个关键认识

> Tool Call 只是模型提出的结构化调用请求，不代表工具已经执行。

ModelClient 只负责把 Provider 返回的 Tool Call 解析出来。真正执行发生在后端 Registry 和 Executor 之后。

---

## 6. Tool Call

假设模型返回：

```json
{
  "id": "call_attendance_1",
  "name": "get_vehicle_attendance",
  "arguments": {
    "date": "2026-09-28"
  }
}
```

### 谁产生它

Tool Call 由 LLM 根据用户问题、System Prompt 和 Tool Definition 产生。不是 Vue 产生，也不是 Service 产生。

### 为什么它不是 Python 代码

它只是数据：一个工具名、一个调用 ID、一组 JSON 参数。它没有模块路径、Python 表达式或任意脚本。

### 为什么模型不能直接执行

模型运行在外部模型服务中：

- 它没有项目进程权限；
- 没有数据库连接；
- 不持有 SQLAlchemy Session；
- 不应该拥有任意代码执行能力。

### 为什么必须经过白名单

模型输出不能被当成可信命令。它可能拼错名称、提供非法字段，甚至在提示注入影响下要求执行不存在的危险工具。因此必须经过 `AgentToolRegistry`，只有显式注册的六个只读工具才有机会执行。

---

## 7. Tool Schema

文件：`backend/app/agent/schemas/tool.py`

### 7.1 它是什么

Tool Schema 是“工具参数合同”：告诉 LLM 参数长什么样，也告诉后端怎样验证模型给出的 JSON。

车辆出勤工具使用：

```python
class GetVehicleAttendanceArgs(StrictToolArgs):
    date: date
    vehicle_id: int | None = Field(default=None, gt=0)
```

### 7.2 Pydantic 做什么

模型返回：

```json
{"date": "2026-09-28", "vehicle_id": 3}
```

Pydantic 会把日期字符串转换为 `datetime.date`，并验证 `vehicle_id > 0`。Tool 拿到的是验证后的强类型对象，不需要自己重复解析日期。

### 7.3 extra="forbid"

`StrictToolArgs` 和 `PaginatedToolArgs` 都配置：

```python
ConfigDict(extra="forbid")
```

因此模型若多传一个 Schema 未声明的字段，请求会被拒绝。这样可以避免“悄悄忽略拼错字段”或把未经设计的参数送进业务层。

### 7.4 ID 和分页限制

- 门店 ID、车辆 ID、方案 ID 使用 `gt=0`；
- `PaginationParams` 使用 `offset >= 0`；
- `limit` 范围为 `1..100`。

这些限制既控制非法业务引用，也防止模型一次请求无上限数据。

### 7.5 JSON Schema 怎样给 LLM

`AgentToolDefinition.parameters` 调用：

```python
arguments_schema.model_json_schema()
```

随后将本地 `$defs` 引用展开。`to_openai_tool()` 最终生成：

```json
{
  "type": "function",
  "function": {
    "name": "get_vehicle_attendance",
    "description": "查询指定日期的车辆出勤情况……",
    "parameters": { "type": "object", "properties": { } }
  }
}
```

### 7.6 三个概念不要混

```text
Tool Schema   = 参数合同
Tool Registry = 工具定义白名单和查找表
Tool Executor = 真正执行查询的代码
```

Schema 不会查数据库，Registry 也不会自动执行业务查询。

---

## 8. Tool Registry

文件：`backend/app/agent/tool_registry.py`

### 8.1 当前白名单

`DEFAULT_TOOL_DEFINITIONS` 只有六项：

```text
list_delivery_demands
get_vehicle_attendance
list_dispatch_plans
get_dispatch_plan_detail
get_unassigned_demands
validate_dispatch_plan
```

全部都是只读工具。

### 8.2 如何按名称查 Definition

初始化时 Registry 构造：

```python
self._definitions_by_name: dict[str, AgentToolDefinition]
```

`get(name)` 只从这张显式字典查找。查不到就抛 `AgentToolNotFoundError`。

### 8.3 如何校验参数

`validate_arguments(name, arguments)`：

1. 先 `get(name)` 验证工具存在；
2. 再调用该 Definition 的 `arguments_schema.model_validate(arguments)`；
3. Pydantic 失败时转成 `AgentToolArgumentsError`。

当前 AgentService 在调度层先校验一次，Executor Registry 在执行边界还会再次校验。后者保证即使未来有其他调用方使用 Executor Registry，也不能绕开参数合同。

### 8.4 Tool Name 为什么必须唯一

若两个 Definition 同名，模型无法知道同一个名称究竟代表哪个参数和行为。Registry 初始化时会检查重复，并抛 `AgentToolRegistrationError`。

### 8.5 为什么不能 eval 或 getattr

如果把模型给出的字符串直接传给 `eval()`，或对任意模块做动态 `getattr()`，模型就可能越过白名单调用危险函数。当前实现只查显式字典，因此“模型说有一个工具”不等于系统真的允许它。

---

## 9. Tool Executor

真实文件：

```text
backend/app/agent/tool_execution.py
backend/app/agent/read_only_tools.py
```

### 9.1 Definition 与 Executor 的区别

`AgentToolDefinition` 是给模型看的说明书；`AgentToolExecutor` 才是服务器内部的真正执行逻辑。

两者通过唯一 Tool Name 对应：

```text
GET_VEHICLE_ATTENDANCE_DEFINITION.name
=
GetVehicleAttendanceTool.name
=
get_vehicle_attendance
```

### 9.2 AgentToolExecutorRegistry

它显式保存 `name → executor`。初始化时会确认：

- Executor 对应的 Definition 确实存在；
- Executor 名称没有重复。

执行流程：

```python
validated_arguments = definition_registry.validate_arguments(name, arguments)
executor = self._executors_by_name.get(name)
return await executor.execute(validated_arguments, context)
```

### 9.3 AgentToolContext

```python
class AgentToolContext:
    current_user: User
    request_id: str | None
```

它把认证后的用户身份和请求链路标识继续传到工具层。当前六个只读 Tool 暂未按用户进一步过滤业务数据，但上下文已经存在，未来增加审计或细粒度数据权限时不需要信任模型传入 user_id。

### 9.4 AgentToolResult

统一结果结构：

```python
class AgentToolResult(BaseModel):
    tool_name: str
    data: dict[str, Any]
```

`from_data()` 使用 Pydantic `TypeAdapter` 转为 JSON 模式，`to_json()` 再生成给 LLM 的 JSON 字符串。

### 9.5 get_vehicle_attendance 实际怎样执行

`GetVehicleAttendanceTool._execute()` 调用：

```python
records = self.service.list(
    arguments.date,
    arguments.vehicle_id,
    0,
    self.QUERY_LIMIT,
)
```

它把 ORM 记录映射成受控字典：

```text
date
vehicle_id_filter
returned_count
truncated
vehicles[]
  vehicle_id
  plate_number
  vehicle_type.code
  vehicle_type.name
  available
```

注意：Tool 调的是 `VehicleAttendanceService`，不是 Repository。

---

## 10. Service

### 10.1 Service 是业务边界

Agent Tool 复用现有业务 Service：

```text
ListDeliveryDemandsTool      → DeliveryDemandService
GetVehicleAttendanceTool     → VehicleAttendanceService
ListDispatchPlansTool        → DispatchPlanService
GetDispatchPlanDetailTool    → DispatchPlanService
GetUnassignedDemandsTool     → DispatchPlanService
ValidateDispatchPlanTool     → DispatchPlanService
```

Service 决定业务上“允许做什么、如何组合 Repository、找不到时返回什么错误、事务在哪里提交”。

### 10.2 VehicleAttendanceService

文件：`backend/app/services/vehicle_attendance_service.py`

车辆出勤 Tool 使用真实方法：

```python
VehicleAttendanceService.list(
    attendance_date,
    vehicle_id,
    offset,
    limit,
)
```

这个方法再调用：

```python
VehicleAttendanceRepository.list_filtered(...)
```

同一个 Service 还拥有创建、更新、删除出勤记录时的车辆存在性和日期唯一性规则。只读 Agent 虽然只调用 `list()`，但依赖的仍是同一个业务入口。

### 10.3 DispatchPlanService 复用真实校验

`ValidateDispatchPlanTool` 调用：

```python
result = self.service.validate_plan(arguments.plan_id)
```

真实链路为：

```text
DispatchPlanService.validate_plan()
↓
DispatchPlanPublicationValidator.validate()
↓
DispatchValidationService + LoadConstraint
```

它会检查方案中的车辆出勤、时段、地形、线路、载重、重复需求、需求日期和状态等既有规则。Agent 没有自己重新写一套“能否发布”的判断。

这样更安全：业务规则以后修改时，正式发布和 Agent 只读解释仍然使用同一个规则来源。

### 10.4 为什么不能 Tool → Repository

如果 Tool 直接调用 Repository：

- 容易绕过 Service 的业务校验；
- Tool 会承担 SQL 查询和业务含义两种职责；
- 普通 API 与 Agent 可能得到不同业务结果；
- 将来增加事务、审计或数据权限时，需要修改每一个 Tool。

因此当前合理链路是：

```text
Tool → Service → Repository
```

---

## 11. Repository

### 11.1 Repository 做什么

Repository 只关心数据访问：组装 SQLAlchemy `select()`、过滤条件、排序、分页、关联加载和持久化。

车辆出勤 Repository 位于：

```text
backend/app/repositories/vehicle_attendance_repository.py
```

实际方法：

```python
VehicleAttendanceRepository.list_filtered(
    attendance_date,
    vehicle_id,
    offset,
    limit,
)
```

它会：

- 按日期和可选车辆 ID 过滤；
- 按日期倒序、记录 ID 排序；
- 应用 offset/limit；
- 用 `joinedload` 一次加载 Vehicle 和 VehicleType。

### 11.2 Service 与 Repository 的区别

```text
Service：这项业务应该怎样做
Repository：这些数据应该怎样读写
```

例如“该车辆当天已有出勤记录”是业务冲突，由 Service 判断；“按 date + vehicle_id 查询记录”由 Repository 完成。

### 11.3 Agent 为什么不能直接调用 Repository

Agent 是新的交互入口，不是新的业务规则来源。如果它直达 Repository，就可能绕过同一系统普通 API 必须遵守的 Service 规则，形成安全和一致性漏洞。

---

## 12. DB

当前 Docker 环境使用 MySQL 8.4。SQLAlchemy Engine 和 Session 位于：

```text
backend/app/infrastructure/database/session.py
```

数据库在 Agent 链路中的职责只有一个：保存和提供真实业务状态，例如：

- `vehicle_attendances`
- `vehicles`
- `vehicle_types`
- `delivery_demands`
- `dispatch_plans`
- `agent_conversations`
- `agent_messages`

需要牢牢记住：

> LLM 没有数据库权限。

LLM 只能提出：

```text
请调用 get_vehicle_attendance，参数是 2026-09-28
```

真正数据库访问仍然是：

```text
VehicleAttendanceRepository
↓ SQLAlchemy
MySQL
```

这层隔离避免模型生成任意 SQL、读取未授权表或修改数据。

---

## 13. Tool Result

### 13.1 为什么不能直接返回 ORM

ORM 对象包含：

- SQLAlchemy 内部状态；
- 懒加载关系；
- 不一定能 JSON 序列化的 Decimal、date、Enum；
- Tool 不希望暴露的字段。

因此 `GetVehicleAttendanceTool` 主动选择允许给模型看的字段，再交给 `AgentToolResult.from_data()` 标准化。

### 13.2 实际结果形态

示意结果：

```json
{
  "tool_name": "get_vehicle_attendance",
  "data": {
    "date": "2026-09-28",
    "vehicle_id_filter": null,
    "returned_count": 2,
    "truncated": false,
    "vehicles": [
      {
        "vehicle_id": 1,
        "plate_number": "湘A001",
        "vehicle_type": {
          "code": "FOUR_METER",
          "name": "四米二"
        },
        "available": true
      }
    ]
  }
}
```

这是对真实结构的示意；车辆内容取决于数据库当日记录。

### 13.3 如何变成 tool role message

AgentService 使用：

```python
AgentModelMessage(
    role=AgentMessageRole.TOOL,
    tool_call_id=tool_call.id,
    content=result.to_json(),
)
```

标准化结果被放入 `content`，原始 Tool Call ID 被放入 `tool_call_id`。

---

## 14. Tool Result 为什么还要重新给 LLM

用户问：

```text
今天哪些车辆出勤？
```

第一次调用 LLM 时，模型只知道语言和 Tool Definition，不知道 MySQL 今天有什么记录。因此它不能可靠地直接回答，只能提出：

```text
get_vehicle_attendance(date=今天)
```

后端执行工具后得到的是结构化 JSON。这个 JSON 适合机器处理，却不是最终用户最容易阅读的回答。

所以系统继续执行：

```text
AgentToolResult
↓ 作为 tool role message
重新调用 ModelClient
↓
LLM 读取真实结果
↓
组织自然语言
```

最终可能回答：

```text
2026年9月28日共有2辆车出勤：湘A001、湘A002。
```

这一步的职责分工很重要：

- Tool 保证事实来自系统；
- LLM 负责把事实组织成人话；
- LLM 不能把 Tool Result 当成新的系统指令；
- 如果结果为空，模型也应该明确说明没有查到，而不是编造车辆。

---

## 15. Response

### 15.1 AgentService 的输出

文件：`backend/app/agent/chat_types.py`

```python
class AgentChatResult(BaseModel):
    content: str
    tool_calls_count: int
    used_tools: tuple[str, ...]
```

它是 Agent Core 的内部结果，不是 Provider 原始 JSON。

### 15.2 API 的输出

Conversation 路由在 Agent 成功后保存消息，再返回 `AgentConversationChatResponse`：

```text
conversation_id
message（已保存的 ASSISTANT 消息）
tool_calls_count
used_tools
request_id
```

无状态 `/agent/chat` 则返回 `AgentChatResponse`，其中直接包含 `content`。

### 15.3 为什么使用项目自己的 Response

项目 Response 可以：

- 隐藏 Provider 差异；
- 保证前端类型稳定；
- 只暴露用户需要的内容；
- 保留项目自己的 `request_id`；
- 将外部错误转换为安全业务错误。

### 15.4 为什么不返回内部信息

当前 API 不返回：

- System Prompt；
- Tool Result 原文；
- `tool_call_id`；
- Provider 原始响应；
- 模型内部思考过程。

这些内容不是正常用户界面的一部分，暴露它们会增加安全风险、耦合 Provider，并让前端依赖内部实现。前端虽然收到 Tool 名称和次数用于调试能力，但当前页面主动不展示。

最终前端链路：

```text
AgentChatResult
↓
AgentConversationService.save_exchange()
↓
AgentConversationChatResponse
↓
frontend/src/api/agent.ts
↓
AgentChatView.vue
↓
重新 GET Conversation Detail
↓
AgentMessageList.vue
```

---

## 16. Conversation 在哪里插入

真实文件：

```text
backend/app/services/agent_conversation_service.py
backend/app/repositories/agent_conversation_repository.py
backend/app/models/agent_conversation.py
```

### 16.1 读取历史

Endpoint 在调用 AgentService 之前先执行：

```python
history = conversation_service.get_model_history(
    conversation_id,
    current_user.id,
)
```

Repository 查询始终同时带：

```text
conversation_id + user_id
```

这防止用户猜测 ID 读取别人的对话。即使是 ADMIN，当前普通 Conversation API 也只能访问自己的会话。

`get_model_history()` 只读取最近 `AGENT_HISTORY_MAX_MESSAGES` 条，默认 20 条。数据库仍保存完整可见历史。

### 16.2 数据库消息与模型消息

数据库角色只有：

```text
USER
ASSISTANT
```

转换后模型协议角色为：

```text
user
assistant
```

System Prompt 由代码每次加入，Tool Call 和 Tool Result 当前不持久化。

### 16.3 第二轮实际怎样发送

数据库已有：

```text
USER: 今天有哪些派车方案？
ASSISTANT: 今天有V1和V2。
```

用户再问：

```text
第二个方案详情呢？
```

AgentService 收到的是：

```text
system: 当前系统规则
user: 今天有哪些派车方案？
assistant: 今天有V1和V2。
user: 第二个方案详情呢？
```

所以模型能把“第二个”理解为上一轮提到的 V2。

### 16.4 成功后怎样保存

模型成功后调用 `save_exchange()`。它：

1. 使用 `conversation_id + user_id` 并加行锁重新确认所有权；
2. 在同一事务增加 USER 消息；
3. 在同一事务增加 ASSISTANT 消息；
4. 首轮用用户问题前 50 字生成标题；
5. 更新 `updated_at`；
6. 一次 commit，失败则 rollback。

因此模型超时不会在数据库留下半条用户消息。

### 16.5 Conversation 不等于 Agent Memory

```text
Conversation = 某个用户、某个会话中的可见聊天历史
Memory       = 从长期交互中提取、存储、检索的长期知识或偏好
```

当前系统只实现 Conversation。它没有自动摘要、向量检索、跨会话偏好记忆或 Agent Memory。

---

## 17. 完整实例：今天哪些车辆出勤？

假设：

- 当前用户已登录；
- 当前 Conversation ID 为 `15`；
- 当前日期按用户问题解析为 `2026-09-28`；
- 数据库中有当日车辆出勤记录。

| 步骤 | 输入 | 主要类 / 方法 | 输出 |
|---:|---|---|---|
| 1 | 用户输入“今天哪些车辆出勤？” | `AgentComposer.vue` | 发出 `send` 事件 |
| 2 | `input` + `currentConversationId=15` | `AgentChatView.sendMessage()` | 调用前端 API；发送期间锁定交互 |
| 3 | ID 15、消息文本 | `sendConversationMessage()` | `POST /agent/conversations/15/messages` |
| 4 | Bearer Token | Axios request interceptor | 带 Authorization 的 HTTP 请求 |
| 5 | HTTP 请求 | `get_current_user()` | 数据库中真实且启用的 `User` |
| 6 | Request + User | `enforce_rbac()` | 确认当前角色拥有 `AGENT_READ` |
| 7 | JSON Body | `AgentChatRequest` | 去空格、长度 1..4000 的 message |
| 8 | Conversation 15 + user_id | `AgentConversationService.get_model_history()` | 最近最多20条 `AgentModelMessage` 历史 |
| 9 | User + UUID | `AgentToolContext` | 当前身份与 `request_id` |
| 10 | 当前问题 + history + context | `AgentService.chat()` | `[system, history..., user]` 消息列表 |
| 11 | messages + 六个 Tool Definition | `OpenAICompatibleModelClient.chat()` | Provider HTTP 请求 |
| 12 | 问题与工具说明 | LLM | `AgentToolCall(name=get_vehicle_attendance, arguments={date})` |
| 13 | Provider 原始 JSON | `_parse_response()` / `_parse_tool_call()` | 项目内部 `AgentModelResponse` |
| 14 | Tool 名和原始参数 | `AgentToolRegistry.validate_arguments()` | `GetVehicleAttendanceArgs(date=date(...))` |
| 15 | Tool 名、参数、context | `AgentToolExecutorRegistry.execute()` | 找到 `GetVehicleAttendanceTool`，再次守住执行边界 |
| 16 | 强类型 arguments | `GetVehicleAttendanceTool._execute()` | 调用 `VehicleAttendanceService.list()` |
| 17 | 日期、可选 vehicle_id、分页 | `VehicleAttendanceService.list()` | 委托 Repository 查询 |
| 18 | 查询条件 | `VehicleAttendanceRepository.list_filtered()` | SQLAlchemy Select + joinedload |
| 19 | SQL | MySQL 8.4 | `VehicleAttendance`、Vehicle、VehicleType 记录 |
| 20 | ORM 记录 | `GetVehicleAttendanceTool` 字段映射 | 受控业务字典 |
| 21 | 字典 | `AgentToolResult.from_data()` | JSON 可序列化的标准结果 |
| 22 | Tool Result + 原 call ID | `AgentService` | `role=tool` 的 `AgentModelMessage` |
| 23 | 完整 messages | `ModelClient.chat()` 第二次调用 | 将真实 Tool Result 再交给 LLM |
| 24 | 真实车辆数据 | LLM | 自然语言最终回答 |
| 25 | 最终 `AgentModelResponse` | `AgentService` | `AgentChatResult(content, count, used_tools)` |
| 26 | 用户问题 + 最终回答 | `AgentConversationService.save_exchange()` | 同一事务保存 USER + ASSISTANT |
| 27 | 已保存 assistant message | `AgentConversationChatResponse` | 稳定的项目 HTTP JSON |
| 28 | HTTP Response | `AgentChatView.sendMessage()` | 发送成功 |
| 29 | Conversation 15 | `getConversation(15)` | 数据库中的完整 Conversation Detail |
| 30 | `messages` | `AgentMessageList.vue` | 用户问题靠右、助手回答靠左显示 |

把这 30 步压缩成口述版就是：

```text
Vue 把问题和真实 Conversation ID 交给前端 API；FastAPI 验证 JWT 和 AGENT_READ，
读取该用户自己的会话历史，再让 AgentService 把 system、历史和当前问题交给 ModelClient。
LLM 不知道数据库答案，所以提出 get_vehicle_attendance Tool Call。
后端 Registry 检查工具白名单和参数，Executor 调 VehicleAttendanceService，
Service 再通过 Repository 查询 MySQL。Tool 把 ORM 映射成标准 AgentToolResult，
AgentService 用原 tool_call_id 把结果作为 tool 消息重新发给 LLM。
LLM 基于真实数据生成最终回答。成功后 ConversationService 原子保存问答，
FastAPI 返回项目 Response，Vue 重新读取数据库会话并显示。
```

---

## 18. 每层一句话记忆

| 层 | 一句话记忆 |
|---|---|
| Vue | 用户和 Agent 交互的界面 |
| Frontend API | 集中管理 Agent HTTP 请求和 TypeScript 类型 |
| API | HTTP、认证、权限和输入输出入口 |
| Conversation | 保存用户可见历史，为多轮问题提供上下文 |
| AgentService | Agent 循环的大脑调度器 |
| ModelClient | 和 LLM 通信、隔离 Provider 差异的适配层 |
| LLM | 决定是否需要工具，并把真实结果组织成自然语言 |
| Tool Call | LLM 提出的结构化工具调用请求 |
| Schema | 工具参数合同 |
| Registry | 工具白名单和查找表 |
| Executor | 真正执行 Tool 的受控代码 |
| Service | 业务规则边界 |
| Repository | 数据访问层 |
| DB | 真实业务数据的持久化来源 |
| Tool Result | Tool 的标准化、JSON 可序列化执行结果 |
| Response | 返回前端的稳定项目结果，不是 Provider 原始数据 |

---

## 19. 常见混淆

### ModelClient vs AgentService

ModelClient 只负责与模型 Provider 通信和协议转换。AgentService 负责循环、Tool 调度、次数限制和判断何时得到最终回答。前者是“通信适配器”，后者是“Agent 流程控制器”。

### Tool Schema vs Tool Registry

Schema 描述一个 Tool 的参数形状和约束。Registry 保存允许模型看到和调用的 Tool Definition，并根据名字找到对应 Schema。一个是合同，一个是白名单目录。

### Tool Definition vs Tool Executor

Definition 给 LLM 看，包含名称、描述和 JSON Schema。Executor 在服务器内运行，调用真实 Service。看到 Definition 不意味着代码已经执行。

### Service vs Repository

Service 表达业务规则和业务错误，可以组合多个 Repository 并控制事务。Repository 负责 SQLAlchemy 查询和持久化，不应该决定复杂业务流程。

### Conversation vs Memory

Conversation 是一个会话内的可见 USER/ASSISTANT 历史。Memory 通常是跨会话提取、总结和检索的长期信息；当前项目没有实现 Memory。

### Tool Call vs Tool 已执行

Tool Call 只是模型输出的一段结构化请求。只有它通过 Registry 白名单、Schema 校验，并被 Executor 调用之后，Tool 才真正执行。

### Tool Result vs 最终 AI 回答

Tool Result 是结构化真实数据，主要供模型继续处理。最终 AI 回答是 LLM 根据这些真实数据组织出来的用户可读语言。

### 前端权限隐藏 vs 后端 RBAC

前端隐藏菜单只能改善体验，用户仍可手工构造 HTTP 请求。后端 `enforce_rbac()` 才是不能绕过的权限边界。

---

## 20. 自测题

1. 为什么 AgentService 不应该直接访问 Repository？
2. Tool Call 是谁产生的，它包含哪些核心字段？
3. 为什么模型返回 Tool Call 后，工具还没有真正执行？
4. AgentToolRegistry 的安全作用是什么？
5. Tool Result 为什么还要重新交给 LLM？
6. `tool_call_id` 有什么作用，多 Tool Call 时为什么尤其重要？
7. ModelClient 和 AgentService 分别负责什么？
8. Service 和 Repository 分别负责什么？
9. 为什么不能把 SQLAlchemy ORM 对象直接交给 LLM？
10. Conversation 和 Agent Memory 有什么区别？
11. 为什么 VIEWER 能使用当前 Agent，却不能通过 Agent 修改物流数据？
12. 为什么前端隐藏写操作按钮不能代替后端 RBAC？
13. 为什么 Agent 模型配置缺失只导致 Agent 请求失败，而不应该影响整个物流系统启动？
14. 为什么必须限制最大 Tool Calls？当前默认上限是多少？
15. 用户第二轮只问“第二个方案呢？”时，系统依靠什么理解“第二个”？

---

## 复盘检查清单

尝试不看上文，回答下面六句话：

1. 用户问题从哪个 Vue 函数进入？
2. JWT、RBAC、Conversation 所有权分别在哪里检查？
3. LLM 产生 Tool Call 后，哪两个 Registry 相关对象参与执行？
4. `get_vehicle_attendance` 最终调用了哪个 Service 和 Repository？
5. Tool Result 怎样带着原 `tool_call_id` 回到 LLM？
6. 最终回答为什么要成功后才和用户消息一起写入数据库？

如果可以完整回答，并能口述第 17 章的压缩版调用链，就已经掌握了当前项目 Agent Phase 1 的核心工程结构。

---

## 21. Phase 2：确认后执行的写操作

Phase 2 在原有六个只读 Tool 之外新增两个写 Tool：

| Tool | 业务作用 | 后端权限 | 首次 Tool Call 是否执行 |
|---|---|---|---|
| `move_delivery_demand` | 移动 DRAFT 方案中的配送需求 | `DISPATCH_WRITE` | 否，只创建 Pending Action |
| `cancel_dispatch_plan` | 取消 DRAFT 或 PUBLISHED 方案 | `DISPATCH_WRITE` | 否，只创建 Pending Action |

Tool Definition 新增 `read_only`、`requires_confirmation` 和
`required_permission` 元数据。模型仍然只能调用 Registry 中明确注册的工具；
当 `requires_confirmation=true` 时，`AgentService` 不会进入写 Executor，而是让
`AgentPendingActionService` 校验参数、当前权限和业务对象，并写入
`agent_pending_actions`。

真实调用链是：

```text
AgentChatView.vue
→ Agent Conversation API
→ AgentService
→ ModelClient
→ LLM Write Tool Call
→ Tool Registry 校验 Schema 与 metadata
→ AgentPendingActionService
→ agent_pending_actions(PENDING)
→ Conversation 问答与 Pending Action 同一次提交
→ Vue AgentPendingActionCard
→ 用户点击确认
→ Confirm API
→ 再次检查用户、Conversation、过期时间、状态与 DISPATCH_WRITE
→ 行锁锁定 Pending Action
→ Write Tool Executor
→ DispatchPlanService
→ Repository / MySQL
→ AuditLog(source=agent, tool_name, pending_action_id)
→ Pending Action(EXECUTED)
→ 一次事务提交
→ Vue 刷新会话
```

### 21.1 为什么要保存 Pending Action

Pending Action 不是前端临时状态。它保存用户、Conversation、Tool 名、不可由前端
重传的原始参数、摘要、风险说明、状态和过期时间，因此页面刷新或服务重启后仍可
恢复，也不会因为前端篡改确认请求而改变执行参数。

状态为：

```text
PENDING → CONFIRMED → EXECUTED
PENDING → CANCELLED
PENDING → EXPIRED
PENDING → CONFIRMED → FAILED（执行时业务条件已经变化）
```

确认时使用数据库行锁，并且只有 `PENDING` 可以进入执行路径。因此双击、重试或并发
确认不会导致业务操作重复执行。

### 21.2 两次 RBAC 与业务重校验

第一次权限检查发生在创建 Pending Action 前，VIEWER 不能生成可执行写操作。第二次
发生在 Confirm 时，因为等待期间用户角色可能已经变化。真正执行时仍调用现有
`DispatchPlanService.move_demand()` 或 `cancel()`，所以线路、地形、载重、方案状态等
业务规则不会被 Agent 绕过。

### 21.3 事务与审计

确认路径由 Pending Action Service 持有最终事务提交。业务 Service 在 Agent 路径中
只 `flush`，Audit Log 与业务修改一起留在同一 Session；随后 Action 改为 `EXECUTED`
并统一 `commit`。任一步失败都会回滚业务修改，Action 会记录为 `FAILED`，且不会留下
成功审计。成功审计沿用现有 `AuditLog.changes`，增加：

```json
{
  "source": "agent",
  "tool_name": "move_delivery_demand",
  "pending_action_id": 123,
  "result": "success"
}
```

### 21.4 Vue 确认卡

`AgentPendingActionCard.vue` 展示操作类型、摘要、关键参数、风险和状态。只有 ADMIN 或
DISPATCHER 显示可用的确认/取消操作；点击确认还有一次界面二次确认。前端只提交
Action ID，不提交 Tool 参数，最终权限与规则仍全部由后端判断。
