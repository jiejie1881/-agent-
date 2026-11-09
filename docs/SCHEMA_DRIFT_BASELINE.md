# 数据库结构差异基线与技术债

## 2026-10-10 P0 修复复核

此前 `alembic check` FAIL 的事实保留在下文。发布修复将 ORM 元数据对齐已经执行的历史 DDL：需求 status/priority 明确 VARCHAR(20)；terrain/route/store/vehicle type/vehicle 业务编码使用独立唯一约束与普通索引；users 保留 migration 010 中的命名唯一约束和唯一索引。

这不是删除约束或忽略比较，也没有修改历史 migration、数据或新增 migration。新增测试从空 SQLite 库实际 upgrade 到 head 后执行 `alembic check`，通过并检查唯一约束；实际 MySQL（当前 Demo 容器）upgrade/current/heads/check 也通过，head 仍为 `20261010_24`，输出 `No new upgrade operations detected.`。用户名的冗余唯一索引/约束暂保留，未来优化需另行迁移。

审查日期：2026-10-10。范围：稳定版 `b3f70e9` 的既有迁移定义，以及待提交 Migration 19～23。

## 当前结论

**`alembic check`：未通过（FAIL，存在历史定义差异）。** 不将迁移升级成功或测试通过等同于此检查通过。

本轮不修改历史 migration，不新增用于修复这些差异的 migration。SQLite 临时空库从 001 升级到 `20261009_23` 成功；`current = heads`。当前演示 MySQL 为 `20261010_24`，本轮对它只读检查，没有回退、重置或清理数据。

## 逐项差异

| 表 / 字段 | 当前模型 | SQLite 迁移库 / 演示 MySQL 实际结构 | 历史来源及原因 | 风险 / 建议 |
|---|---|---|---|---|
| `delivery_demands.status` | `Enum(DeliveryDemandStatus, native_enum=False, create_constraint=True)`，模型 VARCHAR 长度由最长枚举值推导 | `VARCHAR(20) NOT NULL DEFAULT 'PENDING'`；`delivery_demand_status` CHECK 限制六个合法状态；MySQL 另带 `utf8mb4_unicode_ci` 排序规则 | 005 显式选择长度 20 并建立 CHECK；009 设置 PENDING 默认值。模型推导长度与显式长度不同 | 低：当前合法枚举均能完整存储，未发现截断或状态值丢失；后续统一显式长度，保留 CHECK 与数据，不缩短未经扫描的字段 |
| `delivery_demands.priority` | `Enum(DeliveryPriority, native_enum=False, create_constraint=True)` | `VARCHAR(20) NOT NULL DEFAULT 'NORMAL'`；`delivery_priority` CHECK 限制 NORMAL/HIGH/URGENT | 016 显式 VARCHAR(20) + CHECK，模型自动推导枚举长度 | 低：当前合法值均可容纳。后续统一类型长度，不改变优先级含义 |
| `terrains.code` | `unique=True, index=True`：模型使用唯一索引 | 001 创建 code 唯一约束，另创建普通 `ix_terrains_code` 索引；两种方言都确认单列唯一性仍被强制执行 | 001 的“唯一约束 + 普通索引”与 ORM 的“唯一索引”表达不同 | 低：不是唯一性缺失。后续选择统一表达方式，先核查约束名称与方言反射结果，再消除冗余索引 |
| `routes.code` | 同上，`ix_routes_code` 为模型唯一索引 | code 唯一约束 + 普通同名索引；单列唯一性存在 | 001，与 terrains 相同 | 低；同上 |
| `stores.code` | 同上，`ix_stores_code` 为模型唯一索引 | code 唯一约束 + 普通同名索引；单列唯一性存在 | 001，与 terrains 相同 | 低；同上 |
| `vehicle_types.code` | 非原生 VehicleTypeCode 枚举 + 唯一索引 | VARCHAR(10)；code 唯一约束 + 普通 `ix_vehicle_types_code`；单列唯一性存在 | 001 建立唯一约束和索引；006 固定车型身份及代码字段 | 低：三个代码均能容纳；不以载重推断车型。后续统一索引表达并保留枚举 CHECK |
| `vehicles.code` | 唯一索引 `ix_vehicles_code` | code 唯一约束 + 普通同名索引；单列唯一性存在 | 001 的表达方式差异 | 低；统一前先确认既有约束，不先删除唯一保护 |
| `vehicles.plate_number` | 唯一索引 `ix_vehicles_plate_number` | plate_number 唯一约束 + 普通同名索引；单列唯一性存在 | 001 的表达方式差异 | 低；同上，不修改现有车牌数据 |
| `users.username` | `unique=True, index=True`，只声明唯一索引 | 010 同时建立 `uq_users_username` 唯一约束和唯一 `ix_users_username` 索引；两种方言都确认唯一性存在 | 010 冗余建立两种唯一保护；模型不声明额外命名约束，因此 check 提示移除约束 | 低：不属于账号唯一性缺失。后续去重前必须保留至少一种数据库唯一保护，验证大小写及排序规则的账号语义 |

## 方言差异与真实缺陷的区分

- SQLAlchemy 的非原生 Enum 在这两种方言中存为 VARCHAR + CHECK；不是数据库原生 ENUM。长度推导差异属于模型与迁移定义差异。
- SQLite 对唯一约束有自动索引，MySQL 常将唯一约束反射为唯一索引；不能仅凭普通 `ix_*` 的 unique=False 判定失去唯一性，必须同时检查 unique constraints 和 unique indexes。
- MySQL 的 COLLATE 与 CHECK 表达式中的引号、字符集标记不是本次业务缺陷，也未将 SQLite 的反射结果冒充 MySQL 结果。
- 当前未发现上述字段的真实唯一性缺失或非法状态值。当前演示 MySQL 七类唯一键的重复分组数均为 0。
- 本轮只读结构审查不等于所有 MySQL 业务与并发场景已通过；其他数据库实例及未指定生产环境均 **待验证**。

## 验证与边界

1. 独立 SQLite 空库执行完整 migration 到 23；检查单列唯一约束、索引、状态/优先级 CHECK 及默认值。
2. 演示 MySQL 使用 SQLAlchemy inspector 查询同样结构，并 SELECT 汇总重复业务键、状态及优先级；未写入业务数据、未输出账号凭据。
3. Migration 19～23 使用既有整数主键 / 外键与合法状态值；未要求上述 VARCHAR 改为原生 ENUM，也未依赖消失的唯一约束。新增模块没有在 `alembic check` 差异清单中出现新增表或列缺失。
4. 上轮独立前置快照：后端 **432 passed**，前端专项 **38 passed**，类型检查与 build 通过。它们不替代数据库迁移一致性审查。
5. 独立 MySQL 8.4 空库 `agent_upgrade_validation` 已实际执行 001→24，`current = heads = 20261010_24`。七类唯一键重复插入均被拒绝，非法 status / priority 被 CHECK 拒绝，六种合法需求状态可完整写入及读回；共 **10 项探针通过**，全部探针数据事务回滚。五个 demand CHECK 均为 ENFORCED=YES。未写入或删除现有演示库数据。
6. MySQL `alembic check` 实际 **FAIL**：priority/status 类型长度差异、七类业务键“唯一约束 + 普通索引”与模型唯一索引表达差异、users 的额外 username 唯一索引。与上述历史清单一致，未发现 19～24 新增模型缺列/缺表差异。
7. **仍待验证**：生产数据库实例、不同 MySQL 版本、生产排序规则及大小写账号策略、负载下的并发数据完整性。独立测试库的结果不能替代生产验收。

## 后续修复原则

历史债与当前功能提交分开。未来统一元数据时使用新的 migration，先备份并扫描存量值；不修改 001～24 的已执行迁移，不通过关闭 CHECK、忽略所有类型比较或删除测试隐藏问题。若发现任何实例实际缺少唯一保护、CHECK 不生效或存在非法状态，应重新升级为数据安全阻塞，不能沿用本报告的低风险结论。
