# 物流调度后端

Python 3.11+、FastAPI、SQLAlchemy 2、Pydantic 2、Alembic、MySQL 8.4。当前迁移 head 为 `20261014_27`。

## 运行与分层

- `app/api`：登录、RBAC、管理端与独立司机接口。
- `app/services`：业务事务、独立规则校验、导入、异常处理、采纳和人工发布。
- `app/repositories`：权威数据访问与资源锁。
- `app/domain` / `app/dispatch_engine`：约束与传统贪心算法。
- `app/agent`：LangGraph 工作流、模型适配和人工审批。
- `alembic`：保留完整历史迁移；新增字段不会改写已有业务数据。
- `tests` / `tools`：测试夹具及独立验收环境；正式镜像只复制 app，不打包这些替身入口。

## 安装与启动

在独立环境中配置 DATABASE_URL 与 JWT_SECRET_KEY，勿覆盖已有 .env。

```text
python -m pip install -e '.[test]'
python -m alembic upgrade head
python -m app.scripts.create_user --username <管理员账号> --role ADMIN
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

账户密码由交互输入，不放入命令行。数据库启动不注入企业业务资料。

## 正式接口

- `/api/v1/stores`、`routes`、`vehicles`、`vehicle-types`、`terrains`：主数据。
- `/api/v1/business-imports`：空白模板、预览、确认、本人导入记录；主数据导入限 ADMIN，需求导入允许 ADMIN/DISPATCHER。
- `/api/v1/driver-management`：司机与排班；请假、代班和审批维持原有独立流程。
- `/api/v1/delivery-demands`、`vehicle-attendances`、`auto-dispatch`：每日运营。
- `/api/v1/agent/dispatch/shadow`、`accept-draft`：真实数据库候选与签名采纳。
- `/api/v1/dispatch-plans/{id}/agent-move-demand`：内容版本保护的人工调整；传统移动入口继续拒绝 Agent 草稿。
- `/api/v1/dispatch-plans/{id}/agent-publish-preview`、`agent-confirm-publish`：重新校验和人工确认发布。
- `/api/driver`：本人任务、配送、签收/失败、回单和历史。
- `/api/v1/daily-exceptions`、`exception-cases`、`audit-logs`：异常事实、处理工单与审计。

## 安全与事务

Agent 写入仍默认关闭。管理员和调度员的采纳/发布开关分别控制；启用需要测试专用或部署专用的签名密钥。凭据绑定操作者、内容和快照，写入再读权威数据、锁资源、复核并同事务保存审计。不能通过传统接口绕过。

CSV/XLSX 导入限 5MB/1000 行；拒绝错误模板、公式、外部链接和超大解压工作簿。预览不写主数据，确认重新检查引用与唯一键，整批成功或回滚。文件相同且操作者相同的已成功批次返回原结果；重新上传未成功批次会重新校验并更新有效期。

运行检查见 `/health` 与 `/health/ready`。MySQL 连接、读写和连接池等待均有时间边界；数据库冲突和暂不可用返回明确错误，不暴露 SQL 或连接凭据。

## 验证与交付

详见 [正式业务验收](../docs/BUSINESS_SYSTEM_ACCEPTANCE.md)、[数据准备](../docs/BUSINESS_DATA_GUIDE.md)、[操作手册](../docs/BUSINESS_OPERATING_GUIDE.md) 和 [项目状态](../docs/PROJECT_COMPLETION_STATUS.md)。旧设计说明保存在 docs/archive/retired-demo/backend-README-before-business-20261014.md，不能用旧测试数证明当前版本。
