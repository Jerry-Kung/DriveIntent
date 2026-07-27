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


def test_v11_user_analysis_config_uses_v2():
    from app.skills.executor import load_skill_config
    config = load_skill_config("user_lead_analysis")
    assert config.prompt_file == "user_lead_analysis_v2.txt"
    assert config.prompt_version == "v2"
    assert config.version == "1.1"


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
