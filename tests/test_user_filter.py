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

# —— V1.9.2 疑似黑名单复用常量 ——
SUSPECTED_MARKETING_JSON = json.dumps({
    "filtered": False, "is_car_owner": False, "has_purchase_intent": False,
    "is_blacklisted": True, "blacklist_type": "营销号",
    "blacklist_reason": '昵称与简介含"加微信报价、全国发"，评论区多次"找我便宜"引流',
    "profile_tags": ["营销号"], "profile_summary": "汽车销售引流账号",
    "analysis_text": "该账号昵称、简介及多条评论均以商业获客为目的，判定为疑似营销号。",
    "confidence": 0.9}, ensure_ascii=False)

SUSPECTED_FAKE_JSON = json.dumps({
    "filtered": False, "is_car_owner": False, "has_purchase_intent": False,
    "is_blacklisted": True, "blacklist_type": "虚假账号",
    "blacklist_reason": "主页截图显示极少作品（作品<5）却拥有超过5万粉丝，粉丝增长与内容产出严重不符",
    "profile_tags": ["虚假账号"], "profile_summary": "高粉低内容账号",
    "analysis_text": "该账号主页截图显示几乎无作品却有大量粉丝，判定为疑似虚假账号。",
    "confidence": 0.85}, ensure_ascii=False)

MALFORMED_BLACKLIST_JSON = json.dumps({
    "filtered": False, "is_blacklisted": True, "blacklist_reason": "缺类型",
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
    assert config.prompt_file == "user_lead_filter_v1.9.2.txt"
    assert config.prompt_version == "v1.9.2"
    assert config.version == "1.9.2"
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
    assert "不得出现\n   任何英文字段名" in text
    assert "filtered判定为true" in text          # 反例
    assert "予以过滤" in text                    # 正例


# --------------------------------------------------------------------------- #
# V1.9.2：疑似黑名单账号识别
# --------------------------------------------------------------------------- #

def test_v192_user_filter_result_blacklist_defaults():
    from app.schemas.skills import UserFilterResult
    r = UserFilterResult()
    assert r.is_blacklisted is False
    assert r.blacklist_type is None
    assert r.blacklist_reason is None


def test_v192_user_filter_result_accepts_both_types():
    from app.schemas.skills import UserFilterResult
    for t in ("营销号", "虚假账号"):
        r = UserFilterResult(is_blacklisted=True, blacklist_type=t,
                             blacklist_reason="理由")
        assert r.blacklist_type == t


def test_v192_user_filter_result_rejects_invalid_type():
    from app.schemas.skills import UserFilterResult
    with pytest.raises(ValidationError):
        UserFilterResult(is_blacklisted=True, blacklist_type="confirmed")


def test_v192_user_lead_result_blacklist_defaults():
    from app.schemas.skills import UserLeadResult
    r = UserLeadResult(lead_grade="C")
    assert r.is_blacklisted is False
    assert r.blacklist_type is None
    assert r.blacklist_reason is None
    # confirmed 类型仅在 UserLeadResult（确认黑名单）合法，不进过滤节点
    r2 = UserLeadResult(lead_grade="C", is_valid_lead=False,
                        is_blacklisted=True, blacklist_type="confirmed",
                        blacklist_reason="该抖音号已列入系统黑名单")
    assert r2.blacklist_type == "confirmed"


@pytest.mark.asyncio
async def test_v19_run_user_filter_malformed_blacklist_fail_open():
    """is_blacklisted=true 却缺 blacklist_type（输出非法）→ fail-open 放行。"""
    from app.skills.user_filter import run_user_filter
    out = await run_user_filter(_executor(MALFORMED_BLACKLIST_JSON), _EVIDENCE)
    assert out.is_blacklisted is False
    assert out.filtered is False


@pytest.mark.asyncio
async def test_v192_run_user_filter_marketing_hit():
    from app.skills.user_filter import run_user_filter
    out = await run_user_filter(_executor(SUSPECTED_MARKETING_JSON), _EVIDENCE)
    assert out.is_blacklisted is True
    assert out.blacklist_type == "营销号"
    assert out.blacklist_reason
    assert out.filtered is False


@pytest.mark.asyncio
async def test_v192_run_user_filter_fake_hit():
    from app.skills.user_filter import run_user_filter
    out = await run_user_filter(_executor(SUSPECTED_FAKE_JSON), _EVIDENCE)
    assert out.is_blacklisted is True
    assert out.blacklist_type == "虚假账号"


def test_v192_build_filtered_lead_result_blacklist_suspect():
    from app.schemas.skills import UserFilterResult
    from app.skills.user_filter import build_filtered_lead_result
    f = UserFilterResult.model_validate(json.loads(SUSPECTED_MARKETING_JSON))
    out = build_filtered_lead_result(f)
    assert out.lead_grade == "C"
    assert out.is_valid_lead is False
    assert out.filter_category == "blacklist_suspect"   # 内部审计标记
    assert out.is_blacklisted is True
    assert out.blacklist_type == "营销号"
    assert out.blacklist_reason == f.blacklist_reason
    assert out.analysis_text                          # 非空（回退 reason 亦可）


def test_v192_build_filtered_lead_result_analysis_falls_back_to_blacklist_reason():
    from app.schemas.skills import UserFilterResult
    from app.skills.user_filter import build_filtered_lead_result
    f = UserFilterResult(is_blacklisted=True, blacklist_type="虚假账号",
                         blacklist_reason="少作品高粉丝")
    out = build_filtered_lead_result(f)
    assert out.analysis_text == "少作品高粉丝"


def test_v192_build_filtered_lead_result_keeps_filter_category_for_normal_hit():
    from app.schemas.skills import UserFilterResult
    from app.skills.user_filter import build_filtered_lead_result
    f = UserFilterResult.model_validate(json.loads(FILTERED_JSON))
    out = build_filtered_lead_result(f)
    assert out.filter_category == "already_purchased"
    assert out.is_blacklisted is False
    assert out.blacklist_type is None


def test_v192_filter_prompt_has_blacklist_rules():
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("user_lead_filter")
    text = render_prompt(config, {"user_evidence_json": "{}"})
    for key in ("is_blacklisted", "blacklist_type", "blacklist_reason"):
        assert key in text
    for kw in ("疑似黑名单", "营销号", "虚假账号", "作品", "粉丝", "获赞",
               "评论区截流", "蓝", "避免误判", "跳过该条规则"):
        assert kw in text
    # 输出契约：is_blacklisted=true 时 blacklist_type / blacklist_reason 必填
    assert "is_blacklisted=true 时 blacklist_type" in text
    assert "blacklist_reason 必填" in text
    # 旧口径反例仍在（可读性禁令未被替换）
    assert "不得出现\n   任何英文字段名" in text
