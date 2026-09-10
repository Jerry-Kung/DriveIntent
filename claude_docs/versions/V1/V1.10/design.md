# V1.10.0 设计：用户对我方在售车型购车意向分析

> 版本：V1.10.0 | 日期：2026-09-09

## 1. 背景与目标

Agent2（用户精筛定级）当前的对外输出 `intent_level`（H/A/B/C 映射为 high/medium/low）
描述的是"用户购买其**意向车型**的意向强度"，与**我方在售车型**没有关联。销售人员在
拿到线索时，最关心的是"这个用户有多大概率会买**我们的车**"以及"该推荐哪一款"。

本版本在 Agent2 定级工作流中增加对"用户对我方在售车型购车意向"的分析，并对外透出
两个字段，辅助销售人员针对该用户制定销售策略：

1. `our_model_intent_level`：用户对我方在售车型的购车意向等级，为 `"高"` / `"中"` / `"低"`
   三种枚举（对应对外三档，与 `intent_level` 同档位语义，但主体是"我方在售车型"）。
2. `recommend_our_model`：最适合推荐给该用户的我方在售车型名称，从服务端配置的
   `config/our_models.json` 车型列表中选择（如 `"猛士M817"`）。

两个字段在分析工作流中由定级节点（`user_lead_analysis`）的分析要求产生，并在分析总结
（`analysis_text` 第三段）中体现分析结论。

## 2. 范围决策（已与需求方确认）

| 决策点 | 结论 |
|---|---|
| 降级计算 | **代码确定性计算**。LLM 只输出语义判定枚举 `our_model_match`，代码按既定规则换算降级步数。可测、可解释、规则改动不依赖模型重训。 |
| 推荐车型 | **LLM 判定 + 代码适配校验**。LLM 从注入的在售车型清单中选最适合款并输出车型名，代码用 `load_our_models()` 校验该名称是否在配置内，不在则置 `null`（fail-open），不输出配置外车型。 |
| 意向强度基准 | **以 intent_level 为基准降级**（H/A→高、B→中、C→低），而非 lead_grade。因为 lead_grade 会因已购封顶等规则被压到 C（基准为低），但该用户对我们车型可能仍是强潜客；intent_level 恰反映"对意向车型的原始意向强度"。 |
| 匹配判定 | **新增枚举匹配判定字段 `our_model_match`**（`our_model` / `similar` / `unrelated` / `unknown`）。LLM 只做语义判断（意向车型是否为我方/同类且价位匹配/不匹配），代码用确定性规则换算。不引入需要代码了解竞品品类/价格的纯数值匹配（代码无法判定坦克300 的品类）。 |
| 落库范围 | **仅 API/结果层**。两字段加入 `UserLeadResult`（内部结果）与 `ProfileResult`（对外契约），经由既有结果 JSON 落库；不改 lead 表、不新增迁移脚本、不触碰 V0 流水线。 |
| 分析总结体现 | **复用既有第三段"目标车型与我方车型匹配度"**，不新增段落。要求在第三段明确写出"用户对我方在售车型的购车意向（高/中/低）及最适合推荐的我方车型"，并传达降级理由（或"直接命中我方在售车型"的正面结论）。 |
| 对外契约 | **纯增量**：新增 `our_model_intent_level` / `recommend_our_model` 两字段，既有字段行为不变。未命中/历史数据/处理失败时两字段为 `null`。 |

## 3. 降级规则（核心）

以用户对意图车型的意向强度为基准（`intent_level`：H/A→高、B→中、C→低），据
"原始意向车型与我方在售车型的对比"做**只降不升**的调整：

| `our_model_match` | 判定 | 降级 | 结果示例 |
|---|---|---|---|
| `our_model` | 原始意向车型就是我方在售车型（含别名命中） | 不降级 | 高→高、中→中、低→低 |
| `similar` | 不是我方在售，但**类型和价格区间都匹配**（如同为 25-30 万区间的越野车，属竞品） | 降一级 | 高→中、中→低、低→低 |
| `unrelated` | 不是我方在售，**类型或价格区间不匹配** | 降两级 | 高→低、中→低、低→低 |
| `unknown` | 识别不出意向车型 / 故意向车型 / LLM 未输出 | 置为低（默认低意向） | ——→低 |

> 规则语义：`our_model_match` 由 LLM 在阶段二维度从注入的 `our_models_summary` 判定，
> 代码只把枚举换算成"基准等级减去若干步"，最终 `our_model_intent_level` 为
> high/medium/low 三档。**不产生 HABC**——两字段只是"意向强度信息"，不参与评级调整，
> 与 V1.8.0 起"阶段二只识别归档、不调级"的口径一致。

## 4. 对外契约（纯增量）

`ProfileResult`（`app/api/schemas.py`）新增两字段：

| 字段 | 类型 | 默认 | 含义 |
|---|---|---|---|
| `our_model_intent_level` | `str | None` | `null` | 用户对我方在售车型的购车意向：`"高"` / `"中"` / `"低"`；非有效线索/历史数据/处理失败为 `null` |
| `recommend_our_model` | `str | None` | `null` | 最适合推荐的我方在售车型名（如 `"猛士M817"`），来自 `config/our_models.json`；非有效线索/未识别/处理失败为 `null` |

内部 `UserLeadResult` 同步新字段，语义一致：

- `our_model_match`：`Literal["our_model","similar","unrelated","unknown"] | None`，默认
  `null`（LLM 输出，允许 null——Prompt 全局要求"无证据字段输出 null"，昂贵失败代价是整账号
  校验失败丢线索，见 V1.2.1 `intent_model_category` 同款处理）；代码据此算降级，调用方对
  null 兜底按 `"unknown"` 处理。内部审计用，不进对外契约。
- `our_model_reason`：`str | None`，默认 `null`。阶段二判定依据（如"意向坦克300，
  与我方猛士M817同属越野车、价位区间接近，判定为同类竞品"）。内部审计用。
- `our_model_intent_level`：`Literal["高","中","低"] | None`，默认 `null`。代码按 §3
  规则确定性算出，进对外契约。
- `recommend_our_model`：`str | None`，默认 `null`。LLM 输出并经代码适配校验，进对外契约。

### 4.1 各场景对外表现

| 场景 | `our_model_intent_level` | `recommend_our_model` |
|---|---|---|
| 正常定级，意向直指我方车型 | 与基准一致（高/中/低） | 命中我方车型名 |
| 正常定级，意向为同类竞品 | 降一级 | 与我方最接近款 |
| 正常定级，意向不匹配 | 低 | 与我方最接近款（或 null） |
| 正常定级，无意向车型（unknown） | 低 | `null` |
| 被过滤（含黑名单，`is_valid_lead=false`）、无评论、处理失败 | `null` | `null` |
| 定级节点自判 `is_valid_lead=false` | `null` | `null` |
| 未配置我方在售车型（清单为空） | `null` | `null` |
| 历史数据（无该键） | `null` | `null` |

> 门控与校验（V1.10.0 终审加固）：两字段仅对 `is_valid_lead=true` **且我方在售车型清单非空**
> 的账号输出；其余一律 `null`。**推荐车型的配置校验必须无条件执行**——定级 LLM 可自判
> `is_valid_lead=false`，若此时跳过校验，未在清单内的车型名会经 `map_profile_result` 的
> `has_value=false` 分支原样透出对外契约（终审 Critical）。有效 C 级线索（低价值但仍是线索）
> 照常输出两字段。
>
> 校验侧容错：LLM 若输出"品牌 + 车型名"（清单渲染行含品牌前缀）或仅输出别名，服务端
> 经 `normalize` 归一后回落到正式车型名；未命中一律 `null`。
>
> 叙述口径（终审裁决）：`analysis_text` 第三段**只写"意向车型与我方在售车型的关系判断
> （直指我方 / 同类竞品 / 明显不匹配）及依据、推荐车型名"，不要求 LLM 自述"高/中/低"**——
> LLM 不知道代码的基准映射与降级矩阵，自述等级会与字段系统性打架（且复核改级只修订第五段，
> 第三段不自修订）。等级结论统由 `our_model_intent_level` 字段承载。

## 5. 实现

### 5.1 代码改动

| 文件 | 改动 |
|---|---|
| `app/schemas/skills.py` | `UserLeadResult` 加 `our_model_match`(Literal `"our_model"`/`"similar"`/`"unrelated"`/`"unknown"` \| None, 默认 null；调用方兜底 unknown)、`our_model_reason`(str\|None,默认 null)、`our_model_intent_level`(Literal `"高"`/`"中"`/`"低"`,默认 null)、`recommend_our_model`(str\|None,默认 null) |
| `app/api/schemas.py` | `ProfileResult` 加 `our_model_intent_level`(str|None,默认 null)、`recommend_our_model`(str|None,默认 null) |
| `app/api/mapping.py` | `map_profile_result` 两分支纯透传两字段；新增 `resolve_our_model_intent_level(match, lead_grade)`：由 `out.our_model_match` 与 `out.lead_grade`（映射基准等级）确定性算出 `our_model_intent_level` |
| `app/api/agent2.py` | 作业级用 `load_our_models()` 构建车型名集合；在 `map_profile_result` 之前对 `out.recommend_our_model` 做适配校验（不在集合内置 `null`）并调用降级计算写入 `out.our_model_intent_level`；异常兜底补两字段（null/null） |
| `app/workflow/pipeline.py` | `SKILL_VERSIONS[USER_ANALYSIS_SKILL]`→`"1.10.0"` |

校验与降级的职责划分：**降级计算（`our_model_intent_level`）与推荐车型校验
（`recommend_our_model`）都在 `agent2.run_profile_analysis` 中、`map_profile_result` 之前
对 `out` 就地完成**——作业级已加载一次 `load_our_models()`，复用其车型名集合，避免每
账号重复读文件；`map_profile_result` 保持纯透传（两字段原样进入对外契约），不需要新增
参数，既有测试签名完全兼容。V0 路径不调用 `map_profile_result`，也无需做这两步（其结果
`UserLeadResult.model_dump()` 仍会带上两字段落库，供观察）。

### 5.2 透传链路

```text
user_lead_analysis (LLM): 输出 intent_models/intent_model_category + our_model_match +
                           our_model_reason + recommend_our_model
        │
        ▼
UserLeadResult (schema) ──代码算 our_model_intent_level──▶ map_profile_result
        │                                                        │
        ▼                                                        ▼
   api_job.result.results[]  ────▶ ProfileResult (对外契约)
```

> `map_profile_result` 纯透传。降级计算与推荐车型校验在 `agent2.run_profile_analysis`
> 中对 `out` 就地完成（作业级已加载 `load_our_models()` 构建车型名集合）。

### 5.3 版本化资产

- `user_lead_analysis` Prompt：`user_lead_analysis_v1.8.4.txt` → `user_lead_analysis_v1.10.0.txt`
  （阶段二增补：① 判定 `our_model_match` 的规则与输入（我方车型清单 / 意向车型 / 分类）；
  ② 输出 `our_model_match`/`our_model_reason`/`recommend_our_model`；③ 要求第三段
  "目标车型与我方车型匹配度"写出对我方车型购车意向结论与推荐车型）。旧文件同提交删除。
- `user_lead_analysis.yaml`：`version="1.10.0"`、`prompt_file="user_lead_analysis_v1.10.0.txt"`、
  `prompt_version="v1.10.0"`。
- `SKILL_VERSIONS[USER_ANALYSIS_SKILL]`→`"1.10.0"`。
- `OVERVIEW.md` 能力快照与变更索引按规范更新；`docs/DriveIntent-V1-API对接文档.md`
  记录新两字段。

说明：阶段二**任何情况下不改评级**——`our_model_match` 只用于计算对外信息字段
`our_model_intent_level`，不改变 `lead_grade` 及定级/复核/润色流程。这与 V1.8.0 撤销
的匹配调级（改 HABC）本质不同。

## 6. 明确不做（YAGNI）

- 不改 lead 表结构、不新增迁移脚本（两字段随结果 JSON 落库）。
- 不接入 V0 流水线的 lead 表/管理页（V0 已停更；其 `AnalysisResult.result` 以 JSON
  整体落库，`UserLeadResult.model_dump()` 会带上两字段，V0 接口无需改动即可观察）。
- 不改幂等 `our_model_match` 语义为改评级（V1.8.0 已撤销匹配调级）。
- 不为 `recommend_our_model` 做多款排序 / 排序依据单独出字段——LLM 判定 + 代码校验即可。
- 不做独立 LLM 节点（复用 `user_lead_analysis` 定级节点一次调用，零新增调用）。
- 不新增 `analysis_text` 段落（复用既有五段结构，润色/复核锚点不受影响）。

## 7. 测试要点

1. **Schema**：`UserLeadResult` 四字段默认值（`our_model_match=None`、其余 null）与枚举校验（非法 `our_model_match` / `our_model_intent_level` 抛 `ValidationError`；`our_model_match=None` 合法，守护"LLM 输出 null 不致整账号失败"）；`ProfileResult` 两字段默认 null。
2. **降级计算**（`resolve_our_model_intent_level`）：四档枚举 × 基准等级矩阵——our_model
   不降、similar 降一级、unrelated 降两级、unknown 置低；基准 H/A→高、B→中、C→低。
3. **推荐车型适配校验**（agent2）：作业级车型名集合传入，LLM 输出不在集合内 → `null`；
   在集合内 → 原样；无在售车型配置 → `null`。
4. **透传与兜底**：`map_profile_result` 两分支（has_value 真/假）均透传两字段；异常兜底
   `run_profile_analysis` 补两字段 null。
5. **Prompt 渲染**：`user_lead_analysis_v1.10.0.txt` 含 `our_model_match` 枚举规则、
   三个输出字段、第三段述写要求；无英文枚举泄漏到面向人的叙述。
6. **版本同步**：`SKILL_VERSIONS[USER_ANALYSIS_SKILL]`、`user_lead_analysis.yaml`
   的 `version`/`prompt_file`/`prompt_version` 三者一致为 `1.10.0` / `v1.10.0`。
7. **回归**：全量 `python -m pytest -q` 保持全绿（当前 419 passed；需同步改
   `test_agent2.py` 的 v1.8.4 版本断言为 v1.10.0）。
