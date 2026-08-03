import json
import pytest

from app.api.agent2 import run_profile_analysis
from app.api.schemas import ProfileAnalysisRequest
from app.llm.mock import MockProvider
from app.llm.gateway import LLMGateway
from app.skills.executor import SkillExecutor


def _executor_and_gateway(*responses):
    provider = MockProvider()
    provider.queue(*responses)
    gateway = LLMGateway(provider)
    return SkillExecutor(gateway), gateway


@pytest.mark.asyncio
async def test_profile_with_screenshot():
    lead = json.dumps({
        "lead_grade": "H", "is_valid_lead": True, "lead_summary": "已购车主",
        "evidence_comment_ids": ["x"], "confidence": 0.9,
        "profile_tags": ["已购车主"], "profile_summary": "画像",
        "analysis_text": "分析"})
    executor, gateway = _executor_and_gateway("这是科技博主主页", lead)
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u1", "account_name": "用户",
        "account_homepage_screenshot": "https://cdn/x.png",
        "comment_history": [{"video_title": "试驾", "comment_content": "刚提车",
                             "comment_time": "2026-07-19T14:23:00+08:00",
                             "comment_like_count": 10}]}])
    out = await run_profile_analysis(executor, gateway, req)
    r = out["results"][0]
    assert r["account_uid"] == "u1"
    assert r["has_value"] is True
    assert r["intent_level_code"] == "high"
    assert 85 <= r["value_score"] <= 100


@pytest.mark.asyncio
async def test_profile_empty_history_no_value():
    executor, gateway = _executor_and_gateway()  # 无需 LLM
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u2", "account_name": "空用户",
        "account_homepage_screenshot": "", "comment_history": []}])
    out = await run_profile_analysis(executor, gateway, req)
    r = out["results"][0]
    assert r["account_uid"] == "u2" and r["has_value"] is False


@pytest.mark.asyncio
async def test_profile_no_screenshot_lowers_score():
    lead = json.dumps({
        "lead_grade": "A", "is_valid_lead": True, "lead_summary": "对比中",
        "evidence_comment_ids": ["x"], "confidence": 0.8,
        "profile_tags": [], "profile_summary": "p", "analysis_text": "a"})
    executor, gateway = _executor_and_gateway(lead)  # 无截图→只有一次分析调用
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u3", "account_name": "用户",
        "account_homepage_screenshot": "",
        "comment_history": [{"video_title": "对比", "comment_content": "在看这两款",
                             "comment_time": "2026-07-19T14:23:00+08:00",
                             "comment_like_count": 5}]}])
    out = await run_profile_analysis(executor, gateway, req)
    r = out["results"][0]
    assert r["intent_level_code"] == "medium"
    assert r["value_score"] < 77  # 基准 77 因截图缺失降分


def test_v121_user_analysis_config_uses_v4():
    from app.skills.executor import load_skill_config
    config = load_skill_config("user_lead_analysis")
    assert config.prompt_file == "user_lead_analysis_v4.txt"
    assert config.prompt_version == "v4"
    assert config.version == "1.2.1"


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


def test_v11_user_analysis_prompt_has_our_models_var():
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("user_lead_analysis")
    text = render_prompt(config, {
        "user_evidence_json": "{}",
        "grading_standard": "标准",
        "our_models_summary": "- 方舟X7：售价 35-42 万元"})
    assert "方舟X7" in text
    assert "匹配度" in text  # v2 追加的评级考量要求


@pytest.mark.asyncio
async def test_v11_analyze_account_passes_summary(tmp_path, monkeypatch):
    """analyze_account 渲染 v2 模板不抛 KeyError，且 LLM 输入含我方车型摘要。"""
    import json as _json
    from app.api.agent2 import analyze_account
    from app.api.schemas import AccountObject
    from app.config import settings
    from app.llm.gateway import LLMGateway
    from app.llm.mock import MockProvider
    from app.skills.executor import SkillExecutor

    cfg = {"models": [{
        "model_id": "fz-x7", "brand": "方舟", "model_name": "方舟X7",
        "aliases": [], "price_min": 350000, "price_max": 420000,
        "vehicle_category": "越野"}]}
    p = tmp_path / "our_models.json"
    p.write_text(_json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings, "our_models_config_path", str(p))

    provider = MockProvider()
    provider.queue(_json.dumps({
        "lead_grade": "A", "is_valid_lead": True,
        "evidence_comment_ids": ["u1:0"], "confidence": 0.8}))
    sent: list[list[dict]] = []
    orig = provider.chat

    async def spy(messages, **kw):
        sent.append(messages)
        return await orig(messages, **kw)
    provider.chat = spy

    account = AccountObject(
        account_uid="u1", account_name="用户",
        comment_history=[{"video_title": "对比", "comment_content": "纠结中",
                          "comment_time": "2026-07-19T14:23:00+08:00"}])
    from app.matching.loader import build_our_models_summary, load_our_models
    our_models_summary = build_our_models_summary(load_our_models())
    out = await analyze_account(
        SkillExecutor(LLMGateway(provider)), account, "", our_models_summary)
    assert out.lead_grade == "A"
    assert "方舟X7" in sent[0][0]["content"]


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


def test_v121_user_lead_result_has_match_audit_fields():
    from app.schemas.skills import UserLeadResult
    # 默认值：LLM 未输出匹配度字段时向后兼容不报错
    r = UserLeadResult(lead_grade="B")
    assert r.model_match_level == "unknown"
    assert r.match_adjustment == 0
    assert r.match_reason is None
    # 显式提供降级审计
    r2 = UserLeadResult(lead_grade="B", baseline_grade="H",
                        model_match_level="unrelated", match_adjustment=-2,
                        match_reason="意向五菱宏光约4-6万微面，与我方30-70万越野SUV品类价位均差距显著")
    assert r2.model_match_level == "unrelated"
    assert r2.match_adjustment == -2


def test_v121_user_lead_result_rejects_invalid_match_level():
    import pytest as _pytest
    from pydantic import ValidationError
    from app.schemas.skills import UserLeadResult
    with _pytest.raises(ValidationError):
        UserLeadResult(lead_grade="B", model_match_level="not_a_level")


def test_v121_user_analysis_prompt_has_match_rules():
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("user_lead_analysis")
    text = render_prompt(config, {
        "user_evidence_json": "{}",
        "grading_standard": "标准",
        "our_models_summary": "- 方舟X7：售价 35-42 万元"})
    assert "方舟X7" in text                # 我方车型摘要仍注入
    assert "model_match_level" in text     # 匹配度审计字段输出要求
    assert "match_adjustment" in text
    assert "unrelated" in text             # 四档档位名
    assert "降两级" in text                # unrelated 调整幅度
    assert "匹配度" in text                # analysis_text 五段之一
    assert "baseline_grade" in text        # V1.2 画像规则保留
    assert "只上调" in text                # V1.2 画像规则保留
    assert "homepage_profile" in text      # V1.2 画像注入说明保留


def test_v121_pipeline_skill_version_bumped():
    from app.workflow.pipeline import SKILL_VERSIONS, USER_ANALYSIS_SKILL
    from app.skills.executor import load_skill_config
    assert SKILL_VERSIONS[USER_ANALYSIS_SKILL] == "1.2.1"
    # 流水线版本与 skill 配置版本保持一致，防止只改一处
    assert (load_skill_config(USER_ANALYSIS_SKILL).version
            == SKILL_VERSIONS[USER_ANALYSIS_SKILL])


@pytest.mark.asyncio
async def test_v121_unrelated_model_downgrade_maps_final_grade():
    """意向五菱宏光基线 H、unrelated 降两级至 B：对外按最终 lead_grade=B 映射，
    匹配审计字段落库不泄漏。"""
    profile = json.dumps({"auto_relevance": "无明显汽车相关内容"},
                         ensure_ascii=False)
    lead = json.dumps({
        "baseline_grade": "H", "model_match_level": "unrelated",
        "match_adjustment": -2,
        "match_reason": "意向五菱宏光约4-6万微面，与我方30-70万越野SUV价位品类均差距显著",
        "profile_adjustment": "none", "adjustment_reason": None,
        "lead_grade": "B", "is_valid_lead": True,
        "lead_summary": "五菱宏光强意向，与我方在售车型无关",
        "evidence_comment_ids": ["u5:0"], "confidence": 0.85,
        "profile_tags": [], "profile_summary": "p",
        "analysis_text": "含匹配度段的五段分析"})
    executor, gateway = _executor_and_gateway(profile, lead)
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u5", "account_name": "用户",
        "account_homepage_screenshot": "https://cdn/x.png",
        "comment_history": [{"video_title": "宏光评测",
                             "comment_content": "问下宏光落地多少，这周想去订",
                             "comment_time": "2026-07-19T14:23:00+08:00",
                             "comment_like_count": 3}]}])
    out = await run_profile_analysis(executor, gateway, req)
    r = out["results"][0]
    assert r["intent_level_code"] == "low"  # B→低，而非基线 H→高
    # 匹配审计字段不进对外契约
    assert "model_match_level" not in r
    assert "match_adjustment" not in r
    assert "match_reason" not in r


@pytest.mark.asyncio
async def test_v121_our_model_upgrade_maps_final_grade():
    """意向直指我方 M817、基线 A 上调至 H：对外按最终 lead_grade=H 映射。"""
    profile = json.dumps({"auto_relevance": "无明显汽车相关内容"},
                         ensure_ascii=False)
    lead = json.dumps({
        "baseline_grade": "A", "model_match_level": "our_model",
        "match_adjustment": 1,
        "match_reason": "意向直指我方在售车型猛士M817，且有明确询价行为",
        "profile_adjustment": "none", "adjustment_reason": None,
        "lead_grade": "H", "is_valid_lead": True,
        "lead_summary": "M817 意向用户",
        "evidence_comment_ids": ["u6:0"], "confidence": 0.9,
        "profile_tags": [], "profile_summary": "p",
        "analysis_text": "五段分析"})
    executor, gateway = _executor_and_gateway(profile, lead)
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u6", "account_name": "用户",
        "account_homepage_screenshot": "https://cdn/x.png",
        "comment_history": [{"video_title": "M817 试驾",
                             "comment_content": "M817 落地价多少？想去店里看看",
                             "comment_time": "2026-07-19T14:23:00+08:00",
                             "comment_like_count": 8}]}])
    out = await run_profile_analysis(executor, gateway, req)
    r = out["results"][0]
    assert r["intent_level_code"] == "high"
    assert 85 <= r["value_score"] <= 100


def test_v121_unconfigured_summary_renders_unknown_rule():
    """our_models.json 未配置：摘要为占位文本，v4 提示词渲染正常且含 unknown 跳过规则。"""
    from app.matching.loader import build_our_models_summary
    from app.skills.executor import load_skill_config, render_prompt
    summary = build_our_models_summary(None)
    assert "未配置" in summary
    config = load_skill_config("user_lead_analysis")
    text = render_prompt(config, {
        "user_evidence_json": "{}",
        "grading_standard": "标准",
        "our_models_summary": summary})
    assert "未配置" in text
    assert "unknown" in text


@pytest.mark.asyncio
async def test_v13_profile_result_carries_labels():
    lead = json.dumps({
        "lead_grade": "A", "is_valid_lead": True, "lead_summary": "s",
        "evidence_comment_ids": ["x"], "confidence": 0.8,
        "is_car_owner": True, "has_purchase_intent": True,
        "profile_tags": [], "profile_summary": "p", "analysis_text": "a"})
    executor, gateway = _executor_and_gateway(lead)
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u9", "account_name": "用户",
        "account_homepage_screenshot": "",
        "comment_history": [{"video_title": "t", "comment_content": "想置换",
                             "comment_time": "2026-07-19T14:23:00+08:00",
                             "comment_like_count": 1}]}])
    out = await run_profile_analysis(executor, gateway, req)
    r = out["results"][0]
    assert r["is_car_owner"] is True
    assert r["has_purchase_intent"] is True


@pytest.mark.asyncio
async def test_v13_profile_error_item_labels_null():
    # LLM 无响应 → 该账号处理失败，两标签为 null
    executor, gateway = _executor_and_gateway()
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u10", "account_name": "用户",
        "account_homepage_screenshot": "",
        "comment_history": [{"video_title": "t", "comment_content": "c",
                             "comment_time": "2026-07-19T14:23:00+08:00",
                             "comment_like_count": 1}]}])
    out = await run_profile_analysis(executor, gateway, req)
    r = out["results"][0]
    assert r["error"]
    assert r["is_car_owner"] is None
    assert r["has_purchase_intent"] is None
