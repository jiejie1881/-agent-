# 货物分类与运输要求

> 本文档仅为系统 Demo 知识，不代表法律或行业强制规范。

## 当前货物分类

当前 Demo 基础分类包含 NORMAL（常温商品）、FRESH（生鲜）、FROZEN（冷冻品）和 BULK（大宗货物）。DeliveryDemand 通过 cargo_category_id 引用分类，还可以设置 NORMAL、HIGH 或 URGENT 优先级。

## 车型运输能力

车型与货物分类之间使用 VehicleTypeCargoCapability 维护明确能力。is_allowed 决定该车型是否可以承运分类；需要温控时，min_temperature 和 max_temperature 说明车型可支持的温度范围。系统不通过 min_load、max_load 或车型 name 字符串猜测运输能力。

## 常温、生鲜、冷冻与大宗

常温货物仍需要显式的车型分类能力。生鲜和冷冻品在需求开启 requires_temperature_control 时，还必须校验温度覆盖。大宗货物需先通过分类能力校验，然后再独立检查单趟最低和最高载重。

## 第一版边界

当前模型已支持货物分类、优先级和温控范围。危险品、易碎品等独立运输规则尚未实现，不应在回答中声称系统已经自动校验这些能力。
