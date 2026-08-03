# DriveIntent 版本文档体系规范化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `claude_docs/versions/` 树形版本文档目录，迁移 13 份历史文档，新写 VERSIONING.md 与 V0/V1 两份 OVERVIEW.md，最小化更新 CLAUDE.md。

**Architecture:** 纯文档任务，不改任何代码、测试与 README。迁移用 `git mv` 保留历史；新文档内容在本计划中给出完整落稿。上游设计：`claude_docs/2026-08-03-versioning-design.md`。

**Tech Stack:** git、Markdown。

## Global Constraints

- 全程简体中文撰写文档。
- 不修改 `app/`、`tests/`、`scripts/`、`README.md`、`docs/` 下任何文件。
- 所有新写/迁移文件均为 UTF-8 编码。
- CLAUDE.md 变更 ≤ 5 行。
- 本计划与设计文档（`2026-08-03-versioning-*.md`）属"非版本类文档"，留在 `claude_docs/` 根目录，不迁移。
- **对照表以本计划第 Task 2 中核实后的映射为准**（设计文档 §5 的初步判断有两处错误，已核实修正：三个核心 Prompt 的 v1 诞生于 V0；`image_recognition_v1` 诞生于 V1.0）。

---

### Task 1: 建立 versions 树并迁移 13 份历史文档

**Files:**
- Create: `claude_docs/versions/`（目录树）
- Move: 下表 13 份文件（`git mv`）
- Modify: 迁移后 6 份 plan 文件的首部（补元信息行）

**Interfaces:**
- Produces: `claude_docs/versions/V0|V1/...` 目录结构，后续 Task 的 OVERVIEW.md 相对链接以此为准。

- [ ] **Step 1: 创建目录并逐一 git mv**

迁移映射（严格按此执行）：

| 原路径（claude_docs/） | 新路径（claude_docs/versions/） |
|---|---|
| 2026-07-20-v0-design.md | V0/design.md |
| 2026-07-20-v0-plan.md | V0/plan.md |
| 2026-07-23-v1-design.md | V1/V1.0/design.md |
| 2026-07-23-v1-plan.md | V1/V1.0/plan.md |
| 2026-07-27-v1.1-design.md | V1/V1.1/design.md |
| 2026-07-27-v1.1-plan.md | V1/V1.1/plan.md |
| 2026-07-28-v1.1.1-design.md | V1/V1.1/v1.1.1-design.md |
| 2026-07-28-v1.2-design.md | V1/V1.2/design.md |
| 2026-07-28-v1.2-plan.md | V1/V1.2/plan.md |
| 2026-07-30-v1.2.1-design.md | V1/V1.2/v1.2.1-design.md |
| 2026-07-30-v1.2.1-plan.md | V1/V1.2/v1.2.1-plan.md |
| 2026-08-03-v1.3-design.md | V1/V1.3/design.md |
| 2026-08-03-v1.3-plan.md | V1/V1.3/plan.md |

PowerShell 执行：

```powershell
New-Item -ItemType Directory -Force claude_docs/versions/V0, claude_docs/versions/V1/V1.0, claude_docs/versions/V1/V1.1, claude_docs/versions/V1/V1.2, claude_docs/versions/V1/V1.3
git mv claude_docs/2026-07-20-v0-design.md claude_docs/versions/V0/design.md
git mv claude_docs/2026-07-20-v0-plan.md claude_docs/versions/V0/plan.md
git mv claude_docs/2026-07-23-v1-design.md claude_docs/versions/V1/V1.0/design.md
git mv claude_docs/2026-07-23-v1-plan.md claude_docs/versions/V1/V1.0/plan.md
git mv claude_docs/2026-07-27-v1.1-design.md claude_docs/versions/V1/V1.1/design.md
git mv claude_docs/2026-07-27-v1.1-plan.md claude_docs/versions/V1/V1.1/plan.md
git mv claude_docs/2026-07-28-v1.1.1-design.md claude_docs/versions/V1/V1.1/v1.1.1-design.md
git mv claude_docs/2026-07-28-v1.2-design.md claude_docs/versions/V1/V1.2/design.md
git mv claude_docs/2026-07-28-v1.2-plan.md claude_docs/versions/V1/V1.2/plan.md
git mv claude_docs/2026-07-30-v1.2.1-design.md claude_docs/versions/V1/V1.2/v1.2.1-design.md
git mv claude_docs/2026-07-30-v1.2.1-plan.md claude_docs/versions/V1/V1.2/v1.2.1-plan.md
git mv claude_docs/2026-08-03-v1.3-design.md claude_docs/versions/V1/V1.3/design.md
git mv claude_docs/2026-08-03-v1.3-plan.md claude_docs/versions/V1/V1.3/plan.md
```

- [ ] **Step 2: 为缺少日期的文件补元信息行**

已核实：7 份 design 文档首部均已有"日期"字段，**不补**。6 份 plan 文档（V0、V1.0、V1.1、V1.2、v1.2.1、V1.3 的 plan）首部无日期，在标题行（`# ...`）之后紧跟一行插入：

| 文件 | 插入行 |
|---|---|
| V0/plan.md | `> 版本：V0 \| 日期：2026-07-20` |
| V1/V1.0/plan.md | `> 版本：V1.0 \| 日期：2026-07-23` |
| V1/V1.1/plan.md | `> 版本：V1.1 \| 日期：2026-07-27` |
| V1/V1.2/plan.md | `> 版本：V1.2 \| 日期：2026-07-28` |
| V1/V1.2/v1.2.1-plan.md | `> 版本：V1.2.1 \| 日期：2026-07-30` |
| V1/V1.3/plan.md | `> 版本：V1.3 \| 日期：2026-08-03` |

用 Edit 工具逐个插入（先 Read 各文件前 5 行确认标题行内容）。注意 plan 文件标题下已有 `> **For agentic workers:**` 引用行的，元信息行插在标题行与该引用行之间。

- [ ] **Step 3: 验证**

```powershell
Get-ChildItem claude_docs -File | Select-Object Name
Get-ChildItem claude_docs/versions -Recurse -File | Select-Object FullName
git log --follow --oneline -3 -- claude_docs/versions/V1/V1.3/design.md
```

Expected：`claude_docs` 根目录只剩 `2026-08-03-versioning-design.md`（及本计划文件）；versions 树含 13 份文件且与映射表一致；`git log --follow` 能看到迁移前的历史提交。

- [ ] **Step 4: Commit**

```powershell
git add -A claude_docs
git commit -m @'
docs: 建立 claude_docs/versions 树形目录并迁移 13 份历史版本文档

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 2: 撰写 VERSIONING.md

**Files:**
- Create: `claude_docs/versions/VERSIONING.md`

**Interfaces:**
- Produces: 常驻版本管理规范，Task 4 中 CLAUDE.md 将引用其路径 `./claude_docs/versions/VERSIONING.md`。

- [ ] **Step 1: 写入 VERSIONING.md（完整落稿如下）**

````markdown
# DriveIntent 版本管理规范

> 本文档是项目版本号、版本文档目录、代码内版本化资产命名的唯一规范。每次发版按文末检查清单执行。制定于 2026-08-03（设计见 `../2026-08-03-versioning-design.md`）。

## 1. 版本号体系

版本号形如 `V<大>.<小>.<补丁>`，三段语义：

- **大版本**（V0 → V1 → V2…）：架构级演进（如 V0 demo → V1 微服务化）。
- **小版本**（V1.1、V1.2…）：功能迭代。
- **补丁版**（V1.1.1、V1.2.1…）：小修正、契约微调、bugfix。

## 2. 版本文档目录结构

```
claude_docs/versions/
├── VERSIONING.md            # 本规范
├── V0/
│   ├── OVERVIEW.md          # 大版本上层文档
│   ├── design.md
│   └── plan.md
└── V1/
    ├── OVERVIEW.md
    ├── V1.0/                # 大版本首发归入 V<大>.0
    │   ├── design.md
    │   └── plan.md
    ├── V1.1/
    │   ├── design.md
    │   ├── plan.md
    │   └── v1.1.1-design.md # 补丁版文档以完整版本号前缀落入所属小版本目录
    └── ...
```

规则：

1. 大版本为第一层目录，小版本为第二层；不建第三层，补丁版文档以 `v<完整版本号>-` 前缀（如 `v1.2.1-design.md`）落入所属小版本目录。
2. 版本目录内标准文档名为 `design.md`、`plan.md`（目录路径已编码版本号，文件名不重复编码）。
3. 每份文档首部须含版本与日期元信息（标题下 `> 版本：Vx.y | 日期：YYYY-MM-DD`，或文档头部已有等效字段）。
4. `claude_docs/` 根目录只存放 `versions/` 与非版本类文档（如横切规范的设计文档）。

## 3. 大版本上层文档（OVERVIEW.md）

每个大版本目录维护一份 `OVERVIEW.md`，含两部分：

1. **能力快照**：该大版本当前最新状态——定位、核心功能、架构要点、对外契约现状、各 Skill/Prompt 版本对照。只写"现在是什么"，不写演进过程。
2. **变更索引**：一行一版本——版本号、日期、一句话变更摘要、design/plan 相对链接。

**更新规则**：每次小版本/补丁版落地时，必须同步更新所属大版本 OVERVIEW.md（变更索引加行；能力快照改写被本版本改变的部分）。新开大版本时先建 OVERVIEW.md 骨架再落第一个小版本。

骨架模板：

```markdown
# V<N> 版本总览

> 最后更新：YYYY-MM-DD（随 V<N>.<x> 发布）

## 能力快照

- **定位**：…
- **核心功能**：…
- **架构要点**：…
- **对外契约**：…
- **Skill/Prompt 版本对照**：（表格）

## 变更索引

| 版本 | 日期 | 变更摘要 | 文档 |
|---|---|---|---|
| V<N>.0 | YYYY-MM-DD | … | [design](V<N>.0/design.md) / [plan](V<N>.0/plan.md) |
```

## 4. 代码内版本化资产命名规则

**自 2026-08-03 起对新改动生效，不回溯**。适用于所有随项目版本演进的版本化资产——当前为 Prompt 文件与 Skill 配置版本字段；未来出现同类资产（如版本化输出 Schema）同样适用。

1. **Prompt 文件名**：Prompt 内容变更时，新文件命名为 `<skill_id>_v<项目版本号>.txt`（如 V1.3.1 修改用户分析 Prompt → 新增 `user_lead_analysis_v1.3.1.txt`）。旧文件保留不动、不再被引用。
2. **`prompt_version` 字段**：随新文件同步为 `"v<项目版本号>"`（如 `"v1.3.1"`），YAML 配置与落库值一致。
3. **Skill 配置 `version` 字段**：Skill 行为（Prompt、模型参数、输出契约等任一项）变更时，直接写引入变更的项目版本号（如 `"1.3.1"`），不再自成体系。
4. **同一版本多次修改**：一个项目版本开发周期内多次调整同一 Prompt，只留该版本号命名的最终一份，不产生中间文件。
5. **语义**：版本后缀表示"该资产最后一次变更发生在哪个项目版本"。未改动的资产保持旧版本号是正常状态，无需追平。

### 旧口径对照表（历史数据查询参考）

规则生效前的存量 Prompt 版本号为顺延式（v1、v2…），与项目版本映射如下（数据库历史记录中的旧 `prompt_version` 值不迁移，新旧口径并存）：

| Skill | 现行 prompt | 旧口径序列 → 引入版本 |
|---|---|---|
| comment_lead_screening | v3 | v1→V0，v2→V1.1，v3→V1.3 |
| video_context_analysis | v2 | v1→V0，v2→V1.1 |
| user_lead_analysis | v5 | v1→V0，v2→V1.1，v3→V1.2，v4→V1.2.1，v5→V1.3 |
| image_recognition | v2 | v1→V1.0，v2→V1.2 |

Skill 配置 `version` 字段存量值：`comment_lead_screening "1.3"`、`video_context_analysis "1.1"`、`user_lead_analysis "1.3"`、`image_recognition "2.0"`（自成体系旧号，对应 V1.2 引入的识图 v2）。

## 5. 发版检查清单

每次版本落地（design/plan 评审通过、代码合入）时依序核对：

- [ ] 小版本：`versions/V<大>/V<大>.<小>/` 下落 `design.md`（及 `plan.md`，如有）
- [ ] 补丁版：`v<完整版本号>-design.md`（及 plan）落入所属小版本目录
- [ ] 文档首部含版本与日期元信息
- [ ] 更新所属大版本 `OVERVIEW.md`：变更索引加行 + 能力快照改写受影响部分
- [ ] 代码中被修改的 Prompt 文件 / `prompt_version` / Skill `version` 按本规范第 4 节命名
- [ ] 涉及架构/核心数据结构/跨模块契约变更时，同步更新 claude_docs 相关文档（CLAUDE.md 既有规范）
````

- [ ] **Step 2: 验证**

Read `claude_docs/versions/VERSIONING.md` 首尾各 20 行，确认无乱码、相对链接路径正确（`../2026-08-03-versioning-design.md` 存在）。

- [ ] **Step 3: Commit**

```powershell
git add claude_docs/versions/VERSIONING.md
git commit -m @'
docs: 新增版本管理规范 VERSIONING.md

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 3: 撰写 V0 与 V1 的 OVERVIEW.md

**Files:**
- Create: `claude_docs/versions/V0/OVERVIEW.md`
- Create: `claude_docs/versions/V1/OVERVIEW.md`

**Interfaces:**
- Consumes: Task 1 的目录结构（相对链接指向 `V1.0/design.md` 等）。

- [ ] **Step 1: 写入 V0/OVERVIEW.md（完整落稿如下）**

````markdown
# V0 版本总览

> 最后更新：2026-08-03（V0 已冻结，仅结构化归档）

## 能力快照

- **定位**：MVP 验证工程——端到端闭环：导入抖音评论 Excel → 三个 LLM Skill 分析（视频语境 / 评论初筛 / 用户定级）→ 产出 H/A/B/C 销售线索 → 8000 端口页面查看/审核/CSV 导出。
- **架构要点**：单体 FastAPI + MySQL，库中心流水线（导入落库 → 任务表 → Worker → lead 表 → 服务端渲染页面）。
- **状态**：已合入 main 并冻结；V1 起 8000 链路作为测试链路保留。

## 变更索引

| 版本 | 日期 | 变更摘要 | 文档 |
|---|---|---|---|
| V0 | 2026-07-20 | MVP 端到端闭环首版 | [design](design.md) / [plan](plan.md) |
````

- [ ] **Step 2: 写入 V1/OVERVIEW.md（完整落稿如下）**

````markdown
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
````

- [ ] **Step 3: 验证**

逐一检查两份 OVERVIEW 中的相对链接目标文件存在：

```powershell
Test-Path claude_docs/versions/V0/design.md, claude_docs/versions/V0/plan.md, claude_docs/versions/V1/V1.0/design.md, claude_docs/versions/V1/V1.1/v1.1.1-design.md, claude_docs/versions/V1/V1.2/v1.2.1-plan.md, claude_docs/versions/V1/V1.3/plan.md, claude_docs/versions/VERSIONING.md
```

Expected：全部 True。

- [ ] **Step 4: Commit**

```powershell
git add claude_docs/versions/V0/OVERVIEW.md claude_docs/versions/V1/OVERVIEW.md
git commit -m @'
docs: 补写 V0/V1 大版本总览（能力快照+变更索引）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 4: 最小化更新 CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`（"2. 工作规范"一节，两处）

- [ ] **Step 1: 修改归档条目并新增规范引用行**

用 Edit 将：

```
- 新版本的需求分析、模块设计、任务规划等重量级更新，讨论明确后归档到./claude_docs目录。轻量级的代码改动/bug修复可以直接执行，不写文档
```

替换为：

```
- 新版本的需求分析、模块设计、任务规划等重量级更新，讨论明确后归档到./claude_docs/versions对应版本目录。轻量级的代码改动/bug修复可以直接执行，不写文档
- 版本目录结构、版本文档职责、代码内版本命名（Prompt/Skill 版本号跟随项目版本号）遵循./claude_docs/versions/VERSIONING.md，每次发版按其检查清单执行
```

- [ ] **Step 2: 验证**

Read CLAUDE.md 全文，确认：仅上述两行变化（净增 1 行，≤ 5 行约束满足）；其余内容未动。

- [ ] **Step 3: Commit**

```powershell
git add CLAUDE.md
git commit -m @'
docs: CLAUDE.md 引用版本管理规范 VERSIONING.md

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

## 验收标准（对照设计文档 §9）

- `claude_docs/` 根目录不再有平铺的版本 design/plan 文档（仅剩 versioning 设计文档与本计划）；
- 任一历史版本文档可通过 `versions/V*/V*.*/` 路径直达；
- `V1/OVERVIEW.md` 能独立回答"当前 V1 是什么"并索引全部 6 个版本；
- VERSIONING.md 规则完整、检查清单可执行、对照表为核实后的正确映射；
- CLAUDE.md 变更 ≤ 5 行；
- `git log --follow` 可追溯迁移文档历史。
