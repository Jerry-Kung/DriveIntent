# V1.8.0 设计：阶段二重构——意向车型识别与分类，撤销匹配调级

> 版本：V1.8.0 | 日期：2026-08-27

## 1. 背景与目标

V1.2.1 引入、V1.7.4 修补的"[阶段二：车型匹配调整]"存在两个问题：

1. 匹配档位（our_model/similar/partial/unrelated）直接驱动评级升降（-2~+1），
   下游应用无法按自身策略决定如何使用车型匹配信息；
2. 匹配结果只体现在评级调整与叙述文本中，"用户到底想买什么车"这一核心信息
   没有结构化输出，下游拿不到。

本版本按以下三点重构：

1. **明确识别用户意向车型并分类**：识别用户**有购买意向**的车型（严格基于
   评论证据综合判断，提及≠意向、在某车视频下评论≠对该车有意向；无意向则输出
   空），并按可配置的四档标准（A/B/C/D）对意向车型分类。
2. **撤销阶段二的定级调整**：车型匹配（识别+分类）阶段保留，但结果不再参与
   评级升降；如何据此调整定级交给下游应用节点决定。
3. **结果落库并进对外 API**：意向车型与分类作为结构化字段存数据库，并新增到
   对外 API 输出，供下游消费。

## 2. 意向车型识别与分类

### 2.1 识别口径（Prompt 规则）

- 意向车型 = 用户**本人**表达了购买意向的具体车型（如"坦克300"、"猛士M817"）。
- 必须基于全部评论综合判断：用户可能提到多款车（对比、吐槽、围观），须甄别
  其中真正有购买意向的对象；仅提及、仅赞美、仅在某车视频下评论均不构成意向。
- 既有"代询排除"规则（替他人询问不算本人意向）继续适用。
- 无任何有购买意向的车型 → `intent_models` 输出空数组（语义即"无意向车型"）。

### 2.2 四档分类（可配置）

分类标准不写死在 Prompt，由新配置文件提供，默认四档（与我方业务对应）：

| 档位 | 默认标准 |
|---|---|
| A | "东风猛士"系列车型（与我方在售车型一致） |
| B | 越野车 |
| C | 25-30 万元价位的 SUV |
| D | 其他车型，或无意向车型 |

- 四档结构（代码 A/B/C/D）是契约，各档**判定规则文本**可配置。
- 多款意向车型时取**最优档**（A 最优，D 最劣）。
- 分类标准未配置 → `intent_model_category` 输出 null，意向车型照常识别。

### 2.3 配置文件

- 路径：`config/intent_categories.json`（环境变量
  `INTENT_CATEGORIES_CONFIG_PATH` 可覆盖，默认同左）。
- 与 `our_models.json` 同口径：**不入库**（.gitignore），每套部署自行维护；
  模板 `config/intent_categories.example.json` 入库。
- 结构：

```json
{
  "version": "1.0",
  "updated_at": "2026-08-27",
  "categories": [
    {"code": "A", "rule": "\"东风猛士\"系列车型（与我方在售车型一致）"},
    {"code": "B", "rule": "越野车"},
    {"code": "C", "rule": "25-30万元价位的SUV"},
    {"code": "D", "rule": "其他车型，或无意向车型"}
  ]
}
```

- 加载复用 `app/matching/loader.py` 的既有模式：(路径, mtime) 缓存、缺失/解析
  失败告警并返回 None；`build_intent_category_standard()` 渲染注入 Prompt 的
  标准文本，None 时返回"（未配置意向车型分类标准，intent_model_category 输出
  null）"。

## 3. 阶段二重构与评级流水线变化

### 3.1 阶段二：车型匹配调整 → 意向车型识别与分类

Prompt（`user_lead_analysis_v1.8.0.txt`）阶段二标题改为
"[阶段二：意向车型识别与分类]"，职责：

1. 识别意向车型（口径见 2.1），输出 `intent_models`；
2. 按注入的分类标准输出 `intent_model_category`（A/B/C/D 或 null）；
3. `match_reason` 沿用为本阶段依据说明：为何判定这些车型有购买意向、
   为何归入该档（无意向时说明"未识别出意向车型"）；
4. **不做任何评级调整**：阶段二不改变评级，基线评级原样进入阶段三。

移除（不再要求 LLM 输出）：`model_match_level`、`match_adjustment` 及
"最接近在售车型作对比基准"等调级配套规则（V1.7.4 引入的比对基准约束随调级
一并退役）。Schema 中两字段保留默认值（"unknown"/0），历史落库数据读取不受
影响。

### 3.2 审计链变化

```
旧：baseline_grade →(match_adjustment)→ 中间级 →(profile_adjustment)→ pre_review_grade →(review)→ lead_grade
新：baseline_grade →(profile_adjustment)→ pre_review_grade →(review)→ lead_grade
```

阶段三（主页画像有限上调）规则不变，但其输入从"阶段二输出的中间评级"改为
"阶段一的基线评级"。

### 3.3 关联 Prompt 同步

- `user_lead_review_advanced_v1.8.0.txt`：审计链核验步骤删去 match_adjustment
  环节，改为核验 baseline_grade 经 profile_adjustment 到 lead_grade；结构化
  字段核验清单加入 intent_models / intent_model_category。
- 普通复核 `user_lead_review_v1.6.3.txt`、润色 `user_analysis_polish_v1.6.4.txt`
  未引用匹配调整规则，不动。
- analysis_text 五段结构与标题**逐字不变**（第三段"目标车型与我方车型匹配度"
  内容语义变为：意向车型识别结论、分类结果及其与我方在售车型的关系说明，
  不再含调级依据）。锚点/润色校验代码不受影响。

## 4. 数据契约变化

### 4.1 UserLeadResult（内部 Schema）

新增：

```python
intent_models: list[str] = []                                  # 意向车型；空=无意向
intent_model_category: Literal["A", "B", "C", "D"] | None = None  # 未配置/未识别时 None
```

保留兼容（不再由 LLM 输出，仅历史数据读取）：`model_match_level`（默认
"unknown"）、`match_adjustment`（默认 0）。`match_reason` 语义更新为阶段二
识别与分类依据。

### 4.2 数据库

- `analysis_result.result`（JSON）：随 model_dump 自然携带新字段，无迁移。
- `lead` 表（V0 流水线）：新增 `intent_models JSON`、
  `intent_model_category VARCHAR(4)` 两列；`upsert_lead` 同步写入。
  迁移脚本 `scripts/add_lead_intent_columns.py`（幂等，同
  `add_api_job_lead_grades.py` 模式）。
- `api_job.result.results[]`：经 mapping 新增两字段（JSON 列，无迁移）。

### 4.3 对外 API（ProfileResult，profile-analysis 结果）

新增两个字段（纯增量，既有字段不动）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `intent_models` | ArrayString | 有购买意向的车型列表；空数组=无意向车型；该条处理失败时为 [] |
| `intent_model_category` | String \| null | 意向车型分类：`"A"`/`"B"`/`"C"`/`"D"`（服务端可配标准）；无法分类/未配置/处理失败为 null |

`has_value=false`（无评论/被过滤/C 级）时两字段照常输出（通常为 []/null 或
过滤前已识别的值）。评分与 intent_level 映射逻辑不变——本版本不改变评级
语义，仅停用阶段二调级。

### 4.4 内部查询/展示（/leads 页面与 CSV）

`lead_results._to_row` 增列 `intent_models`、`intent_model_category`；
`leads.html` 列表加"意向车型"列，`lead_detail.html` 详情加两项；CSV 导出加
"意向车型"、"车型分类"两列。历史数据无此键，显示"-"。

## 5. 版本化资产

| 资产 | 变更 |
|---|---|
| `user_lead_analysis` | Prompt → `user_lead_analysis_v1.8.0.txt`，version/prompt_version → 1.8.0 |
| `user_lead_review_advanced` | Prompt → `user_lead_review_advanced_v1.8.0.txt`，version/prompt_version → 1.8.0 |
| `pipeline.SKILL_VERSIONS` | 上述两项 → "1.8.0" |

## 6. 不做的事（YAGNI）

- 不改评论初筛（Agent1）、无效用户过滤、普通复核、润色节点；
- 不改 intent_level/value_score 映射与 H/A/B/C→high/medium/low 对外口径；
- 不为分类档位数量做泛化（四档 A-D 固定，仅规则文本可配）；
- 不迁移历史数据（旧结果无新字段，读取端以默认值/占位展示）。

## 7. 测试要点

1. 分类配置 loader：正常加载/缺失/解析失败/缓存失效；标准文本渲染。
2. Schema：新字段默认值与校验（非法档位拒绝）；旧字段兼容。
3. Prompt 渲染：新阶段二标题与规则关键词；调级规则已移除；
   `$intent_category_standard` 注入。
4. 流水线两路径（V0 pipeline / API agent2）：LLM 输出新字段 → AnalysisResult
   / lead 表 / api_job results 均携带；处理失败行两字段为 []/null。
5. mapping / lead_results / CSV / 模板：新字段透传与历史数据回退。
6. 高级复核 Prompt：审计链新表述渲染断言。
