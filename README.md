# 物流车辆智能分配系统

面向物流调度、司机配送执行和 AI 辅助决策的完整业务 Demo / 内部测试版。系统以真实 MySQL、FastAPI 与 Vue 管理端运行，核心规则仍由可测试的 Service、Repository 和约束模块负责，Agent 不绕过业务层直接修改数据库。

详细后端设计见 [backend/README.md](backend/README.md)，固定演示步骤见 [docs/项目演示流程.md](docs/项目演示流程.md)，RAG 设计见 [docs/RAG_DESIGN.md](docs/RAG_DESIGN.md)。

## 核心业务

- 地形、线路、门店、车型、车辆和每日出勤维护；
- 配送需求、货物分类、优先级、常温/冷藏/冷冻要求与车辆运输能力；
- 自动派车 V1、逻辑多趟、未分配原因、同日多版本；
- DRAFT 人工调整、发布前全量校验、发布和取消；
- Driver API：今日任务、开始配送、逐店到店、签收/失败、图片回单和整趟完成；
- 每日异常工作台：方案内未分配、方案外待计划、车辆异常和配送失败停靠点；
- JWT、Refresh Token、RBAC、任务 ownership 与 Audit Log；
- Agent Phase 1 只读查询、Phase 2 Pending Action / HITL、Phase 3 企业知识库 RAG。

## 技术栈

- Backend：Python 3.12、FastAPI、SQLAlchemy 2、Pydantic 2、Alembic
- Database：MySQL 8.4
- Frontend：Vue 3、Vite、TypeScript、Element Plus、Vue Router、Pinia、Axios
- Agent：OpenAI-compatible Tool Calling、Conversation、Pending Action / HITL
- RAG：OpenAI-compatible Embedding、Markdown 知识文档、Chroma
- Deployment：Docker Compose、Nginx、Docker Volume
- Test：pytest

## 系统架构

```text
Vue 管理端 / Driver API / Agent
              ↓
         FastAPI Router
              ↓
            Service
              ↓
          Repository
              ↓
            MySQL
```

自动派车位于 `backend/app/dispatch_engine/`，统一合法性规则位于 `backend/app/domain/constraints/`。

Agent 调用链：

```text
Vue → Agent API → AgentService → ModelClient → Tool Call
→ Registry → Executor → Service → Repository → DB
→ Tool Result → LLM → Response
```

RAG 调用链：

```text
Markdown → Chunk → Embedding → Chroma
用户问题 → search_knowledge_base → Retriever → 引用片段 → LLM
```

写操作不会由模型直接执行：

```text
LLM 提议 → Pending Action(PENDING) → 用户确认
→ RBAC 与业务状态二次校验 → 原业务 Service
→ Database + Audit Log 原子提交
```

## 业务演示流程

```text
登录 → RBAC → 基础资料 → 车辆出勤 → 配送需求
→ 自动派车 → 方案详情 → 人工调整 → 发布
→ Driver 配送与回单 → 每日异常 → Audit Log
→ Agent 只读查询 → RAG → Pending Action → 人工确认
```

## 权限角色

| 角色 | 权限 |
|---|---|
| `ADMIN` | 全部后台能力、用户权限和审计日志 |
| `DISPATCHER` | 每日运营、派车、调整、发布和配送执行 |
| `VIEWER` | 后台只读和 Agent 只读查询 |
| `DRIVER` | 仅访问 `/api/driver/*`，只能处理绑定车辆的任务 |

后端是最终权限边界；前端隐藏按钮仅改善操作体验。

## Docker 启动

复制配置模板，在本地 `.env` 填写数据库密码、JWT Secret、模型和 Embedding 配置。不要提交真实密钥。

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

默认地址：

- 管理端：`http://127.0.0.1/`
- Backend：`http://127.0.0.1:8000`
- OpenAPI：`http://127.0.0.1:8000/docs`

Backend 启动时自动执行 `alembic upgrade head`。

## Migration

当前共 18 个 migration，唯一 head：

```text
20261001_18
```

关键尾部链路：

```text
20260930_15 → 20260930_16 → 20261001_17 → 20261001_18
```

```powershell
cd backend
python -m alembic upgrade head
python -m alembic current
python -m alembic heads
```

## 测试与构建

```powershell
cd backend
python -m pytest -q

cd ../frontend
npm run build
```

稳定版候选验证结果：

```text
Backend: 295 passed, 1 warning
Frontend: build PASS
Docker: backend/frontend/mysql healthy
Alembic: current == heads == 20261001_18
RAG: 4 documents / 19 chunks, persistence PASS
```

## 当前限制

- 自动派车 V1 不保证数学全局最优，也不计算实时路况、真实返仓时间和跨趟时间冲突；
- 危险品和易碎品尚无独立运输规则；
- RAG 只读取 Markdown，暂不支持 PDF、reranker 和增量更新，向量库为单机 Chroma；
- 回单使用本地 Docker Volume，暂无云 OSS 生命周期管理；
- Driver 后端已完成，微信小程序真机验收仍未完成，不能标记为通过；
- Agent 在线能力依赖外部模型/Embedding 服务和配额，普通物流业务不依赖模型。

后续增强项统一记录在 [docs/FUTURE_IMPROVEMENTS.md](docs/FUTURE_IMPROVEMENTS.md)。
