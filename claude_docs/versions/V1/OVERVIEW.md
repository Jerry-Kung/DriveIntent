# V1 版本总览

> 最后更新：2026-08-03（随 V1.3 发布）

## 能力快照

- **定位**：可通过 docker compose 独立部署的后端微服务，对外提供两个异步 Agent API（评论价值初筛 / 账号画像精筛），同时保留 V0 的 8000 测试链路。
- **对外契约**：`POST /api/v1/comment-screening`、`POST /api/v1/profile-analysis` 提交作业，`GET /api/v1/jobs/{job_id}` 轮询结果；静态 API Key 认证（`Authorization: Bearer`）；`GET /health` 探活。对接文档：`docs/DriveIntent-V1-API对接文档.md`（当前 1.3 版）。
- **核心能力现状（V1.3 后）**：
  - **Agent1（评论初筛）**：filter_type 分类（`genuine_user` / `bot_spam` / `marketing_account` / `noise` / `off_topic` / `no_purchase_intent`）；评论级 `is_car_owner` / `has_purchase_intent` 两独立标签；"有购车意向必过筛"等硬规则由代码层 `resolve_filter_type()` 确定性合成；非本人意向（替他人问询/怂恿/营销口吻）识别降档。
  - **Agent2（账号精筛）**：账号级两标签 + H/A/B/C 定级三段流水线——评论基线 → 在售车型匹配度四档调整 → 主页截图结构化画像有限上调。
  - **配套能力**：视频语境分析注入初筛与用户证据包；主页截图识图（结构化画像 JSON）；我方在售车型配置（`our_models.json`）。
- **架构要点**：API 路径（`api_job` 表 + ApiJobWorker，纯异步轮询，不写 lead 表）与 V0 流水线路径（lead 表 + Web 页面）并存，共享 LLM Gateway / Skill 执行器 / Prompt 模板层。
- **Skill/Prompt 版本对照（现行）**：

| Skill | config version | prompt |
|---|---|---|
| comment_lead_screening | 1.3 | v3 |
| video_context_analysis | 1.1 | v2 |
| user_lead_analysis | 1.3 | v5 |
| image_recognition | 2.0 | v2 |

（旧口径版本号与项目版本的映射见 [VERSIONING.md](../VERSIONING.md) 第 4 节。）

## 变更索引

| 版本 | 日期 | 变更摘要 | 文档 |
|---|---|---|---|
| V1.0 | 2026-07-23 | 微服务化 + 两个异步 API + 识图 Skill + api_job 作业模型 | [design](V1.0/design.md) / [plan](V1.0/plan.md) |
| V1.1 | 2026-07-27 | filter_type 评论分类、已购/已大定车主过滤、非我方车型意向降级、主力车型配置 | [design](V1.1/design.md) / [plan](V1.1/plan.md) |
| V1.1.1 | 2026-07-28 | 补丁：Agent1 对外输出契约定点优化（model_mismatch 语义） | [design](V1.1/v1.1.1-design.md) |
| V1.2 | 2026-07-28 | 主页截图纳入 Agent2：识图结构化画像 + 评级有限上调 | [design](V1.2/design.md) / [plan](V1.2/plan.md) |
| V1.2.1 | 2026-07-30 | 补丁：在售车型匹配度纳入 Agent2 评级（四档调整三段流水线） | [design](V1.2/v1.2.1-design.md) / [plan](V1.2/v1.2.1-plan.md) |
| V1.3 | 2026-08-03 | 评论/账号两级"车主/购车意向"独立标签、初筛规则重构（新增 no_purchase_intent）、视频语境降级模块下线、非本人意向 bugfix | [design](V1.3/design.md) / [plan](V1.3/plan.md) |
