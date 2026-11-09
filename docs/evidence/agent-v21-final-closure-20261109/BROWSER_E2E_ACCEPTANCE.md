# 浏览器验收

2026-11-09 在本机 Edge 实测。最终构建入口为 `http://127.0.0.1:52206/agent`，仅在验收主机可访问。

| 路径 | 结论 | 实际观察 |
| --- | --- | --- |
| Nginx → API | PASS | 登录、新建会话、SSE 启动和配置不可用错误、刷新恢复列表、另一测试用户看不到该会话 |
| 合成模型侧车 → API → MySQL | PASS | UI 显示真实只读工具结果与分段增量，停止按钮得到取消终态 |
| 实际模型回复、自然语言工具选择、RAG 引用、上下文融合 | BLOCKED | 专用真实调用预算门禁；合成侧车的输出是预置文本 |
| 实际供应商取消与用量 | BLOCKED | 无供应商请求 |

实际命令为 `node backend/tools/v21_closure_browser.cjs` 和 `node docs/evidence/agent-v21-final-closure-20261109/synthetic_browser.cjs`，通过本地 Playwright 控制已安装的 Edge。测试账号口令只通过进程环境注入。初次刷新断言将登录重定向误当作目标页面，改为精确路径检查后重跑通过。

最终构建证据见 `final-browser/browser-result.json` 及同目录三张通过截图。合成侧车见 `synthetic-browser-result.json`、`synthetic-first-token.png`、`synthetic-cancelled.png`。
