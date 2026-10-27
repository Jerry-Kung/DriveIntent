# V1.7.0 实施计划：审查节点分级分流 + 高级模型

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增高级模型 `LLM_MODEL_ADVANCED`（永久开启深度思考），审查节点按初始定级分流——C 级不审查不润色、B 级普通模型审查、A/H 级高级模型审查（B 经普通审查 upgrade 到 A/H 时追加高级终审），润色节点保持不变。

**Architecture:** `LLMProvider.chat` / `LLMGateway.chat` / `SkillExecutor` 三级透传 `advanced` 能力位；`SkillConfig` 新增 `advanced`；新增高级审查 Skill `user_lead_review_advanced`；`apply_review` 重构为分级分流（抽出 `_run_review`），`apply_polish` 对最终 C 级短路。两条路径（V0 流水线 / 对外 API）共享同一编排函数，无需分别改。设计文档：`claude_docs/versions/V1/V1.7/design.md`（已批准）。

**Tech Stack:** Python / FastAPI / SQLAlchemy / Pydantic / pytest（`asyncio_mode = auto`，async 测试无需装饰器）/ MockProvider（FIFO 响应队列）。

## Global Constraints

- 简体中文写文档与注释；**每次向文件写入中文后必须读回检查是否乱码**（CLAUDE.md 临时要求），乱码须立即修复。
- 代码风格与现有代码一致：行宽约 79 列、中文注释只写代码无法表达的约束。
- Prompt 文件经 `string.Template.substitute` 渲染：**正文除占位符外不得出现裸 `$`**（会抛 KeyError/ValueError）。
- MockProvider 是 FIFO 队列：每个 LLM 节点恰好消费一个响应；**队列长度必须与节点调用数严格一致**，多排会错位、少排会被 fail-open 吞掉（V1.6.2 教训）。集成测试必须断言审计字段证明节点真实走到。
- 对外 API 契约（`ProfileResult`）、DB schema、映射逻辑一律不动。
- 普通审查 Prompt（`user_lead_review_v1.6.3.txt`）、定级 Prompt（`user_lead_analysis_v1.6.3.txt`）、润色 Prompt、过滤 Prompt 均不动、不重命名。
- 测试命令统一 `python -m pytest tests/... -v`（仓库根目录执行）。
- 每个任务结束提交一次 git；提交信息末尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

---

### Task 1: LLM 链路 `advanced` 能力位透传

**Files:**
- Modify: `app/config.py`、`.env.example`、`app/llm/base.py`、`app/llm/mock.py`、`app/llm/openai_compat.py`、`app/llm/gateway.py`、`app/skills/executor.py`
- Test: `tests/test_config.py`、`tests/test_llm_gateway.py`、`tests/test_skill_executor.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `Settings.llm_model_advanced: str = ""`
  - `LLMProvider.chat(..., enable_thinking: bool = False)`（base/mock/openai_compat 三处签名）
  - `LLMGateway.chat(..., advanced: bool = False)`
  - `SkillConfig.advanced: bool = False`；`SkillExecutor.run` 透传 `advanced=config.advanced`
  - `OpenAICompatProvider.chat` 注入 `enable_thinking or settings.llm_enable_thinking`

- [ ] **Step 1: 写失败测试**

`tests/test_config.py` 追加：

```python
def test_llm_model_advanced_defaults_empty():
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.llm_model_advanced == ""
```

`tests/test_llm_gateway.py` 追加（用既有 `RecordingProvider`，其 `chat` 签名补 `enable_thinking` 参数，并记录 `last_enable_thinking`）：

```python
async def test_gateway_advanced_uses_advanced_model(monkeypatch):
    import app.llm.gateway as gwmod
    monkeypatch.setattr(gwmod.settings, "llm_model", "text-m")
    monkeypatch.setattr(gwmod.settings, "llm_model_advanced", "adv-m")
    provider = RecordingProvider(); provider.queue("ok")
    gw = LLMGateway(provider)
    await gw.chat([{"role": "user", "content": "hi"}], advanced=True)
    assert provider.last_model == "adv-m"

async def test_gateway_advanced_falls_back_to_text_when_unset(monkeypatch):
    import app.llm.gateway as gwmod
    monkeypatch.setattr(gwmod.settings, "llm_model", "text-m")
    monkeypatch.setattr(gwmod.settings, "llm_model_advanced", "")
    provider = RecordingProvider(); provider.queue("ok")
    gw = LLMGateway(provider)
    await gw.chat([{"role": "user", "content": "hi"}], advanced=True)
    assert provider.last_model == "text-m"

async def test_gateway_advanced_forces_thinking(monkeypatch):
    import app.llm.gateway as gwmod
    monkeypatch.setattr(gwmod.settings, "llm_enable_thinking", False)
    provider = RecordingProvider(); provider.queue("ok")
    gw = LLMGateway(provider)
    await gw.chat([{"role": "user", "content": "hi"}], advanced=True)
    assert provider.last_enable_thinking is True
```

`tests/test_skill_executor.py` 追加（仿既有 `test_executor_passes_multimodal_to_gateway`）：

```python
async def test_executor_passes_advanced_to_gateway(tmp_path, monkeypatch):
    # 构造 model.advanced: true 的 demo.yaml，captured 断言 advanced is True
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_config.py tests/test_llm_gateway.py tests/test_skill_executor.py -v`
Expected: 新增用例 FAIL（`AttributeError` / 断言失败 / `TypeError` 缺参）。

- [ ] **Step 3: 实现**

`app/config.py` 在 `llm_multimodal_model` 之后加：

```python
    llm_model_advanced: str = ""      # 高级模型；留空回退 llm_model
```

`.env.example` 在 `LLM_MULTIMODAL_MODEL=` 注释块之后加：

```
# 高级模型：用于高价值线索的终审等对质量要求高的节点；与普通模型共用
# BASE_URL 与 API_KEY，仅模型名不同；留空则回退到 LLM_MODEL。
# 该模型请求永久强制 enable_thinking=true。
LLM_MODEL_ADVANCED=
```

`app/llm/base.py`：

```python
    @abc.abstractmethod
    async def chat(self, messages: list[dict], *, model: str,
                   temperature: float, enable_thinking: bool = False) -> LLMResponse:
        ...
```

`app/llm/mock.py`：`chat` 签名补 `enable_thinking: bool = False`（忽略）。

`app/llm/openai_compat.py`：

```python
    async def chat(self, messages: list[dict], *, model: str,
                   temperature: float, enable_thinking: bool = False) -> LLMResponse:
        ...
        payload = {"model": model, "messages": messages,
                   "temperature": temperature,
                   "enable_thinking": enable_thinking or settings.llm_enable_thinking}
```

`app/llm/gateway.py` `chat`：

```python
    async def chat(self, messages: list[dict], *, skill_id: str = "",
                   skill_version: str = "", prompt_version: str = "",
                   model: str | None = None, multimodal: bool = False,
                   advanced: bool = False,
                   temperature: float | None = None) -> LLMResponse:
        if model is None:
            if advanced:
                model = settings.llm_model_advanced or settings.llm_model
            else:
                model = settings.multimodal_model if multimodal else settings.llm_model
        ...
                resp = await self.provider.chat(
                    messages, model=model, temperature=temperature,
                    enable_thinking=advanced or settings.llm_enable_thinking)
```

`app/skills/executor.py`：

```python
class SkillConfig(BaseModel):
    ...
    advanced: bool = False
    ...
def load_skill_config(...):
    ...
    return SkillConfig(model_name=model.get("name", ""),
                       temperature=model.get("temperature", 0.1),
                       multimodal=model.get("multimodal", False),
                       advanced=model.get("advanced", False), **data)
```

`SkillExecutor.run` 的 `gateway.chat(...)` 调用追加 `advanced=config.advanced`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_config.py tests/test_llm_gateway.py tests/test_skill_executor.py -v`
Expected: 全部通过（既有用例的 provider 子类签名已同步补参）。

- [ ] **Step 5: 读回所有改动的 .py / .env.example 检查中文无乱码**

- [ ] **Step 6: Commit**

---

### Task 2: Schema——`review_tier` 审计字段

**Files:**
- Modify: `app/schemas/skills.py`
- Test: `tests/test_agent2.py`（追加断言，不改既有用例）

**Interfaces:**
- Produces: `UserLeadResult.review_tier: str = "none"`（`none | standard | advanced`）。

- [ ] **Step 1: 写失败测试**

`tests/test_agent2.py` 追加：

```python
def test_v170_user_lead_result_review_tier_default():
    from app.schemas.skills import UserLeadResult
    assert UserLeadResult(lead_grade="B").review_tier == "none"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_agent2.py::test_v170_user_lead_result_review_tier_default -v`
Expected: FAIL（`AttributeError`）。

- [ ] **Step 3: 实现**

`app/schemas/skills.py` 的 `UserLeadResult`，在 `review_reason` 之后加：

```python
    # V1.7.0：审查层级审计字段。none=未审查（被过滤或初始定级 C）；
    # standard=普通模型审查；advanced=高级模型审查（最终生效层级）。
    review_tier: str = "none"          # none | standard | advanced
```

同时把 `analysis_polish` 字段注释里的 `none=未走润色（被过滤账号）` 扩展为
`none=未走润色（被过滤账号或最终定级 C）`（取值集合不变）。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_agent2.py::test_v170_user_lead_result_review_tier_default -v`
Expected: 1 passed。

- [ ] **Step 5: 读回 `app/schemas/skills.py` 新增部分检查中文无乱码**

- [ ] **Step 6: Commit**

---

### Task 3: 高级审查 Skill 与 Prompt

**Files:**
- Create: `app/skills/configs/user_lead_review_advanced.yaml`、`app/skills/prompts/user_lead_review_advanced_v1.7.0.txt`
- Test: `tests/test_user_review.py`（追加 config/prompt 断言）

**Interfaces:**
- Consumes: 普通审查 Prompt（`user_lead_review_v1.6.3.txt`）作参照。
- Produces: 高级审查 Skill 与 Prompt；输出沿用 `UserLeadReviewResult`。

- [ ] **Step 1: 写失败测试**

`tests/test_user_review.py` 追加：

```python
def test_v170_advanced_review_config():
    from app.skills.executor import load_skill_config
    config = load_skill_config("user_lead_review_advanced")
    assert config.version == "1.7.0"
    assert config.prompt_file == "user_lead_review_advanced_v1.7.0.txt"
    assert config.prompt_version == "v1.7.0"
    assert config.advanced is True
    assert config.multimodal is False

def test_v170_advanced_review_prompt_renders():
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("user_lead_review_advanced")
    text = render_prompt(config, {
        "user_evidence_json": "{}",
        "grading_standard": "标准",
        "our_models_summary": "- 方舟X7：售价 35-42 万元",
        "preliminary_result_json": "{}"})
    assert "review_action" in text
    assert "reviewed_grade" in text
    assert "revised_conclusion" in text
    assert "revised_lead_summary" in text
    assert "不得跨越" in text          # 单次复核不得跨一级
    assert "C 级不可再降" in text
    assert "推理" in text              # 全链路细致推导要求
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_user_review.py::test_v170_advanced_review_config -v`
Expected: FAIL（`FileNotFoundError`）。

- [ ] **Step 3: 实现**

`app/skills/configs/user_lead_review_advanced.yaml`（见设计 3.4 节）。

`app/skills/prompts/user_lead_review_advanced_v1.7.0.txt`：以普通审查 Prompt
为骨架，占位符完全一致（`$user_evidence_json`、`$grading_standard`、
`$our_models_summary`、`$preliminary_result_json`），强化点：

1. 角色定位为「高价值线索终审」——这是对 A/H 级线索的最终裁决，宁可多花
   推理也不许草率确认；
2. 逐段核验 `analysis_text` 五段的每处论证与结构化字段
   （`target_models`/`core_needs`/`main_concerns` 等）是否有证据支撑；
3. 沿审计链 `baseline_grade → match_adjustment → profile_adjustment →
   lead_grade` 检查逻辑断裂、证据不足却上调、证据充分却低估；
4. 输出 JSON 字段与普通审查完全一致（`review_action` / `reviewed_grade` /
   `review_reason` / `revised_conclusion` / `revised_lead_summary` /
   `confidence`），保留「单次不得跨一级、C 不可再降」约束。

注意：正文除占位符外不得有裸 `$`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_user_review.py::test_v170_advanced_review_config tests/test_user_review.py::test_v170_advanced_review_prompt_renders -v`
Expected: 2 passed。

- [ ] **Step 5: 读回新增 YAML 与 Prompt 检查中文无乱码**

- [ ] **Step 6: Commit**

---

### Task 4: 审查分流编排 + 润色短路

**Files:**
- Modify: `app/skills/user_review.py`、`app/skills/analysis_polish.py`
- Test: `tests/test_user_review.py`（新增分流用例，改造既有用例的 mock 队列与断言）

**Interfaces:**
- Consumes: `UserLeadResult.lead_grade`、`UserLeadReviewResult`。
- Produces: `apply_review`（分级分流，签名不变）、`apply_polish`（最终 C 短路）。

- [ ] **Step 1: 写失败测试**

`tests/test_user_review.py` 新增/改造：

1. `test_initial_c_skips_review_and_polish`：定级响应 `lead_grade == "C"`，
   队列只排 `NOT_FILTERED_JSON` + C 级 lead 两个响应（无审查、无润色响应）；
   断言 `review_tier == "none"`、`analysis_polish == "none"`、
   `pre_review_grade is None`，且 `provider._responses` 为空（未多消费）。
2. `test_initial_b_confirmed_standard_review`：初始 B + confirmed，队列
   `NOT_FILTERED_JSON` + B lead + REVIEW_CONFIRMED + POLISH_OK；断言
   `review_tier == "standard"`、`analysis_polish == "polished"`。
3. `test_initial_b_upgraded_triggers_advanced_review`：初始 B + upgraded→A，
   队列 `NOT_FILTERED_JSON` + B lead + upgraded(→A) + 高级 confirmed + POLISH_OK；
   断言最终 A、`review_tier == "advanced"`。
4. `test_initial_b_downgraded_to_c_skips_polish`：初始 B + downgraded→C，
   队列 `NOT_FILTERED_JSON` + B lead + downgraded(→C)；断言最终 C、
   `review_tier == "standard"`、`analysis_polish == "none"`。
5. 既有 `test_upgrade_revises_narrative_...` / `test_confirmed_...` /
   `test_downgrade_...` 的 lead 初始级为 A，现走高级审查——mock 队列长度不变
   （仍是 4 个响应：过滤+定级+审查+润色），补断言 `review_tier == "advanced"`。
   `test_review_failure_keeps_grade_and_narrative_together` 补断言
   `review_tier == "advanced"`（fail-open 前已记录）。

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_user_review.py -v`
Expected: 新增用例 FAIL（`review_tier` 不存在 / `analysis_polish` 断言不符 /
队列多消费）。

- [ ] **Step 3: 实现**

`app/skills/user_review.py`：按设计 3.3 节重构。要点：

- 顶部新增 `USER_REVIEW_ADVANCED_SKILL = "user_lead_review_advanced"`；
- 抽出 `_run_review(executor, evidence_json, our_models_summary, out, tier)`，
  把现有 `apply_review` 的「构造 context → 调用 → 审计字段赋值 → 改级时锚点
  修订」整体迁入，仅 `skill_id` 由 `tier` 决定；调用 `executor.run` 前先写
  `out.review_tier = tier`；
- `apply_review` 改为分流入口（C 短路；B 走 standard，upgrade 到 A/H 后追加
  advanced；A/H 走 advanced）。

`app/skills/analysis_polish.py`：`apply_polish` 开头加：

```python
    if out.lead_grade == "C":
        out.analysis_polish = "none"    # 最终无价值线索不润色
        return
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_user_review.py -v`
Expected: 全部通过。

- [ ] **Step 5: 读回 `app/skills/user_review.py`、`app/skills/analysis_polish.py` 检查中文无乱码**

- [ ] **Step 6: Commit**

---

### Task 5: 版本号升版 + 全量回归

**Files:**
- Modify: `app/workflow/pipeline.py`、`app/skills/configs/user_lead_analysis.yaml`
- Test: `tests/test_agent2.py`（版本断言）、`tests/test_analysis_polish.py`（如涉及）

**Interfaces:**
- Produces: `SKILL_VERSIONS[USER_ANALYSIS_SKILL] == "1.7.0"`、
  `SKILL_VERSIONS[USER_REVIEW_ADVANCED_SKILL] == "1.7.0"`。

- [ ] **Step 1: 写失败测试**

`tests/test_agent2.py` 追加：

```python
def test_v170_pipeline_skill_version_bumped():
    from app.workflow.pipeline import (SKILL_VERSIONS, USER_ANALYSIS_SKILL,
                                       USER_REVIEW_ADVANCED_SKILL)
    from app.skills.executor import load_skill_config
    assert SKILL_VERSIONS[USER_ANALYSIS_SKILL] == "1.7.0"
    assert SKILL_VERSIONS[USER_REVIEW_ADVANCED_SKILL] == "1.7.0"
    assert (load_skill_config(USER_ANALYSIS_SKILL).version
            == SKILL_VERSIONS[USER_ANALYSIS_SKILL])
```

注意：既有 `test_v121_pipeline_skill_version_bumped` 与
`test_v163_analysis_config_uses_v163` 断言 `"1.6.4"`，需同步改为 `"1.7.0"`。

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_agent2.py::test_v170_pipeline_skill_version_bumped -v`
Expected: FAIL（`ImportError`：`USER_REVIEW_ADVANCED_SKILL` 不存在）。

- [ ] **Step 3: 实现**

`app/workflow/pipeline.py`：

- import 区补 `USER_REVIEW_ADVANCED_SKILL`（从 `app.skills.user_review`）；
- `SKILL_VERSIONS` 增加 `USER_REVIEW_ADVANCED_SKILL: "1.7.0"`，
  `USER_ANALYSIS_SKILL` 升 `"1.7.0"`。

`app/skills/configs/user_lead_analysis.yaml`：仅 `version: "1.7.0"`，
`prompt_file` / `prompt_version` 维持 v1.6.3。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_agent2.py -v`
Expected: 全部通过。

- [ ] **Step 5: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全部通过（既有 213+ 用例无回归）。重点核对：所有走 `run_user_analysis`
与 `run_profile_analysis` 的既有用例 mock 队列长度无需改动（H/A 级原本就是
「过滤+定级+审查+润色」4 次，仅审查换成了高级 skill；B 级与 C 级的既有用例
需按 Task 4 已调整的队列核对）。若有 C 级历史用例仍排了审查/润色响应，会
多消费导致断言失败，逐一修正队列。

- [ ] **Step 6: Commit**

---

### Task 6: 文档归档

**Files:**
- Modify: `claude_docs/versions/V1/OVERVIEW.md`

- [ ] 变更索引加 V1.7.0 行（日期 2026-08-17，摘要：审查节点分级分流 + 高级模型 `LLM_MODEL_ADVANCED` + 润色对最终 C 短路；链接 design/plan）。
- [ ] 能力快照「核心能力现状（V1.6 后）」中复核节点描述更新为分级分流（C 短路 / B 普通审查 / A·H 高级审查，B→A/H 追加高级终审）；`analysis_polish` 描述补「最终 C 不润色」。
- [ ] 「LLM 调用（V1.4.1）」节补充高级模型 `LLM_MODEL_ADVANCED`（共用 BASE_URL/API_KEY、仅模型名不同、永久深度思考、留空回退）。
- [ ] Skill/Prompt 版本对照表：新增 `user_lead_review_advanced | 1.7.0 | v1.7.0`；`user_lead_analysis` 的 config version 升 `1.7.0`（prompt 维持 v1.6.3）；`user_lead_review` 维持 `1.6.3`。
- [ ] 更新 OVERVIEW 顶部「最后更新」日期。
- [ ] 读回检查中文无乱码。
- [ ] Commit。

---

## 完成定义

- [ ] 高级模型 `LLM_MODEL_ADVANCED` 可配置、留空回退普通模型、请求强制 `enable_thinking=true`。
- [ ] 审查节点按初始定级分流：C 短路、B 普通审查、A/H 高级审查、B→A/H 追加高级终审。
- [ ] 最终 C 级不润色；润色节点本身（普通模型）不变。
- [ ] `review_tier` 审计字段落库可观测各分流分支实际走到。
- [ ] 全量测试通过；中文无乱码；OVERVIEW 更新；每任务一提交。
