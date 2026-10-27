# DriveIntent V1.3 设计文档

**文档版本：** 1.3
**日期：** 2026-08-03
**状态：** 已评审通过
**上游文档：** `claude_docs/2026-07-30-v1.2.1-design.md`（V1.2.1 设计）、`claude_docs/2026-07-27-v1.1-design.md`（V1.1 设计，含视频语境降级）、`docs/DriveIntent-V1-API对接文档.md`（对接契约）

---

## 1. 目标与范围

V1.3 解决三个需求：

1. **两个独立分析标签**：为评论（Agent1）与账号（Agent2）各增加"是否车主"（`is_car_owner`）与"购车意向"（`has_purchase_intent`）两个独立布尔标签，写入数据库与对外 API 结果。
2. **初筛流程优化**：有购车意向者必过初筛；无意向车主（纯讨论/吐槽）原则上不过筛；无意向非车主视积极信号决定。`filter_type` 枚举同步调整：取消 `model_mismatch` / `existing_owner` / `ordered_owner`，新增 `no_purchase_intent`。
3. **bugfix（非本人意向识别）**：替他人问询、怂恿他人购买、营销推广口吻不得作为本人购车信号，初筛与定级阶段均需识别并降级处理。

**总体架构（方案 A，已评审确认）**：LLM 负责"判断"（输出标签与信号），代码层负责"规则"（确定性合成 `filter_type` 与 `passed`）——"有购车意向必过筛"等硬规则由代码保证，不依赖 LLM 自觉。与现有 `resolve_filter_type()` 合成模式一致。

### 1.1 标签语义（需求方确认的关键口径）

- **`is_car_owner`（是否车主）**：仅判断发布者**是否已购买车辆**（已下单/下大定也算已购车），**不要求**已购我方在售车型。有明确证据表明大概率有车 → `true`，否则 `false`。
- **`has_purchase_intent`（购车意向）**：仅判断发布者**是否表达了买车相关倾向**，**不要求**指向我方在售车型或与之匹配。表达出任何购买相关倾向 → `true`，否则 `false`。
- 两标签相互独立、可任意组合；Agent1 按单条评论判定，Agent2 综合该账号全部历史评论（可结合主页画像）判定。

### 1.2 不做

- 不改视频语境分析技能（`video_context_analysis`）——Agent2 的意向车型识别仍依赖视频语境注入初筛提示词与用户证据包，此链路不变。
- 不改 Agent2 定级流水线结构——v4 三段流水线（基线 → 在售车型匹配度调整 → 画像上调）原样保留，"购车意向结合目标车型与在售车型匹配度定级"即现状行为。
- 不改 `app/matching/loader.py` / `app/matching/models.py`（Agent2 的 `our_models_summary` 仍依赖）。
- `Lead` 表不加列（YAGNI：`AnalysisResult.result` JSON 已完整落库两标签，Web 侧无新查询需求）。
- 不新增"意向主体"（本人/他人）结构化字段——非本人意向识别仅以提示词规则实现，理由写入 `reason` / `analysis_text`。

---

## 2. Agent1 LLM 输出契约（comment_lead_screening v3）

`CommentScreeningItem`（`app/schemas/skills.py`）变更：

| 字段 | 变更 | 说明 |
|------|------|------|
| `is_car_owner: bool = False` | 新增 | 见 1.1 口径 |
| `has_purchase_intent: bool = False` | 新增 | 见 1.1 口径 |
| `positive_attitude: bool = False` | 新增 | **内部信号**：非车主对车辆表达了兴趣/赞美类积极信号（如"内饰好看""底盘不错"），用于代码层决定无意向非车主是否过筛；**不进对外契约** |
| `owner_status` | 移除 | `none/existing_owner/ordered_owner` 三枚举由 `is_car_owner` 布尔替代 |
| 其余字段 | 不变 | `comment_actor` 五选一、`intent_strength`、`intent_signals`、`target_brand/model`、`reason`、`confidence` 及 V1.0 兼容字段 |

---

## 3. 初筛通过规则（代码层合成）

`app/api/mapping.py::resolve_filter_type()` 重写，优先级从高到低：

| 优先级 | 条件 | filter_type | passed |
|---|---|---|---|
| 1 | `comment_actor` ≠ `genuine_user` | `bot_spam` / `marketing_account` / `noise` / `off_topic` | false |
| 2 | `has_purchase_intent` = true | `genuine_user` | true |
| 3 | 无意向 + 车主 | `no_purchase_intent` | false |
| 4 | 无意向 + 非车主 + `positive_attitude` = true | `genuine_user` | true |
| 5 | 无意向 + 非车主 + 无积极信号 | `no_purchase_intent` | false |

- `passed` 与 `filter_type` 恢复严格一一对应：`genuine_user` → true，其余全部 → false（`model_mismatch` 这一 passed=true 的特例随字段取消而消失）。
- V1.0 旧字段兜底保留：LLM 未输出 `comment_actor` 时回退 `is_suspected_marketing` → `marketing_account`、`not is_meaningful` → `noise`（置于优先级 1 与 2 之间，语义与现状一致）。
- `map_screening_item()` 去除 `mismatch_reason` 参数；`filter_reason` 恒为 null。

---

## 4. 视频语境降级模块下线

`model_mismatch` 取消后（初筛不再考虑车型匹配），V1.1 引入的确定性降级模块同步下线：

| 对象 | 处理 |
|------|------|
| `app/matching/downgrade.py` | 删除（`evaluate_video_context` / `DowngradeDecision` 及全部内部函数） |
| `tests/test_matching_downgrade.py` | 删除 |
| `app/api/agent1.py` | 移除降级调用链（`load_our_models` / `evaluate_video_context` / `decisions` / `mismatch_reason`） |
| `app/config.py::intent_downgrade_enabled` | 删除 |
| `app/matching/loader.py` / `models.py` | **保留**（Agent2 `our_models_summary` 依赖） |
| `video_context_analysis` 技能 | **保留不动**（初筛提示词与用户证据包仍注入视频语境） |

**边界说明（评审时确认）**：下线的仅是"视频语境 × our_models.json 的代码层比对器"。Agent2 对意向车型的识别链路——视频语境技能 → 初筛 LLM 输出 `target_brand/model` → `build_user_evidence` 打包 `video_context` 进证据包 → v4/v5 与 `our_models_summary` 比较判档——完全不经过 downgrade.py，不受影响。

---

## 5. Agent1 对外契约（ScreeningResult）

每条结果新增两个字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `is_car_owner` | Boolean \| null | 是否车主；该条处理失败时为 null |
| `has_purchase_intent` | Boolean \| null | 是否有购车意向；该条处理失败时为 null |

`filter_type` 枚举与 `passed` 对应表（V1.3 对外契约）：

| filter_type | 含义 | passed |
|---|---|---|
| `genuine_user` | 真实用户，有购车意向或积极信号，通过初筛 | `true` |
| `no_purchase_intent` | **新增**：提到汽车相关内容但无购车意向/积极信号（车主纯讨论吐槽、非车主无兴趣表达） | `false` |
| `bot_spam` | 批量刷屏水军 | `false` |
| `marketing_account` | 营销号/广告引流 | `false` |
| `noise` | 无实质内容 | `false` |
| `off_topic` | 与汽车无关 | `false` |

对接文档"V1.3 契约变更"小节需写明：

- **移除** `model_mismatch` / `existing_owner` / `ordered_owner` 三个枚举值；车主状态改由独立字段 `is_car_owner` 表达。
- `passed` 与 `filter_type` 恢复严格一一对应，对接方不再需要处理 `model_mismatch` 这个 passed=true 的特例。
- `filter_reason` 字段**保留**在响应结构中但恒为 `null`（原唯一使用场景随 model_mismatch 取消；保留字段避免解析结构变动）。
- 车主评论不再一刀切过滤：V1.1 时代 `existing_owner`/`ordered_owner` 恒不过筛；V1.3 后车主若表达增换购/处置意向则 `has_purchase_intent=true` 并通过初筛。
- 无意向非车主的兴趣/赞美类评论通过初筛（`genuine_user` + `has_purchase_intent=false`），对接方可据两布尔字段识别其为 B 级弱线索。
- 请求侧（入参）无变化。
- `positive_attitude` 为内部信号，不对外透出。

落库：8100 链路结果 JSON 与 8000 流水线 `AnalysisResult.result`（`item.model_dump()`）均自动携带新字段，无需额外建表/加列。

---

## 6. Agent2（user_lead_analysis v5）

- `UserLeadResult`（`app/schemas/skills.py`）新增 `is_car_owner: bool = False`、`has_purchase_intent: bool = False`——综合该账号**所有历史评论 + 主页画像**判定。
- 对外 `ProfileResult`（`app/api/schemas.py`）新增同名两字段透出，`map_profile_result()` 同步映射（含 `has_value=false` 分支）。
- 定级流水线不变：v5 提示词在 v4 基础上仅增加两标签判定指引与非本人意向规则（见第 7 节），三段流水线、匹配度四档、画像上调、审计字段全部原样保留。
- `analysis_text` 五段结构不变；两标签的判定依据融入"评论行为"段说明。

---

## 7. 提示词判定指引（v3 与 v5 共用要点）

### 7.1 车主判定（`is_car_owner`）

有明确证据表明发布者大概率已购车（含已下单/下大定）→ `true`，否则 `false`。不要求已购我方在售车型。证据示例："提车三个月""我这台开了2万公里""大定已下"。反例（判 false）："准备订""想下定""打算买"是意向不是已购；咨询他人用车体验（"车主们保养贵不贵"）是潜在买家不是车主；证据不足一律 false。

### 7.2 购车意向判定（`has_purchase_intent`）

- **车主的意向表达** → `true`：
  - 增换购类：换车、再买、添一台、置换、升级、入手、增换、二胎车等；
  - 处置意图类：卖了、出手、保值率等；
  - 抱怨不满类：不够用、空间小、开腻了、下一台、开了xx年等。
- **非车主的意向表达** → `true`：询价、询问配置、对比、联系、优惠政策、等上市及其他类似表述。
- **反例**（→ `false`）：单纯夸赞、技术讨论（"内饰好看""底盘不错"）不算购车意向；非车主此类内容记 `positive_attitude=true`（仅 v3）。

### 7.3 非本人意向识别（bugfix，v3 与 v5 均加入）

评论描述的购车意向必须判断**是否为发布者本人意向**：

- 明确替他人问询/转述他人意向（如"我朋友想买一辆xxx"）→ 非本人意向，`has_purchase_intent=false`；
- 疑似怂恿他人购买/营销推广口吻（如选车视频下"分期30期买小鹏"，看不出是自己想买）→ 降级处理：v3 降低 `intent_strength`、v5 定级下调，理由写入 `reason` / `analysis_text`；营销特征明显时判 `comment_actor=marketing_account`（v3）/ `is_valid_lead=false`（v5）。

---

## 8. 通过判定统一（8000 流水线一致性）

现状：`services/aggregation.py::_valid_screenings` 与 `services/leads.py::_screening_passed` 用旧字段（`is_purchase_related and not is_suspected_marketing`）判定"通过"，与 8100 的 passed 口径不一致。

V1.3 抽出**共享判定函数**（定义于 `app/api/mapping.py`，两处 services 复用；services 已依赖 schemas，不引入循环依赖）：对 screening 结果 dict 按第 3 节同一规则表判定。效果：

- 8000 流水线候选用户口径与 8100 API 的 passed 口径一致：有购车意向或非车主积极信号的真实用户进入 Agent2 用户分析，无意向车主（纯讨论/吐槽）不进入；
- `query_screened_out_comments` 的分类展示同步适配新口径：`no_purchase_intent` 单列为新 category（`no_intent`），与既有 `marketing` / `unrelated` 并列。

旧字段兜底：结果 dict 无新字段时（历史数据）回退旧判定，保证向后兼容。

---

## 9. 版本与失效

| 技能 | version | prompt |
|------|---------|--------|
| `comment_lead_screening` | 1.1 → **1.3** | v2 → **v3** |
| `user_lead_analysis` | 1.2.1 → **1.3** | v4 → **v5** |

`SKILL_VERSIONS`（`app/workflow/pipeline.py`）两处升版 → 旧分析结果失效、触发重分析（沿用现有幂等机制）。`video_context_analysis` 版本不变。

---

## 10. 测试

沿用 mock/fake LLM 测试模式：

- **合成规则单测**：`resolve_filter_type` 全分支（第 3 节规则表 5 行 + 旧字段兜底回退 + LLM 未输出新字段的默认值路径）。
- **Prompt 渲染**：v3/v5 模板含两标签判定规则、非本人意向规则关键内容，占位符齐全；`no_purchase_intent` 不出现在 LLM 输出 JSON 模板中（它由代码合成）。
- **契约测试**：`CommentScreeningItem` / `UserLeadResult` 新字段默认值向后兼容（LLM 未输出时不报错）；`ScreeningResult` / `ProfileResult` 序列化含两布尔字段；`positive_attitude` 不泄漏到对外结果。
- **端到端（fake LLM）**：
  1. 有购车意向（含车主增换购表达）→ 必过筛，`passed=true`；
  2. 车主无意向纯讨论/吐槽 → `no_purchase_intent`、`passed=false`；
  3. 非车主无意向但有兴趣/赞美 → `genuine_user`、`passed=true`、`has_purchase_intent=false`；
  4. 降级模块移除后：任何输入不再产生 `model_mismatch`，`filter_reason` 恒 null。
- **8000 口径一致性**：共享判定函数下，候选用户筛选与 passed 口径一致；历史旧字段数据回退兼容。

---

## 11. 影响文件清单

| 文件 | 变更 |
|------|------|
| `app/schemas/skills.py` | `CommentScreeningItem` 新增 3 字段、移除 `owner_status`；`UserLeadResult` 新增 2 字段 |
| `app/skills/prompts/comment_lead_screening_v3.txt` | 新增：两标签 + 积极信号 + 非本人意向规则，移除 owner_status |
| `app/skills/prompts/user_lead_analysis_v5.txt` | 新增：基于 v4 增加两标签与非本人意向规则 |
| `app/skills/configs/comment_lead_screening.yaml` | version→1.3，prompt→v3 |
| `app/skills/configs/user_lead_analysis.yaml` | version→1.3，prompt→v5 |
| `app/api/mapping.py` | `resolve_filter_type` 重写；`map_screening_item` 去 `mismatch_reason`；`map_profile_result` 映射新字段；新增共享通过判定函数 |
| `app/api/schemas.py` | `ScreeningResult` / `ProfileResult` 新增两布尔字段 |
| `app/api/agent1.py` | 移除降级调用链 |
| `app/matching/downgrade.py` | 删除 |
| `tests/test_matching_downgrade.py` | 删除 |
| `app/config.py` | 删除 `intent_downgrade_enabled` |
| `app/services/aggregation.py` / `app/services/leads.py` | 改用共享通过判定函数 |
| `app/workflow/pipeline.py` | `SKILL_VERSIONS` 两处升版 |
| `docs/DriveIntent-V1-API对接文档.md` | filter_type 枚举表更新、新增字段说明、V1.3 变更说明，版本号 1.3 |
| `tests/`（相应测试文件） | 第 10 节测试用例 |
