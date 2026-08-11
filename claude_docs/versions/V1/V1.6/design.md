# V1.6 设计：Agent2 无效用户过滤节点

> 版本：V1.6 | 日期：2026-08-11

## 1. 背景与目标

Agent2（用户精筛 / profile-analysis）现行流程中，"实际无购车意向但信号强"的用户
（已购车主、怂恿他人购买者、汽车从业者等）容易被误判为高价值线索，相关处置规则
（已购封顶、怂恿降档、营销判无效）分散在定级 Prompt 的多个段落，规则间耦合且只能
在定级末段"事后压级"。

本版本在 HABC 基线评级之前新增独立的**无效用户过滤节点**：基于用户全量证据包
（全部评论 + 主页画像）综合判断，提前把这类用户过滤出去——直接定 C 级、不进后续
定级流水线；同时把分散的用户级过滤规则统一迁移收口到该节点。

## 2. 新流程总览

```
账号输入
  ├─ 无评论 ──────────────→ 直接 C（不变，零 LLM）
  ├─ 识图节点（不变，可选多模态调用）
  ├─ 组装用户证据包（不变，纯代码）
  ├─ ★ 新节点：无效用户过滤（新 Skill：user_lead_filter，文本模型）
  │     ├─ 命中过滤 → 代码直接构造 C 级结果，按现有契约返回，不再调定级
  │     └─ 未命中 → 进入定级节点
  └─ 定级节点（Prompt 升 v1.6：已迁移规则删除，四段流水线瘦身）
```

- 过滤节点输入 = **完整用户证据包**（全部评论 + 主页画像），不注入评级标准与
  我方车型摘要（过滤判断与车型匹配无关，保持 Prompt 精简）。
- 过滤节点放在识图**之后**：主页画像是识别从业者（车评人/同行销售）和营销账号
  的关键证据，值得为此付识图成本。
- 未被过滤的用户多付一次轻量文本 LLM 调用（延迟与成本略增）；被过滤的用户省下
  定级大 Prompt 的 tokens。

## 3. 过滤节点输出契约（新 Schema：`UserFilterResult`）

```python
class UserFilterResult(BaseModel):
    filtered: bool = False
    filter_category: Literal[
        "already_purchased",      # 已购车/已下单且无新增购车计划
        "promoting_others",       # 怂恿他人购买/营销推广口吻
        "proxy_inquiry",          # 仅替他人问询，无本人意向
        "marketing_suspect",      # 疑似营销/水军账号
        "industry_professional",  # 车评人/汽车媒体/同行销售等从业者
        "other",                  # 其他明确无效情形（须给出具体理由）
    ] | None = None               # filtered=true 时必填
    filter_reason: str | None = None  # 必须引用具体评论/画像证据
    is_car_owner: bool = False        # 账号级独立标签（契约需要）
    has_purchase_intent: bool = False
    evidence_comment_ids: list[str] = []
    profile_tags: list[str] = []      # 简版画像，供 has_value=false 契约字段
    profile_summary: str = ""
    analysis_text: str = ""
    confidence: float = 0.0
```

要点：

1. **两个独立标签由过滤节点一并判定**——被过滤用户不进定级，但对外契约的
   `is_car_owner` / `has_purchase_intent` 仍需真实值（如 already_purchased 用户
   应为 `is_car_owner=true`、`has_purchase_intent=false`）。未过滤时以定级节点
   输出为准，过滤节点的标签丢弃。
2. Prompt 明确约束**宁放过勿误杀**：证据不足时一律放行进定级；`other` 类必须
   写明具体情形，禁止凭"感觉"过滤。

## 4. 内部审计字段与落库

`UserLeadResult` 新增两个内部审计字段（不进对外 API 契约，与 V1.2 以来审计字段
惯例一致）：

```python
filter_category: str | None = None   # 被过滤时写入；未过滤为 None
filter_reason: str | None = None
```

被过滤用户由代码合成：

```python
UserLeadResult(lead_grade="C", is_valid_lead=False,
               filter_category=..., filter_reason=...,
               is_car_owner=..., has_purchase_intent=...,
               profile_tags=..., profile_summary=..., analysis_text=...)
```

走既有 `map_profile_result` 出对外结果（C 级 → `has_value=false`，`analysis`
携带过滤理由）。**对外 API 响应结构零变化，对接方零改造，对接文档不动。**

审计链变为：`filter →(放行)→ baseline → match → profile → merge_boost → lead_grade`。

## 5. 定级 Prompt v1.6 瘦身（规则迁出对照）

| 现行规则（v1.5.1） | 去向 |
|---|---|
| 第四段规则 2「已购信号封顶 B」（含豁免） | **迁出**：过滤节点 already_purchased，命中直接 C（比封顶 B 更严，已确认接受）；豁免条件（明确新增购车意向、已购信号年代久远）转为**不过滤**条件，放行进定级且不再封顶 |
| 意向主体判断中「怂恿/营销口吻 → 降档/is_valid_lead=false」 | **迁出**：过滤节点 promoting_others / marketing_suspect |
| 要求 3「疑似营销、水军 → is_valid_lead=false」 | **迁出**：过滤节点 marketing_suspect |
| 意向主体判断中「替他人问询不作为本人意向证据」 | **保留**：混合型用户（部分评论替他人问、部分本人意向）会通过过滤，定级时仍需剔除代问评论作为证据；仅当**全部**意向均为替他人时才被过滤（proxy_inquiry） |
| 第四段规则 1「多条相近评论合并增强」 | **保留**：第四段只剩此一条 |

相应地，`purchase_downgrade` / `purchase_downgrade_reason` 从 Prompt 输出中移除
（`UserLeadResult` 字段保留默认值，兼容历史落库数据的读取）。

## 6. V0 流水线路径同步

`run_user_analysis`（V0 lead 表路径）与 API 路径共享 `user_lead_analysis` Skill。
Prompt 升 v1.6 后若 V0 路径不接过滤节点，已购/营销用户将失去处置规则、评级虚高。

方案：过滤逻辑抽为共享函数，V0 路径同样先过滤——命中则落 C 级 AnalysisResult
（含审计字段）并跳过 `upsert_lead`。两路径行为一致。

## 7. 错误处理

- 过滤节点 LLM 调用失败：**fail-open 放行**，记 warning，直接进定级（与识图失败
  降级同哲学——可选优化节点失败不阻断主流程；此时定级 Prompt 已无已迁出规则，
  属可接受的降级窗口）。
- 过滤节点输出 Schema 校验失败：同上 fail-open。
- `filtered=true` 但 `filter_category` 缺失：视为输出非法，fail-open 放行。

## 8. 版本化资产（按 VERSIONING.md）

- 新增 `app/skills/prompts/user_lead_filter_v1.6.txt`、
  `app/skills/configs/user_lead_filter.yaml`（version "1.6"、prompt_version "v1.6"）
- `user_lead_analysis` 升 `user_lead_analysis_v1.6.txt`、config version "1.6"、
  prompt_version "v1.6"
- `SKILL_VERSIONS` 注册新 Skill
- `claude_docs/versions/V1/OVERVIEW.md` 能力快照 + 变更索引更新
- API 对接文档不动（契约无变化）

## 9. 测试计划

1. 过滤命中 → 返回 C、`has_value=false`、审计字段落库、**定级 LLM 未被调用**；
2. 过滤未命中 → 正常走定级，`filter_category=None`；
3. 过滤 LLM 失败 / 输出非法（含 filtered=true 无 category）→ fail-open 进定级；
4. 被过滤用户对外字段完整性（`is_car_owner` 等来自过滤节点输出）；
5. V0 路径过滤命中 → 落 C 级结果、不 `upsert_lead`；
6. 枚举六类 Literal 校验；
7. 现有 Agent2 回归测试（无评论、识图失败等）不回归。
