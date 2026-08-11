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
    assert config.prompt_file == "user_lead_filter_v1.6.1.txt"
    assert config.prompt_version == "v1.6.1"
    assert config.version == "1.6.1"
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


def test_v161_filter_prompt_readability_ban():
    """v1.6.1：过滤输出面向人的文本字段禁用英文字段名/枚举值。"""
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("user_lead_filter")
    text = render_prompt(config, {"user_evidence_json": "{}"})
    assert "不得出现任何英文字段名" in text
    assert "filtered判定为true" in text          # 反例
    assert "予以过滤" in text                    # 正例
