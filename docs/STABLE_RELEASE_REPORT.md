# Stable Release Report

## Version

版本候选：`v1.0.0-rc1`

报告日期：2026-10-08（Asia/Shanghai）

## Git commits

| 功能 | Commit |
| --- | --- |
| Cargo / Cold Chain | `c11bfe7 feat(cargo): add cargo transport capabilities` |
| Driver / Delivery Proof | `a283cc6 feat(driver): add delivery stop status and proof foundation` |
| Daily Exception | `87eb217 feat(dispatch): add daily exception workbench` |
| Agent Phase 3 RAG | `080a10c feat(agent): add enterprise RAG knowledge base` |

以上提交均在本地 `main`，未 push、未打 tag。

## Migration

尾部链路：

```text
20260930_15 → 20260930_16 → 20261001_17 → 20261001_18
```

- 唯一 head：`20261001_18`；
- 真实 MySQL：`current == heads == 20261001_18`；
- 临时 SQLite：空库 upgrade 到 18、downgrade 到 16、再次 upgrade 到 18，PASS；
- 未在真实开发 MySQL 上执行 downgrade。

## Backend

- Cargo 专项：`6 passed`；
- Driver / Delivery Proof 专项：`33 passed, 1 warning`；
- Daily Exception 专项：`15 passed, 1 warning`；
- Agent + RAG 专项：`43 passed, 1 warning`；
- 当前提交快照完整测试：`295 passed, 1 warning`。

现存 warning 为测试依赖的 Starlette/httpx 弃用提示，不是业务失败。

## Frontend

- `npm run build`：PASS；
- Vite 仅报告大 chunk 建议，不影响构建产物生成；
- 当前没有配置 lint script。

## Docker

- MySQL：healthy；
- Backend：healthy；
- Frontend：healthy；
- Backend 启动迁移正常，不再出现无法定位 `20261001_18`；
- 健康检查、登录、基础资料、配送需求、方案查询、每日异常和 Agent 会话 smoke test：PASS；
- 自动派车、发布、Driver 与 Agent 写操作路径在 OpenAPI 中存在，核心行为由自动化测试覆盖；
- Driver 临时 JWT 只读 profile：HTTP 200；无凭证访问：HTTP 401。

## Cargo / Cold Chain

- 货物分类、优先级、温控要求和车辆运输能力：PASS；
- 自动派车、人工调整和发布前校验复用统一货物能力约束：PASS；
- 危险品、易碎品独立运输规则尚未实现。

## Driver / Delivery Proof

- DRIVER 角色、车辆一对一绑定、任务 ownership：PASS；
- 停靠点 `PENDING / ARRIVED / SIGNED / FAILED`：PASS；
- 图片类型、大小、UUID 文件名、最多 3 张和 Docker Volume：PASS；
- 未完成停靠点时禁止完成整趟：PASS；
- 微信司机端代码实现及后端接口集成：已完成；生产发布因平台认证与上线流程暂缓，开发者工具/真机验收为 `NOT INCLUDED IN CURRENT RELEASE ACCEPTANCE`，不阻塞当前 Stable Demo。

## Daily Exception

- 方案内未分配、方案外待计划、车辆异常和配送失败停靠点：PASS；
- `PUBLISHED` 优先，没有时使用有效 `DRAFT`：PASS；
- 2026-10-03 自动选择 V3 `PUBLISHED`（方案 #14），不受 V1 `CANCELLED`（#3）和 V2 `DRAFT`（#4）污染：PASS；
- 手动查询取消方案显示历史标识：PASS；
- API 失败时页面不白屏、loading 结束、不保留旧报告，恢复后可重载：PASS。

## Agent

- Phase 1 只读 Tool / Conversation：PASS；
- Phase 2 Pending Action / HITL：PASS；
- `move_delivery_demand` 和 `cancel_dispatch_plan` 未确认时不写数据库：PASS；
- 执行时重新检查 RBAC、ownership 和业务状态：PASS；
- Agent Tool 继续复用 Service / Repository，不直接绕过业务层。

## RAG

- Real Embedding：PASS（此前真实端到端验证）；
- Documents：4；
- Chunks：19；
- Retriever：PASS；
- Pure RAG：PASS；
- Pure Business Tool：PASS；
- Mixed Tool Calling：PASS；
- HITL Regression：PASS；
- Vue E2E：PASS；
- Chroma named volume 读取：PASS；
- Backend 容器重启后仍为 4 documents / 19 chunks：PASS。

本轮稳定版收口没有重复消耗外部模型额度，也没有伪造在线模型结果。

## Security

- 高风险 API Key / Private Key 模式扫描：0；
- 禁止跟踪文件检查：0；
- 根 `.env`、`backend/.env`：ignored；
- `miniprogram/project.private.config.json`：ignored；
- `backend/rag_data/`：ignored；
- `backend/uploads/` 实际图片：ignored，仅 `.gitkeep` 可跟踪；
- `node_modules`、`dist`、缓存：ignored；
- `git diff --check`：PASS。

## Documentation

- 根 `README.md`：稳定版入口、架构、流程、启动和限制；
- `backend/README.md`：迁移 18、Cargo、Driver、Daily Exception、Agent 与 RAG；
- `docs/项目演示流程.md`：固定演示顺序和人工验收证据；
- `docs/RAG_DESIGN.md`：架构、安全边界、配置和真实验证记录；
- `docs/FUTURE_IMPROVEMENTS.md`：冻结后的增强项清单。

## Known limitations

- 自动派车 V1 不计算实时路况、真实返仓时间和跨趟时间冲突；
- 危险品、易碎品独立运输规则未实现；
- RAG 不支持 PDF、增量更新和 reranker，使用单机 Chroma；
- 回单仍使用本地 Docker Volume，未接入 OSS；
- 微信小程序生产发布暂缓，开发者工具/真机验收不属于当前 Stable Demo 发布范围；
- 外部模型和 Embedding 受网络与配额影响，普通物流业务不依赖模型。

## Release verdict

`READY FOR STABLE DEMO`

核心代码、迁移、测试、构建、Docker、RAG 持久化、安全边界和 Demo 文档均已达到稳定演示候选要求。建议用户确认本报告后再创建 `v1.0.0-rc1` 标签；本轮不创建、不推送标签。
