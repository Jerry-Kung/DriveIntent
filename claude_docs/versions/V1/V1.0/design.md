# DriveIntent V1（1.0 正式版）设计文档

**文档版本：** 1.0
**日期：** 2026-07-23
**状态：** 已评审通过
**上游文档：** `docs/DriveIntent服务对接文档.md`（对接契约 v1.0）、`claude_docs/2026-07-20-v0-design.md`（V0 设计）

------

## 1. 目标与范围

V1 目标：把 DriveIntent 从 demo 验证工程升级为**可通过 docker compose 独立部署的 Python 后端微服务**，对外通过 API 提供两个 Agent 能力，与系统其他部分对接。

### 1.1 核心决策

| 决策项 | 结论 |
|---|---|
| 服务形态 | 同一 FastAPI 应用同时提供：V1 对外 API（`/api/v1/*`）+ 保留的 V0 测试页面/流水线（8000）。docker compose 打包一个应用服务 + 一个 MySQL |
| 异步模式 | 纯异步 + 轮询：提交作业返回 `job_id`，轮询 `GET /api/v1/jobs/{job_id}` 取状态与结果 |
| 认证 | 静态 API Key，`Authorization: Bearer <key>`，`.env` 配置 `API_KEYS`（逗号分隔可多个） |
| 持久化 | 保留 MySQL；API 作业落新表 `api_job`，支持重启恢复与历史查询 |
| 字段适配 | 保留 V0 内部丰富分析结构（四维判断、H/A/B/C、证据链），仅在 API 边界映射为文档要求的 `passed`/`has_value`/`intent_level` 等结构 |
| 视频语境 | 保留 V0「视频语境分析」Skill；Agent 1 内部按视频分组先跑语境再跑评论筛选 |
| 视觉能力 | 同一多模态 LLM 端点，`.env` 单模型配置；新增 `image_recognition` Skill 识别主页截图 |
| lead 表写入 | 外部 API 调用**不写** V0 的 lead 线索表；lead 表 + 线索页面仅由 8000 测试链路使用 |

### 1.2 明确不做

- V1 不做前后端分离（8000 测试页面仍服务端渲染）。
- API 路径不写 lead 表、不进 V0 线索页面。
- 不做多租户、登录权限（仅静态 API Key）。
- 不改动 V0 已验证的 lead 生成、人工审核、CSV 导出逻辑。

------

## 2. 总体架构：两条数据路径并存

V0 是**库中心**流水线（导入落库 → 任务表 → Worker → lead 表 → Web 页面）。对接文档的两个 Agent 是**无状态批量接口**（请求自带全部数据，不依赖导入库）。V1 让两条路径并存、共享底层能力。

| 路径 | 入口 | 数据来源 | 产出 | 状态 |
|---|---|---|---|---|
| **API 路径** | `/api/v1/*` | 请求 payload 自带 | 轮询返回 JSON，不写 lead 表 | V1 新增 |
| **流水线路径** | `/`、`/leads`、`/api/import` 等 | 导入落库 | lead 表 + Web 页面 | V0 保留 |

**共享层**（两条路径复用同一套代码）：LLM Gateway、Skill 执行器、Prompt 模板、三个 Skill（视频语境 / 评论筛选 / 用户分析）+ 新增 `image_recognition` Skill。

区别仅在于：数据从哪来（payload vs DB）、结果去哪（轮询返回 vs lead 表）。V0 测试链路完全保留，V1 是叠加而非重写。

```
                 ┌──────────────── 共享层 ────────────────┐
API 路径 ─┐      │  LLM Gateway (含多模态)                 │
          ├──→   │  Skill 执行器 + Prompt 模板             │  ←─┐
8000 路径 ┘      │  Skills: 视频语境/评论筛选/用户分析/识图 │    ├─ 流水线路径
                 └────────────────────────────────────────┘
API 路径:   api_job 表 + ApiJobWorker  → 轮询返回
流水线路径: analysis_task 表 + Worker   → lead 表 + Web 页面
```

------

## 3. 两个异步 API 契约

### 3.1 提交作业

**Agent 1 — 评论价值初筛**
- `POST /api/v1/comment-screening`
- 请求体：对接文档定义的 `{comments: [CommentObject, ...]}`
- 响应（202）：`{"job_id": "<uuid>", "status": "pending", "type": "comment_screening"}`

**Agent 2 — 账号画像精筛**
- `POST /api/v1/profile-analysis`
- 请求体：对接文档定义的 `{accounts: [AccountObject, ...]}`
- 响应（202）：`{"job_id": "<uuid>", "status": "pending", "type": "profile_analysis"}`

### 3.2 统一轮询

- `GET /api/v1/jobs/{job_id}`
- 响应：

```json
{
  "job_id": "b3f...",
  "type": "comment_screening",
  "status": "pending|running|success|partial|failed",
  "progress": {"total": 100, "done": 100},
  "result": { "results": [ ... ] },
  "error": null,
  "created_at": "2026-07-23T10:00:00+08:00",
  "finished_at": "2026-07-23T10:03:20+08:00"
}
```

- `result` 在 `status ∈ {success, partial}` 时有值，结构为对接文档定义的输出（`{results: [...]}`）。
- `status` 语义：
  - `pending`：已入队未开始
  - `running`：处理中（`progress` 反映进度）
  - `success`：全部条目成功
  - `partial`：批内部分条目失败但整体可用，失败条目在 `result.results[]` 内以 `error` 字段单独标注
  - `failed`：整单失败（`error` 有值，`result` 为 null）

### 3.3 健康检查

- `GET /health`：返回 `{"status": "ok"}`，不需认证，供 compose/负载均衡探活。

### 3.4 认证与错误码

- 除 `/health` 外，`/api/v1/*` 需 `Authorization: Bearer <key>`，key 命中 `.env` 的 `API_KEYS` 列表之一。
- 错误码（沿用对接文档）：

| 错误码 | 说明 |
|---|---|
| `400` | 请求参数不合法（字段缺失/类型错误） |
| `401` | 认证失败（缺失/非法 API Key） |
| `404` | job_id 不存在 |
| `429` | 请求频率超限 |
| `500` | 服务内部错误 |

------

## 4. API 作业模型与执行

### 4.1 新增表 `api_job`

独立于 V0 的 `analysis_task`，两者互不干扰。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | String(36) PK | UUID |
| `job_type` | String(32) | `comment_screening` / `profile_analysis` |
| `status` | String(16) | pending / running / success / partial / failed |
| `request_payload` | JSON | 原始请求体 |
| `result` | JSON | 输出结构（对接文档格式） |
| `progress_total` | Integer | 总条目数 |
| `progress_done` | Integer | 已完成条目数 |
| `error` | Text | 整单失败原因 |
| `attempt_count` | Integer | 尝试次数 |
| `max_attempts` | Integer | 默认 3 |
| `created_at` / `updated_at` / `finished_at` | DateTime | 时间戳 |

### 4.2 执行：ApiJobWorker

- 新增 `ApiJobWorker`，与 V0 Worker 同样在 FastAPI `lifespan` 中随 asyncio 启动，轮询 `api_job` 领取 pending 作业（领取即置 running）。
- 复用 V0 已验证机制：并发度可配、失败自动重试（最多 3 次）、进程启动时将遗留 running 重置为 pending（断点恢复，状态只在库）。
- 作业执行完写回 `result` 与 `status`，`finished_at` 落时间戳。
- 两个 Worker 共享 LLM Gateway 与 Skill 执行器实例。

------

## 5. Agent 内部处理流程

### 5.1 Agent 1：comment-screening

1. **视频分组与语境**：从 payload comments 中按 `video_title`（+ `video_author`）提取唯一视频，对每个视频跑一次**视频语境 Skill**，结果在本 job 内缓存复用。`video_metrics`、`video_author_fans` 等作为语境 Skill 的补充输入（丰富热度背景）。
2. **批量筛选**：按批（默认 30 条/批，`COMMENT_BATCH_SIZE` 可配）跑**评论筛选 Skill**，沿用 V0 的批次 ID 一致性校验 + 整批重试 + 拆半递归防错位机制。
3. **边界映射**到文档输出结构（`ScreeningResult`）：

| 文档字段 | 映射来源 |
|---|---|
| `comment_id` | 原样透传 |
| `passed` | `is_meaningful and not is_suspected_marketing`（且非纯无关噪声） |
| `filter_reason` | 内部四维判断 → 文档枚举：`批量刷屏水军` / `广告/引流类评论` / `无实质内容` / `重复内容评论`；`passed=true` 时为 `null` |
| `analysis` | 筛选 Skill 的 `reason` 扩写至 200-500 字（Prompt 增补长度要求） |
| `processed_at` | 处理时间戳 |

内部丰富字段（`intent_strength`、`target_brand`、`is_purchase_related` 等）保留在内部结果中，不在 API 输出暴露。

### 5.2 Agent 2：profile-analysis

1. **主页截图识别**：`account_homepage_screenshot` 非空 → 跑一次 `image_recognition` Skill（多模态 LLM），得到主页可见信息的文字描述；为空 → 跳过并标记降级。
2. **用户分析**：用 payload 的 `comment_history` + 识图文字 + 分级标准，跑**用户分析 Skill**。此处使用 **payload 版 evidence 构造器**（直接从请求组装，不走 V0 的 DB 聚合）。
3. **空值降级**：`comment_history` 为空 → 直接 `has_value=false`，不调用 LLM（对齐文档「评论历史为空无法画像」）。
4. **边界映射**到文档输出结构（`ProfileResult`）：

| 文档字段 | 映射来源 |
|---|---|
| `account_uid` | 原样透传 |
| `has_value` | `is_valid_lead` |
| `intent_level` / `intent_level_code` | H→高/`high`，A→中/`medium`，B→低/`low`，C→`has_value=false`（无值） |
| `value_score` | 等级基准分（high 85-100 / medium 70-84 / low 50-69）+ confidence 微调；主页截图缺失时按文档降 10-15 分 |
| `profile_tags` | 用户分析 Skill 直接产出（Prompt 增补标签要求） |
| `profile_summary` | 用户分析 Skill 产出的 150-300 字摘要 |
| `analysis` | 用户分析 Skill 产出的 300-500 字分析过程 |
| `processed_at` | 处理时间戳 |

**等级映射说明**：文档为高/中/低三级 + 无价值，V0 为 H/A/B/C 四级。采用 H→高、A→中、B→低、C→无价值的对应关系（C 级弱相关归为无线索价值）。

------

## 6. 多模态 LLM 扩展

- `account_homepage_screenshot` 支持 **URL 或 Base64**（对接文档两种都允许）。
- 扩展 LLM Gateway / Provider：`chat` 的 messages 支持 OpenAI 标准的多模态 content 块（`{"type": "image_url", "image_url": {"url": "..."}}`）。同一多模态模型端点，`.env` 单模型配置即可。
- 新增 `image_recognition` Skill：Prompt 要求详尽、客观描述主页截图中所有可见信息（昵称、头像特征、简介、已发布视频标题/主题、互动数据等），输出为结构化文字，作为用户分析的参考输入。
- **兼容性**：URL 不可达 / Base64 解析失败 / 视觉模型报错 → 记录并降级为「无截图」路径，不使整单失败。
- **MockProvider**：补充图像分支，识别到 image content 块时返回预置文字描述，保证无真实模型时端到端测试可跑。

------

## 7. 8000 测试服务适配

保留全部 Web 页面（任务页 `/`、线索列表 `/leads`、线索详情 `/leads/{id}`）与流水线、人工审核、CSV 导出。调整点：

1. **双输入格式导入**：
   - 原始 xlsx：沿用现有解析，内部转标准结构；对接文档新增字段（video_metrics、comment_like_count、author_fans 等）在 xlsx 缺失时置空/补默认值。
   - **新版 JSON 文本文件**：与对接文档字段对齐的评论/账号结构，可直接作为导入源（内部转为标准导入结构）。
2. **内部数据结构对齐**：L1 表（video/comment）补充对接文档相关的可空字段（video_metrics、comment_like_count 等），保持 `raw_data` 完整保存原则。
3. lead 页面、审核、导出逻辑不变。

------

## 8. 项目结构变更（增量）

```
app/
├── api/                    # V1 新增：对外 API 路径
│   ├── routes.py           #   /api/v1/* 路由 + 认证依赖
│   ├── schemas.py          #   对接文档的输入/输出 Pydantic 模型
│   ├── jobs.py             #   api_job CRUD + 状态机
│   ├── worker.py           #   ApiJobWorker
│   ├── agent1.py           #   comment-screening 编排 + 边界映射
│   ├── agent2.py           #   profile-analysis 编排 + 边界映射
│   └── mapping.py          #   内部结构 → 文档结构映射
├── models/api_job.py       # V1 新增：api_job 表
├── skills/
│   ├── configs/image_recognition.yaml    # V1 新增
│   └── prompts/image_recognition_v1.txt  # V1 新增
├── llm/                    # 扩展：多模态 content 块支持
├── importer/               # 扩展：JSON 文本导入 + 新字段
└── ...（其余 V0 保留）
docker-compose.yml          # V1 新增
Dockerfile                  # V1 新增
.env.example                # 扩展：API_KEYS、多模态模型配置
```

依赖方向：`api/routes → api/worker → api/agent{1,2} → skills → llm`，与 V0 分层一致。API 路径不依赖 V0 的 `services/leads`、`services/aggregation`（DB 聚合）。

------

## 9. 配置项（.env 新增/变更）

```
# V1 API
API_KEYS=key1,key2              # 逗号分隔，Bearer 认证
API_WORKER_ENABLED=true
API_WORKER_CONCURRENCY=3

# 多模态 LLM（复用现有 LLM_* 单模型端点，需支持图像输入）
# LLM_PROVIDER / LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 沿用

# 图像输入
IMAGE_FETCH_TIMEOUT_SECONDS=30  # URL 截图下载超时
```

------

## 10. Docker Compose 部署

- `Dockerfile`：Python 3.11 slim，装 requirements，uvicorn 启动。
- `docker-compose.yml`：
  - `app`：FastAPI（含 API 路径 + 8000 测试链路 + 两个 Worker），依赖 mysql healthy 后启动。
  - `mysql`：MySQL 8，data volume 持久化，健康检查。
- 启动时自动建表（`init_db` 已有，补 `api_job`）。
- `app` 暴露健康检查 `/health`。

------

## 11. 错误处理汇总

| 异常 | 处理 |
|---|---|
| API 请求参数不合法 | 400，Pydantic 校验错误明细 |
| 认证失败 | 401 |
| job_id 不存在 | 404 |
| LLM 超时/网络 | Gateway 层自动重试 2-3 次（沿用 V0） |
| 批次 ID 不一致 | 整批重试 → 拆半 → 标记条目失败（partial） |
| 主页截图不可达/解析失败/视觉模型错误 | 降级为无截图路径，value_score 降分，不整单失败 |
| 评论历史为空 | has_value=false，不调 LLM |
| API 作业多次失败 | status=failed，error 记录原因 |
| 进程重启 | api_job running 重置 pending 续跑 |
| 全部 LLM 调用 | 落 `llm_call_log`（沿用 V0） |

------

## 12. 测试

### 12.1 单元测试（MockProvider，不依赖真实 LLM）

- API 契约：输入 Schema 校验、输出结构符合对接文档。
- 边界映射：各过滤原因枚举、各意向等级（H/A/B/C → 高/中/低/无价值）、value_score 计算与降分。
- payload evidence 构造器（Agent 2 不走 DB）。
- 降级：空截图、空评论历史、图像 content 块组装。
- 认证：无 key/错误 key → 401。

### 12.2 集成测试（MockProvider）

- 提交 comment-screening job → 轮询到 success → 校验输出结构与条目一一对应。
- 提交 profile-analysis job（带图 / 不带图两种）→ 轮询到 success → 校验输出。
- api_job 断点恢复：running 重置 pending 续跑。

### 12.3 真实模型联调（实现阶段最后）

- 配置真实多模态 LLM，用真实截图 + 评论子集跑通两个 API，做 Prompt 初步调优。

------

## 13. 与 V0 的关系

- V0 三 Skill、Prompt、LLM Gateway、Worker 机制、lead 流水线、Web 页面**全部保留**。
- V1 在其上叠加 API 路径（新表、新 Worker、新路由、边界映射）+ 多模态能力 + JSON 导入 + docker 部署。
- 两条路径共享 Skill 与 Gateway，互不写对方存储。
