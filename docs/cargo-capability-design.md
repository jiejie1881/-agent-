# 货物分类与车型运输能力设计

## 1. 功能目标

本版本为单一配送需求增加一种货物分类、配送优先级和可选温控范围，并允许车型声明针对各货物分类的运输能力。自动派车、人工调整和方案发布前校验使用相同的货物兼容与温控规则。

支持的初始分类为 `NORMAL`（常温商品）、`FRESH`（生鲜）、`FROZEN`（冷冻品）、`BULK`（大宗货物）。`URGENT` 是配送优先级，不是货物分类。

## 2. 数据模型

### CargoCategory

| 字段 | 说明 |
| --- | --- |
| id | 主键 |
| code | 唯一业务编码 |
| name | 分类名称 |
| description | 可选说明 |
| is_active | 是否可用于新业务 |
| created_at / updated_at | 审计时间 |

删除接口执行软停用，保留历史需求引用。

### DeliveryDemand

在既有需求上增加货物分类、优先级和温控要求。每条需求仍只表示一种货物，不支持混装或拆单。

### VehicleTypeCargoCapability

| 字段 | 说明 |
| --- | --- |
| vehicle_type_id | 车型 |
| cargo_category_id | 货物分类 |
| is_allowed | 是否允许运输 |
| min_temperature / max_temperature | 该车型对此分类可提供的温区 |

`vehicle_type_id + cargo_category_id` 唯一。温度上下限必须同时为空或同时存在，存在时最低温度不得高于最高温度。

## 3. ER 关系

```text
CargoCategory 1 ─── N DeliveryDemand
CargoCategory 1 ─── N VehicleTypeCargoCapability N ─── 1 VehicleType
VehicleType    1 ─── N Vehicle
DeliveryDemand N ─── 1 DispatchOrder（通过 DispatchOrderDetail）
```

## 4. DeliveryDemand 新字段

- `cargo_category_id`：必填外键；历史数据迁移为 `NORMAL`。
- `priority`：`NORMAL / HIGH / URGENT`，默认 `NORMAL`。
- `requires_temperature_control`：默认 `false`。
- `min_temperature / max_temperature`：温控开启时必填，并满足 `min <= max`。

这些字段属于需求核心字段。需求进入 `PLANNED / PUBLISHED / DELIVERING / COMPLETED / CANCELLED` 后不能通过通用 PATCH 修改。

## 5. VehicleTypeCargoCapability

车型通过整体覆盖接口维护运输能力。没有对应能力记录或 `is_allowed=false` 都视为不兼容。需要温控的需求还要求车型能力温区完整覆盖需求温区。

为兼容历史业务，第 16 个 migration 给所有既有车型增加 `NORMAL` 能力；此后新建车型也会自动获得 `NORMAL` 能力，调度员可再通过能力配置调整。

## 6. Constraint 执行流程

新增两个独立约束：

- `CargoCompatibilityConstraint`：检查车型对货物分类是否有允许记录。
- `TemperatureConstraint`：仅在需求要求温控时检查车型温区是否完整覆盖需求温区。

```text
DeliveryDemand
      ↓
DispatchService
      ↓
Candidate Vehicle
      ↓
Constraint Engine
      ↓
LoadConstraint
TerrainConstraint
RouteConstraint
PeriodConstraint
CargoCompatibilityConstraint
TemperatureConstraint
      ↓
PASS
      ↓
Create Assignment
```

## 7. 自动派车如何使用

`DispatchEngineRepository` 一次加载有效需求、出勤车辆和车型能力。`CandidateBuilder` 在形成候选关系前执行货物兼容与温控约束，不兼容车辆不会进入候选集合。

需求装载排序首先按 `URGENT > HIGH > NORMAL`，相同优先级继续使用既有货量和 ID 排序；车型最低趟次、载重、地形、线路和多趟规则未被重写。

## 8. 人工调整如何使用

`DispatchPlanService.move_demand()` 仍调用统一的 `DispatchValidationService.validate_result()`。目标车辆不支持货物或温区不足时，整个事务回滚，并返回 `CARGO_NOT_ALLOWED` 或 `TEMPERATURE_NOT_SUPPORTED`。

## 9. 发布前校验如何使用

`DispatchPlanPublicationValidator` 对每一趟、每一条需求重新调用统一校验器。车型能力在草稿生成后被修改时，发布会发现并汇总所有货物兼容或温控问题，方案和需求状态不会发生部分更新。

## 10. API 列表

### 货物分类

```text
GET    /api/v1/cargo-categories
GET    /api/v1/cargo-categories/{id}
POST   /api/v1/cargo-categories
PATCH  /api/v1/cargo-categories/{id}
DELETE /api/v1/cargo-categories/{id}   # 软停用
```

### 车型运输能力

```text
GET /api/v1/vehicle-types/{vehicle_type_id}/cargo-capabilities
PUT /api/v1/vehicle-types/{vehicle_type_id}/cargo-capabilities
```

### 配送需求

既有创建、查询和修改接口增加五项运输属性；权限继续沿用 JWT + RBAC。

## 11. 前端页面

- 基础资料新增“货物分类”页面，支持列表、新增、编辑、启用状态维护和停用。
- 配送需求表单支持选择分类和优先级；开启温控后显示并校验温度上下限。
- 车型管理增加“运输能力”配置表格。
- 方案详情的已分配和未分配需求展示分类、优先级和温控范围。

前端校验用于交互提示，后端 Schema、Service、数据库约束和派车 Constraint 才是最终规则边界。

## 12. 测试覆盖

新增测试覆盖：分类创建/重复/停用、温控需求参数校验、两个独立 Constraint、URGENT 优先、冷冻需求只进入兼容车型、人工移动不可绕过、车型能力变化后发布失败。完整回归继续覆盖原有物流、RBAC、Agent 与审计功能。

## 13. 当前限制

- 一条 DeliveryDemand 只能包含一种货物。
- 不支持混装限制、危险品、易碎品、体积、托盘和重量/体积双约束。
- 不支持多温区车辆、实时温度监控、IoT、拆单和部分派车。
- 温控能力按车型配置，不区分同车型下个别车辆的设备差异。

## 14. V2 可扩展方向

后续可在明确业务规则后引入 `DeliveryDemandItem`、车辆实例级设备能力、禁止混装矩阵、重量与体积双容量、温度遥测、冷链告警和多温区车厢。上述能力不属于本版本范围。
