# DriveIntent V0（MVP）设计文档

**文档版本：** 1.0
**日期：** 2026-07-20
**状态：** 已评审通过
**上游文档：** `README.md`（项目总体设计 V0.1）

------

## 1. 目标与范围

V0 目标：实现一个可端到端运行的最小闭环——导入真实抖音评论数据，经过三个 LLM Skill 分析，产出 H/A/B/C 分级销售线索，并提供简单页面供业务人员查看、审核和导出。

### 1.1 V0 已确认的关键决策

| 决策项 | 结论 |
|---|---|
| LLM 接入 | 封装为独立 LLM Gateway，通用输入输出接口；默认实现 OpenAI 兼容 Provider，具体模型接入方式在实现阶段通过 `.env` 配置；另提供 MockProvider 用于开发测试 |
| 数据来源 | 真实业务数据 `data/test_data.xlsx`（抖音，45 视频 / 约 2.38 万评论 / 约 2 万用户），导入格式以此为准 |
| 数据库 | MySQL，连接配置写在 `.env` |
| 前端 | 后端内嵌简单页面（FastAPI + Jinja2 服务端渲染），不做前后端分离 |
| 用户主页数据 | V0 不含（真实数据中没有 UserProfileSnapshot、点赞数、账号类型等字段）；数据模型和 Skill 输入保留可选字段，后续到位直接启用 |
| 执行架构 | 单进程 FastAPI + MySQL 任务表 + 进程内 asyncio 后台 Worker |

### 1.2 V0 明确不做

- 用户公开主页数据链路（UserProfileSnapshot 表不建）
- N/S 等级的前端展示（无效/营销判断仅存于分析结果）
- 根据人工审核自动优化 Prompt 或训练模型
- 多租户、登录权限
- 实时/增量流式分析（但数据可增量导入，工作流不依赖全量日批）
- 消息队列、独立 Worker 进程、DAG 编排平台

------

## 2. 输入数据

### 2.1 真实数据结构（test_data.xlsx）

单张宽表，每行一条评论及其所属视频、发布用户信息：

| 字段 | 含义 | 映射 |
|---|---|---|
| `aweme_id` | 抖音视频 ID | video.external_id |
| `title` / `desc` | 视频标题 / 文案（含 `#话题` 标签，导入时解析） | video.title / description / tags |
| `cover_url` | 封面地址 | video.cover_url |
| `nickname` | 评论用户昵称 | platform_user.nickname |
| `sec_uid` | 用户加密 ID | platform_user.external_id |
| `comment_id` | 评论 ID | comment.external_id |
| `content` | 评论文本（约 0.7% 为空，导入时跳过并计数） | comment.content |
| `create_time` | 评论时间（Unix 秒） | comment.comment_time（转 datetime） |

数据特征：评论数每视频 2—4169 条不等；约 1865 个用户有 2 条以上评论；存在高频评论账号（如单用户 506 条，疑似博主自己回复），营销/水军识别和用户级聚合有真实用武之地。

### 2.2 标准导入格式

定义标准 JSON 导入格式（videos / comments / users 三个数组）作为长期数据接口；Excel 导入在内部转换为该格式后走同一条导入管道。两种入口共用幂等逻辑。

------

## 3. 技术栈与项目结构

**技术栈**：Python 3.11+、FastAPI、SQLAlchemy 2.0、Pydantic v2、MySQL（PyMySQL）、Jinja2、pandas + openpyxl（Excel 解析）。

```
app/
├── main.py            # FastAPI 入口，lifespan 中拉起后台 Worker
├── config.py          # .env 配置加载（数据库、LLM、并发度等）
├── db.py              # SQLAlchemy engine / session
├── models/            # ORM 模型（L1）
├── schemas/           # Pydantic Schema：导入格式 + 三个 Skill 输入输出
├── importer/          # Excel/JSON 导入，幂等处理（L1）
├── llm/               # LLM Gateway：通用接口 + Provider 适配（横向公共能力）
├── skills/            # Skill 执行器（L3）
│   ├── configs/       # 每个 Skill 一个 YAML（skill_id、版本、模型参数、prompt 路径）
│   └── prompts/       # Prompt 模板文件，文件名带版本号
├── workflow/          # 固定工作流编排 + 任务管理 + Worker（横向公共能力）
├── services/          # L4：用户聚合、线索生成、CSV 导出
├── web/               # 路由：页面 + JSON API（L5）
└── templates/         # Jinja2 页面
tests/                 # 单元与集成测试
data/                  # 测试数据
.env.example           # 配置模板
```

模块间依赖方向：`web → services/workflow → skills → llm`，`importer/models` 被各层引用。逻辑分层清晰，物理上一个应用。

------

## 4. 数据模型（MySQL）

### 4.1 表清单

**video** — 视频
- `id` PK；`platform` + `external_id`(aweme_id) 唯一键（幂等）
- `title`、`description`、`cover_url`、`tags`(JSON，从 title/desc 解析的话题标签)
- 可选扩展字段：`author_name`、`account_type`、`publish_time`、`transcript`、`preset_brand`、`preset_model`（当前数据为空）
- `raw_data`(JSON，原始行完整保存)、`imported_at`

**platform_user** — 平台用户
- `id` PK；`platform` + `external_id`(sec_uid) 唯一键
- `nickname`；可选：`avatar_url`、`bio`、`region`
- `raw_data`、`imported_at`

**comment** — 评论
- `id` PK；`platform` + `external_id`(comment_id) 唯一键
- `video_id` FK、`user_id` FK、`content`、`comment_time`
- 可选：`like_count`、`reply_count`、`is_reply`
- `raw_data`、`imported_at`

**analysis_task** — 分析任务队列
- `id` PK；`task_type`(=skill_id) + `target_type` + `target_id` + `skill_version` 唯一键（幂等键）
- `status`：pending / running / success / failed
- `payload`(JSON)：评论批次任务在此存放评论 ID 列表
- `attempt_count`、`max_attempts`(默认 3)、`error`、`created_at`、`updated_at`

**analysis_result** — 统一分析结果
- `id` PK；`target_type` + `target_id` + `skill_id` + `skill_version`
- `model_name`、`prompt_version`、`status`、`result`(JSON)、`confidence`、`error`、`created_at`
- 多版本并存不覆盖；业务读取当前生效版本（按 skill_version 取最新成功结果）

**lead** — 销售线索
- `id` PK；`user_id` FK（每用户当前一条有效线索，按 skill_version 可重新生成）
- `grade`(H/A/B/C)、`is_valid`、`status`
- `target_brands`(JSON)、`target_models`(JSON)、`summary`、`purchase_stage`
- `core_needs`(JSON)、`main_concerns`(JSON)、`purchase_time`、`usage_scenario`
- `entry_point`、`verification_questions`(JSON)、`evidence`(JSON，评论 ID+内容)
- `confidence`、`skill_version`
- 人工审核：`review_status`(未审核/有效/无效)、`review_tags`(JSON 多选)、`review_note`
- `created_at`、`updated_at`

**llm_call_log** — LLM 调用日志
- `skill_id`、`skill_version`、`model_name`、`prompt_version`
- `input_digest`(输入摘要)、`output_text`、`prompt_tokens`、`completion_tokens`
- `duration_ms`、`error`、`retry_count`、`created_at`

### 4.2 数据设计原则（承接 README 5.1.3）

- 原始数据不可覆盖：每张 L1 表保留 `raw_data` 完整 JSON
- 分析结果多版本并存：升级 Skill 版本号即可对历史数据重新分析，旧结果保留
- 幂等导入：重复导入同一批数据只跳过不重写

------

## 5. LLM Gateway

对上暴露统一异步接口：

```python
async def chat(messages, *, model=None, temperature=None,
               response_format=None) -> LLMResponse
# LLMResponse: text, prompt_tokens, completion_tokens, duration_ms
```

- **Provider 适配层**：V0 实现两个 Provider
  - `OpenAICompatProvider`：`base_url` + `api_key` + `model` 全部来自 `.env`，可对接 Qwen(DashScope)、DeepSeek、本地 vLLM/Ollama 等任何 OpenAI 兼容端点
  - `MockProvider`：返回预置/规则生成的结构化结果，用于无真实模型时跑通端到端流程与自动化测试
- Gateway 内置：超时控制、网络/超时自动重试（2—3 次）、每次调用落 `llm_call_log`
- 换模型 = 改 `.env` 或新增 Provider，业务代码零改动

------

## 6. Skill 设计（L3）

### 6.1 Skill 机制

一个 Skill = YAML 配置 + Prompt 模板文件 + Pydantic 输入/输出 Schema。

Skill 执行器统一流程：读配置 → 取上游数据 → 组装 Prompt → 调 Gateway → 解析 JSON → Pydantic 校验 → 失败时自动修复/重试 → 结果写 `analysis_result`（记录模型、Prompt、Skill 版本）。

执行器不决定业务流程；流程由工作流模块控制。

### 6.2 Skill 1：`video_context_analysis` 视频语境理解

- **输入**：视频标题、文案、话题标签；可选：账号类型、转写、预置品牌车型（V0 为空）
- **输出**：品牌、车型、内容类型、主要讨论主题、目标受众、竞品车型、商业属性、评论分析注意事项（对应 README 5.2.2 JSON 结构）
- **粒度**：每视频一次，结果供该视频全部评论复用

### 6.3 Skill 2：`comment_lead_screening` 评论线索筛选

- **输入**：视频语境结果 + 一批评论（默认 30 条/批，可配置 20—50）+ 当前线索判断原则
- **输出**（每条评论）：`is_meaningful`、`is_automotive_related`、`is_purchase_related`、`is_suspected_marketing`、`intent_signals`、`target_brand`、`target_model`、`intent_strength`、`reason`、`confidence`（对应 README 5.2.3）
- **Prompt 要点**：
  - 明确区分四级：正面情绪 / 产品兴趣 / 潜在购车需求 / 明确交易意向
  - 负面表达中含换车需求的不得过滤（README 例："售后太差准备换品牌"）
  - Few-shot 覆盖典型负样本（"厉害"、"good"、玩梗、纯吹捧、营销号召）
- **批次防错位**（README 12.5）：每条评论带唯一 ID 输入；校验输出条数与 ID 集合和输入完全一致；不一致整批重试；再失败拆半重试；超长评论单独成批

### 6.4 Skill 3：`user_lead_analysis` 用户线索综合分析

- **输入**：用户全部通过筛选的评论（附各自视频语境）+ 代码计算的统计特征 + H/A/B/C 分级标准文本；可选：用户主页信息（V0 恒为空，Schema 预留）
- **输出**：`lead_grade`、`is_valid_lead`、`purchase_stage`、`target_brands/models`、`core_needs`、`main_concerns`、`purchase_time`、`usage_scenario`、`recommended_entry_point`、`verification_questions`、`evidence`(评论 ID 引用)、`confidence`（对应 README 6.7 示例）
- **画像边界**（README 12.3）：严格限定购车转化相关内容，无证据的信息输出未知，不推断职业/收入/家庭
- **分级标准**（README 5.4.2）：以购车决策阶段和行动信号为主判据——H 交易或行动 / A 主动评估 / B 产品兴趣 / C 弱相关；标准文本作为 Prompt 一部分，可随版本迭代

------

## 7. 工作流与任务执行

### 7.1 固定工作流

```
数据导入完成
→ 每个视频建 video_context 任务（无当前版本成功结果的）
→ 某视频语境完成后，该视频评论按批建 screening 任务
→ 全部筛选完成后，代码聚合候选用户
→ 每个候选用户建 user_analysis 任务
→ 用户分析成功后写入/更新 lead 表
```

- **候选用户门槛**：`is_purchase_related=true` 且非疑似营销的评论 ≥ 1 条。控制进入 Skill 3 的用户量（先准确率后召回率，控制 token 成本）
- **用户聚合**（纯代码，不调 LLM）：有效评论列表、所在视频、时间范围、涉及品牌车型、有效评论数、高意向评论数等简单统计

### 7.2 后台 Worker

- FastAPI lifespan 中启动 asyncio 循环，轮询 `analysis_task` 领取 pending 任务（领取即置 running），执行后置 success/failed
- 失败自动重试最多 3 次（`attempt_count`），最终失败记录错误原因，页面可人工重试
- 进程启动时将遗留 running 任务重置为 pending（断点恢复；任务状态只在数据库，不在内存）
- LLM 并发度可配置（默认 3—5）
- 任务完成后由 Worker 触发下游阶段建任务（视频语境完成 → 建该视频评论批任务；某用户全部依赖就绪 → 建用户分析任务）

### 7.3 幂等与重新分析

- 幂等键：`task_type + target_type + target_id + skill_version`，同对象同版本不重复执行
- Prompt/标准变化 → 升级 Skill 版本号 → 对历史数据自动产生新任务重新分析，旧结果保留可对比

------

## 8. 业务应用层（L5）

### 8.1 页面（Jinja2 服务端渲染 + 原生 JS 轮询）

1. **任务页 `/`**：上传 Excel 导入（显示新增/跳过统计）；启动分析；各阶段任务进度计数；失败任务列表与重试按钮
2. **线索列表 `/leads`**：昵称、平台、等级、品牌车型、摘要、核心需求、主要顾虑、置信度、来源视频、分析时间、审核状态；按等级/品牌/车型/审核状态筛选；导出 CSV（UTF-8 BOM）
3. **线索详情 `/leads/{id}`**：用户全部有效评论及所在视频、每条评论筛选结果、意向画像、分级理由、销售切入点、待确认问题、置信度、原始证据；页内人工审核操作

### 8.2 人工审核

- `review_status`：未审核 / 有效 / 无效
- `review_tags` 多选：等级偏高、等级偏低、疑似水军、无真实购车需求、画像错误、切入点无价值
- `review_note`：自由备注
- 审核数据仅存库，作为 Prompt 优化样本、Few-shot 案例和回归测试集来源，不自动回灌模型

### 8.3 JSON API

`POST /api/import`、`POST /api/analysis/start`、`GET /api/analysis/progress`、`POST /api/tasks/{id}/retry`、`GET /api/leads`（筛选+分页）、`GET /api/leads/{id}`、`POST /api/leads/{id}/review`、`GET /api/leads/export`

------

## 9. 错误处理汇总（承接 README 第 8 章）

| 异常 | 处理 |
|---|---|
| LLM 超时 / 网络异常 | Gateway 层自动重试 2—3 次 |
| JSON 解析失败 / Schema 不符 / 空返回 | 执行器层自动修复尝试 → 重新调用 → 多次失败标 failed |
| 批次输出与输入 ID 不一致 | 整批重试 → 拆半重试 → 标 failed |
| 任务多次失败 | 记录错误原因，页面人工重试 |
| 进程重启 | running 任务重置 pending 续跑 |
| 全部 LLM 调用 | 落 `llm_call_log`（模型、token、耗时、错误、重试次数） |

------

## 10. 测试与评测

### 10.1 自动化测试（全部基于 MockProvider，不依赖真实 LLM）

- **单元测试**：导入幂等；话题标签解析；空评论跳过；用户聚合统计；三个 Skill 输出 Schema 校验；批次 ID 一致性校验；任务重试、断点恢复逻辑
- **集成测试**：小样本数据跑通"导入 → 视频语境 → 评论筛选 → 聚合 → 用户分析 → lead 产出"全流程

### 10.2 真实模型联调

实现阶段最后进行：配置真实 LLM，用真实数据抽样子集（2—3 个视频）跑通并进行 Prompt 初步调优。

### 10.3 评测脚手架（V0 轻量版）

- 标注模板 CSV：评论 ID、人工判定（是否有意义/是否购车相关/意向强度等）
- 评测脚本：对照人工标注计算——无意义评论过滤准确率、购车相关识别准确率、H 级准确率、H/A 级合并准确率、JSON 输出合格率、平均单评论/单用户分析成本
- 标注集由业务方在系统产出结果后标注，不阻塞开发

------

## 11. 配置项（.env）

```
# 数据库
DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME

# LLM（OpenAI 兼容）
LLM_PROVIDER=openai_compat | mock
LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
LLM_TIMEOUT_SECONDS / LLM_MAX_RETRIES

# Worker
WORKER_CONCURRENCY=3
COMMENT_BATCH_SIZE=30
```

------

## 12. 与 README 的差异说明

| README 内容 | V0 处理 |
|---|---|
| UserProfileSnapshot / 工作流步骤五（获取用户主页） | V0 移除该步骤，Schema 与 Skill 输入预留可选字段 |
| PostgreSQL | 按用户决策改为 MySQL |
| 点赞数、回复数、账号类型、视频发布时间等字段 | 表结构保留为可空字段，当前数据源没有则为空 |
| N/S 等级展示 | 仅保存于分析结果，不进线索列表 |

其余设计（五层逻辑架构、三个 Skill、固定工作流、H/A/B/C 标准、证据驱动、幂等与多版本）均与 README 保持一致。
