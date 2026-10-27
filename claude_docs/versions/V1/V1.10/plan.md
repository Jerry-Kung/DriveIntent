# V1.10.0 实现计划：用户对我方在售车型购车意向分析

> 版本：V1.10.0 | 日期：2026-09-09
> 设计文档：`claude_docs/versions/V1/V1.10/design.md`

**Goal**：在"用户精筛定级"定级节点（`user_lead_analysis`）增加对"用户对我方在售车型购车意向"的分析，对外新增 `our_model_intent_level`（高/中/低）与 `recommend_our_model`（最适合推荐的我方在售车型名）两字段，并写入分析总结第三段，辅助销售人员制定销售策略。

**Architecture**：LLM 在阶段二只做语义判定（输出 `our_model_match` 枚举 + `our_model_reason` + 推荐车型名）；代码在 `agent2.run_profile_analysis` 中复用作业级已加载的 `load_our_models()`，确定性降级算出 `our_model_intent_level`、校验推荐车型名；`map_profile_result` 纯透传两字段到对外契约。只改 API/结果层，不动 lead 表、不触碰 V0。

## 任务分解

### Task 1: Schema 四字段

- `app/schemas/skills.py`：`UserLeadResult` 加 `our_model_match`(Literal `"our_model"`/`"similar"`/`"unrelated"`/`"unknown"` | None, 默认 null；调用方兜底 unknown)、`our_model_reason`(str|None, null)、`our_model_intent_level`(Literal `"高"`/`"中"`/`"低"`, null)、`recommend_our_model`(str|None, null)。
- `app/api/schemas.py`：`ProfileResult` 加 `our_model_intent_level`(str|None, null)、`recommend_our_model`(str|None, null)。
- 测试：`test_user_analysis.py` `test_v110_user_lead_result_our_model_defaults`、`test_v110_user_lead_result_rejects_invalid_our_model`；`test_api_schemas.py` `ProfileResult` 默认值断言。

### Task 2: 降级计算 + 映射透传

- `app/api/mapping.py`：新增 `resolve_our_model_intent_level(match: str, lead_grade: str) -> str`（基准 H/A→"高"、B→"中"、C→"低"；our_model 不降、similar 降一级、unrelated 降两级、unknown 置"低"；内部用 `_GRADE_MAP` 复用基准映射）。`map_profile_result` 两分支透传 `out.our_model_intent_level` / `out.recommend_our_model`。
- 测试：`test_api_mapping.py` 降级矩阵（4 枚举×3 基准）+ `map_profile_result` 两分支透传 + 默认 null。

### Task 3: Agent2 集成（降级/校验/兜底）

- `app/api/agent2.py`：作业级构建设定名集合（`load_our_models()`，`model_name` 列表）；每账号在 `map_profile_result` 前：调 `resolve_our_model_intent_level` 写入 `out.our_model_intent_level`；`out.recommend_our_model` 不在集合内置 `null`；异常兜底补两字段 null。`analyze_account` 透传（无需改动，schema 默认即可）。
- 测试：`test_agent2.py` 正常定级透传两字段、推荐车型不在配置内置 null、异常兜底 null、被过滤账号两字段 null。

### Task 4: Prompt 升版 + 版本同步

- 新增 `app/skills/prompts/user_lead_analysis_v1.10.0.txt`（阶段二增补 `our_model_match` 判定规则与三输出字段、第三段要求写关系判断与推荐车型而不自述等级），删除 `user_lead_analysis_v1.8.4.txt`。
- `app/skills/configs/user_lead_analysis.yaml`：`version="1.10.0"`、`prompt_file="user_lead_analysis_v1.10.0.txt"`、`prompt_version="v1.10.0"`。
- `app/workflow/pipeline.py`：`SKILL_VERSIONS[USER_ANALYSIS_SKILL]="1.10.0"`。
- 测试（改基线）：`test_agent2.py` 的 `test_analysis_config_matches_current_version` / `test_v121_pipeline_skill_version_bumped` / `test_v170_pipeline_skill_version_bumped` 版本断言；新增 `test_v110_analysis_prompt_has_our_model_rules`。

### Task 5: 文档

- `claude_docs/versions/V1/OVERVIEW.md`：Skill/Prompt 版本对照表、能力快照、变更索引。
- `docs/DriveIntent-V1-API对接文档.md`：响应结果表加两字段 + 新增 V1.10.0 行为变化小节。
- 本设计文档与计划。

## 验证

- 全量 `python -m pytest -q`：**419 passed 基线**，改断言后同步全绿（新增约 10+ 测试，总量预计 430+）。
- 关键集成断言：正常定级账号 `our_model_intent_level` 依降级矩阵正确；`recommend_our_model` 不在配置内 → null；异常兜底两字段 null。
- 版本一致性：`SKILL_VERSIONS[USER_ANALYSIS_SKILL]` == `user_lead_analysis.yaml.version` == `"1.10.0"`，`prompt_version == "v1.10.0"`。

## 全局约束

- 遵循 VERSIONING.md 第 4 节：Prompt 文件名 `<skill_id>_v<版本号>.txt`，旧文件同提交删除；`prompt_version`/Skill `version` 写入版本号。
- 仅改 API/结果层，**不改 lead 表、不新增迁移脚本**；不触碰 V0 流水线与 `analysis_text` 五段结构（润色/复核锚点不动）。
- `our_model_match` 只用于计算对外信息字段，**不参与评级调整**（`lead_grade`/定级/复核/润色流程不变），与 V1.8.0"阶段二只识别归档、不调级"口径一致。
- 命名与契约：对外字段为 `our_model_intent_level` / `recommend_our_model`；内审为 `our_model_match`（允许 null，调用方兜底 unknown） / `our_model_reason`。
- 门控与校验（终审加固）：两字段仅对 `is_valid_lead=true` **且我方在售车型清单非空**时输出，其余一律 null；推荐车型的配置校验**必须无条件执行**（定级 LLM 可自判 `is_valid_lead=false`，跳过校验会让未在清单内的车型名经 `has_value=false` 分支透出）。
- 中文编码：写入文件后检查乱码（项目 CLAUDE.md 临时要求）。
