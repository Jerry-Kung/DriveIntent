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
