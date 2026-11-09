# Docker Compose 部署

Stage 4 发布、隔离验收和恢复手册见 [docs/V1_STAGE4_RUNBOOK.md](docs/V1_STAGE4_RUNBOOK.md)。当前默认Compose是开发基线；生产示例覆盖文件为 `deploy/compose.production.example.yml`，仅做配置准备，不能直接作为生产准入批准。生产关闭自动迁移，使用分离的DDL/DML账号；真实模型、HTTPS、企业UAT和告警触达仍需独立验收。Stage 4 结果见 [docs/V1_FINAL_STAGE4_REPORT.md](docs/V1_FINAL_STAGE4_REPORT.md)。

当前源码的正式运行说明见 docs/BUSINESS_OPERATING_GUIDE.md，验收与阻塞见 docs/BUSINESS_SYSTEM_ACCEPTANCE.md。本轮没有升级现有服务或数据库；新前端、后端和迁移必须按同一版本协调发布，不能混用。

Agent 调度员采纳/发布分别由 `AGENT_DRAFT_ACCEPT_DISPATCHER_ENABLED` 和 `AGENT_PLAN_PUBLISH_DISPATCHER_ENABLED` 控制，默认 false，仍需总开关、签名密钥及人工确认。不要将历史验收提案视为生产启用批准。

## 前置条件

- Docker Engine 或 Docker Desktop
- Docker Compose v2（使用 `docker compose` 命令）

## 配置环境变量

在项目根目录复制模板：

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

编辑 `.env`，至少填写：

- `MYSQL_PASSWORD`
- `MYSQL_ROOT_PASSWORD`
- `DATABASE_URL`
- `JWT_SECRET_KEY`

容器内 MySQL 主机名固定为 `mysql`。`DATABASE_URL` 示例格式：

```text
mysql+pymysql://logistics:<URL编码后的密码>@mysql:3306/logistics_dispatch?charset=utf8mb4
```

`MYSQL_USER`、`MYSQL_DATABASE` 与 `DATABASE_URL` 中的用户名和数据库名必须一致。数据库密码含有 `@`、`:`、`/` 等 URL 保留字符时，需要先进行 URL 编码。

生成 JWT Secret 的一种方式：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`.env` 已被 Git 忽略，不要提交真实密码、JWT Secret 或 API Key。

Agent 草稿保存和人工发布使用迁移 `20261013_25`。采纳开关 `AGENT_DRAFT_ACCEPT_ENABLED`、`AGENT_DRAFT_ACCEPT_ADMIN_ENABLED`，发布开关 `AGENT_PLAN_PUBLISH_ENABLED`、`AGENT_PLAN_PUBLISH_ADMIN_ENABLED` 均默认关闭；启用时还需独立的 `AGENT_DRAFT_RECEIPT_SECRET`（至少 32 字节）。Step 11 和 Step 12 已在专用 MySQL 8.4 实例验证迁移、并发与回滚，Step 12 也通过隔离浏览器验证替身模型规划至人工发布。真实模型完整链路和生产准入仍未通过，不应在业务环境开启这些开关；证据见 `docs/STEP12_FINAL_ACCEPTANCE.md`。

## 启动

```powershell
docker compose up --build -d
```

启动顺序由健康检查控制：

1. MySQL 启动并通过 `mysqladmin ping`；
2. Backend 自动执行 `alembic upgrade head`，成功后启动 Uvicorn；
3. Backend `/health` 正常后启动 Frontend。

默认地址：

- 前端：`http://localhost`
- 后端：`http://localhost:8000`
- 后端 API 文档：`http://localhost:8000/docs`
- 前端健康检查：`http://localhost/health`
- 后端健康检查：`http://localhost:8000/health`

可通过 `.env` 中的 `FRONTEND_PORT` 和 `BACKEND_PORT` 修改宿主机端口。

## 创建首个管理员

数据库 migration 完成后执行：

```powershell
docker compose exec backend python -m app.scripts.create_user --username admin --role ADMIN
```

账号和角色通过参数提供，密码及确认密码通过交互输入，不放入命令行或 Git。不要使用公开的测试密码部署对外服务。正式运行包已移除业务演示种子；企业通过管理端录入或导入自身资料。

## 检查状态和日志

```powershell
docker compose ps
docker compose logs -f backend
docker compose exec backend python -m alembic current
```

## 数据持久化与停止

MySQL 数据保存在 `mysql_data` volume；图片回单在 `delivery_proofs`；Chroma 在 `rag_data`；LangGraph SQLite Checkpoint 在 `agent_checkpoints`。Compose 会加项目名前缀，切换项目名可能创建另一套空 volume。普通停止或重新构建不会删除原 volume：

```powershell
docker compose down
```

`docker compose down -v` 会删除数据库 volume 和其中的全部数据，只能在明确需要清空数据库时使用。

## 前端 API 路由

浏览器使用同源相对地址 `/api/v1`。Frontend 容器中的 Nginx 把 `/api/` 请求转发到 Compose 网络内的 `backend:8000`，因此浏览器不需要访问 Docker 内部服务名，也不需要额外配置 CORS。

## Agent / RAG 与配置来源

Compose 使用根目录 `.env` 插值并注入容器。直接 `cd backend` 运行 Python 时，Settings 的 `env_file=".env"` 指向 `backend/.env`，环境变量优先于文件。两个文件不会自动合并；配置一处不能保证另一启动方式可用。

填写模板中的 AGENT_* 和 RAG_EMBEDDING_*，不要公开真实配置。知识库不会随迁移自动构建；确认允许文档发送到配置的 Embedding 服务后执行：

```powershell
docker compose exec backend python -m app.scripts.build_knowledge_base
docker compose exec backend python -m alembic heads
docker compose exec backend python -m alembic check
```

当前 head 为 `20261014_27`。新 checkout 不包含本机的 MySQL、回单、Chroma 或 Checkpoint 内容，需要自己的凭据和业务资料。备份应覆盖业务库、图片和对应 Checkpoint，避免把一套数据库的审批状态接到另一套库。27 的降级会拒绝仍含自定义车型的库；不得删业务车型制造降级成功。

## 部署边界

当前 Compose 是内部部署基线，尚未通过公网生产准入。端口映射默认可能监听所有宿主机网卡，应限制本机或受控网络；公网使用需要 TLS、访问限制、监控、备份和单独安全审查。`/docs` 与 `/openapi.json` 默认公开，用户管理接口有 ADMIN 校验；`/health` 验证应用响应，`/health/ready` 验证数据库连接，均不验证模型。最新准入差距见 docs/BUSINESS_SYSTEM_ACCEPTANCE.md。

Nginx API 读取超时设为 130 秒，长于 Agent 页面 120 秒的请求超时；真实慢请求、连接中断和重试恢复仍需部署环境验收。不要把日志、SQL_ECHO=true 的输出或本地账号文档上传 GitHub。
