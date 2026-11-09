# V2.1 验收结果

工程交付：PARTIAL。隔离前端交互演示：已验证；真实模型完整演示：BLOCKED。生产准入：NO-GO。

已执行证据：targeted-latest.log（92通过；为一次集合，不与历史91/78/11批次相加）、frontend-final-tests.log（152通过，0失败/跳过）、frontend-build-final.log（含vue-tsc与生产构建）、browser-cancelled.png（隔离合成模型浏览器验收）、mysql-acceptance.json（独立MySQL 8.4.11与Chroma专项通过）。

后端完整回归先执行900秒上限的首段，再继续未完成用例。按当前收集的1685个精确节点ID去重，1589通过、24失败、51个setup错误、21跳过；没有缺失结果。原始1704次记录包含18次重复及1个已被参数化替代的旧节点，均没有直接相加。详见TEST_SUMMARY.json、backend-full.log、backend-remaining.log及backend-remaining.xml。

保留原始失败不覆盖：其中5项答案合约在提供规定的evidence临时路径后复测通过（contracts-isolated.log）；4项本地SDK协议测试补充预算层要求的稳定operation_id后复测通过（loopback-recheck.log）。其余包括14项Windows O_NOATIME/链接权限相关取证失败和1项历史显式opt-in浏览器服务测试失败。51个RAG Batch2 setup错误均依赖专用batch2_guard_attestation executor，普通pytest缺失该fixture；没有用空fixture绕过保护。数据库旧MySQL身份执行器/进程重启等跳过项仍未作为PASS计入。

| 项目 | 结果 | 证据/边界 |
|---|---|---|
| 原生Function Calling / 多工具 | PARTIAL | 专项与SQLite工具闭环通过，真实模型未验收 |
| 多轮上下文 | PARTIAL | 后端历史/分页、既有会话测试；未做完整真实业务场景 |
| 长期记忆融合 | PARTIAL | 当前Outbox修复、11项单元/接口及独立MySQL+Chroma专项通过；真实模型融合未验收 |
| SSE / 工具状态 / 取消 | PARTIAL | 增量专项及实际页面完成、取消；RAG非逐Token、多实例未验收 |
| 超时 / 重试 / 恢复 / 幂等 / RBAC | PARTIAL | 沿用既有保护并有专项；新HTTP操作幂等，分布式未验收 |
| Trace / Token / 延迟 / 成本 | PARTIAL | 本地事件、供应商usage解析、显式价格计算；真实供应商和远端Trace未验收 |
| 前端联调 | PARTIAL | 真实页面+真实后端+真实LangGraph，模型合成且业务库为空 |
| 原有物流业务全回归 | PARTIAL | 1685个节点去重结果如上，保留失败/错误/跳过 |

没有将本地测试PASS等同于生产就绪，也未重用历史81.2%完成度。
