# 物流调度管理系统

面向企业基础资料、每日调度、司机配送和业务审计的内部管理系统。企业从空库录入或导入自己的资料；正式应用不再提供固定场景、虚构数据种子或匿名派车演示入口。

当前版本的实施和验收范围见 [正式业务验收报告](docs/BUSINESS_SYSTEM_ACCEPTANCE.md)；生产准入状态以 [项目状态](docs/PROJECT_COMPLETION_STATUS.md) 为准。真实模型与微信真机未验收，不能据代码和替身模型测试宣布生产就绪。

## 业务能力

- 门店地址、联系人、经纬度、配送区域、启停及多线路关联。
- 人工维护线路起终点、地理说明、地形有效期、车型通行许可；距离和时间必须注明来源。
- 自定义车型编码与载重范围；车辆组织、额定载重、运行状态、司机绑定、允许线路、每日趟次上限。
- CSV/XLSX 空白模板、上传校验、持久化预览、人工确认、整批事务、幂等及导入历史。
- 司机账号、出勤、排班、请假审批和确认代班。
- 配送需求、传统贪心派车、未分配原因、草稿调整、校验发布及历史版本。
- Agent 基于数据库快照生成候选；后端独立校验、签名采纳、人工调整和确认发布。所有写入开关默认关闭，管理员与调度员分别授权。
- 司机归属权限、任务开始、到店、签收/失败、回单上传/补传/审核、任务完成和历史查询。
- 每日异常事实、回单异常、状态冲突及有责任人、版本和审计的处理工单。
- JWT、RBAC、审计、Agent 问答、RAG 和人工审批 HITL。

## 架构

```text
Vue 管理端 / 微信司机端 / Agent
              ↓
         FastAPI Router + RBAC
              ↓
Service + 确定性业务规则 + 事务与审计
              ↓
          Repository
              ↓
           MySQL 8.4
```

Agent 工作流使用 LangGraph；模型仅提出候选，业务写入由后端执行。问答审批 Checkpoint 使用 SQLite，业务与审批记录使用 MySQL，不构成分布式原子事务。

## 从空库开始

1. 按 [部署说明](DEPLOYMENT.md) 建立专属环境，填写自己的密钥和数据库账号。启动只执行迁移，不注入业务数据。
2. 创建第一个管理员，登录管理端。密码通过交互输入：`python -m app.scripts.create_user --username <管理员账号> --role ADMIN`。
3. 按 [数据准备说明](docs/BUSINESS_DATA_GUIDE.md) 建立地形、车型和线路通行规则，再录入或导入业务资料。
4. 按 [正式业务操作手册](docs/BUSINESS_OPERATING_GUIDE.md) 设置出勤、创建需求、派车、确认发布、执行配送并处理异常。

本任务没有更新正在运行的服务、迁移现有业务库或启用真实模型。源码改动需经正式发布流程交付。

## 本地验证

在 backend 目录安装项目及测试依赖后运行：

```text
python -m pytest -q -o faulthandler_timeout=30 --junitxml=tmp/backend.xml
python tools/run_business_acceptance.py
python tools/run_step11_isolated_mysql.py
```

两个 MySQL 脚本只创建随机命名、已核验的新实例，并清理自己创建的资源；Docker 必须已经运行。不得将手工脚本指向现有业务库。

在 frontend 目录运行 `npm ci`、`node --test tests/*.test.mjs` 和 `npm run build`。小程序在 miniprogram 目录运行 `node --test tests/*.test.js`；这些测试不能替代微信编译或真机验收。

## 运维边界

- `/health` 为进程存活检查；`/health/ready` 检查数据库连接，不验证模型、对象存储或全部业务。
- 门店地图只显示已录入坐标，没有固定仓库、公共道路规划或自动 ETA。可选 HTTPS 底图服务由部署管理员配置。
- 原业务库、历史记录和本地资料不自动删除；已撤下的演示资料保留在 `docs/archive/retired-demo`，测试夹具保留在 `backend/tests/legacy_support`，均不属于正式业务入口。
- CI 定义位于 `.github/workflows/business-ci.yml`；本地执行结果与远程 CI 首跑状态分别记录。
