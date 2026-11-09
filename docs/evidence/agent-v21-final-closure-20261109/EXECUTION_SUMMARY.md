# 执行摘要

执行日 2026-11-09（Asia/Shanghai）。基线为目标 GitHub `main` 的 `0216e94`，从该提交创建独立工作树。应用与测试修复为 `3a150af`、`49392f2`。

| 时间（当地） | 实际执行 | 结果 |
| --- | --- | --- |
| 11:21–11:48 | 初始 `python -m pytest` 后端单进程回归 | 1568 PASS、14 FAIL、67 ERROR、25 跳过。保留独立基线记录 |
| 11:24 起 | `npm ci`、`node --test tests/*.test.mjs`、`npm run build` | 152 PASS，类型检查、构建 PASS；首次安装的镜像域名解析失败，修复后重跑 |
| 11:41–11:48 | `python -m pytest` 四组不重叠文件清单，独立 `--basetemp`、JUnit 和重放输出目录 | 1586 PASS、25 跳过、0 FAIL、0 ERROR；5 个通过子测试单列 |
| 11:41 | 用原有强制保护执行器运行 RAG Batch2，用受限 Linux 容器和 Landlock 执行取证测试 | 51 + 24 PASS，和宿主四组不重叠 |
| 11:40 | 隔离 MySQL 专用 schema 与原生 Chroma 的 `test_agent_memory_core.py` | 13 PASS，替换宿主的同名 13 个跳过 |
| 11:46–11:49 | 最终镜像就绪检查、Alembic、真实 Edge 回归 | V2.1 迁移到 head，页面验证通过 |
| 11:52 | `python probe_crash_recovery.py` | 持久执行 ID 取消、进程崩溃后读取日志、拒绝重复流操作、重启后显式恢复均通过 |

最终后端共 1674 PASS，12 个仍跳过。跳过原因和节点见 `BACKEND_TEST_SUMMARY.json`。其中 7 个需要身份确认的专用 MySQL 执行器，3 个依赖未归档的 Stage 7 证据，1 个需要专用临时浏览器服务，1 个需要经审阅的双进程执行器。另有专项 149 PASS、依赖修复定向 93 PASS，均与最终用例重叠。

四组原始终端日志、JUnit、用例清单、隔离运行记录保存在本地证据目录。分支收录结果、可复跑脚本和通过截图。
