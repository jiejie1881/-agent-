# RAG 验收

**原版隔离执行器 51 项通过。** 从历史验收复制 `strict_batch2_worker.py`、`path_boundary.py` 和 `memory_collection.py` 到本轮独立目录。最终执行器副本仅调整输出目录。其 pytest attestation 由审计钩子、路径边界和禁止 SQL、网络、子进程及原生提供方导入的检查支撑。`batch2-final/GUARD.json` 记录实际拒绝动作，JUnit 在 `batch2-final/junit.xml`。

这些用例验证安全边界、版本切换和排名等逻辑，使用原执行器的 Python 向量集合协议。原生 Chroma 的独立验证见长期记忆报告。RAG 与记忆使用不同持久化目录。真实 Embedding、Reranker 和真实模型引用生成仍待完整联合验收。
