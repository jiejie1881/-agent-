# 长期记忆验收

**隔离 MySQL 与原生 Chroma 持久化 PASS。真实模型语义融合 BLOCKED。**

- 在独立库 `logistics_v21_acceptance` 使用两个测试用户。验证用户级 Outbox 处理和向量重建只作用于目标用户，另一个用户的待处理记录与召回保持独立。
- 隔离后端重启后，两名用户分别召回自己的条目。验证更新版本、删除向量投影，以及另一个用户的召回仍可用。
- 在同一隔离 MySQL 服务的独立测试 schema 执行 `pytest backend/tests/test_agent_memory_core.py`，13 例通过。该套与宿主跳过的 13 例重合。
- 存储、索引和重启为实测。使用确定性的合成向量。真实向量语义、模型识别过期与无关记忆、真实业务事实与长期记忆冲突时的回答尚待外部预算门禁。

证据见 `mysql-chroma-prepare.json`、`mysql-chroma-reopen.json`、本地 `mysql-memory-pytest.log` 与 `backend/tools/v21_closure_runtime_probe.py`。
