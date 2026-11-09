# 隔离运行态验收

**本轮 V2.1 独立部署 PASS。既有运行环境继续使用旧镜像与迁移。**

- 2026-11-09，Compose 项目 `logistics-v21-closure-20261109`，独立 MySQL、Chroma、SQLite Checkpoint 和 RAG 数据卷。应用端口仅绑定回环。最终前端 `127.0.0.1:52206`，后端 `127.0.0.1:62368`，第二实例 `127.0.0.1:62313`。
- 后端和前端最终镜像的 OCI revision 均为 `49392f272c882ce464f5c4de990f7eb653a0b9f9`。第二实例和合成侧车使用上一轮应用镜像，后续应用代码无改动。
- 新库执行迁移至 `20261108_30 (head)`，后端 readiness 200。OpenAPI 有 SSE 和取消路由，运行态端点源码 SHA-256 为 `c4834d02fd766db431af99f3dc155ac5cce27032d36b2290d23b016275b12d14`。
- 既有后端只读取样本，迁移为 `20261027_29`。本轮部署与故障注入仅针对验收项目。
- 初次 Linux 构建因 Windows CRLF 入口脚本报 `set: Illegal option -`，通过 Git 规则规范 shell 文件。初次前端安装的镜像源域名解析失败，替换锁文件内的 tarball 主机名，版本及完整性值保持一致。
- 实际命令包括 `docker compose --env-file .env.v21-acceptance -p logistics-v21-closure-20261109 -f compose.v21-acceptance.yml up -d --build --wait`、`docker exec logistics-v21-closure-20261109-backend-1 alembic current` 和 `GET /health/ready`。

证据见 `runtime-final.txt`、`runtime-api.json`、本地 `runtime-original.txt` 和 `docker-final-build-up.log`。
