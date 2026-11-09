# 货物分类与温控功能停用验收

## 当前业务

需求不再选择常温、生鲜、冷冻或大宗分类，也不填写温度。保留门店、日期、上午/下午、正数kg货量及已有优先级；线路关系、载重、地形、车辆出勤、司机绑定/请假/正式确认代班继续校验。

重要：派车成功不表示满足冷链、危险品或易碎品运输要求；这些条件当前必须人工核实。

## 检查与处理结果

- 未发现独立 TransportRequirement 实体。旧实现使用需求温控字段与车型分类能力表。
- 删除 CargoCategory 管理 API、Schema、Service、Repository、Vue 页面、API 封装与菜单。
- 删除车型分类运输能力 API、Service、Repository、Schema、Vue 配置对话框。
- 删除需求与任务响应中的分类/温控字段、表单选择、首页分类统计、小程序分类显示。
- 删除 CargoCompatibilityConstraint、TemperatureConstraint；统一校验仅保留原有五类核心约束。司机校验仍由现有 Service 执行。
- 候选构建与数据读取不再加载分类能力；贪心策略、车辆趟次、载重、线路和状态机不变。
- AI 解析及人工批量确认不再提取或提交分类/温度字段，特殊运输文本作为不可自动处理的备注提示。
- Agent 原有查询工具、HITL、权限与审计不变，系统提示明确当前能力边界。
- 更新两份知识文档。RAG 检索会过滤与现有文档不一致的旧分类/温控片段；未自动调用真实 Embedding 重建索引。
- Demo Seed 不再创建分类或车型分类能力，也不需要预置 NORMAL 分类。
- 新评分规则标记 dispatch-quality-v2，历史评分仍保留；不同规则版本不得直接对比分数。

## 数据库安全

新增 migration：`20261010_24_retire_cargo_classification.py`，父版本 `20261009_23`。

只将 delivery_demands.cargo_category_id 改为可空。保留外键、分类表、车型能力表、旧分类与温度值及 ORM 历史映射；不删除需求、任务、签收或回单。

主展示库备份：`docs/local/compact-demo/compact-before-cargo-retirement-20261010.sql`，121098字节，被Git忽略。结构调整前主展示库有7账号、4车辆、7门店、3线路、13需求、2方案、12任务、13明细、1回单、4旧分类、8旧车型能力。

回退：如果所有需求仍有旧分类，可以降级至23；存在无分类的新需求时 migration 明确拒绝降级。不得自动填造分类或删除新需求。需要恢复旧版本时，先单独备份新增数据，再在独立恢复库恢复原SQL备份；不要覆盖现用数据库。

## 主要文件范围

- 后端：delivery_demand 模型/Schema/Service；dispatch_validator、constraints、candidate_builder、engine模型与Repository；dispatch_validation_service；车辆Schema/Service/Repository与车型API；auto_dispatch/dispatch_plan/driver 的Schema、序列化及关联读取；AI解析、批量确认、评分和Seed脚本；API路由与权限路径清理。
- 前端：路由/菜单、需求列表和表单、AI预览及确认、车型管理、方案详情、Dashboard及相关types/API。
- 小程序：仅 task-detail/index.wxml 移除分类/温度展示，签收与回单逻辑未改。
- Agent/RAG：Tool描述、系统提示、知识文档与RagService旧片段安全过滤。
- 测试：分类停用回归、迁移数据保留/降级保护、AI解析、派车规则数、Seed/司机/历史数据夹具、RAG、前端预览及首页指标。

原历史 migration 16～23 未修改。已有未提交修改保留；不自动commit/push，v1.0.0-rc1不移动。

## 验证结果

- 前端48项测试通过；vue-tsc与生产构建通过（既有大包体积警告仍在）。
- 小程序35项Node测试通过；真实微信编译/实机操作需人工确认。
- 停用及migration专项12项通过；RAG专项10项通过。
- 最终完整后端：448 passed；没有删除或跳过测试。前端48项、小程序35项均无失败或跳过。
- MySQL：主展示库与独立验证库升级至20261010_24；主展示库current=head，backend/frontend/mysql均healthy。主展示库上述记录数量及13条需求原有分类、温度值逐项一致。
- 独立MySQL验证库2026-11-12：7个账号登录、权限隔离、请假审批、候选推荐与确认代班、V1→V2→V3、人工调整、评分、发布、司机归属、到店、签收/异常、回单JWT访问、完成与历史、每日异常及审计全部通过。V3方案#10包含11趟，12条需求全部分配，未分配0，最终12条需求COMPLETED。未处理门店禁止完成，匿名回单访问401，他人任务访问404；失败操作不产生成功审计。
- 预留4条需求通过正式批量确认接口创建，不冒充真实AI文本解析；未调用真实模型或Embedding。验收证据保存在被Git忽略的docs/local/compact-demo/cargo-retirement-validation.json。
- 浏览器实查：配送需求列表无分类字段，新增表单仅门店、日期、时段、货量与已有优先级；基础资料菜单无分类入口。仅打开表单查看，没有在主展示库提交需求。
- git diff --check通过；HEAD和v1.0.0-rc1仍为b3f70e9f307fde975faabef35c81cb3d35408906，未暂存、提交或推送。

## 人工复核

### 2026-10-10 独立提交快照复核

上方448/48/35及主展示库记录是此前完整工作区的验收结果，不代表本次独立提交包含所有演示环境、小程序或Dashboard改动。本次分类停用提交快照：后端 **439 passed**；前端专项 **38 passed**；vue-tsc与build通过。未纳入未跟踪的小程序、Dashboard页面、Compact Demo初始化、PPT及私有配置。

本轮已先提交19～23前置功能，再单独提交24；稳定Tag仍保留在b3f70e9，无push。`alembic check`仍未通过，已归档于`SCHEMA_DRIFT_BASELINE.md`，不得将迁移升级成功描述为结构比对PASS。

1. 管理后台刷新，确认没有货物分类菜单；车型管理没有运输能力配置。
2. 新建/编辑PENDING需求，只填写门店、日期、时段、货量和已有优先级。
3. 登记车辆及司机有效出勤，自动派车；检查载重和线路，发布方案。
4. 司机小程序重新编译，任务显示货量而非分类；到店、签收/失败、完成与回单审核保持原流程。
5. Agent查询需求；当前工具返回不含分类字段。真实模型和Embedding未验证的结果不得视为通过。
6. 需最新知识索引时，使用原构建命令重新向量化两份更新文档；在此之前旧分类片段会被过滤，并非伪造检索结果。
