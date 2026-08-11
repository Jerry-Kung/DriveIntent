# V1 版本总览

> 最后更新：2026-08-11（随 V1.6 发布）

## 能力快照

- **定位**：可通过 docker compose 独立部署的后端微服务，对外提供两个异步 Agent API（评论价值初筛 / 账号画像精筛），同时保留 V0 的 8000 测试链路。
- **对外契约**：`POST /api/v1/comment-screening`、`POST /api/v1/profile-analysis` 提交作业，`GET /api/v1/jobs/{job_id}` 轮询结果；静态 API Key 认证（`Authorization: Bearer`）；`GET /health` 探活。对接文档：`docs/DriveIntent-V1-API对接文档.md`（当前 1.3 版）。
- **核心能力现状（V1.5.1 后）**：
  - **Agent1（评论初筛）**：filter_type 分类（`genuine_user` / `bot_spam` / `marketing_account` / `noise` / `off_topic` / `no_purchase_intent`）；评论级 `is_car_owner` / `has_purchase_intent` 两独立标签；"有购车意向必过筛"等硬规则由代码层 `resolve_filter_type()` 确定性合成；非本人意向（替他人问询/怂恿/营销口吻）识别降档。
  - **Agent2（账号精筛）**：定级前先过"无效用户过滤"节点（独立 LLM 调用，V1.6）——已购无新购计划/怂恿他人/仅替他人问询/疑似营销水军/汽车从业者/其他六类命中直接定 C 不进定级，fail-open 放行；账号级两标签 + H/A/B/C 定级四段流水线——评论基线 → 在售车型匹配度四档调整 → 主页截图结构化画像有限上调 → 终判调整（多条相近评论合并增强酌情上调）。
  - **配套能力**：视频语境分析注入初筛与用户证据包；主页截图识图（结构化画像 JSON）；我方在售车型配置（`our_models.json`）。
  - **后端审计（V1.4）**：内部页 `/audit` 按东八区自然天/小时展示 API 任务量（接收/成功/部分成功/失败）与 LLM 消耗（调用次数/失败/输入输出 tokens/平均耗时，按 skill × 模型细分）；纯只读模块，数据源为既有 `api_job` / `llm_call_log` 落库。
- **架构要点**：API 路径（`api_job` 表 + ApiJobWorker，纯异步轮询，不写 lead 表）与 V0 流水线路径（lead 表 + Web 页面）并存，共享 LLM Gateway / Skill 执行器 / Prompt 模板层。
- **数据库会话纪律（V1.4.3 + V1.4.4 + V1.4.5）**：两类 Worker 均不得在 LLM 调用期间持有数据库连接，且**不得在事件循环内执行同步 DB 调用**。API Worker 的 `run_once` 按「认领 → 执行 → 落状态」拆为三段独立短会话，`_execute` 只接纯数据不接 ORM 对象；三段会话与 reaper 全部经 `asyncio.to_thread` 执行（V1.4.4：同步大读取会冻结整个事件循环——实测远程读 13MB payload 阻塞 3.2s，期间所有协程与 HTTP 请求停摆，是连接池耗尽的直接成因；V1.4.5：**LLM 调用日志落库是漏网的另一处高频同步 DB 写入**——实测 3 小时 6703 行约为作业数 27 倍，池耗尽时在事件循环内同步等 `pool_timeout`（30s）且异常被吞、报错全落在受害者调用点上，本次 149 次 QueuePool 报错即由此放大）。业务 Worker 的认领/落状态/推进三处同步调用同样经线程池。进度回调 `progress_cb` 相应改为 async。对应回归测试：`tests/test_api_worker_session.py`、`tests/test_pipeline_connection_release.py`、`tests/test_event_loop_not_blocked.py`、`tests/test_llm_log_not_blocking.py`。
- **截图存储模型（V1.4.4）**：数据库不存 base64 原始截图。POST 接收 base64 后抽入落盘暂存区（`data/staging/<job_id>.json`，docker 需挂载 `./data:/app/data`），payload 中该字段置空后落库；Worker 认领时读回识图，识图纯文本在作业终态写回 `payload.accounts[].homepage_vision_text`，终态即删暂存文件（重试期间保留）。识图失败或暂存缺失均降级为无截图继续，作业不失败。**对外契约不变**——调用方仍传 base64。存量作业 payload 内联 base64 的路径保留兼容。
- **LLM 调用（V1.4.1）**：模型配置拆分为文本模型（`LLM_MODEL`）与多模态模型（`LLM_MULTIMODAL_MODEL`，留空回退文本）；节点通过 Skill 配置 `model.multimodal` 声明能力需求（当前仅识图为 true），由 Gateway 路由默认模型。深度思考全局开关 `LLM_ENABLE_THINKING`（默认关）对 openai_compat 请求注入 `enable_thinking`。
- **Skill/Prompt 版本对照（现行）**：

| Skill | config version | prompt |
|---|---|---|
| comment_lead_screening | 1.3 | v3 |
| video_context_analysis | 1.1 | v2 |
| user_lead_analysis | 1.6 | v1.6 |
| user_lead_filter | 1.6 | v1.6 |
| image_recognition | 1.4.1 | v2 |

（旧口径版本号与项目版本的映射见 [VERSIONING.md](../VERSIONING.md) 第 4 节；`user_lead_analysis` 自 V1.5.1 起启用 VERSIONING.md 第 4 节新口径版本号。）

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
| V1.4.4 | 2026-08-05 | 补丁：连接池耗尽真因修复——同步 DB IO 移出事件循环（to_thread）+ base64 截图不入库改存识图文本（落盘暂存区），契约不变 | [design](V1.4/v1.4.4-design.md) |
| V1.4.5 | 2026-08-05 | 补丁：连接池耗尽放大器修复——LLM 调用日志落库（全系统最高频 DB 写入）移出事件循环，`_log` 拆同步体 + async to_thread，契约不变 | [design](V1.4/v1.4.5-design.md) |
| V1.5.1 | 2026-08-06 | 定级终判调整：多条相近评论合并增强 + "已购"信号封顶（原则上不高于 B），仅 Prompt + 审计字段，契约不变 | [design](V1.5/v1.5.1-design.md) / [plan](V1.5/v1.5.1-plan.md) |
| V1.6 | 2026-08-11 | 无效用户过滤节点：定级前独立 LLM 过滤（六类命中直接 C），已购封顶/怂恿/营销规则迁出定级 Prompt，两路径接入，契约不变 | [design](V1.6/design.md) / [plan](V1.6/plan.md) |

> **V1.4.4 的"测试环境闭环"结论已被 V1.4.5 推翻**：V1.4.4 修复后的一段时间内
> 未再观察到 `QueuePool limit reached`，但 2026-08-05 12:16 起复发（本次日志 149 次
> TimeoutError，静默间隔为 `pool_timeout` 的 30s 整数倍）。真因是 V1.4.4 遗漏的
> LLM 日志落库同步写库（3 小时 6703 行 ≈ 作业数 27 倍，异常被吞、报错全落在
> 受害者调用点上）。V1.4.5 已修复并新增 `tests/test_llm_log_not_blocking.py` 守护；
> **测试环境验证待 V1.4.5 上线后观察**。存量处置与部署核对见 V1.4.4 条目；
> MySQL `max_connections=151` 已打满，调大步骤见部署文档 §7。
