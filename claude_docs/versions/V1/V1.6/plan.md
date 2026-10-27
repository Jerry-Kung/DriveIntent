# V1.6 实施计划：Agent2 无效用户过滤节点

> 版本：V1.6 | 日期：2026-08-11
> 设计文档：[design.md](design.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Agent2 定级流水线之前新增独立 LLM 过滤节点，提前过滤"实际无购车意向但易被误判为高价值"的用户（直接定 C），并把分散在定级 Prompt 中的用户级过滤规则统一迁移收口。

**Architecture:** 新增 `user_lead_filter` Skill（文本模型、独立 Prompt），共享函数 `run_user_filter`（fail-open）供 API 路径（`app/api/agent2.py`）与 V0 流水线路径（`app/workflow/pipeline.py`）复用；命中者由 `build_filtered_lead_result` 合成 C 级 `UserLeadResult` 走既有映射/落库，对外契约零变化。定级 Prompt 升 v1.6，删除已迁出规则。

**Tech Stack:** Python / Pydantic v2 / pytest（asyncio）/ MockProvider 测试桩。

## Global Constraints

- 简体中文注释与文档；遵循 `claude_docs/versions/VERSIONING.md`（Prompt 文件名 `<skill_id>_v1.6.txt`、`prompt_version "v1.6"`、Skill config `version "1.6"`）
- 对外 API 响应结构零变化（新增字段仅内部审计，不进 `ProfileResult`）
- 过滤节点 fail-open：LLM 失败/输出非法一律放行进定级，不阻断主流程
- 测试命令：`python -m pytest tests/ -q`（Windows 环境）
- 提交信息风格：`feat(v1.6): …` / `test(v1.6): …` / `docs(v1.6): …`，每任务一提交

---

### Task 1: Schema——新增 UserFilterResult 与 UserLeadResult 审计字段

**Files:**
- Modify: `app/schemas/skills.py`（`UserLeadResult` 之后追加新类；`UserLeadResult` 内追加两字段）
- Test: `tests/test_user_filter.py`（新建）

**Interfaces:**
- Produces: `app.schemas.skills.UserFilterResult`（字段见下）；`UserLeadResult.filter_category: str | None`、`UserLeadResult.filter_reason: str | None`（默认均 None）

- [x] **Step 1: 写失败测试**（新建 `tests/test_user_filter.py`）

```python
import json

import pytest
from pydantic import ValidationError


def test_v16_user_filter_result_defaults():
    from app.schemas.skills import UserFilterResult
    r = UserFilterResult()
    assert r.filtered is False
    assert r.filter_category is None
    assert r.filter_reason is None
    assert r.is_car_owner is False
    assert r.has_purchase_intent is False
    assert r.evidence_comment_ids == []
    assert r.profile_tags == []
    assert r.confidence == 0.0


def test_v16_user_filter_result_accepts_all_categories():
    from app.schemas.skills import UserFilterResult
    for cat in ("already_purchased", "promoting_others", "proxy_inquiry",
                "marketing_suspect", "industry_professional", "other"):
        r = UserFilterResult(filtered=True, filter_category=cat,
                             filter_reason="理由")
        assert r.filter_category == cat


def test_v16_user_filter_result_rejects_invalid_category():
    from app.schemas.skills import UserFilterResult
    with pytest.raises(ValidationError):
        UserFilterResult(filtered=True, filter_category="not_a_category")


def test_v16_user_lead_result_has_filter_audit_fields():
    from app.schemas.skills import UserLeadResult
    r = UserLeadResult(lead_grade="C")
    assert r.filter_category is None
    assert r.filter_reason is None
    r2 = UserLeadResult(lead_grade="C", is_valid_lead=False,
                        filter_category="already_purchased",
                        filter_reason='评论"已提车"为已完成购买信号且无新购意向')
    assert r2.filter_category == "already_purchased"
```

- [x] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_user_filter.py -q`
Expected: FAIL（`ImportError: cannot import name 'UserFilterResult'`）

- [x] **Step 3: 实现 Schema**（`app/schemas/skills.py`）

`UserLeadResult` 的 `purchase_downgrade_reason` 字段之后、`confidence` 之前插入：

```python
    # V1.6：无效用户过滤审计字段（内部用，不进对外 API 契约）。
    # 被前置过滤节点命中时写入；未过滤（走完整定级流水线）为 None。
    filter_category: str | None = None
    filter_reason: str | None = None
```

文件末尾追加：

```python
class UserFilterResult(BaseModel):
    """V1.6 无效用户前置过滤输出。

    识别"实际无购车意向但易被误判为高价值"的用户，命中者不进定级流水线。
    两个独立标签由本节点一并判定：被过滤用户不进定级，对外契约的
    is_car_owner / has_purchase_intent 由此供给；未过滤时以定级输出为准。
    """
    filtered: bool = False
    filter_category: Literal["already_purchased", "promoting_others",
                             "proxy_inquiry", "marketing_suspect",
                             "industry_professional", "other"] | None = None
    filter_reason: str | None = None
    is_car_owner: bool = False
    has_purchase_intent: bool = False
    evidence_comment_ids: list[str] = []
    profile_tags: list[str] = []
    profile_summary: str = ""
    analysis_text: str = ""
    confidence: float = 0.0
```

- [x] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_user_filter.py -q`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add app/schemas/skills.py tests/test_user_filter.py
git commit -m "feat(v1.6): UserFilterResult 输出 Schema 与 UserLeadResult 过滤审计字段"
```

---

### Task 2: 过滤 Skill 资产与共享模块（Prompt / 配置 / run_user_filter）

**Files:**
- Create: `app/skills/prompts/user_lead_filter_v1.6.txt`
- Create: `app/skills/configs/user_lead_filter.yaml`
- Create: `app/skills/user_filter.py`
- Test: `tests/test_user_filter.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `UserFilterResult`；`app.skills.executor.SkillExecutionError`；executor 鸭子类型接口 `await executor.run(skill_id: str, context: dict, output_model) -> BaseModel`
- Produces: `app.skills.user_filter.USER_FILTER_SKILL = "user_lead_filter"`；`async run_user_filter(executor, evidence: dict) -> UserFilterResult`（fail-open）；`build_filtered_lead_result(f: UserFilterResult) -> UserLeadResult`

- [x] **Step 1: 写失败测试**（追加到 `tests/test_user_filter.py`）

```python
# —— 供本文件与其他测试文件复用的 Mock 响应 ——
NOT_FILTERED_JSON = json.dumps({
    "filtered": False, "is_car_owner": False, "has_purchase_intent": True,
    "confidence": 0.8}, ensure_ascii=False)

FILTERED_JSON = json.dumps({
    "filtered": True, "filter_category": "already_purchased",
    "filter_reason": '评论"提车三个月"表明已完成购车且无新增购车意向',
    "is_car_owner": True, "has_purchase_intent": False,
    "evidence_comment_ids": ["u1:0"], "profile_tags": ["已购车主"],
    "profile_summary": "已购车主，近期无再购信号",
    "analysis_text": "多条评论均为已购后的用车分享，无新增购车意向",
    "confidence": 0.9}, ensure_ascii=False)

_EVIDENCE = {"user": {"nickname": "用户", "homepage_profile": "（无主页截图）"},
             "comments": [{"comment_id": "u1:0", "content": "提车三个月"}],
             "statistics": {"valid_comment_count": 1}}


def _executor(*responses):
    from app.llm.gateway import LLMGateway
    from app.llm.mock import MockProvider
    from app.skills.executor import SkillExecutor
    provider = MockProvider()
    provider.queue(*responses)
    return SkillExecutor(LLMGateway(provider))


@pytest.mark.asyncio
async def test_v16_run_user_filter_hit():
    from app.skills.user_filter import run_user_filter
    out = await run_user_filter(_executor(FILTERED_JSON), _EVIDENCE)
    assert out.filtered is True
    assert out.filter_category == "already_purchased"
    assert out.is_car_owner is True


@pytest.mark.asyncio
async def test_v16_run_user_filter_pass():
    from app.skills.user_filter import run_user_filter
    out = await run_user_filter(_executor(NOT_FILTERED_JSON), _EVIDENCE)
    assert out.filtered is False


@pytest.mark.asyncio
async def test_v16_run_user_filter_llm_failure_fail_open():
    from app.skills.user_filter import run_user_filter
    out = await run_user_filter(_executor(), _EVIDENCE)  # 空队列→LLMError
    assert out.filtered is False


@pytest.mark.asyncio
async def test_v16_run_user_filter_missing_category_fail_open():
    from app.skills.user_filter import run_user_filter
    bad = json.dumps({"filtered": True, "filter_reason": "缺类别"},
                     ensure_ascii=False)
    out = await run_user_filter(_executor(bad), _EVIDENCE)
    assert out.filtered is False


def test_v16_build_filtered_lead_result():
    from app.schemas.skills import UserFilterResult
    from app.skills.user_filter import build_filtered_lead_result
    f = UserFilterResult.model_validate(json.loads(FILTERED_JSON))
    out = build_filtered_lead_result(f)
    assert out.lead_grade == "C"
    assert out.is_valid_lead is False
    assert out.filter_category == "already_purchased"
    assert out.filter_reason == f.filter_reason
    assert out.is_car_owner is True
    assert out.has_purchase_intent is False
    assert out.profile_tags == ["已购车主"]
    assert out.analysis_text  # 非空：有 analysis_text 或回退 filter_reason


def test_v16_build_filtered_lead_result_analysis_falls_back_to_reason():
    from app.schemas.skills import UserFilterResult
    from app.skills.user_filter import build_filtered_lead_result
    f = UserFilterResult(filtered=True, filter_category="other",
                         filter_reason="具体理由")
    assert build_filtered_lead_result(f).analysis_text == "具体理由"


def test_v16_filter_config():
    from app.skills.executor import load_skill_config
    config = load_skill_config("user_lead_filter")
    assert config.prompt_file == "user_lead_filter_v1.6.txt"
    assert config.prompt_version == "v1.6"
    assert config.version == "1.6"
    assert config.multimodal is False


def test_v16_filter_prompt_renders_with_categories():
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("user_lead_filter")
    text = render_prompt(config, {"user_evidence_json": "{}"})
    for cat in ("already_purchased", "promoting_others", "proxy_inquiry",
                "marketing_suspect", "industry_professional", "other"):
        assert cat in text
    assert "宁放过勿误杀" in text
    assert "filter_category" in text and "filter_reason" in text
    assert "is_car_owner" in text and "has_purchase_intent" in text
    assert "我朋友想买" in text          # proxy_inquiry 示例
    assert "刚提车" in text              # already_purchased 豁免示例
    assert "comment_time" in text        # 时效性引导
```

- [x] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_user_filter.py -q`
Expected: 新增用例 FAIL（`ModuleNotFoundError: app.skills.user_filter` / 配置文件不存在）

- [x] **Step 3: 写过滤 Prompt**（新建 `app/skills/prompts/user_lead_filter_v1.6.txt`，完整内容如下）

```text
你是汽车销售线索质检专家。以下是一位抖音用户的全部有效评论及其上下文，
以及从其主页截图识别出的结构化画像。你的任务是"无效用户过滤"：在正式意向
评级之前，识别那些实际无购车意向、但容易被误判为高价值客户的用户。

用户证据包（JSON，user.homepage_profile 为主页画像，缺失时为"（无主页截图）"）：
$user_evidence_json

【过滤类别】仅当用户整体符合以下情形之一时过滤（filtered=true），
filter_category 取对应值：
- already_purchased：已完成购买动作（已下单/已大定/已提车/已购）且无任何
  新增购车意向——近期已购车者短期内再购可能性很低，销售价值有限。
  豁免（不过滤）：同时有明确新增购车意向（如"刚提车，想再买一台给家里人"
  "已提车但空间太小打算换了"）；或已购信号距今久远（参考 comment_time，
  如一年以上）且有其他购车相关信号。
- promoting_others：评论主要是怂恿/引导他人购买或营销推广口吻（如选车
  视频下"分期30期买XX"），看不出本人购车意向。
- proxy_inquiry：全部购车相关表达均为替他人问询/转述他人意向（如"我朋友想买
  一辆xxx"），无本人意向。只要存在任何本人意向表达 → 不过滤，交由评级环节。
- marketing_suspect：疑似营销账号/水军——评论模板化、跨视频重复推广话术、
  主页画像呈现营销/引流特征等。
- industry_professional：车评人、汽车媒体、同行销售等汽车从业者——评论专业
  但目的是内容创作/获客而非本人购车（须结合主页画像与评论行为综合判断）。
- other：以上类别之外的其他明确无效情形，必须写明具体情形与理由。

【判定原则】
1. 全量综合判断：必须综合该用户全部评论与主页画像整体判断，严禁凭单条
   评论片面定性；
2. 宁放过勿误杀：过滤必须有明确证据（filter_reason 中引用具体评论内容或
   画像字段）；证据不足、情形模糊、多种解释并存时一律 filtered=false 放行，
   交由后续评级环节甄别；
3. 无论是否过滤，两个独立标签照常判定：
   - is_car_owner（是否车主）：有明确证据表明该用户大概率已购车
     （已下单/下大定也算已购，不要求是我方在售车型）→ true；
     "准备订""想下定"是意向不是已购，咨询他人用车体验的是潜在买家，均判 false；
   - has_purchase_intent（购车意向）：表达了任何本人买车相关倾向 → true；
     替他人问询/怂恿他人不算本人意向；单纯夸赞、技术讨论不算。

请严格输出以下 JSON（不要输出任何其他内容）：
{
  "filtered": "是否过滤布尔值：true | false",
  "filter_category": "过滤类别：already_purchased | promoting_others | proxy_inquiry | marketing_suspect | industry_professional | other，未过滤为 null",
  "filter_reason": "过滤理由，必须引用具体评论/画像证据，未过滤为 null",
  "is_car_owner": "是否车主布尔值：true | false",
  "has_purchase_intent": "是否有购车意向布尔值：true | false",
  "evidence_comment_ids": ["支撑判断的评论 comment_id，必须来自输入"],
  "profile_tags": ["账号画像标签，如：已购车主、营销账号、汽车从业者"],
  "profile_summary": "账号画像摘要，50-150 字",
  "analysis_text": "过滤判定说明，100-300 字，说明过滤或放行的依据",
  "confidence": 0.9
}

要求：
1. 过滤结论必须有证据支撑：filtered=true 时 filter_category 与 filter_reason
   必填，evidence_comment_ids 不得为空；
2. 没有证据的字段输出 null 或空数组，严禁编造。
```

- [x] **Step 4: 写 Skill 配置**（新建 `app/skills/configs/user_lead_filter.yaml`）

```yaml
skill_id: user_lead_filter
version: "1.6"
description: >
  无效用户前置过滤：基于用户全量证据包（全部评论+主页画像）识别实际无
  购车意向但易被误判为高价值客户的用户（已购无新购计划/怂恿他人/仅替
  他人问询/疑似营销水军/汽车从业者/其他），命中者直接定 C 级，不进入
  后续定级流水线；宁放过勿误杀，证据不足一律放行。
model:
  name: ""
  temperature: 0.1
prompt_file: user_lead_filter_v1.6.txt
prompt_version: "v1.6"
```

- [x] **Step 5: 写共享模块**（新建 `app/skills/user_filter.py`，完整内容如下）

```python
import json
import logging

from app.schemas.skills import UserFilterResult, UserLeadResult
from app.skills.executor import SkillExecutionError

logger = logging.getLogger(__name__)

USER_FILTER_SKILL = "user_lead_filter"


async def run_user_filter(executor, evidence: dict) -> UserFilterResult:
    """V1.6 无效用户前置过滤。

    fail-open：LLM 调用/校验失败，或 filtered=true 却缺 filter_category
    （输出非法）时，一律放行进入定级流水线，不阻断主流程。
    """
    ctx = {"user_evidence_json": json.dumps(evidence, ensure_ascii=False)}
    try:
        out: UserFilterResult = await executor.run(
            USER_FILTER_SKILL, ctx, UserFilterResult)
    except SkillExecutionError as e:
        logger.warning("无效用户过滤失败，放行进入定级: %s", e)
        return UserFilterResult()
    if out.filtered and out.filter_category is None:
        logger.warning("过滤输出缺少 filter_category，放行进入定级")
        return UserFilterResult()
    return out


def build_filtered_lead_result(f: UserFilterResult) -> UserLeadResult:
    """把过滤命中结果合成为 C 级 UserLeadResult，走既有映射与落库路径。"""
    return UserLeadResult(
        lead_grade="C", is_valid_lead=False,
        filter_category=f.filter_category, filter_reason=f.filter_reason,
        is_car_owner=f.is_car_owner,
        has_purchase_intent=f.has_purchase_intent,
        evidence_comment_ids=list(f.evidence_comment_ids),
        profile_tags=list(f.profile_tags),
        profile_summary=f.profile_summary,
        analysis_text=f.analysis_text or (f.filter_reason or ""),
        confidence=f.confidence)
```

- [x] **Step 6: 运行确认通过**

Run: `python -m pytest tests/test_user_filter.py -q`
Expected: PASS（全部用例）

- [x] **Step 7: 提交**

```bash
git add app/skills/prompts/user_lead_filter_v1.6.txt app/skills/configs/user_lead_filter.yaml app/skills/user_filter.py tests/test_user_filter.py
git commit -m "feat(v1.6): 无效用户过滤 Skill——Prompt/配置/共享模块（fail-open）"
```

---

### Task 3: API 路径接入（run_profile_analysis）

**Files:**
- Modify: `app/api/agent2.py`（`run_profile_analysis` 内、`analyze_account` 调用处）
- Test: `tests/test_agent2.py`（新增 2 个用例 + 更新既有用例的 Mock 队列）

**Interfaces:**
- Consumes: Task 2 的 `run_user_filter` / `build_filtered_lead_result`；`tests.test_user_filter.NOT_FILTERED_JSON` / `FILTERED_JSON`
- Produces: 行为变更——每个有评论账号在定级前先过一次过滤 LLM 调用；命中者不再发起定级调用

- [x] **Step 1: 写失败测试**（追加到 `tests/test_agent2.py`）

```python
@pytest.mark.asyncio
async def test_v16_filtered_account_returns_c_without_grading():
    """过滤命中：直接 C（has_value=false），不发起定级调用，标签来自过滤节点。"""
    from tests.test_user_filter import FILTERED_JSON
    provider = MockProvider()
    provider.queue(FILTERED_JSON)  # 无截图→仅一次过滤调用，无定级响应
    gateway = LLMGateway(provider)
    executor = SkillExecutor(gateway)
    sent = []
    orig = provider.chat

    async def spy(messages, **kw):
        sent.append(messages)
        return await orig(messages, **kw)
    provider.chat = spy
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u1", "account_name": "用户",
        "account_homepage_screenshot": "",
        "comment_history": [{"video_title": "t", "comment_content": "提车三个月",
                             "comment_time": "2026-07-19T14:23:00+08:00",
                             "comment_like_count": 1}]}])
    out = await run_profile_analysis(executor, gateway, req)
    r = out["results"][0]
    assert len(sent) == 1                    # 仅过滤一跳，定级未被调用
    assert r["has_value"] is False
    assert r["is_car_owner"] is True         # 标签由过滤节点供给
    assert r["has_purchase_intent"] is False
    assert r["analysis"]                     # 携带过滤判定说明
    assert "filter_category" not in r        # 审计字段不进对外契约
    assert "filter_reason" not in r


@pytest.mark.asyncio
async def test_v16_unfiltered_account_proceeds_to_grading():
    """过滤放行：正常走定级，结果与过滤节点无关。"""
    from tests.test_user_filter import NOT_FILTERED_JSON
    lead = json.dumps({
        "lead_grade": "H", "is_valid_lead": True, "lead_summary": "s",
        "evidence_comment_ids": ["u2:0"], "confidence": 0.9,
        "profile_tags": [], "profile_summary": "p", "analysis_text": "a"})
    executor, gateway = _executor_and_gateway(NOT_FILTERED_JSON, lead)
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u2", "account_name": "用户",
        "account_homepage_screenshot": "",
        "comment_history": [{"video_title": "t", "comment_content": "落地多少钱",
                             "comment_time": "2026-07-19T14:23:00+08:00",
                             "comment_like_count": 1}]}])
    out = await run_profile_analysis(executor, gateway, req)
    r = out["results"][0]
    assert r["has_value"] is True
    assert r["intent_level_code"] == "high"
```

- [x] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_agent2.py -q -k v16`
Expected: FAIL（当前流程无过滤调用：第一个用例 `len(sent)` 为 1 但结果按定级解析报错，或断言失败）

- [x] **Step 3: 实现接入**（`app/api/agent2.py`）

顶部 import 追加：

```python
from app.skills.user_filter import build_filtered_lead_result, run_user_filter
```

`run_profile_analysis` 中，将：

```python
                out = await analyze_account(
                    executor, account, vision_text, our_models_summary)
```

替换为：

```python
                # V1.6：定级前先过无效用户过滤（fail-open），命中直接定 C
                filt = await run_user_filter(
                    executor, _build_evidence(account, vision_text))
                if filt.filtered:
                    out = build_filtered_lead_result(filt)
                else:
                    out = await analyze_account(
                        executor, account, vision_text, our_models_summary)
```

- [x] **Step 4: 更新既有用例的 Mock 队列**（`tests/test_agent2.py`）

文件顶部追加 `from tests.test_user_filter import NOT_FILTERED_JSON`，下列用例在定级响应**之前**插入一条 `NOT_FILTERED_JSON`：

- `test_profile_with_screenshot`：`queue("这是科技博主主页", lead)` → `queue("这是科技博主主页", NOT_FILTERED_JSON, lead)`
- `test_profile_no_screenshot_lowers_score`：`(lead)` → `(NOT_FILTERED_JSON, lead)`
- `test_v12_profile_upgrade_maps_final_grade`：`(profile, lead)` → `(profile, NOT_FILTERED_JSON, lead)`
- `test_v12_profile_baseline_c_not_upgraded`：同上
- `test_v121_unrelated_model_downgrade_maps_final_grade`：同上
- `test_v121_our_model_upgrade_maps_final_grade`：同上
- `test_v13_profile_result_carries_labels`：`(lead)` → `(NOT_FILTERED_JSON, lead)`

不改：`test_profile_empty_history_no_value`（零 LLM）、`test_v11_analyze_account_passes_summary`（直调 `analyze_account`，不含过滤）、`test_v13_profile_error_item_labels_null`（空队列→过滤 fail-open 放行→定级失败→error item，行为不变）。

- [x] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_agent2.py tests/test_user_filter.py -q`
Expected: PASS（全部）

- [x] **Step 6: 提交**

```bash
git add app/api/agent2.py tests/test_agent2.py
git commit -m "feat(v1.6): API 路径接入无效用户过滤——命中直接 C 不进定级"
```

---

### Task 4: V0 流水线路径接入（run_user_analysis）

**Files:**
- Modify: `app/workflow/pipeline.py`（`run_user_analysis`）
- Test: `tests/test_user_analysis.py`（新增 1 用例 + 既有队列更新）、`tests/test_pipeline_connection_release.py`（队列与断言更新）

**Interfaces:**
- Consumes: Task 2 的 `run_user_filter` / `build_filtered_lead_result`；`tests.test_user_filter.NOT_FILTERED_JSON` / `FILTERED_JSON`
- Produces: V0 路径行为与 API 路径一致——过滤命中落 C 级 `AnalysisResult`（含审计字段），`is_valid_lead=False` 自然跳过 `upsert_lead`

- [x] **Step 1: 写失败测试**（追加到 `tests/test_user_analysis.py`）

```python
async def test_v16_run_user_analysis_filtered_no_lead(session):
    from app.models import AnalysisResult
    from tests.test_user_filter import FILTERED_JSON
    _, u1, _, c1, _ = _setup(session)
    provider = MockProvider()
    provider.queue(FILTERED_JSON)  # 仅过滤一跳，无定级响应
    executor = SkillExecutor(LLMGateway(provider))

    await run_user_analysis(session, executor, u1.id)

    assert session.query(Lead).count() == 0
    res = session.query(AnalysisResult).filter_by(
        target_type="user", target_id=str(u1.id)).one()
    assert res.result["lead_grade"] == "C"
    assert res.result["filter_category"] == "already_purchased"
    assert res.result["filter_reason"]
```

- [x] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_user_analysis.py -q -k v16`
Expected: FAIL（当前流程把 FILTERED_JSON 当定级输出解析，`lead_grade` 缺失 → SkillExecutionError）

- [x] **Step 3: 实现接入**（`app/workflow/pipeline.py`）

顶部 import 追加：

```python
from app.skills.user_filter import build_filtered_lead_result, run_user_filter
```

`run_user_analysis` 中，将：

```python
    out: UserLeadResult = await executor.run(
        USER_ANALYSIS_SKILL, context, UserLeadResult)
```

替换为：

```python
    # V1.6：定级前先过无效用户过滤（fail-open）。命中合成 C 级结果照常
    # 落 AnalysisResult（含审计字段）；is_valid_lead=False 自然跳过 upsert_lead。
    filt = await run_user_filter(executor, evidence)
    if filt.filtered:
        out: UserLeadResult = build_filtered_lead_result(filt)
    else:
        out = await executor.run(
            USER_ANALYSIS_SKILL, context, UserLeadResult)
```

- [x] **Step 4: 更新既有用例队列**

`tests/test_user_analysis.py`：顶部追加 `from tests.test_user_filter import NOT_FILTERED_JSON`；下列用例在每次定级响应前插入 `NOT_FILTERED_JSON`：

- `test_run_user_analysis_creates_lead`：`queue(LEAD…)` → `queue(NOT_FILTERED_JSON, LEAD…)`
- `test_run_user_analysis_upsert`：`queue(lead1, lead2)` → `queue(NOT_FILTERED_JSON, lead1, NOT_FILTERED_JSON, lead2)`
- `test_run_user_analysis_filters_hallucinated_evidence_ids`、`test_run_user_analysis_invalid_lead_creates_no_lead`、`test_run_user_analysis_valid_lead_all_evidence_hallucinated_creates_no_lead`：各自 `queue(payload)` → `queue(NOT_FILTERED_JSON, payload)`

`tests/test_pipeline_connection_release.py` 的 `test_run_user_analysis_releases_connection_during_llm`：

```python
    from tests.test_user_filter import NOT_FILTERED_JSON
    spy = _spy(session, NOT_FILTERED_JSON, LEAD_JSON.replace("__CID__", str(c1.id)))

    await run_user_analysis(session, spy, u1.id)

    assert spy.in_txn_at_call == [False, False]  # 过滤与定级两跳均不持有事务
```

- [x] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_user_analysis.py tests/test_pipeline_connection_release.py -q`
Expected: PASS（全部）

- [x] **Step 6: 提交**

```bash
git add app/workflow/pipeline.py tests/test_user_analysis.py tests/test_pipeline_connection_release.py
git commit -m "feat(v1.6): V0 流水线路径接入无效用户过滤——与 API 路径行为一致"
```

---

### Task 5: 定级 Prompt v1.6 瘦身（已迁出规则删除）与升版

**Files:**
- Create: `app/skills/prompts/user_lead_analysis_v1.6.txt`（由 v1.5.1 复制修改，旧文件保留不动）
- Modify: `app/skills/configs/user_lead_analysis.yaml`
- Modify: `app/workflow/pipeline.py`（`SKILL_VERSIONS` 中 `user_lead_analysis` 值 `"1.5.1"` → `"1.6"`）
- Test: `tests/test_agent2.py`（既有版本锚点测试更新）

**Interfaces:**
- Consumes: 无（纯资产变更）
- Produces: `load_skill_config("user_lead_analysis")` → `version "1.6"` / `prompt_file "user_lead_analysis_v1.6.txt"` / `prompt_version "v1.6"`

- [x] **Step 1: 更新版本锚点测试为失败态**（`tests/test_agent2.py`）

`test_v151_user_analysis_config_uses_v151` 整体替换为：

```python
def test_v16_user_analysis_config_uses_v16():
    from app.skills.executor import load_skill_config
    config = load_skill_config("user_lead_analysis")
    assert config.prompt_file == "user_lead_analysis_v1.6.txt"
    assert config.prompt_version == "v1.6"
    assert config.version == "1.6"
```

`test_v151_user_analysis_prompt_has_final_adjust_rules` 整体替换为：

```python
def test_v16_user_analysis_prompt_final_adjust_merge_only():
    """v1.6：第四段只剩合并增强；已购封顶与怂恿降档、营销判无效均已迁出。"""
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("user_lead_analysis")
    text = render_prompt(config, {
        "user_evidence_json": "{}",
        "grading_standard": "标准",
        "our_models_summary": "- 方舟X7：售价 35-42 万元"})
    # 四段流水线仍在，第四段仅合并增强
    assert "四段流水线" in text
    assert "merge_boost" in text
    assert "merge_boost_reason" in text
    assert "酌情将等级上调一级" in text
    # 已迁出规则不复存在
    assert "purchase_downgrade" not in text
    assert "不得高于 B 级" not in text
    assert "怂恿" not in text
    assert "水军" not in text
    # 前三段与保留规则回归锚点
    assert "baseline_grade" in text
    assert "model_match_level" in text
    assert "只上调" in text
    assert "homepage_profile" in text
    assert "我朋友想买" in text          # 替他人问询证据剔除规则保留
    assert "六段" in text
```

`test_v121_pipeline_skill_version_bumped` 中 `assert SKILL_VERSIONS[USER_ANALYSIS_SKILL] == "1.5.1"` 改为 `== "1.6"`。

- [x] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_agent2.py -q -k "v16_user_analysis or v121_pipeline"`
Expected: FAIL（配置仍指 v1.5.1）

- [x] **Step 3: 生成 v1.6 Prompt**

复制 `app/skills/prompts/user_lead_analysis_v1.5.1.txt` 为 `user_lead_analysis_v1.6.txt`，做以下修改（其余内容一字不动）：

(a) 【意向主体判断】整段替换为：

```text
【意向主体判断（重要）】购车意向必须是该用户本人的意向：
明确替他人问询/转述他人意向（如"我朋友想买一辆xxx"）→ 不作为本人购车信号，
has_purchase_intent=false，相关评论不得作为评级的意向证据。
（注：其余无本人意向的无效用户情形已在前置过滤环节处理，本环节收到的
用户默认已通过该过滤，无需重复判定，但仍须按上述规则剔除替他人问询的
证据。）
```

(b) 【第四段：终判调整】整段（从标题到"最终仍不高于 B。"）替换为：

```text
【第四段：终判调整（合并增强）】
多条相近评论的合并增强（酌情上调）：若该用户发布过多条内容相近、
且对购车倾向有积极印证作用的评论（如在多个汽车视频下持续讨论购车、
对某款车反复表达兴趣），可酌情将等级上调一级（B→A、A→H）。注意：
- 仅"购车倾向"相关的相近评论参与此判断；内容相似但与购车倾向无关的
  评论（如反复玩梗、重复夸赞外观）不构成上调依据；
- 是否上调由你结合评论数量、时间跨度、内容质量综合裁量，不设硬性门槛；
- 等级为 C 不参与上调；上调上限为 H；
- 触发时 merge_boost="upgraded"，merge_boost_reason 写明依据；
  未触发 merge_boost="none"，merge_boost_reason=null。
本段执行后的等级即最终 lead_grade。
```

(c) 输出 JSON 中删除两行：

```text
  "purchase_downgrade": "已购信号封顶：none | capped",
  "purchase_downgrade_reason": "识别到的已购信号或豁免依据，无已购信号为 null",
```

(d) `analysis_text` 字段说明中，`（含合并增强与已购封顶的触发或未触发情况）` 改为 `（含合并增强的触发或未触发情况）`。

(e) 末尾"要求"列表删除第 3 条（`疑似营销、水军或完全无购车相关信号的用户：is_valid_lead=false;`），原第 4 条顺次改编号为 3。

(f) 开头第一段之后（"用户证据包"之前）不新增内容；`is_car_owner`/`has_purchase_intent` 独立标签段保持原样（定级输出仍为放行用户的标签权威来源）。

- [x] **Step 4: 升级配置**（`app/skills/configs/user_lead_analysis.yaml` 整文件替换为）

```yaml
skill_id: user_lead_analysis
version: "1.6"
description: >
  基于用户全部有效评论、视频语境与统计特征，综合判断购车意向，
  输出 H/A/B/C 等级、购车画像与销售建议；独立判定账号级"是否车主"
  与"购车意向"标签；评级采用四段流水线：评论基线 → 在售车型匹配度
  调整（四档）→ 主页画像有限上调 → 终判调整（多条相近评论合并增强）。
  已购封顶、怂恿他人、营销水军等无效用户处置已迁移至前置过滤节点
  user_lead_filter（V1.6）。
model:
  name: ""
  temperature: 0.1
prompt_file: user_lead_analysis_v1.6.txt
prompt_version: "v1.6"
```

同时把 `app/workflow/pipeline.py` 的 `SKILL_VERSIONS` 中 `"user_lead_analysis": "1.5.1"` 改为 `"user_lead_analysis": "1.6"`。

- [x] **Step 5: 运行确认通过（全量回归）**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS（既有 v11/v12/v121/v13 锚点测试断言的字符串在 v1.6 中均保留：`方舟X7`、`baseline_grade`、`model_match_level`、`降两级`、`匹配度`、`只上调`、`homepage_profile`、`我朋友想买`、`置换`、`unknown`、`未配置`）

- [x] **Step 6: 提交**

```bash
git add app/skills/prompts/user_lead_analysis_v1.6.txt app/skills/configs/user_lead_analysis.yaml app/workflow/pipeline.py tests/test_agent2.py
git commit -m "feat(v1.6): 定级 Prompt 升 v1.6——已迁出规则删除，第四段仅合并增强"
```

---

### Task 6: 文档收尾与全量回归

**Files:**
- Modify: `claude_docs/versions/V1/OVERVIEW.md`（能力快照 + Skill/Prompt 版本对照 + 变更索引）
- Modify: `claude_docs/versions/V1/V1.6/plan.md`（勾选完成项）

**Interfaces:** 无（纯文档）

- [x] **Step 1: 更新 OVERVIEW.md**

(a) 能力快照中 Agent2 一条替换为：

```markdown
  - **Agent2（账号精筛）**：定级前先过"无效用户过滤"节点（独立 LLM 调用，V1.6）——已购无新购计划/怂恿他人/仅替他人问询/疑似营销水军/汽车从业者/其他六类命中直接定 C 不进定级，fail-open 放行；账号级两标签 + H/A/B/C 定级四段流水线——评论基线 → 在售车型匹配度四档调整 → 主页截图结构化画像有限上调 → 终判调整（多条相近评论合并增强酌情上调）。
```

(b) Skill/Prompt 版本对照表（三列：Skill | config version | prompt）：`user_lead_analysis` 行改为 `| user_lead_analysis | 1.6 | v1.6 |`；其后新增一行 `| user_lead_filter | 1.6 | v1.6 |`。

(c) 变更索引表追加一行：

```markdown
| V1.6 | 2026-08-11 | 无效用户过滤节点：定级前独立 LLM 过滤（六类命中直接 C），已购封顶/怂恿/营销规则迁出定级 Prompt，两路径接入，契约不变 | [design](V1.6/design.md) / [plan](V1.6/plan.md) |
```

(d) 顶部"最后更新"日期改为 `2026-08-11（随 V1.6 发布）`。

- [x] **Step 2: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS

- [x] **Step 3: 提交**

```bash
git add claude_docs/versions/V1/OVERVIEW.md claude_docs/versions/V1/V1.6/plan.md
git commit -m "docs(v1.6): OVERVIEW 能力快照与变更索引更新——无效用户过滤节点"
```
