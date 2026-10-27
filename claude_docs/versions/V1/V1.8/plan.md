# V1.8.0 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 阶段二重构——意向车型识别与四档分类（配置驱动），撤销匹配调级，结果落库并新增对外 API 字段。

**Architecture:** LLM 在定级 Prompt 阶段二内完成意向车型识别与分类（分类标准由 `config/intent_categories.json` 注入）；不再输出/应用 match_adjustment；新字段沿 UserLeadResult → AnalysisResult/lead 表 →（API 路径）ProfileResult → api_job.result 全链路透传。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / Pydantic v2 / pytest（既有栈，无新依赖）

**Spec:** `claude_docs/versions/V1/V1.8/design.md`

## Global Constraints

- 简体中文注释/文档；写入中文后须检查无乱码（CLAUDE.md 临时要求）。
- 版本化资产命名遵循 `claude_docs/versions/VERSIONING.md`：Prompt 文件改动 → 重命名 `_v1.8.0.txt` 并删除旧文件；YAML `version`/`prompt_version` → `1.8.0`/`v1.8.0`。
- analysis_text 五段标题逐字不变（锚点：`五、总体评价`；SECTION_HEADINGS 不动）。
- 对外契约仅增量新增 `intent_models` / `intent_model_category` 两字段。
- 全量回归基线：326 passed（提交前必须全绿）。

---

### Task 1: 分类标准配置与加载器

**Files:**
- Create: `config/intent_categories.example.json`、`config/intent_categories.json`（本地，gitignore）
- Modify: `.gitignore`（+`config/intent_categories.json`）、`app/config.py`（+`intent_categories_config_path`）、`.env.example`、`app/matching/models.py`、`app/matching/loader.py`
- Test: `tests/test_matching_loader.py`

**Interfaces:**
- Produces: `load_intent_categories(path=None) -> IntentCategoriesConfig | None`；`build_intent_category_standard(config) -> str`（None → "（未配置意向车型分类标准，intent_model_category 输出 null）"）

- [ ] 写失败测试：加载正常配置返回四档、缺失/坏 JSON 返回 None、标准文本含 "A"/规则文本、None 渲染占位文本
- [ ] 实现 `IntentCategory`/`IntentCategoriesConfig`（code+rule）与 loader（mtime 缓存，复用 our_models 模式）
- [ ] `pytest tests/test_matching_loader.py -q` 通过

### Task 2: UserLeadResult 新字段

**Files:**
- Modify: `app/schemas/skills.py`
- Test: `tests/test_agent2.py`

**Interfaces:**
- Produces: `UserLeadResult.intent_models: list[str] = []`；`intent_model_category: Literal["A","B","C","D"] | None = None`；`match_reason` 注释更新为阶段二依据；`model_match_level`/`match_adjustment` 保留默认值仅兼容历史数据

- [ ] 写失败测试：默认值、显式赋值、非法档位（"E"）触发 ValidationError
- [ ] 实现字段与注释（审计链注释同步为 baseline →profile_adjustment→ …）
- [ ] 相关 schema 测试通过

### Task 3: 定级 Prompt v1.8.0 与上下文注入

**Files:**
- Create: `app/skills/prompts/user_lead_analysis_v1.8.0.txt`（删除 `user_lead_analysis_v1.7.4.txt`）
- Modify: `app/skills/configs/user_lead_analysis.yaml`、`app/workflow/pipeline.py`（SKILL_VERSIONS + context）、`app/api/agent2.py`（context）
- Test: `tests/test_agent2.py`、`tests/test_user_analysis.py`

**Interfaces:**
- Consumes: Task 1 的 loader；Task 2 的 schema
- Produces: Prompt 模板变量 `$intent_category_standard`；阶段二标题 `[阶段二：意向车型识别与分类]`；输出 JSON 含 `intent_models`/`intent_model_category`，不含 `model_match_level`/`match_adjustment`

- [ ] 更新/新增 Prompt 渲染断言测试（新标题、"不调整评级"、intent 字段、旧调级规则移除、标准注入），先失败
- [ ] 重写阶段二、阶段三输入改为基线、输出 JSON 与要求条款；yaml 与 SKILL_VERSIONS → 1.8.0；两路径 context 注入 `intent_category_standard`
- [ ] 全部 prompt/流水线相关测试通过（历史断言同步修正）

### Task 4: 高级复核 Prompt v1.8.0

**Files:**
- Create: `app/skills/prompts/user_lead_review_advanced_v1.8.0.txt`（删除 v1.7.0）
- Modify: `app/skills/configs/user_lead_review_advanced.yaml`、`app/workflow/pipeline.py`（SKILL_VERSIONS）
- Test: `tests/test_user_review.py`、`tests/test_agent2.py`

- [ ] 更新配置/渲染断言测试（version 1.8.0、审计链新表述、intent 字段核验），先失败
- [ ] 审计链步骤改写：baseline_grade 经 profile_adjustment 到 lead_grade；字段核验清单加入 intent_models/intent_model_category
- [ ] 测试通过

### Task 5: API 契约透传（ProfileResult/mapping/agent2）

**Files:**
- Modify: `app/api/schemas.py`（ProfileResult）、`app/api/mapping.py`（map_profile_result 双分支）、`app/api/agent2.py`（异常行补键）
- Test: `tests/test_api_mapping.py`、`tests/test_agent2.py`、`tests/test_api_schemas.py`

**Interfaces:**
- Produces: `ProfileResult.intent_models: list[str] = []`；`intent_model_category: str | None = None`

- [ ] 写失败测试：map 透传（has_value 真/假）、run_profile_analysis 结果行含新字段、失败行为 []/None
- [ ] 实现透传与异常行字段
- [ ] 测试通过

### Task 6: lead 表落库与迁移脚本

**Files:**
- Modify: `app/models/lead.py`、`app/services/leads.py`（upsert_lead）
- Create: `scripts/add_lead_intent_columns.py`
- Test: `tests/test_user_analysis.py`

- [ ] 写失败测试：run_user_analysis 后 lead.intent_models / lead.intent_model_category 已写入
- [ ] 加列（`intent_models` JSON、`intent_model_category` String(4)）+ upsert 赋值 + 幂等迁移脚本（模式同 add_api_job_lead_grades.py）
- [ ] 测试通过

### Task 7: 内部查询/展示

**Files:**
- Modify: `app/services/lead_results.py`（_to_row + CSV）、`app/templates/leads.html`、`app/templates/lead_detail.html`
- Test: `tests/test_lead_results.py`

- [ ] 写失败测试：行含新字段、历史数据（无键）回退 []/None、CSV 表头新两列
- [ ] 实现
- [ ] 测试通过

### Task 8: 文档与发版清单

**Files:**
- Modify: `docs/DriveIntent-V1-API对接文档.md`（结果表两字段 + V1.8.0 行为变化章节）、`docs/DriveIntent-部署文档.md`（intent_categories 配置 + env 变量 + lead 迁移脚本）、`claude_docs/versions/V1/OVERVIEW.md`（快照 + 变更索引）
- 已有: `claude_docs/versions/V1/V1.8/design.md`、本 plan

- [ ] 文档更新，检查中文无乱码
- [ ] VERSIONING.md 发版检查清单逐项核对

### Task 9: 全量回归与提交

- [ ] `python -m pytest -q` 全绿
- [ ] 单次提交 `feat(v1.8.0): 阶段二重构——意向车型识别与分类，撤销匹配调级`（含代码+文档），推送 dev
