# V1 版本总览

> 最后更新：2026-09-03（随 V1.8.5 发布）

## 能力快照

- **定位**：可通过 docker compose 独立部署的后端微服务，对外提供两个异步 Agent API（评论价值初筛 / 账号画像精筛），同时保留 V0 的 8000 测试链路。
- **对外契约**：`POST /api/v1/comment-screening`、`POST /api/v1/profile-analysis` 提交作业，`GET /api/v1/jobs/{job_id}` 轮询结果；静态 API Key 认证（`Authorization: Bearer`）；`GET /health` 探活。对接文档：`docs/DriveIntent-V1-API对接文档.md`（当前 1.3 版）。V1.7.3 起 Agent2 等级多对一映射：H/A→high、B→medium、C→low，分数区间随之调整（见对接文档等级表）。V1.8.0 起 Agent2 结果新增 `intent_models`（意向车型）/ `intent_model_category`（四档分类，标准可配）两字段；V1.8.2 起 `intent_model_category` 对外返回中文正式内容（配置 `label`：东风猛士系列/越野车/25-30万SUV/其他），库内仍存码值 A/B/C/D 供内部统计。
- **核心能力现状（V1.6 后）**：
  - **Agent1（评论初筛）**：filter_type 分类（`genuine_user` / `bot_spam` / `marketing_account` / `noise` / `off_topic` / `no_purchase_intent`）；评论级 `is_car_owner` / `has_purchase_intent` 两独立标签；"有购车意向必过筛"等硬规则由代码层 `resolve_filter_type()` 确定性合成；非本人意向（替他人问询/怂恿/营销口吻）识别降档。批内 `content` 为空的评论由代码层剔除（不喂 LLM）并合成 `off_topic` 确定性结果（V1.8.5）——廉价模型会跳过空内容条目、若照常编 index 会整批错位致 index 集合校验失败、整单重试全败；剔除后保证每条输入评论都有落库结果，index 校验只针对非空评论。
  - **Agent2（账号精筛）**：定级前先过"无效用户过滤"节点（独立 LLM 调用，V1.6）——已购无新购计划/推广他人/仅替他人问询/疑似营销号/汽车从业者/其他六类命中直接定 C 不进定级，fail-open 放行；账号级两标签 + H/A/B/C 定级三阶段流水线（V1.6.2，V1.8.0 重构阶段二）——评论基线（多条同质评论累积强化已并入基线）→ 意向车型识别与分类（V1.8.0：只识别归档、**不调整评级**；识别有购买意向的车型 `intent_models`，按可配置四档标准输出 `intent_model_category`，标准配置 `config/intent_categories.json`；V1.2.1 引入的匹配调级与 V1.7.4 的对比基准约束随之退役，如何用分类调整优先级交下游决定）→ 主页截图结构化画像有限上调（作用于基线评级）；定级后接分级复核（V1.7.0）——初始 C 不审查不润色直接输出、初始 B 走普通模型审查（`user_lead_review`，V1.6.2/1.6.3 销售视角复核 + 单次至多改一级、C 为下限、fail-open）、初始 A/H 走高级模型审查（`user_lead_review_advanced`，逐段核验五段论证与推理链，模型路由到 `LLM_MODEL_ADVANCED` 并强制深度思考）；初始 B 经普通审查 upgrade 到 A/H 时追加一次高级终审。复核改级时一并修订对外叙述（V1.6.3）——按段标题锚点替换 `analysis_text` 第五段"总体评价"与 `lead_summary`，前四段事实陈述逐字保留，锚点缺失退化为文末追加。V1.8.4：定级 Prompt 收紧 `analysis_text` 第四段"主页画像与调整结论"的措辞——只陈述画像事实与是否触发上调，禁止输出等级性结论（如"最终评级维持/调整为 X 级"），等级结论统归第五段，消除"初评 B 经复核降级到 C"时第四段残留旧等级的矛盾。复核后统一接 analysis 润色节点 `user_analysis_polish`（V1.6.4，两路径同接，最终定级 C 跳过）——针对最终定级重写 analysis_text / lead_summary / profile_summary，清除英文字段泄漏、消除叙述与定级矛盾，只改文本不改级，fail-open 保留原文；复核节点同版起接入对外 API 路径（此前仅 V0 流水线有复核）。**等级对外映射（V1.7.3）**：H/A→high、B→medium、C→low，各内部等级保留原 base/floor（C 新增 45/40）；由于外部 code 已多对一，`api_job.lead_grades` 落每账号真实 HABC 供内部审计读取（`lead_results.py`），审计仍以 HABC 四档呈现，旧数据回退按 code 反推。
  - **配套能力**：视频语境分析注入初筛与用户证据包；主页截图识图（结构化画像 JSON）；我方在售车型配置（`our_models.json`）；意向车型分类标准配置（`intent_categories.json`，V1.8.0）。
  - **后端审计（V1.4）**：内部页 `/audit` 按东八区自然天/小时展示 API 任务量（接收/成功/部分成功/失败）与 LLM 消耗（调用次数/失败/输入输出 tokens/平均耗时，按 skill × 模型细分）；纯只读模块，数据源为既有 `api_job` / `llm_call_log` 落库。
- **架构要点**：API 路径（`api_job` 表 + ApiJobWorker，纯异步轮询，不写 lead 表）与 V0 流水线路径（lead 表 + Web 页面）并存，共享 LLM Gateway / Skill 执行器 / Prompt 模板层。
- **数据库会话纪律（V1.4.3 + V1.4.4 + V1.4.5）**：两类 Worker 均不得在 LLM 调用期间持有数据库连接，且**不得在事件循环内执行同步 DB 调用**。API Worker 的 `run_once` 按「认领 → 执行 → 落状态」拆为三段独立短会话，`_execute` 只接纯数据不接 ORM 对象；三段会话与 reaper 全部经 `asyncio.to_thread` 执行（V1.4.4：同步大读取会冻结整个事件循环——实测远程读 13MB payload 阻塞 3.2s，期间所有协程与 HTTP 请求停摆，是连接池耗尽的直接成因；V1.4.5：**LLM 调用日志落库是漏网的另一处高频同步 DB 写入**——实测 3 小时 6703 行约为作业数 27 倍，池耗尽时在事件循环内同步等 `pool_timeout`（30s）且异常被吞、报错全落在受害者调用点上，本次 149 次 QueuePool 报错即由此放大）。业务 Worker 的认领/落状态/推进三处同步调用同样经线程池。进度回调 `progress_cb` 相应改为 async。对应回归测试：`tests/test_api_worker_session.py`、`tests/test_pipeline_connection_release.py`、`tests/test_event_loop_not_blocked.py`、`tests/test_llm_log_not_blocking.py`。
- **截图存储模型（V1.4.4）**：数据库不存 base64 原始截图。POST 接收 base64 后抽入落盘暂存区（`data/staging/<job_id>.json`，docker 需挂载 `./data:/app/data`），payload 中该字段置空后落库；Worker 认领时读回识图，识图纯文本在作业终态写回 `payload.accounts[].homepage_vision_text`，终态即删暂存文件（重试期间保留）。识图失败或暂存缺失均降级为无截图继续，作业不失败。**对外契约不变**——调用方仍传 base64。存量作业 payload 内联 base64 的路径保留兼容。
- **LLM 调用（V1.4.1）**：模型配置拆分为文本模型（`LLM_MODEL`）与多模态模型（`LLM_MULTIMODAL_MODEL`，留空回退文本）；节点通过 Skill 配置 `model.multimodal` 声明能力需求（当前仅识图为 true），由 Gateway 路由默认模型。深度思考全局开关 `LLM_ENABLE_THINKING`（默认关）对 openai_compat 请求注入 `enable_thinking`。V1.7.0 新增高级模型 `LLM_MODEL_ADVANCED`（与普通模型共用 BASE_URL/API_KEY、仅模型名不同、留空回退 `LLM_MODEL`、请求永久强制 `enable_thinking=true`），节点通过 Skill 配置 `model.advanced` 声明（当前仅高级审查 `user_lead_review_advanced` 为 true）。
- **Skill/Prompt 版本对照（现行）**：

| Skill | config version | prompt |
|---|---|---|
| comment_lead_screening | 1.8.3 | v1.8.3 |
| video_context_analysis | 1.8.3 | v1.8.3 |
| user_lead_analysis | 1.8.4 | v1.8.4 |
| user_lead_review | 1.6.3 | v1.6.3 |
| user_lead_review_advanced | 1.8.0 | v1.8.0 |
| user_lead_filter | 1.6.1 | v1.6.1 |
| image_recognition | 1.4.1 | v2 |
| user_analysis_polish | 1.6.4 | v1.6.4 |

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
| V1.6.1 | 2026-08-11 | analysis 可读性修复：定级/过滤 Prompt 对外文本禁用内部审计字段名与枚举值，analysis 六段业务化，契约不变 | [design](V1.6/v1.6.1-design.md) / [plan](V1.6/v1.6.1-plan.md) |
| V1.6.2 | 2026-08-12 | 定级重构：HABC 由决策阶段改为销售价值口径，H/A 按持续深度与单次信号分界，合并增强并入基线（merge_boost 下线）；新增独立复核节点 user_lead_review，契约不变 | 未归档（见 [v1.6.3-design.md](V1.6/v1.6.3-design.md) 文末说明） |
| V1.6.3 | 2026-08-12 | 复核改级后同步修订对外叙述：定级 Prompt 为 analysis_text 五段加固定标题，复核输出 revised_conclusion / revised_lead_summary，pipeline 按锚点替换第五段与 lead_summary，前四段逐字保留，契约不变 | [design](V1.6/v1.6.3-design.md) / [plan](V1.6/v1.6.3-plan.md) |
| V1.6.4 | 2026-08-13 | analysis 润色节点：定级+复核后独立 LLM 润色三个对外叙述字段（英文泄漏/定级矛盾/可读性），复核节点补接入对外 API 路径，复核 fail-open 补日志，契约不变 | [design](V1.6/v1.6.4-design.md) / [plan](V1.6/v1.6.4-plan.md) |
| V1.7.0 | 2026-08-17 | 审查节点分级分流（C 短路 / B 普通审查 / A·H 高级审查，B→A/H 追加高级终审）+ 高级模型 `LLM_MODEL_ADVANCED`（永久深度思考）+ 润色对最终 C 短路，契约不变 | [design](V1.7/design.md) / [plan](V1.7/plan.md) |
| V1.7.1 | 2026-08-17 | 管理页重构：线索列表对接 api_job 实时精筛结果（分页/倒序/日期·等级筛选/CSV 导出/链路详情），撤销分析任务模块 | [design](V1.7/v1.7.1-design.md) / [plan](V1.7/v1.7.1-plan.md) |
| V1.7.2 | 2026-08-24 | 评论初筛 ID 抄写移出 LLM：以批次内临时序号 index 定位评论、代码层集合校验并还原真实 comment_id，修复廉价模型抄错 19 位 ID 导致的静默失败（3246/6794 单条作业假失败），对外契约不变 | [design](V1.7/v1.7.2-design.md) |
| V1.7.3 | 2026-08-24 | 定级等级对外映射统一：H/A→high、B→medium、C→low；各内部等级保留原 base/floor（C 新增 45/40）；新增 `api_job.lead_grades` 列落真实 HABC 供内部审计，不再靠反推 code | [design](V1.7/v1.7.3-design.md) |
| V1.7.4 | 2026-08-24 | 阶段二匹配基准约束：先用与用户目标车型最接近的在售车型作对比车型，修复多款在售车型并存时选错参考车导致误判无关而错误降级，契约不变 | [design](V1.7/v1.7.4-design.md) |
| V1.8.0 | 2026-08-27 | 阶段二重构：意向车型识别与四档分类（标准可配 `intent_categories.json`），撤销匹配调级（V1.2.1 调级与 V1.7.4 基准约束退役）；`intent_models` / `intent_model_category` 落库（lead 表新两列 + api_job 结果 JSON）并新增对外 API 字段（纯增量） | [design](V1.8/design.md) / [plan](V1.8/plan.md) |
| V1.8.2 | 2026-08-27 | 精筛定级接口 `intent_model_category` 对外改返回中文正式内容（配置 `label`：东风猛士系列/越野车/25-30万SUV/其他），库内仍存码值 A/B/C/D 供内部统计，仅返回层映射 | [design](V1.8/v1.8.2-design.md) |
| V1.8.3 | 2026-09-01 | 补丁：video_context 品牌/车型/品类/动力四字段数组化（跨品牌对比视频 LLM 输出数组致整单校验失败的线上事故修复）+ 初筛 target_brand/model 单值选取规则 + 精筛阶段二"视频语境仅为背景"禁令与多意向车型最优档显式例子，契约不变 | [design](V1.8/v1.8.3-design.md) |
| V1.8.4 | 2026-09-02 | 补丁：定级 Prompt 收紧 `analysis_text` 第四段"主页画像与调整结论"措辞——禁止输出等级性结论（如"最终评级维持/调整为 X 级"），等级结论统归第五段，修复"初评 B 经复核降级到 C 时第四段残留旧等级导致定级与分析文本矛盾"，契约不变 | [design](V1.8/v1.8.4-design.md) |
| V1.8.5 | 2026-09-03 | 补丁：评论初筛批内空 content 评论由代码层剔除并合成确定性结果（off_topic），修复廉价模型跳过空内容致 index 集合校验失败、整单 3 次重试全败（2026-09-03 当天 199 failed / 87 pending），契约不变，无 Prompt/Skill 版本变更 | [design](V1.8/v1.8.5-design.md) |

> **V1.4.4 的"测试环境闭环"结论已被 V1.4.5 推翻**：V1.4.4 修复后的一段时间内
> 未再观察到 `QueuePool limit reached`，但 2026-08-05 12:16 起复发（本次日志 149 次
> TimeoutError，静默间隔为 `pool_timeout` 的 30s 整数倍）。真因是 V1.4.4 遗漏的
> LLM 日志落库同步写库（3 小时 6703 行 ≈ 作业数 27 倍，异常被吞、报错全落在
> 受害者调用点上）。V1.4.5 已修复并新增 `tests/test_llm_log_not_blocking.py` 守护；
> **测试环境验证待 V1.4.5 上线后观察**。存量处置与部署核对见 V1.4.4 条目；
> MySQL `max_connections=151` 已打满，调大步骤见部署文档 §7。
