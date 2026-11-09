# 多实例与故障恢复

**同一 Docker 主机共享持久化 PARTIAL。跨主机故障接管 NOT RUN。**

| 场景 | 结论 | 实测 |
| --- | --- | --- |
| 实例 A 创建、B 读取 | PASS | 共享 MySQL 会话和持久化 SSE，其他用户读取及取消 404 |
| 流级取消发往另一实例 | FAIL | 运行中 `/stream/cancel` 返回 `requested=false`，当前活跃任务表为进程内状态 |
| 执行 ID 取消发往另一实例 | PASS（合成模型） | `/executions/{execution_id}/cancel` 写共享取消信号，执行实例实际到达 `CANCELLED` |
| 合成执行实例在首个 token 后崩溃 | PASS（同主机） | B 读到已保存工具与 token 事件，报告 `can_resume=true`、`WORKER_RELEASED` |
| 重启后显式恢复 | PASS（合成模型） | 启动同一隔离容器后调用 `/resume`，HTTP 200、`COMPLETED` |
| 重试同一个流操作键 | PASS | 原跨实例调用以及崩溃后的重试均返回 409 |
| 宕机时重复审批、恢复后重复业务提交和重复记忆写入 | NOT RUN | 本次故障注入使用只读车辆工具，回归和常规记忆验收见对应报告 |

实际命令为 `python docs/evidence/agent-v21-final-closure-20261109/probe_crash_recovery.py`，2026-11-09 11:52 当地时间。探针验证目标标签后只对专用合成实例执行 `docker kill --signal=KILL` 和 `docker start`。第一次重启后的临时端口已变化，探针改为重新读取回环端口后重跑通过。证据见 `crash-recovery-final.json`、`multi-instance.json` 和 `synthetic-browser-result.json`。

最小改造是为流消息到执行 ID 建立持久映射，流取消走已验证的持久取消信号，同时保留进程内立即取消。跨主机需要能原子更新的租约和执行所有权、持久检查点及业务幂等回执。上线迁移需验证旧执行记录可读、租约过期和双持有、未确认写操作不被自动重放、取消和完成竞争、版本回滚。共享卷上的 SQLite 和文件锁仅验证了本机拓扑。
