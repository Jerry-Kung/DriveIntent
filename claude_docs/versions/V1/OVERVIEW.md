# V1 版本总览

> 最后更新：2026-08-05（随 V1.4.3 发布）

## 能力快照

- **定位**：可通过 docker compose 独立部署的后端微服务，对外提供两个异步 Agent API（评论价值初筛 / 账号画像精筛），同时保留 V0 的 8000 测试链路。
- **对外契约**：`POST /api/v1/comment-screening`、`POST /api/v1/profile-analysis` 提交作业，`GET /api/v1/jobs/{job_id}` 轮询结果；静态 API Key 认证（`Authorization: Bearer`）；`GET /health` 探活。对接文档：`docs/DriveIntent-V1-API对接文档.md`（当前 1.3 版）。
- **核心能力现状（V1.3 后）**：
  - **Agent1（评论初筛）**：filter_type 分类（`genuine_user` / `bot_spam` / `marketing_account` / `noise` / `off_topic` / `no_purchase_intent`）；评论级 `is_car_owner` / `has_purchase_intent` 两独立标签；"有购车意向必过筛"等硬规则由代码层 `resolve_filter_type()` 确定性合成；非本人意向（替他人问询/怂恿/营销口吻）识别降档。
  - **Agent2（账号精筛）**：账号级两标签 + H/A/B/C 定级三段流水线——评论基线 → 在售车型匹配度四档调整 → 主页截图结构化画像有限上调。
  - **配套能力**：视频语境分析注入初筛与用户证据包；主页截图识图（结构化画像 JSON）；我方在售车型配置（`our_models.json`）。
  - **后端审计（V1.4）**：内部页 `/audit` 按东八区自然天/小时展示 API 任务量（接收/成功/部分成功/失败）与 LLM 消耗（调用次数/失败/输入输出 tokens/平均耗时，按 skill × 模型细分）；纯只读模块，数据源为既有 `api_job` / `llm_call_log` 落库。
- **架构要点**：API 路径（`api_job` 表 + ApiJobWorker，纯异步轮询，不写 lead 表）与 V0 流水线路径（lead 表 + Web 页面）并存，共享 LLM Gateway / Skill 执行器 / Prompt 模板层。
- **数据库会话纪律（V1.4.3）**：两类 Worker 均不得在 LLM 调用期间持有数据库连接。API Worker 的 `run_once` 按「认领 → 执行 → 落状态」拆为三段独立短会话，`_execute` 只接纯数据不接 ORM 对象（避免 deferred 的 `request_payload` 触发隐式 SELECT 并把连接钉在池外）；业务 Worker 在 pipeline 三个入口以 `session.commit()` 提前结束读取事务。由此连接占用与 Worker 并发数解耦。对应回归测试：`tests/test_api_worker_session.py`、`tests/test_pipeline_connection_release.py`。
- **LLM 调用（V1.4.1）**：模型配置拆分为文本模型（`LLM_MODEL`）与多模态模型（`LLM_MULTIMODAL_MODEL`，留空回退文本）；节点通过 Skill 配置 `model.multimodal` 声明能力需求（当前仅识图为 true），由 Gateway 路由默认模型。深度思考全局开关 `LLM_ENABLE_THINKING`（默认关）对 openai_compat 请求注入 `enable_thinking`。
- **Skill/Prompt 版本对照（现行）**：

| Skill | config version | prompt |
|---|---|---|
| comment_lead_screening | 1.3 | v3 |
| video_context_analysis | 1.1 | v2 |
| user_lead_analysis | 1.3 | v5 |
| image_recognition | 1.4.1 | v2 |

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
| V1.4 | 2026-08-04 | 后端审计：任务量/LLM tokens 明细统计 + /audit 内置页面（只读，业务零改动） | [design](V1.4/design.md) / [plan](V1.4/plan.md) |
| V1.4.1 | 2026-08-04 | 补丁：LLM 调用优化——文本/多模态模型拆分（识图走多模态、留空回退文本）+ 深度思考全局开关（enable_thinking，默认关） | [design](V1.4/v1.4.1-design.md) |
| V1.4.2 | 2026-08-05 | **已回退**（a57b1f7）：线程池收敛 + 截图强制 URL；根因判断有误且含破坏性契约变更，上线报错后整体撤回 | — |
| V1.4.3 | 2026-08-05 | 补丁：连接池耗尽根因修复——API Worker 会话生命周期改造（LLM 期间零连接持有），契约不变 | [design](V1.4/v1.4.3-design.md) |
