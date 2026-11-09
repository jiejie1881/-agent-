# SSE 与取消验收

| 场景 | 结论 | 本轮观察 |
| --- | --- | --- |
| HTTP SSE 启动、状态、失败终态 | PASS | Edge 经最终 Nginx 路由连接隔离 Agent，收到多个状态与 `error` |
| 工具开始、结果、逐步文本、正常终态 | PASS（合成模型） | Edge 收到真实 MySQL 只读工具 `SUCCEEDED`、3 个独立 `token` 与 `message_complete` |
| 同实例点击停止 | PASS（合成模型） | SSE 终态 `cancelled`，从另一实例读取到持久化 `CANCELLED` |
| 另一实例直接调 `/stream/cancel` | FAIL | 请求在模型仍活跃时到达，返回 `requested=false` |
| 同一操作键重复请求 | PASS | 第二实例请求得到 409 |
| 真实供应商 SSE、取消后停止计费 | BLOCKED | 缺少本轮会话预算，未发起供应商请求 |

结果与截图见 `browser-result.json`、`synthetic-browser-result.json`、`synthetic-first-token.png`、`synthetic-cancelled.png`。执行 ID 取消和故障恢复的结论见 [多实例验收](MULTI_INSTANCE_ACCEPTANCE.md)。
