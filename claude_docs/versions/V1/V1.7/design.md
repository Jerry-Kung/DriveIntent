# V1.7.0 设计：审查节点分级分流 + 高级模型

> 版本：V1.7.0 | 日期：2026-08-17

## 1. 背景与问题

V1.6.2 引入的独立复核节点 `user_lead_review`，对定级节点给出的 H/A/B/C 一律
使用同一个普通模型（`LLM_MODEL`）、同一套 Prompt 做一次复核。这带来两点问题：

1. **高价值线索审查强度不足**：H/A 级是精筛产出的关键线索，销售团队会据此
   优先触达客户。当前对它们的审查强度与 B 级无差别——单次普通模型复核，
   既未逐段核验上游推理链，也没有动用更强模型兜底，误判（尤其是高估）的
   代价直接落到销售资源上。
2. **低价值线索空耗调用**：定级为 C 的用户本就无价值、不该被触达，却仍要
   走一遍复核与润色，白白消耗 LLM 调用（每账号 2 次）。

本版本引入「高级模型 + 分级分流」：A/H 级用更强的模型做更细致的终审，C 级
直接短路到输出，B 级维持现状——用模型成本与审查深度去匹配线索价值。

## 2. 范围决策

1. **新增 `LLM_MODEL_ADVANCED` 高级模型**：与 `LLM_MODEL` 共用 `LLM_BASE_URL`
   与 `LLM_API_KEY`，仅模型名不同。高级模型请求**永久强制**
   `enable_thinking=true`，不受全局 `LLM_ENABLE_THINKING` 开关影响。
2. **审查节点按初始定级分流**：
   - 初始 C：不进审查、不进润色，直接走输出链路；
   - 初始 B：普通模型审查，复用现有 `user_lead_review` 节点，行为不变；
   - 初始 A/H：高级模型审查，新增 `user_lead_review_advanced` 节点，要求把
     整个输出内容及推理链路全部细致推导分析一遍；
   - **初始 B 经普通审查 upgrade 到 A/H 时，追加一次高级模型终审**（用户需求
     明确点名此场景）。
3. **`LLM_MODEL_ADVANCED` 留空时**（已与用户确认）：高级审查仍走「高级 Prompt」，
   仅模型回退为 `LLM_MODEL`。与现有多模态模型留空回退文本模型机制对称；
   不把「更细致审查」的语义一并降级掉。
4. **润色触发条件**（已与用户确认）：**最终 `lead_grade == "C"` 一律不润色**。
   即初始 C 不润色，B 被普通审查 downgrade 到 C 也不润色——凡最终无价值的
   线索都不花润色成本。其余（最终 A/B/H）照常润色。
5. **润色节点本身不变**：继续用普通模型（`LLM_MODEL`），Prompt 与行为均不动。
6. **对外契约 / DB schema / 映射逻辑均不动**：本版本只改内部编排与模型路由，
   新增的审计字段不进对外 API。

## 3. 方案

### 3.1 配置：`Settings.llm_model_advanced`

`app/config.py` 新增：

```python
llm_model_advanced: str = ""   # 高级模型；留空回退 llm_model
```

`.env.example` 增补 `LLM_MODEL_ADVANCED=`（注释说明：与普通模型共用 BASE_URL /
API_KEY，仅模型名不同；留空回退 `LLM_MODEL`；该模型永久开启深度思考）。

### 3.2 LLM 路由与思考开关传递

当前模型路由只区分「文本 / 多模态」（`gateway.chat(multimodal=...)`），
`enable_thinking` 是全局开关、由 `openai_compat` 直接读 `settings` 注入。
要支持「按请求走高级模型 + 按请求强制思考」，做三处最小扩展：

1. **`LLMProvider.chat` 签名扩展**（`app/llm/base.py`，同步 `mock.py` /
   `openai_compat.py`）：追加关键字参数 `enable_thinking: bool = False`。
   - `openai_compat` 注入值改为 `enable_thinking or settings.llm_enable_thinking`
     （保留对直接调用 provider 的既有测试与全局开关的兼容）；
   - `mock` 忽略该参数。
2. **`LLMGateway.chat` 追加 `advanced: bool = False`**：
   - 模型选择：`model is None` 时，`advanced` → `settings.llm_model_advanced
     or settings.llm_model`；否则维持现有多模态/文本路由。
   - 思考开关：`enable_thinking = advanced or settings.llm_enable_thinking`，
     传给 provider。
3. **`SkillExecutor` 读取 `model.advanced`**：`SkillConfig` 新增
   `advanced: bool = False`，`load_skill_config` 从 YAML `model.advanced`
   读取，`run()` 把 `config.advanced` 透传给 `gateway.chat`。

这样高级审查 Skill 只需在 YAML 里声明 `model.advanced: true`，即可同时获得
「高级模型（留空回退普通模型）」与「强制深度思考」两项能力，节点代码零特判。

### 3.3 审查分流编排（`app/skills/user_review.py`）

把现有 `apply_review` 的一次性复核重构为「分级分流」，新增高级审查 Skill 常量，
内部抽出单次复核核心 `_run_review`：

```python
USER_REVIEW_SKILL = "user_lead_review"           # 普通审查（v1.6.3 不变）
USER_REVIEW_ADVANCED_SKILL = "user_lead_review_advanced"  # 高级审查（v1.7.0）

async def _run_review(executor, evidence_json, our_models_summary,
                      out, tier: str) -> None:
    skill_id = (USER_REVIEW_ADVANCED_SKILL if tier == "advanced"
                else USER_REVIEW_SKILL)
    out.review_tier = tier          # 调用前即记录，fail-open 也留下"尝试过"痕迹
    review_context = { ... }        # 同现状
    try:
        review = await executor.run(skill_id, review_context, UserLeadReviewResult)
    except SkillExecutionError as e:
        logger.warning("复核节点失败，保留初步定级与叙述: %s", e)
        return
    out.pre_review_grade = out.lead_grade
    out.review_action = review.review_action
    out.review_reason = review.review_reason
    if review.review_action != "confirmed":
        # V1.6.3 锚点修订逻辑原样保留（_revise_analysis + lead_summary 覆写 + 改级）

async def apply_review(executor, evidence_json, our_models_summary, out) -> None:
    grade = out.lead_grade
    if grade == "C":
        return                      # 初始 C：无价值，不审查（review_tier 保持 none）
    if grade == "B":
        await _run_review(executor, evidence_json, our_models_summary,
                          out, "standard")
        # 普通审查 upgrade 到 A/H → 追加高级终审（需求点名的场景）
        if out.lead_grade in ("A", "H"):
            await _run_review(executor, evidence_json, our_models_summary,
                              out, "advanced")
    else:  # A / H
        await _run_review(executor, evidence_json, our_models_summary,
                          out, "advanced")
```

要点：

- `_run_review` 复用现有复核的全部赋值与 V1.6.3 锚点修订逻辑（`_revise_analysis`
  替换第五段、`lead_summary` 覆写、`lead_grade` 改级），普通与高级两条路径共享，
  只是 `skill_id` 不同。
- 高级审查输出沿用 `UserLeadReviewResult`（`review_action` / `reviewed_grade` /
  `review_reason` / `revised_conclusion` / `revised_lead_summary` / `confidence`），
  因此改级时的高级审查同样能修订对外叙述，无需新输出模型。
- fail-open 语义不变：任一层审查失败都保留当前等级与叙述；`review_tier` 在调用
  前已写入，可观测「某层审查被尝试但失败」而非无声跳过。
- 已知的审计链压缩：B→A/H 二次审查后，`pre_review_grade` 记录的是第二次审查前
  的等级（A/H），初始 B 的信息不保留。这是为控制字段数量做的取舍，测试环境
  观察以 `review_tier == "advanced"` 判定高级审查是否真实走到即可。

### 3.4 高级审查 Skill 与 Prompt

新增 `app/skills/configs/user_lead_review_advanced.yaml`：

```yaml
skill_id: user_lead_review_advanced
version: "1.7.0"
description: >
  高价值线索（A/H 级，含 B 级经普通复核上调者）的高级终审：使用更强模型，
  对上游定级输出与推理链做全面细致的二次核验，避免误判高价值客户。
model:
  name: ""          # 留空由 gateway 按 advanced 路由到 LLM_MODEL_ADVANCED
  temperature: 0.1
  advanced: true    # 路由到高级模型 + 强制深度思考
prompt_file: user_lead_review_advanced_v1.7.0.txt
prompt_version: "v1.7.0"
```

新增 `app/skills/prompts/user_lead_review_advanced_v1.7.0.txt`，在普通审查
Prompt 的销售视角复核基础上，强化以下几点（输出字段与 `UserLeadReviewResult`
一致，保留「单次复核不得跨一级、C 不可再降」约束）：

1. **终审定位**：明确这是高价值线索的最终裁决，宁可多花推理也不许草率确认；
2. **全链路细致推导**：逐段核验上游 `analysis_text` 五段（评论行为/购车阶段/
   车型匹配/主页画像/总体评价）的每一处论证是否与用户证据吻合，逐字段核验
   `target_models` / `core_needs` / `main_concerns` 等结构化输出是否有证据支撑；
3. **审计链核验**：沿着 `baseline_grade → match_adjustment → profile_adjustment
   → lead_grade` 推导链，判断是否存在逻辑断裂、证据不足却上调、或证据充分却
   低估；
4. **改级时同步修订叙述**：`revised_conclusion` / `revised_lead_summary` 与
   普通审查同契约（不含段标题、不引入新事实、承接前四段）。

### 3.5 润色触发调整（`app/skills/analysis_polish.py`）

`apply_polish` 开头增加短路：

```python
if out.lead_grade == "C":
    out.analysis_polish = "none"    # 最终无价值线索不润色
    return
```

其余逻辑（占位符、五段标题校验、fail-open、三字段原子赋值）完全不动。
这样编排层（`pipeline.py` / `agent2.py`）无需改调用条件——依旧「过滤 → 定级 →
apply_review → apply_polish」串行，分流收敛在两个函数内部。

### 3.6 Schema 变更（`app/schemas/skills.py`）

`UserLeadResult` 新增一个审计字段（内部用，不进对外契约，风格同
`review_action` / `analysis_polish`）：

```python
# V1.7.0：审查层级审计字段。none=未审查（被过滤或初始定级 C）；
# standard=普通模型审查；advanced=高级模型审查（最终生效层级）。
review_tier: str = "none"          # none | standard | advanced
```

`analysis_polish` 字段注释语义扩展：`none` 由「未走润色（被过滤账号）」扩展为
「未走润色（被过滤账号或最终定级 C）」，字段取值集合不变。

`UserLeadReviewResult` 复用，不新增输出模型。

### 3.7 代码配套（版本号与接线）

| 文件 | 改动 |
|---|---|
| `app/config.py` | 新增 `llm_model_advanced: str = ""` |
| `.env.example` | 增补 `LLM_MODEL_ADVANCED=` 及注释 |
| `app/llm/base.py` / `mock.py` / `openai_compat.py` | `chat` 追加 `enable_thinking` 参数；`openai_compat` 注入值改为 `enable_thinking or settings.llm_enable_thinking` |
| `app/llm/gateway.py` | `chat` 追加 `advanced` 参数：模型路由 + 思考开关计算，透传 provider |
| `app/skills/executor.py` | `SkillConfig.advanced`；`load_skill_config` 读 `model.advanced`；`run` 透传 `advanced` |
| `app/skills/configs/user_lead_review_advanced.yaml` | 新增，`version: "1.7.0"`、`model.advanced: true` |
| `app/skills/prompts/user_lead_review_advanced_v1.7.0.txt` | 新增 |
| `app/skills/user_review.py` | 新增 `USER_REVIEW_ADVANCED_SKILL`；`apply_review` 重构为分级分流 + `_run_review` |
| `app/skills/analysis_polish.py` | `apply_polish` 开头对最终 C 短路 |
| `app/workflow/pipeline.py` | `SKILL_VERSIONS[USER_ANALYSIS_SKILL]` → `"1.7.0"`；新增 `USER_REVIEW_ADVANCED_SKILL: "1.7.0"` 条目并 import |
| `app/skills/configs/user_lead_analysis.yaml` | 仅 `version` 升 `"1.7.0"`（维持「YAML version == `SKILL_VERSIONS`」不变式）；`prompt_file` / `prompt_version` 维持 v1.6.3 |
| 普通审查 `user_lead_review` 的 YAML 与 Prompt | **不动**（v1.6.3；B 级审查行为无变化） |

**影响**：`SKILL_VERSIONS[USER_ANALYSIS_SKILL]` 升版使 V0 流水线路径旧版本定级
结果失效并触发重分析（与历次升版行为一致）；API 路径无状态，无此影响。

**每账号 LLM 调用次数**（识图另计）：

| 场景 | 过滤 | 定级 | 审查 | 润色 | 合计 |
|---|---|---|---|---|---|
| 过滤命中 → C | 1 | — | — | — | 1 |
| 初始 C | 1 | 1 | — | — | 2 |
| 初始 B，confirmed/downgraded | 1 | 1 | 1 | 0~1 | 3~4 |
| 初始 B，upgraded → A/H | 1 | 1 | 2 | 1 | 5 |
| 初始 A/H | 1 | 1 | 1（高级） | 1 | 4 |

相对 V1.6.4（统一 4 次），C 级样本省 2 次、B 级维持或略降、A/H 级不变——
模型单价上移但调用次数不增，成本向高价值样本集中。

### 3.8 明确不做

- 不动定级 Prompt、过滤 Prompt、普通审查 Prompt、润色 Prompt、Agent1 初筛
  Prompt；
- 不删 V1.6.3 锚点修订机制（仍是润色/高级审查 fail-open 时的兜底）；
- 高级审查不改对外契约、不新增输出 Schema；
- 不回填/清洗历史落库数据；
- 不引入「高级模型专属 base_url/api_key」（沿用用户明确的范围：仅模型名不同）。

## 4. 测试

MockProvider 为 FIFO 队列，节点调用数变化会导致响应错位（V1.6.2 教训），因此
**每个分流分支都要有断言审计字段（`review_tier` / `analysis_polish`）证明节点
真实走到，且队列长度与调用数严格一致**。

1. `tests/test_config.py`：`llm_model_advanced` 默认空。
2. `tests/test_llm_gateway.py`：
   - `advanced=True` 且 `llm_model_advanced` 已配置 → 用高级模型；
   - `advanced=True` 且留空 → 回退 `llm_model`；
   - `advanced=True` → provider 收到 `enable_thinking=True`（即使全局 false）；
   - 既有 `RecordingProvider` / `FlakyProvider` 签名补 `enable_thinking`。
3. `tests/test_skill_executor.py`：`model.advanced: true` 的 Skill 经 executor
   把 `advanced` 透传给 gateway（仿既有 multimodal 透传测试）。
4. `tests/test_user_review.py`（分流核心）：
   - 初始 C → 不审查不润色：`review_tier == "none"`、`analysis_polish == "none"`、
     `pre_review_grade is None`，队列无审查/润色响应；
   - 初始 B + confirmed → `review_tier == "standard"`，照常润色；
   - 初始 B + upgraded → 二次审查，`review_tier == "advanced"`，最终 A/H；
   - 初始 B + downgraded → `review_tier == "standard"`、最终 C、
     `analysis_polish == "none"`（不润色）；
   - 初始 A/H → `review_tier == "advanced"`（既有 upgraded/confirmed 用例
     需补 `review_tier` 断言，mock 队列长度不变）。
5. `tests/test_agent2.py`：API 路径集成用例（既有 lead 多为 H/A）现走高级审查，
   响应契约兼容、队列长度不变，补 `review_tier` 断言；新增初始 B→A 的二次
   审查集成用例与初始 C 跳过用例。
6. 新增高级审查 Prompt 断言：`user_lead_review_advanced_v1.7.0.txt` 存在、
   占位符齐全、含「单次不得跨一级」与「C 不可再降」约束、正文无裸 `$`；
   YAML `advanced: true`、`prompt_version == "v1.7.0"`。

**验收（用户侧）**：真实 LLM 联调观察——A/H 级样本 `review_tier == "advanced"`
的占比、`llm_call_log` 中 `user_lead_review_advanced` 的 `model_name` 是否为
`LLM_MODEL_ADVANCED`、高级审查 upgrade/downgrade 分布是否合理；统计 C 级样本
是否确实零审查零润色。列为发版观察点。

## 5. 文档归档

- 本设计文档：`claude_docs/versions/V1/V1.7/design.md`；
- 实施计划：`claude_docs/versions/V1/V1.7/plan.md`；
- `claude_docs/versions/V1/OVERVIEW.md`：变更索引加 V1.7.0 行；能力快照更新
  复核节点描述（分级分流）与 Skill/Prompt 版本对照表（新增
  `user_lead_review_advanced` 1.7.0 / v1.7.0；`user_lead_analysis` skill_version
  升 1.7.0，prompt 维持 v1.6.3）。
