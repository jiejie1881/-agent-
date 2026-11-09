# Agent LangChain / LangGraph 迁移记录

> 当前核验入口（2026-10-10）：原迁移阶段记录保留为历史证据，不代表当前发布状态。`1c59467` 已纳入 Dashboard、小程序及 Demo 相关源码；`8276cc2` 已修正历史 DDL 与模型元数据差异。本轮 486 tests / MySQL alembic check PASS。受控演示数据发送授权已获得，真实普通对话、业务工具、RAG、混合、多轮及 HITL API 已验证。用户手动启动 Docker 后，Vue 主要流程及真实连接/事务故障探针已执行；浏览器断网/超时与部分权限/过期交互仍待核验，当前 NOT READY，详见[最终报告](../GITHUB_RELEASE_FINAL_REPORT.md)。

## 提交范围与不变边界

本轮仅在 `codex/agent-langchain-langgraph` 分支开发。保留稳定 Tag，不 push、不修改已执行历史迁移、不删除既有业务数据。

前置提交按模块拆分：

- `17da3b3`：Migration 19～21，司机排班、固定出勤、请假审批与确认代班。
- `b689217`：Migration 22，AI 需求录入、确认批量写入、调度评分及关联前端。
- `9f24d9b`：Migration 23，鉴权回单访问、审核历史与非破坏性补传。
- `4161fc5`：Migration 24，退出货物分类/温控业务，历史列、表及引用保留。

自动派车的载重、线路、地形、时段、出勤、司机绑定、请假和代班规则不由 Agent 实现或绕过；全部仍由原业务 Service 校验。数据库状态机、JWT/Refresh Token、原 Vue API 响应契约与小程序接口不因框架迁移改变。

## 实际调用链

Vue Agent Chat → FastAPI / JWT / RBAC → AgentConversationService + AgentService
→ StateGraph model 节点（ChatOpenAI / bind_tools）
→ tools 节点（StructuredTool + 现有 Schema / Registry / Executor）
→ 原业务 Service → Repository → MySQL
→ Tool Result → model 节点 → 最终回答。

只读工具：`list_delivery_demands`、`get_vehicle_attendance`、`list_dispatch_plans`、`get_dispatch_plan_detail`、`get_unassigned_demands`、`validate_dispatch_plan`。

知识工具：`search_knowledge_base`，复用原 Chroma / Embedding / Retriever，不新增 RAG 能力。

写工具：`move_delivery_demand`、`cancel_dispatch_plan`。tools 节点只创建 PendingAction，不执行写 Service；模型给出待确认说明后，approval 节点通过 `interrupt` 暂停。现有确认 API 用 `Command(resume=...)` 恢复，execute 节点调用原 PendingActionService，重新检查所有者、权限、过期时间、业务状态，成功业务操作与审计同事务提交。取消待确认操作不会取消派车方案。

最多工具调用次数仍由 `AGENT_MAX_TOOL_CALLS` 控制；同一模型响应的每个调用分别计数。未知工具、参数错误、业务异常、模型连接/超时/格式错误都沿用明确业务错误，不伪装成功。

## Checkpoint 与恢复

- 使用 `AsyncSqliteSaver`，路径由 `AGENT_CHECKPOINT_PATH` 配置，默认 `backend/agent_data/checkpoints.sqlite3`（从 backend 工作目录启动）。Docker 固定 `/app/agent_data/checkpoints.sqlite3` 并挂载 `agent_checkpoints` volume。
- 这是框架执行状态存储，不增加 MySQL 业务表或 Alembic migration。保存 JSON 化消息、调用结果、审批状态及用户/会话 ID；不保存 User ORM 对象、密码、JWT、API Key、Session 或角色权限快照。
- 服务端生成 thread_id，不接受客户端指定任意线程；PendingAction 映射同时校验 user_id + conversation_id。原会话归属校验保持不变。
- 原 MySQL 会话历史仍是多轮对话的持久化来源；Checkpoint 保存当前工具轮次及审批暂停点。两者不是同一种“记忆”。
- 历史没有 Checkpoint 的 PendingAction 仍可通过原业务确认路径处理，执行相同 RBAC 与 Service 校验，不通过重新运行模型迁移历史数据。
- 重复确认由 MySQL PendingAction 状态拒绝；Repository 使用条件 UPDATE 领取 PENDING，避免 SQLite 不支持 FOR UPDATE 导致重复领取；MySQL 同时保留行锁。
- MySQL 是业务事实来源。业务已提交但 Checkpoint 未更新时，重试先读取最新 PendingAction 状态，拒绝再次执行，不承诺两个数据库之间存在分布式原子事务。
- 权限拒绝后审批任务可能停在 execute；再次取消时显式更新 decision，不能重放旧 confirm。
- 恢复时核对 PendingAction 的 created_at，避免数据库恢复或测试库重建后重复 ID 误接历史 Checkpoint。

## 部署与配置

`pip install -e .[test]` 安装已验证的依赖版本：LangChain 1.4.4、langchain-openai 1.7.0、LangGraph 1.2.14、langgraph-checkpoint-sqlite 3.1.1。

沿用 `AGENT_PROVIDER` / `AGENT_MODEL` / `AGENT_API_KEY` / `AGENT_BASE_URL` / `AGENT_TIMEOUT`。真实密钥仅在本地 env，不提交。新增 `AGENT_CHECKPOINT_PATH` 不包含凭据。

Dockerfile 预先创建并授权 agent_data 目录，避免非 root 用户挂载新 volume 后无法写入。容器持久化目录与回单、Chroma 分开。

## 原迁移阶段验证记录与限制（历史，不代表当前发布状态）

最终验证：完整工作树 **485 passed**；仅包含提交范围的独立快照 **476 passed**（另9项未提交 Compact Demo 测试不在快照内）。本轮新增37项模型适配、行为等价、Checkpoint、API、HITL和隔离测试全部通过，未删除原测试。

独立快照前端类型检查/build **PASS**，测试 **38 passed**；完整工作树前端 build **PASS**、测试 **48 passed**（另10项 Dashboard 测试未进入本轮提交）。大型 bundle 警告保留，不伪称无警告。

Docker 后端镜像重建并部署成功，backend/frontend/mysql healthy。使用真实 AsyncSqliteSaver 写入一个独立的框架持久化探针，后端非root用户可写 volume；重启后恢复 interrupt 并 resume 成功。这是持久化验证，不是伪造的模型回答或真实模型 E2E。

独立 MySQL 8.4 空库实际 001→24 升级成功，current=heads=20261010_24；10项真实数据完整性探针通过并回滚。历史 `alembic check` **FAIL** 保留，详见 [SCHEMA_DRIFT_BASELINE.md](SCHEMA_DRIFT_BASELINE.md)，没有通过忽略比较掩盖差异。

真实模型与浏览器端到端：**NOT VERIFIED**。配置项存在，但安全审批拦截了向已配置外部模型发送 Demo 工具结果的探针；正在等待明确的数据发送授权，没有绕过限制或发出该探针调用。当前自动化模型适配测试采用确定性假客户端/HTTP 测试传输，不冒充真实模型联调。因此本轮不宣称全部架构升级最终验收完成。

当前 SQLite Checkpoint 面向单实例 Demo（可多进程，文件在同一主机/volume）；不宣称具备跨主机集群 Checkpoint 高可用。扩展多副本部署时应换用受支持的共享持久化后端，做好备份、权限与保留周期。不要把一个业务库的 Checkpoint volume 移接到另一业务库。框架持久化支持审批恢复，不提供任意失败业务写操作的自动重试；业务状态冲突仍必须由人处理。

保留 `OpenAICompatibleModelClient` 是因为 AI 需求解析仍使用其受控 HTTP 客户端及兼容性测试；它不是遗留 Agent 调度循环。Agent 的旧 while 调度循环已经清除，只有 StateGraph 执行路径。

参考：[LangGraph interrupt](https://reference.langchain.com/python/langgraph/types/interrupt)、[LangChain bind_tools](https://reference.langchain.com/python/langchain-openai/chat_models/base/BaseChatOpenAI/bind_tools)。
