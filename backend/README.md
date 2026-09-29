# 物流车辆智能分配系统后端

## 1. 项目简介

本项目是物流车辆智能分配系统的后端服务，使用 FastAPI、SQLAlchemy、MySQL 和 Alembic 构建。

当前版本已经形成后端业务 V1 闭环：维护基础资料和每日业务数据，使用贪心策略生成派车草稿，保存同日多版本方案，支持人工调整、发布前重新校验、方案发布，以及配送任务的开始和完成。

系统已加入 JWT 登录和 RBAC。角色包括 `ADMIN`、`DISPATCHER`、`VIEWER`；所有 `/api/v1` 业务接口均由后端校验登录状态和权限。

自动派车 V1 强调规则正确、结构清晰和可维护性，不保证数学意义上的全局最优。目前不计算真实道路距离、行驶时间、返仓时间和路况。

主要技术栈：

- Python 3.11+
- FastAPI
- SQLAlchemy 2.x
- Pydantic 2.x
- MySQL + PyMySQL
- Alembic
- pytest

所有业务 API 默认使用 `/api/v1` 前缀。健康检查为 `GET /health`，OpenAPI 文档为 `/docs`。

## 2. 当前业务流程

```text
维护地形、线路、门店、车型和车辆
        ↓
配置门店线路、线路生效地形、车型地形权限
        ↓
录入指定日期的车辆出勤
        ↓
录入上午/下午门店配送需求（PENDING）
        ↓
执行自动派车
        ↓
生成并持久化 DRAFT 方案版本，已分配需求进入 PLANNED
        ↓
可选：在 DRAFT 方案内人工移动需求并重新校验
        ↓
发布前基于当前业务数据执行全量校验
        ↓
发布方案（PUBLISHED），需求进入 PUBLISHED
        ↓
按 DispatchOrder 开始配送，需求进入 DELIVERING
        ↓
按 DispatchOrder 完成配送，需求进入 COMPLETED
```

无法形成合法车次的需求不会丢失，而是写入当前方案的 `unassigned_demands`，同时保留失败原因。

## 3. 已完成功能

### 基础资料

- 地形维护；
- 线路维护；
- 门店维护；
- 门店与线路多对多关系；
- 按生效日期维护线路地形配置；
- 车型维护，车型身份使用固定 `code`；
- 车型与地形通行权限；
- 车辆维护。

车型编码：

| code | 业务名称 |
| --- | --- |
| `FOUR_METER` | 四米二 |
| `BIG_VAN` | 大包 |
| `SMALL_VAN` | 小包 |

`min_load` 和 `max_load` 是可配置业务参数，不用于识别车型。

### 每日业务

- 每日车辆出勤维护；
- 每日门店配送需求维护；
- 配送时段 `MORNING`、`AFTERNOON`；
- DeliveryDemand 状态机；
- 已进入派车流程的需求核心字段锁定；
- 普通 PATCH 禁止直接修改需求状态。

### 派车与方案

- 独立的自动派车 V1 贪心引擎；
- 单次派车合法性校验接口；
- 同车逻辑多趟；
- 自动派车结果持久化；
- 未分配需求及原因持久化；
- 同一日期多版本方案；
- DRAFT 方案人工移动需求；
- 发布前全量重新校验并聚合返回全部问题；
- 同一天只允许一个 PUBLISHED 方案；
- 发布新版本时处理旧的已发布方案；
- 按任务开始配送、完成配送；
- 关键状态变更和人工调整使用事务。

### 数据库与测试

- 当前共有 12 个 Alembic migration；
- pytest 使用 SQLite 内存数据库，与开发 MySQL 隔离；
- 当前全量测试结果：`91 passed`。

### 认证与权限

- 密码使用随机盐 PBKDF2-SHA256 保存，不存储明文密码；
- 登录成功返回带有效期的 HS256 Access Token 和 Refresh Token；
- 密码、角色或启用状态发生安全变更后，旧 Token 立即失效；
- ADMIN 可管理用户、角色和启用状态，所有用户可修改自己的密码；
- `ADMIN` 可执行全部操作；
- `DISPATCHER` 可维护每日出勤和配送需求，并执行自动派车、人工调整、发布及配送状态操作；
- `VIEWER` 只能读取；
- 前端隐藏无权限按钮，后端仍会独立返回 `403 FORBIDDEN`。

### 审计日志

- 核心业务操作在业务事务内同步写入审计日志；
- 记录操作用户及用户名快照、操作类型、业务对象、对象 ID、操作时间和必要变更信息；
- 已覆盖登录、配送需求创建/修改、自动派车、人工调整、方案发布/取消、开始/完成配送、用户及权限修改；
- 业务事务失败时审计记录一并回滚，不会留下成功日志；
- 审计查询接口和前端审计页面仅允许 `ADMIN` 访问；
- 密码、密码哈希和 Token 不写入审计变更信息。

## 4. 项目目录结构

```text
backend/
├── alembic/
│   ├── env.py                         # Alembic 运行环境
│   └── versions/                      # 12 个数据库迁移版本
├── app/
│   ├── api/
│   │   ├── dependencies.py            # FastAPI 数据库依赖
│   │   ├── exception_handlers.py      # 统一业务异常响应
│   │   └── v1/
│   │       ├── router.py              # V1 路由汇总
│   │       └── endpoints/             # Controller/API 层，只处理请求响应
│   ├── core/
│   │   └── config.py                  # 环境变量和应用配置
│   ├── dispatch_engine/
│   │   ├── dispatch_engine.py         # 贪心派车流程编排
│   │   ├── candidate_builder.py       # 候选车辆、线路关系构建
│   │   ├── load_optimizer.py          # 整单装载组合
│   │   ├── priority_rules.py          # 车型趟次和优先级规则
│   │   ├── models.py                  # 引擎输入输出模型
│   │   └── constraints/               # 引擎内部候选约束
│   ├── domain/
│   │   ├── constraints/               # 可复用统一派车约束
│   │   ├── dispatch_validator.py      # 统一约束执行器
│   │   ├── enums.py                   # 业务枚举
│   │   └── exceptions.py              # 业务异常
│   ├── infrastructure/database/
│   │   ├── base.py                    # SQLAlchemy Base
│   │   └── session.py                 # Engine 和 Session
│   ├── models/                        # SQLAlchemy 数据库模型
│   ├── repositories/                  # 数据库访问层
│   ├── schemas/                       # Pydantic 请求响应模型
│   ├── services/                      # 业务逻辑、事务和状态控制
│   └── main.py                        # FastAPI 应用入口
├── tests/                             # API、Service、约束和引擎测试
├── .env.example                       # 环境变量示例
├── alembic.ini                        # Alembic 配置
├── pyproject.toml                     # 依赖与 pytest 配置
└── README.md
```

分层约定：

- API 层只负责接收参数和返回响应；
- Service 层负责业务规则、状态转换和事务；
- Repository 层负责数据库查询与持久化；
- `dispatch_engine` 是不直接访问数据库的派车计算模块；
- 可复用的派车合法性规则集中在 `domain/constraints`。

## 5. 核心数据模型

| 模型 | 主要职责与关系 |
| --- | --- |
| `Terrain` | 地形基础资料 |
| `Route` | 配送线路 |
| `RouteTerrainConfig` | 线路按 `effective_date` 生效的地形配置；同一线路同一天唯一 |
| `Store` | 门店基础资料 |
| `StoreRoute` | 门店与线路多对多关联 |
| `VehicleType` | 车型身份、最低/最高载重量 |
| `VehicleTypeTerrainPermission` | 车型对地形的通行权限 |
| `Vehicle` | 车辆及其车型 |
| `VehicleAttendance` | 车辆指定日期是否出勤；日期和车辆唯一 |
| `DeliveryDemand` | 门店指定日期、时段的配送需求；日期、门店、时段唯一 |
| `DispatchPlan` | 指定配送日期和版本的派车方案 |
| `DispatchOrder` | 方案中的单车、单时段、单趟、单线路任务 |
| `DispatchOrderDetail` | 任务与配送需求的分配明细及数量 |
| `DispatchPlanUnassignedDemand` | 当前方案未分配的需求及失败原因 |

派车方案关系：

```text
DispatchPlan
├── DispatchOrder
│   └── DispatchOrderDetail ── DeliveryDemand
└── DispatchPlanUnassignedDemand ── DeliveryDemand
```

`DispatchOrder` 通过 `(plan_id, vehicle_id, period, trip_no)` 保证同一方案内逻辑车次唯一。

## 6. 派车规则

### 统一硬约束

一次车辆、需求、线路、时段和货量组合必须同时满足：

1. 车辆在需求日期存在出勤记录且 `available = true`；
2. 需求时段与派车时段一致；
3. 所选线路在配送日期存在已生效的地形配置；
4. 车辆车型拥有该地形的通行权限；
5. 门店属于所选线路；
6. 车型参数满足 `min_load > 0`、`max_load > 0`、`min_load <= max_load`；
7. 每趟实际载重满足 `min_load <= load <= max_load`。

`POST /api/v1/dispatch-validations` 会执行统一约束并返回所有约束结果，而不是只返回第一个失败原因。

### 自动派车 V1

- 按 `MORNING`、`AFTERNOON` 顺序分别处理；
- 只加载当天可出勤车辆；
- 自动派车读取当天 `PENDING` 需求，以及由同日 DRAFT 方案占用的 `PLANNED` 需求，因此生成 V2/V3 时可以重新计算旧草稿中的有效需求；
- `PUBLISHED`、`DELIVERING`、`COMPLETED`、`CANCELLED` 不进入新草稿计算；
- 门店可以关联多条线路，引擎根据当前生效地形和车型权限构建候选组合；
- 单条需求当前不可拆分，但同一车次可以合并多个完整需求；
- 装载使用按需求货量降序的 first-fit 贪心组合；
- 无法达到车辆最低载重量时不生成该趟；
- 任何车次不得超过车型最高载重量；
- 同一个需求在一次计算中只会被分配一次；
- 无法分配的需求进入 `unassigned_demands`。

### 车型趟次优先级

当前目标趟次按“配送时段 + 车型”统计，不是按单辆车统计：

| 车型 | 每个时段目标趟次 |
| --- | ---: |
| 四米二 `FOUR_METER` | 1 |
| 大包 `BIG_VAN` | 1 |
| 小包 `SMALL_VAN` | 2 |

未满足目标趟次时，车型优先顺序为：大包、小包、四米二。所有车型目标满足后，剩余合法方案优先顺序为：四米二、大包、小包。

目标趟次不是最大趟数。如果仍有可组成合法载重的需求，车辆可以继续生成后续逻辑趟次。

### 人工调整

当前支持将一个 `DeliveryDemand` 从 DRAFT 方案中的原任务移动到目标任务。移动前会重新检查目标车辆出勤、时段、地形、线路和载重，同时检查原任务移出后是否低于最低载重量。任何一步失败都会回滚。

当前不支持通过人工调整接口新建任务、删除任务、整车换车或整条线路替换。

### 发布前最终校验

DRAFT 发布前会基于当前数据库数据重新检查每一个任务和明细：

- 车辆当前出勤状态；
- 时段；
- 地形权限；
- 门店线路关系；
- 车型载重参数；
- 明细实际合计的最低/最高载重；
- `DispatchOrder.total_load` 与明细合计；
- 跨任务重复需求；
- 需求日期和需求状态。

所有问题会聚合到同一个 `issues` 列表返回。只要存在一个问题，整个发布事务回滚，不会发生部分需求已发布或旧方案已取消的情况。

## 7. 派车方案版本机制

- 每次执行 `POST /api/v1/auto-dispatch` 都会保存一个新的 DRAFT 方案；
- `version` 按 `delivery_date` 独立递增；
- 某日期第一次生成是 V1，第二次是 V2；不同日期重新从 V1 开始；
- 历史方案、任务、明细和未分配记录保留，可按日期和版本查询；
- 同一天可以有多个 DRAFT 或 CANCELLED 版本；
- 同一天只能有一个 PUBLISHED 版本，数据库也通过唯一索引保护；
- 发布新方案时，旧 PUBLISHED 方案会转为 CANCELLED；
- PUBLISHED 方案不会被自动派车覆盖；
- CANCELLED 方案不能重新发布。

常用接口：

```text
POST /api/v1/auto-dispatch
GET  /api/v1/dispatch-plans
GET  /api/v1/dispatch-plans/by-date/{delivery_date}
GET  /api/v1/dispatch-plans/by-date/{delivery_date}/versions/{version}
GET  /api/v1/dispatch-plans/{plan_id}
GET  /api/v1/dispatch-plans/{plan_id}/unassigned
POST /api/v1/dispatch-plans/{plan_id}/move-demand
POST /api/v1/dispatch-plans/{plan_id}/publish
POST /api/v1/dispatch-plans/{plan_id}/cancel
```

取消 DRAFT 时，仅当需求不再被其他 DRAFT 版本引用，才会从 `PLANNED` 释放回 `PENDING`。这样可以避免取消一个历史草稿时破坏其他草稿对同一需求的版本引用。

## 8. DeliveryDemand 状态机

主业务流程：

```text
PENDING
   │ 自动派车并写入 DRAFT
   ▼
PLANNED
   │ 发布方案
   ▼
PUBLISHED
   │ 开始配送任务
   ▼
DELIVERING
   │ 完成配送任务
   ▼
COMPLETED
```

当前状态机允许的转换：

| 当前状态 | 允许进入 |
| --- | --- |
| `PENDING` | `PLANNED`、`CANCELLED` |
| `PLANNED` | `PENDING`、`PUBLISHED`、`CANCELLED` |
| `PUBLISHED` | `PENDING`、`DELIVERING`、`CANCELLED` |
| `DELIVERING` | `COMPLETED`、`CANCELLED` |
| `COMPLETED` | `CANCELLED` |
| `CANCELLED` | 无 |

状态修改规则：

- 新建需求只能是 `PENDING`；
- 普通 `PATCH /delivery-demands/{id}` 不接受 `status`；
- 自动派车负责进入 `PLANNED`；
- 方案发布负责进入 `PUBLISHED`；
- 开始配送任务负责进入 `DELIVERING`；
- 完成配送任务负责进入 `COMPLETED`；
- `POST /delivery-demands/{id}/cancel` 负责进入 `CANCELLED`；
- 非法状态跳转返回 HTTP 409；
- 只有 `PENDING` 可以修改 `date`、`store_id`、`period`、`quantity`；其他状态修改这些核心字段会返回 `DEMAND_LOCKED_BY_DISPATCH`。

## 9. DispatchPlan 状态

| 状态 | 含义 | 允许的主要操作 |
| --- | --- | --- |
| `DRAFT` | 自动派车生成的草稿 | 查询、人工移动需求、发布、取消 |
| `PUBLISHED` | 已正式发布的方案 | 查询、按任务开始/完成配送；所有关联需求仍为 PUBLISHED 时可取消 |
| `CANCELLED` | 已取消的历史方案 | 仅查询，不能重新发布 |

方案状态与需求状态是两个独立层次：`DispatchPlan` 当前没有 `DELIVERING` 或 `COMPLETED` 状态。配送执行进度记录在方案内各 `DeliveryDemand` 的状态上，因此任务开始或完成后，方案本身仍保持 `PUBLISHED`。

一旦方案中的需求已经进入 `DELIVERING` 或 `COMPLETED`，当前 Service 会拒绝直接取消该 PUBLISHED 方案，避免把执行中的需求错误释放回 `PENDING`。

## 10. 多趟机制

逻辑趟次按以下维度编号：

```text
vehicle_id + delivery_date + period + trip_no
```

在数据库方案内，唯一性由以下字段保证：

```text
plan_id + vehicle_id + period + trip_no
```

当前行为：

- 同一辆车上午可以有 `trip_no = 1、2、3...`；
- 同一辆车下午也从 `trip_no = 1` 重新编号；
- 车辆生成一趟后不会从候选车辆中永久移除；
- 优先选择当前时段已执行趟数较少的同类可用车辆；
- 每一趟独立满足线路、地形、最低载重和最高载重；
- 同一需求不会同时分配给两个趟次；
- 每个 `DispatchOrder` 表示一个独立逻辑车次。

当前多趟是“逻辑多趟”，尚未校验真实出发时间、配送耗时、返仓时间或车次时间重叠。因此结果表示车辆可以完成多趟，但不承诺真实时间上一定可执行。

## 11. 如何启动后端

以下命令以 Windows PowerShell 为例。

### 11.1 创建并激活虚拟环境

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 11.2 安装依赖

开发与测试环境：

```powershell
python -m pip install -e ".[test]"
```

### 11.3 配置数据库

先在 MySQL 中创建数据库和账号，然后复制环境变量示例：

```powershell
Copy-Item .env.example .env
```

修改 `.env`：

```dotenv
APP_NAME=物流车辆智能分配系统
API_V1_PREFIX=/api/v1
DATABASE_URL=mysql+pymysql://logistics:your_password@127.0.0.1:3306/logistics_dispatch?charset=utf8mb4
SQL_ECHO=false
JWT_SECRET_KEY=replace-with-a-long-random-secret
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=480
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
```

### 11.4 启动服务

先执行数据库 migration，再启动：

```powershell
alembic upgrade head
python -m app.scripts.create_user --username admin --role ADMIN
uvicorn app.main:app --reload
```

创建用户命令会在终端中安全提示输入并确认密码。可用角色为 `ADMIN`、`DISPATCHER`、`VIEWER`。必须先执行 migration，再创建第一个管理员。

默认访问地址：

- 健康检查：`http://127.0.0.1:8000/health`
- Swagger UI：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

## 12. 如何执行 migration

当前 migration 链：

```text
20260924_01_initial_master_data
→ 20260924_02_daily_operations
→ 20260924_03_dispatch_validation
→ 20260924_04_dispatch_plan_persistence
→ 20260924_05_delivery_demand_status
→ 20260924_06_vehicle_type_code
→ 20260924_07_dispatch_plan_updated_at
→ 20260924_08_dispatch_plan_single_published
→ 20260924_09_delivery_demand_pending_default
→ 20260925_10_auth_rbac
→ 20260927_11_user_token_version
→ 20260927_12_audit_logs
```

升级到最新版本：

```powershell
alembic upgrade head
```

查看当前版本：

```powershell
alembic current
```

查看迁移历史：

```powershell
alembic history
```

Alembic 使用与应用相同的 `DATABASE_URL`。执行 migration 前应确认 `.env` 指向正确数据库，并在生产环境提前备份。

## 13. 如何运行 pytest

运行全部测试：

```powershell
python -m pytest -q
```

运行单个测试文件：

```powershell
python -m pytest tests/test_dispatch_plan_publish_validation.py -q
```

测试配置位于 `pyproject.toml`，测试夹具会把 `DATABASE_URL` 切换为 SQLite 内存数据库，不会修改开发 MySQL 数据。当前基线为：

```text
91 passed
```

## 14. 当前未完成功能

以下能力当前代码尚未实现：

- 地图服务接入和真实路线计算；
- 配送顺序、距离和路径优化；
- 真实出发时间、配送耗时和返仓时间；
- 多趟任务的时间冲突检查；
- 可拆分需求的派车计算；
- 加急订单和加急调车完整流程；
- 按日期范围、星期和日期优先级配置调度规则；
- 将车型目标趟次改为数据库可配置规则；
- 人工新建/删除派车任务、换车、整单换线路；
- GPS、实时车辆位置和路况；
- 消息通知、导出和打印；
- MySQL 集成测试、并发压力测试和性能优化；
- 生产监控、日志采集和备份恢复方案。

## 15. 后续 Roadmap

### 阶段 A：完善后端业务闭环

- 增加更完整的人工调整能力；
- 增加派车任务执行记录、实际出发和返仓记录；
- 明确方案取消、任务取消和需求取消之间的业务边界；
- 将车型目标趟次、周期规则和日期优先级配置化；
- 增加幂等请求保护和更细粒度的审计查询能力。

### 阶段 B：地图与时间模型

- 接入地图服务；
- 计算门店间距离和预计时间；
- 增加仓库出发、返仓和下一趟装货时间；
- 校验同车多趟时间不重叠；
- 优化线路内门店访问顺序。

### 阶段 C：高级派车

- 支持可拆分需求；
- 支持加急订单和临时调车；
- 引入可配置评分和成本函数；
- 在保留规则可解释性的前提下评估 OR-Tools 等优化方案。

### 阶段 D：前端和生产化

- 继续完善 Vue 3 + Element Plus 调度工作台；
- 增加方案版本对比、人工拖拽调整和校验反馈；
- 增加运行日志、指标和监控告警；
- 增加 MySQL 集成测试、端到端测试和压力测试；
- 完善多环境发布流水线、备份恢复演练和部署回滚方案。

## 16. Docker Compose 启动

项目根目录已经提供 Backend、Frontend 和 MySQL 的 Compose 配置。Backend 容器会在启动 Uvicorn 前自动执行 `alembic upgrade head`；MySQL 数据使用 Docker volume 持久化。

部署时先从根目录 `.env.example` 创建 `.env` 并填写数据库密码、`DATABASE_URL` 和 `JWT_SECRET_KEY`，然后执行：

```powershell
docker compose up --build -d
```

完整配置、安全注意事项、健康检查和管理员初始化步骤见根目录 `DEPLOYMENT.md`。
