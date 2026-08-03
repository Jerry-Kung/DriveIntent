# DriveIntent V1.2 实现计划

> 版本：V1.2 | 日期：2026-07-28

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把用户抖音主页截图正式纳入 Agent2 分析流程——识图阶段建立结构化用户画像，评级阶段依据画像对高质量线索（基线 B/A）做有限上调。

**Architecture:** 复用现有 skill 执行框架。`image_recognition` skill 升级为输出结构化画像 JSON；`user_lead_analysis` skill 升级为注入画像并做"先评论定基线、再画像有限上调"的单阶段评级；`UserLeadResult` 增加内部审计字段。对外 API 契约不变。

**Tech Stack:** Python 3 / FastAPI / Pydantic / SQLAlchemy / pytest / YAML skill 配置 + `string.Template` prompt 渲染 / 多模态 LLM Gateway。

## Global Constraints

- 使用简体中文编写 prompt、文档、注释与提交信息。
- 对外 API 输出字段结构**不得变更**（`intent_level` / `intent_level_code` / `value_score` / `profile_tags` / `profile_summary` / `analysis` / `error`），画像与审计字段仅供内部使用。
- 等级从高到低：H > A > B > C。画像**只上调、不下调**，最多上调一级；仅基线为 B 或 A 时考虑画像，C 及以下忽略画像；H 不再上调。
- prompt 模板变量用 `$var` 语法（`string.Template.substitute`），新增模板不得引入 skill context 未提供的变量。
- LLM 输出 JSON 经 `app/skills/executor.py::extract_json` 解析，容忍 ```` ```json ```` 代码块包裹。
- 每个任务以 TDD 推进：先写失败测试 → 确认失败 → 最小实现 → 确认通过 → 提交。测试命令 `pytest`，异步测试用 `@pytest.mark.asyncio`。

---

## 文件结构

| 文件 | 责任 |
|------|------|
| `app/skills/prompts/image_recognition_v2.txt` | 新增：结构化画像识图 prompt |
| `app/skills/configs/image_recognition.yaml` | 修改：version→2.0，指向 v2 prompt |
| `app/schemas/skills.py` | 修改：`UserLeadResult` 增加 3 个审计字段 |
| `app/skills/prompts/user_lead_analysis_v3.txt` | 新增：注入画像 + 有限上调规则 + 审计字段输出 |
| `app/skills/configs/user_lead_analysis.yaml` | 修改：version→1.2，指向 v3 prompt |
| `app/workflow/pipeline.py` | 修改：`SKILL_VERSIONS[USER_ANALYSIS_SKILL]`→"1.2" |
| `app/api/agent2.py` | 修改：`_build_evidence` 注入结构化画像 + 新增 `_parse_profile` 辅助 |
| `docs/DriveIntent-V1-API对接文档.md` | 修改：补充 V1.2 行为说明 |
| `tests/test_agent2.py` | 修改：更新 config 版本断言 + 新增画像相关用例 |

---

## Task 1: 结构化画像识图 prompt + config 升级

**Files:**
- Create: `app/skills/prompts/image_recognition_v2.txt`
- Modify: `app/skills/configs/image_recognition.yaml`
- Test: `tests/test_agent2.py`

**Interfaces:**
- Consumes: `app/skills/executor.py::load_skill_config(skill_id)` → `SkillConfig(skill_id, version, prompt_file, prompt_version, model_name, temperature)`
- Produces: `image_recognition` skill 加载后 `config.version == "2.0"`、`config.prompt_file == "image_recognition_v2.txt"`、`config.prompt_version == "v2"`；prompt 文本要求 LLM 输出结构化画像 JSON。

- [ ] **Step 1: 写失败测试**

在 `tests/test_agent2.py` 末尾追加：

```python
def test_v12_image_recognition_config_uses_v2():
    from app.skills.executor import load_skill_config
    config = load_skill_config("image_recognition")
    assert config.prompt_file == "image_recognition_v2.txt"
    assert config.prompt_version == "v2"
    assert config.version == "2.0"


def test_v12_image_recognition_prompt_asks_structured_json():
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("image_recognition")
    text = render_prompt(config, {})
    # 结构化画像的关键字段与硬约束
    assert "auto_relevance" in text
    assert "raw_description" in text
    assert "content_themes" in text
    assert "JSON" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agent2.py::test_v12_image_recognition_config_uses_v2 tests/test_agent2.py::test_v12_image_recognition_prompt_asks_structured_json -v`
Expected: FAIL（config 仍为 1.0 / v1；prompt 无 `auto_relevance`）

- [ ] **Step 3: 创建 v2 prompt 模板**

创建 `app/skills/prompts/image_recognition_v2.txt`：

```
你是用户画像分析专家。这是一张抖音（或 TikTok）用户的账号主页截图。
请识别截图中所有与该用户相关的可见信息，并归纳为结构化的用户画像。

请严格输出以下 JSON（不要输出任何其他内容）：
{
  "nickname": "账号昵称，不可见为 null",
  "douyin_id": "抖音号，不可见为 null",
  "signature": "个性签名/简介，不可见为 null",
  "age": "年龄（整数或描述），不可见或明显异常（如 111 岁）为 null",
  "gender": "性别：男 | 女 | null",
  "ip_location": "IP 属地，不可见为 null",
  "follow_count": "关注数（整数），不可见为 null",
  "fans_count": "粉丝数（整数），不可见为 null",
  "likes_count": "获赞数（整数），不可见为 null",
  "verification": "认证标识文本，无认证为 null",
  "content_themes": ["已发布作品体现的内容主题，如：游戏/电竞、自驾游、汽车评测、家庭生活"],
  "consumption_signals": ["消费能力/生活方式线索，如：高端旅行、奢侈品、房车，无则空数组"],
  "interest_tags": ["兴趣标签，如：汽车发烧友、户外爱好者、游戏玩家"],
  "auto_relevance": "与汽车/自驾/购车相关性的客观判断：明确描述有无相关线索及其内容，如“大量自驾游与越野内容，疑似汽车发烧友”或“无明显汽车/自驾相关内容”",
  "raw_description": "对截图可见信息的完整自然段描述，作为结构化字段的兜底"
}

要求：
1. 只描述你实际看到的内容，不要推测或编造；不可见的字段输出 null 或空数组；
2. 明显异常/不真实的数值（如年龄 111 岁）判为 null，可在 raw_description 中说明；
3. auto_relevance 必须客观，无相关线索时明确写“无明显汽车/自驾相关内容”，不得强行关联；
4. raw_description 尽可能完整，防止结构化字段遗漏信息。
```

- [ ] **Step 4: 升级 config**

将 `app/skills/configs/image_recognition.yaml` 修改为：

```yaml
skill_id: image_recognition
version: "2.0"
description: >
  识别抖音/TikTok 账号主页截图，输出结构化用户画像 JSON
  （主题、消费能力、兴趣、年龄性别属地、汽车相关性），供用户画像分析上调评级参考。
model:
  name: ""
  temperature: 0.1
prompt_file: image_recognition_v2.txt
prompt_version: "v2"
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_agent2.py::test_v12_image_recognition_config_uses_v2 tests/test_agent2.py::test_v12_image_recognition_prompt_asks_structured_json -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add app/skills/prompts/image_recognition_v2.txt app/skills/configs/image_recognition.yaml tests/test_agent2.py
git commit -m "feat(v1.2): image_recognition 升级为结构化画像输出 (v2/2.0)"
```

---

## Task 2: UserLeadResult 增加审计字段

**Files:**
- Modify: `app/schemas/skills.py:45-62`
- Test: `tests/test_agent2.py`

**Interfaces:**
- Consumes: 无（纯数据模型）
- Produces: `UserLeadResult` 新增可选字段 `baseline_grade: str | None = None`、`profile_adjustment: str = "none"`、`adjustment_reason: str | None = None`。`lead_grade` 语义变为**最终等级**（画像上调后）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_agent2.py` 末尾追加：

```python
def test_v12_user_lead_result_has_audit_fields():
    from app.schemas.skills import UserLeadResult
    # 默认值：未提供审计字段时不报错
    r = UserLeadResult(lead_grade="B")
    assert r.baseline_grade is None
    assert r.profile_adjustment == "none"
    assert r.adjustment_reason is None
    # 显式提供上调审计
    r2 = UserLeadResult(lead_grade="A", baseline_grade="B",
                        profile_adjustment="upgraded",
                        adjustment_reason="主页大量自驾游内容")
    assert r2.baseline_grade == "B"
    assert r2.profile_adjustment == "upgraded"
    assert r2.adjustment_reason == "主页大量自驾游内容"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agent2.py::test_v12_user_lead_result_has_audit_fields -v`
Expected: FAIL（`baseline_grade` 等属性不存在）

- [ ] **Step 3: 增加字段**

在 `app/schemas/skills.py` 的 `UserLeadResult` 类中，`confidence: float = 0.0` 之前插入三个字段：

```python
    analysis_text: str = ""
    # V1.2：画像上调审计字段（内部用，不进对外 API 契约）。
    # lead_grade 为最终等级；baseline_grade 为仅评论证据的基线等级。
    baseline_grade: str | None = None
    profile_adjustment: str = "none"  # none | upgraded
    adjustment_reason: str | None = None
    confidence: float = 0.0
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_agent2.py::test_v12_user_lead_result_has_audit_fields -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/schemas/skills.py tests/test_agent2.py
git commit -m "feat(v1.2): UserLeadResult 增加画像上调审计字段"
```

---

## Task 3: user_lead_analysis v3 prompt + 版本升级

**Files:**
- Create: `app/skills/prompts/user_lead_analysis_v3.txt`
- Modify: `app/skills/configs/user_lead_analysis.yaml`
- Modify: `app/workflow/pipeline.py:19-23`
- Modify: `tests/test_agent2.py:70-87`（更新既有 v2 断言为 v3）
- Test: `tests/test_agent2.py`

**Interfaces:**
- Consumes: skill context 变量 `$user_evidence_json`、`$grading_standard`、`$our_models_summary`（与 v2 相同，不新增模板变量——画像通过 `user_evidence_json` 内的 `homepage_profile` 键传入）。
- Produces: `user_lead_analysis` 加载后 `config.version == "1.2"`、`config.prompt_file == "user_lead_analysis_v3.txt"`、`config.prompt_version == "v3"`；`SKILL_VERSIONS[USER_ANALYSIS_SKILL] == "1.2"`；prompt 要求 LLM 输出 `baseline_grade` / `profile_adjustment` / `adjustment_reason`。

- [ ] **Step 1: 更新既有版本断言测试为 v3 并新增规则断言**

将 `tests/test_agent2.py` 中现有的 `test_v11_user_analysis_config_uses_v2` 整体替换为：

```python
def test_v12_user_analysis_config_uses_v3():
    from app.skills.executor import load_skill_config
    config = load_skill_config("user_lead_analysis")
    assert config.prompt_file == "user_lead_analysis_v3.txt"
    assert config.prompt_version == "v3"
    assert config.version == "1.2"


def test_v12_user_analysis_prompt_has_profile_rules():
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("user_lead_analysis")
    text = render_prompt(config, {
        "user_evidence_json": "{}",
        "grading_standard": "标准",
        "our_models_summary": "- 方舟X7：售价 35-42 万元"})
    assert "方舟X7" in text          # 我方车型摘要仍注入
    assert "baseline_grade" in text  # 审计字段输出要求
    assert "homepage_profile" in text  # 画像注入位置说明
    assert "只上调" in text          # 画像上调规则
```

同时保留原 `test_v11_user_analysis_prompt_has_our_models_var`，但把其中的断言 `assert "匹配度" in text` 保持不变（v3 需保留"匹配度"考量措辞）。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agent2.py::test_v12_user_analysis_config_uses_v3 tests/test_agent2.py::test_v12_user_analysis_prompt_has_profile_rules -v`
Expected: FAIL（config 仍 v2/1.1；prompt 无 `baseline_grade`）

- [ ] **Step 3: 创建 v3 prompt 模板**

创建 `app/skills/prompts/user_lead_analysis_v3.txt`：

```
你是汽车销售线索分析专家。以下是一位抖音用户的全部有效评论及其上下文，
以及从其主页截图识别出的结构化画像，请综合判断该用户的购车意向，形成销售线索。

用户证据包（JSON，user.homepage_profile 为主页画像，缺失时为“（无主页截图）”）：
$user_evidence_json

意向等级标准：
$grading_standard

我方在售主力车型信息：
$our_models_summary

评级与画像上调规则（务必严格遵守）：
1. 先仅依据评论证据判定基线等级 baseline_grade（H/A/B/C），主页画像不参与基线判定；
2. 基线为 C 或以下：忽略画像，最终等级 lead_grade = baseline_grade；
3. 基线为 B 或 A：检查 homepage_profile 是否有直接证据支持上调
   （如 auto_relevance/interest_tags 明确体现“汽车发烧友、自驾爱好者、明确高消费信号”等）：
   - 有直接证据 → 上调一级（B→A 或 A→H），最多一级，profile_adjustment="upgraded"，
     adjustment_reason 写明具体画像证据；
   - 无直接证据 → 保持基线，profile_adjustment="none"，adjustment_reason=null；
4. 画像只上调、不下调：严禁因画像证据弱而调低基线等级；
5. 上调必须能指名 homepage_profile 中的具体证据，不得因“感觉”或弱关联上调；
6. H 已是最高级，不再上调。

请严格输出以下 JSON（不要输出任何其他内容）：
{
  "baseline_grade": "仅评论证据的基线等级：H | A | B | C",
  "profile_adjustment": "none | upgraded",
  "adjustment_reason": "上调依据（画像直接证据），未上调为 null",
  "lead_grade": "最终等级（画像上调后）：H | A | B | C",
  "is_valid_lead": true,
  "lead_summary": "线索摘要，销售人员一眼能懂，一到两句话",
  "purchase_stage": "购车阶段，如：初步了解/主动对比/交易准备，无法判断为 null",
  "target_brands": ["关注品牌"],
  "target_models": ["关注车型"],
  "core_needs": ["核心需求，如家庭空间、越野"],
  "main_concerns": ["主要顾虑，如落地价格、售后"],
  "purchase_time": "购车时间，如：近期/半年内/未知，无法判断为 null",
  "usage_scenario": "使用场景，无法判断为 null",
  "recommended_entry_point": "推荐销售切入点，一句话",
  "verification_questions": ["销售需要向用户确认的问题"],
  "evidence_comment_ids": ["支撑结论的评论 comment_id，必须来自输入"],
  "profile_tags": ["账号画像标签，如：已购车主、智驾关注、高活跃度"],
  "profile_summary": "账号画像摘要，150-300 字，综合评论行为与主页画像信息",
  "analysis_text": "分析过程说明，300-500 字，分评论行为/购车阶段/主页画像/综合评分四段，需说明基线与是否上调",
  "confidence": 0.9
}

要求：
1. 所有结论必须有评论证据支撑，evidence_comment_ids 不得为空；
2. 没有证据的字段输出 null 或空数组，严禁编造；
3. 疑似营销、水军或完全无购车相关信号的用户：is_valid_lead=false；
4. 结合“我方在售主力车型信息”考量匹配度：用户意向车型与我方车型的价位、
   品类差异显著、且无任何我方品牌相关信号时，适当下调等级（如 H→A、A→B）
   并在 analysis_text 中说明理由；用户意向直接指向我方品牌/车型时正常评定；
   我方车型信息为“未配置”时忽略本条。该匹配度调整作用于基线判定，与画像上调相互独立。
```

- [ ] **Step 4: 升级 config**

将 `app/skills/configs/user_lead_analysis.yaml` 中 `version`、`prompt_file`、`prompt_version` 三处更新为 1.2 / v3。用 Read 确认现有内容后，把版本号 `"1.1"`→`"1.2"`、`prompt_file` 值→`user_lead_analysis_v3.txt`、`prompt_version`→`"v3"`。

- [ ] **Step 5: 升级 SKILL_VERSIONS**

在 `app/workflow/pipeline.py` 的 `SKILL_VERSIONS` 字典中，把 `USER_ANALYSIS_SKILL: "1.1"` 改为 `USER_ANALYSIS_SKILL: "1.2"`。

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/test_agent2.py -k "v12_user_analysis or v11_user_analysis_prompt" -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add app/skills/prompts/user_lead_analysis_v3.txt app/skills/configs/user_lead_analysis.yaml app/workflow/pipeline.py tests/test_agent2.py
git commit -m "feat(v1.2): user_lead_analysis v3 注入画像+有限上调规则 (1.2)"
```

---

## Task 4: agent2 注入结构化画像

**Files:**
- Modify: `app/api/agent2.py:37-51`（`_build_evidence` + 新增 `_parse_profile`）
- Modify: `app/api/agent2.py:1-16`（import `extract_json`）
- Test: `tests/test_agent2.py`

**Interfaces:**
- Consumes: `app/skills/executor.py::extract_json(text)` → `dict | list`（无 JSON 抛 `ValueError`）；`recognize_screenshot()` 返回值（LLM 识图文本，理想为画像 JSON 字符串，空截图返回 `""`）。
- Produces: `_parse_profile(vision_text: str) -> dict | str`（能解析则返回画像对象，否则返回原文本）；`_build_evidence` 产出的 evidence 中 `user.homepage_profile` 为画像对象（或 `"（无主页截图）"`）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_agent2.py` 末尾追加：

```python
def test_v12_build_evidence_injects_structured_profile():
    import json as _json
    from app.api.agent2 import _build_evidence
    from app.api.schemas import AccountObject
    account = AccountObject(
        account_uid="u1", account_name="用户",
        comment_history=[{"video_title": "对比", "comment_content": "纠结",
                          "comment_time": "2026-07-19T14:23:00+08:00"}])
    profile_json = _json.dumps({"nickname": "应许",
                                "auto_relevance": "大量自驾游内容",
                                "interest_tags": ["自驾爱好者"]},
                               ensure_ascii=False)
    ev = _build_evidence(account, profile_json)
    hp = ev["user"]["homepage_profile"]
    assert isinstance(hp, dict)
    assert hp["auto_relevance"] == "大量自驾游内容"


def test_v12_build_evidence_empty_profile_placeholder():
    from app.api.agent2 import _build_evidence
    from app.api.schemas import AccountObject
    account = AccountObject(
        account_uid="u2", account_name="用户",
        comment_history=[{"video_title": "x", "comment_content": "y",
                          "comment_time": "2026-07-19T14:23:00+08:00"}])
    ev = _build_evidence(account, "")
    assert ev["user"]["homepage_profile"] == "（无主页截图）"


def test_v12_build_evidence_non_json_falls_back_to_text():
    from app.api.agent2 import _build_evidence
    from app.api.schemas import AccountObject
    account = AccountObject(
        account_uid="u3", account_name="用户",
        comment_history=[{"video_title": "x", "comment_content": "y",
                          "comment_time": "2026-07-19T14:23:00+08:00"}])
    ev = _build_evidence(account, "这是一段无结构的识图文本")
    assert ev["user"]["homepage_profile"] == "这是一段无结构的识图文本"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agent2.py -k v12_build_evidence -v`
Expected: FAIL（当前 evidence 键为 `homepage_description`，无 `homepage_profile`）

- [ ] **Step 3: 修改 import**

在 `app/api/agent2.py` 顶部 import 区，把
```python
from app.skills.executor import load_skill_config, render_prompt
```
改为
```python
from app.skills.executor import extract_json, load_skill_config, render_prompt
```

- [ ] **Step 4: 新增 `_parse_profile` 并改造 `_build_evidence`**

将 `app/api/agent2.py` 中现有 `_build_evidence` 函数替换为：

```python
def _parse_profile(vision_text: str):
    """把识图文本解析为结构化画像对象；解析失败回退为原始文本。"""
    try:
        return extract_json(vision_text)
    except ValueError:
        return vision_text


def _build_evidence(account: AccountObject, vision_text: str) -> dict:
    comments = [{
        "comment_id": f"{account.account_uid}:{idx}",
        "content": h.comment_content,
        "comment_time": h.comment_time,
        "video_title": h.video_title,
        "comment_like_count": h.comment_like_count,
    } for idx, h in enumerate(account.comment_history)]
    profile = _parse_profile(vision_text) if vision_text else "（无主页截图）"
    return {
        "user": {"nickname": account.account_name,
                 "douyin_id": account.account_douyin_id,
                 "homepage_profile": profile},
        "comments": comments,
        "statistics": {"valid_comment_count": len(comments)},
    }
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_agent2.py -k v12_build_evidence -v`
Expected: PASS

- [ ] **Step 6: 运行 agent2 全量测试确认无回归**

Run: `pytest tests/test_agent2.py -v`
Expected: PASS（既有 `test_profile_with_screenshot` 等用例：识图返回非 JSON 文本时回退为字符串，评级流程不受影响）

- [ ] **Step 7: 提交**

```bash
git add app/api/agent2.py tests/test_agent2.py
git commit -m "feat(v1.2): _build_evidence 注入结构化主页画像"
```

---

## Task 5: 画像上调流程端到端测试

**Files:**
- Test: `tests/test_agent2.py`

**Interfaces:**
- Consumes: `app/api/agent2.py::run_profile_analysis(executor, gateway, request)`；`MockProvider.queue(*responses)`（按序返回，Agent2 先识图后评级，故 `queue(识图响应, 评级响应)`）。
- Produces: 无（纯验证）。

**说明:** 单阶段评级中"是否上调"由 LLM 依 prompt 判定，单测用 mock 固定 LLM 输出，验证审计字段随 `UserLeadResult` 正确流转、且 `map_profile_result` 依据最终 `lead_grade` 映射对外等级、审计字段不泄漏到对外输出。

- [ ] **Step 1: 写测试**

在 `tests/test_agent2.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_v12_profile_upgrade_maps_final_grade():
    """基线 B 经画像上调为 A：对外等级按最终 lead_grade=A 映射，审计字段不泄漏。"""
    profile = json.dumps({"nickname": "应许", "auto_relevance": "大量自驾游内容",
                          "interest_tags": ["自驾爱好者"]}, ensure_ascii=False)
    lead = json.dumps({
        "baseline_grade": "B", "profile_adjustment": "upgraded",
        "adjustment_reason": "主页大量自驾游内容",
        "lead_grade": "A", "is_valid_lead": True, "lead_summary": "自驾意向",
        "evidence_comment_ids": ["u1:0"], "confidence": 0.85,
        "profile_tags": ["自驾爱好者"], "profile_summary": "画像", "analysis_text": "分析"})
    executor, gateway = _executor_and_gateway(profile, lead)
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u1", "account_name": "应许",
        "account_homepage_screenshot": "https://cdn/x.png",
        "comment_history": [{"video_title": "越野", "comment_content": "在看这款",
                             "comment_time": "2026-07-19T14:23:00+08:00",
                             "comment_like_count": 5}]}])
    out = await run_profile_analysis(executor, gateway, req)
    r = out["results"][0]
    assert r["intent_level_code"] == "medium"  # A→中
    assert 85 <= r["value_score"] <= 100 or r["value_score"] >= 70
    # 审计字段不进对外契约
    assert "baseline_grade" not in r
    assert "profile_adjustment" not in r


@pytest.mark.asyncio
async def test_v12_profile_baseline_c_not_upgraded():
    """基线 C 且 LLM 未上调：最终 lead_grade=C，映射为 has_value=false（C 不在对外区间）。"""
    profile = json.dumps({"auto_relevance": "无明显汽车相关内容"}, ensure_ascii=False)
    lead = json.dumps({
        "baseline_grade": "C", "profile_adjustment": "none",
        "adjustment_reason": None, "lead_grade": "C", "is_valid_lead": False,
        "evidence_comment_ids": ["u4:0"], "confidence": 0.6,
        "profile_tags": [], "profile_summary": "p", "analysis_text": "a"})
    executor, gateway = _executor_and_gateway(profile, lead)
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u4", "account_name": "用户",
        "account_homepage_screenshot": "https://cdn/x.png",
        "comment_history": [{"video_title": "吐槽", "comment_content": "这车真丑",
                             "comment_time": "2026-07-19T14:23:00+08:00"}]}])
    out = await run_profile_analysis(executor, gateway, req)
    r = out["results"][0]
    assert r["has_value"] is False  # C 级 lead_grade 不在 _GRADE_MAP 对外区间
```

- [ ] **Step 2: 运行测试确认通过**

Run: `pytest tests/test_agent2.py -k v12_profile -v`
Expected: PASS

> 注：本任务为纯测试，若 Step 2 直接通过（因 Task 2/4 已使审计字段与画像注入生效），说明流程正确，无需额外实现代码。

- [ ] **Step 3: 提交**

```bash
git add tests/test_agent2.py
git commit -m "test(v1.2): 画像上调端到端流程与对外契约不泄漏"
```

---

## Task 6: 用示例截图实测识图 prompt（人工验证）

**Files:**
- 无代码变更（验证 + 视需要微调 `app/skills/prompts/image_recognition_v2.txt`）

**Interfaces:**
- Consumes: `data/douyin_screenshot_example.png`；真实多模态 LLM（需 `.env` 配置）或 `scripts/` 下现有识图调用脚本。
- Produces: 验证结论；若字段缺漏/异常处理不佳则回到 Task 1 prompt 微调。

**说明:** 此任务依赖真实 LLM，属人工/联调验证，不阻塞单元测试。若当前环境无 LLM 配置，标记为待联调并在完成报告中说明。

- [ ] **Step 1: 编写/复用一次性识图脚本**

用现有 `recognize_screenshot` 对示例图做一次真实调用（若 `.env` 已配置多模态模型）。可临时脚本：

```python
import asyncio, base64
from app.llm.gateway import LLMGateway
from app.llm.factory import build_provider  # 若存在；否则参考 scripts/api_smoke_test.py 构造
from app.api.agent2 import recognize_screenshot

async def main():
    b64 = base64.b64encode(open("data/douyin_screenshot_example.png", "rb").read()).decode()
    gateway = LLMGateway(build_provider())
    print(await recognize_screenshot(gateway, b64))

asyncio.run(main())
```

（构造 provider 的确切方式以 `scripts/api_smoke_test.py` 中现有做法为准，Read 该文件后对齐。）

- [ ] **Step 2: 核对输出**

检查：nickname/ip_location/性别/粉丝关注获赞数是否准确；111 岁是否判为 null；content_themes 是否覆盖游戏/电竞/宠物；auto_relevance 是否客观写明"无明显汽车/自驾相关内容"（示例账号无汽车信号）；JSON 是否可被 `extract_json` 解析。

- [ ] **Step 3: 视需要微调 prompt 并复测**

若字段缺漏或异常处理不佳，回 `image_recognition_v2.txt` 微调后重复 Step 1-2。稳定后：

```bash
git add app/skills/prompts/image_recognition_v2.txt
git commit -m "chore(v1.2): 依示例截图实测调优识图 prompt"
```

（无改动则跳过提交。）

---

## Task 7: 更新 API 对接文档

**Files:**
- Modify: `docs/DriveIntent-V1-API对接文档.md`（版本头 + Agent2 章节 + 顶部标题下方版本号）

**Interfaces:**
- Consumes: 无
- Produces: 文档说明 V1.2 起主页截图正式纳入评级、契约不变。

- [ ] **Step 1: 更新版本头**

把文档第 3 行 `**版本**：1.1.1　**更新日期**：2026-07-28` 更新为 `**版本**：1.2　**更新日期**：2026-07-28`。

- [ ] **Step 2: 在 Agent2「V1.1 行为变化」小节后补充 V1.2 说明**

在 `docs/DriveIntent-V1-API对接文档.md` 的「### V1.1 行为变化：评级考量我方车型匹配度」小节之后，新增：

```markdown
### V1.2 行为变化：主页截图正式纳入评级

自 V1.2 起，`account_homepage_screenshot` 正式参与分析：服务端先对截图做识别，
归纳出结构化用户画像（内容主题、消费能力、兴趣标签、年龄性别、IP 属地、汽车相关性等），
再据此对**高质量线索**做有限上调——仅当基线为中/低（B/A 内部等级）且画像有直接证据
（如自驾爱好者、汽车发烧友、明确高消费信号）时，最多上调一级；画像只上调不下调，
低质量线索（C 及以下）不受画像影响。**输出字段结构不变**，对接方无需改动解析逻辑；
截图为空或识别失败时行为与 V1.1 一致（走降级路径、`value_score` 降 10-15 分）。
```

- [ ] **Step 3: 提交**

```bash
git add docs/DriveIntent-V1-API对接文档.md
git commit -m "docs(v1.2): 对接文档补充主页截图纳入评级说明"
```

---

## Task 8: 全量回归 + 归档提交

**Files:**
- 无代码变更（验证 + 归档）

- [ ] **Step 1: 全量测试**

Run: `pytest -q`
Expected: 全部 PASS（重点关注 `tests/test_agent2.py`、`tests/test_api_schemas.py`、`tests/test_v1_integration.py`、`tests/test_api_worker_failures.py` 无回归）

- [ ] **Step 2: 若有失败，定位修复后重跑**

对失败用例逐一排查（常见：其它测试硬编码了 `user_lead_analysis` v2/1.1 或 `image_recognition` v1/1.0 版本断言）。用 Grep 搜索 `"1.1"`、`user_lead_analysis_v2`、`image_recognition_v1` 定位并更新。

- [ ] **Step 3: 确认工作树干净并回顾提交历史**

Run: `git status && git log --oneline -8`
Expected: 工作树干净，V1.2 各任务提交完整。

---

## Self-Review

**Spec coverage（对照 `claude_docs/2026-07-28-v1.2-design.md`）:**
- §2 识图结构化画像 → Task 1（prompt+config）、Task 6（实测调优）✅
- §3.1 有限上调规则 → Task 3（v3 prompt 规则）✅
- §3.2 内部审计字段 → Task 2（schema）、Task 5（流转验证）✅
- §3.3 prompt/版本升级 → Task 3 ✅
- §4 数据流（`homepage_profile` 注入、映射不变、8000 路径空画像）→ Task 4 + Task 5 ✅
- §5 测试（注入/降级/基线C不上调/B上调/契约回归）→ Task 4/5/8 ✅
- §6 影响文件清单 → 全部任务覆盖，含文档 Task 7 ✅

**Placeholder scan:** 无 TBD/TODO；所有代码步骤含完整代码块；Task 6 依赖真实 LLM 已显式标注为联调验证并给出降级说明。

**Type consistency:** `_parse_profile(vision_text: str) -> dict | str`、`homepage_profile` 键名、审计字段名（`baseline_grade`/`profile_adjustment`/`adjustment_reason`）在 Task 2/3/4/5 中一致；`extract_json` 抛 `ValueError`（`json.JSONDecodeError` 为其子类）与 Task 4 catch 一致；`SKILL_VERSIONS` 键 `USER_ANALYSIS_SKILL` 与 pipeline 现有定义一致。
