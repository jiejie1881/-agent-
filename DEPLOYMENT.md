# Docker Compose 部署

## 前置条件

- Docker Engine 或 Docker Desktop
- Docker Compose v2（使用 `docker compose` 命令）

## 配置环境变量

在项目根目录复制模板：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少填写：

- `MYSQL_PASSWORD`
- `MYSQL_ROOT_PASSWORD`
- `DATABASE_URL`
- `JWT_SECRET_KEY`

容器内 MySQL 主机名固定为 `mysql`。`DATABASE_URL` 示例格式：

```text
mysql+pymysql://logistics:<URL编码后的密码>@mysql:3306/logistics_dispatch?charset=utf8mb4
```

`MYSQL_USER`、`MYSQL_DATABASE` 与 `DATABASE_URL` 中的用户名和数据库名必须一致。数据库密码含有 `@`、`:`、`/` 等 URL 保留字符时，需要先进行 URL 编码。

生成 JWT Secret 的一种方式：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`.env` 已被 Git 忽略，不要提交真实密码、JWT Secret 或 API Key。

## 启动

```powershell
docker compose up --build -d
```

启动顺序由健康检查控制：

1. MySQL 启动并通过 `mysqladmin ping`；
2. Backend 自动执行 `alembic upgrade head`，成功后启动 Uvicorn；
3. Backend `/health` 正常后启动 Frontend。

默认地址：

- 前端：`http://localhost`
- 后端：`http://localhost:8000`
- 后端 API 文档：`http://localhost:8000/docs`
- 前端健康检查：`http://localhost/health`
- 后端健康检查：`http://localhost:8000/health`

可通过 `.env` 中的 `FRONTEND_PORT` 和 `BACKEND_PORT` 修改宿主机端口。

## 创建首个管理员

数据库 migration 完成后执行：

```powershell
docker compose exec backend python -m app.scripts.create_user
```

按终端提示输入用户名、密码和角色。

## 检查状态和日志

```powershell
docker compose ps
docker compose logs -f backend
docker compose exec backend python -m alembic current
```

## 数据持久化与停止

MySQL 数据保存在名为 `mysql_data` 的 Docker volume 中。普通停止或重新构建不会删除数据：

```powershell
docker compose down
```

`docker compose down -v` 会删除数据库 volume 和其中的全部数据，只能在明确需要清空数据库时使用。

## 前端 API 路由

浏览器使用同源相对地址 `/api/v1`。Frontend 容器中的 Nginx 把 `/api/` 请求转发到 Compose 网络内的 `backend:8000`，因此浏览器不需要访问 Docker 内部服务名，也不需要额外配置 CORS。
