"""V1.6.3：复核改级后同步修订对外叙述。

analysis_text 第五段"总体评价"与 HABC 绑定，复核改级后必须随之改写，
否则对销售人员呈现"最终 H 级、全文论证 A 级"的矛盾文本。前四段是事实
陈述，与等级无关，必须逐字保留——这是代码切分（而非让模型照抄）的理由。
"""
import json

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.models import AnalysisResult
from app.skills.executor import SkillExecutor
from app.skills.user_review import CONCLUSION_ANCHOR, _revise_analysis
from app.workflow.pipeline import run_user_analysis
from tests.test_aggregation import _setup
from tests.test_user_filter import NOT_FILTERED_JSON

FOUR = ("一、评论行为与用户身份\n该用户多次在评论中询价。\n"
        "二、购车阶段评估\n处于积极对比阶段。\n"
        "三、目标车型与我方车型匹配度\n目标车型与我方同级且价位接近。\n"
        "四、主页画像与调整结论\n主页画像无支持上调的直接证据。\n")
ANALYSIS = FOUR + CONCLUSION_ANCHOR + "\n综合判定为 A 级线索，建议常规跟进。"
NEW_BODY = "多条评论跨时间印证持续购车关注，判定为 H 级线索，建议最高优先级跟进。"


def _polish_echo(text: str) -> str:
    """润色响应：原样回显 analysis_text，summary 留空表示保留原值。

    集成测试的关注点是复核修订本身，回显可让既有断言原样成立。
    """
    return json.dumps({"polished_analysis_text": text,
                       "polished_lead_summary": "",
                       "polished_profile_summary": "",
                       "confidence": 0.9}, ensure_ascii=False)


def test_replace_keeps_first_four_sections_byte_identical():
    """核心承诺：锚点命中时前四段逐字节保留，只有第五段被换掉。"""
    new, revision = _revise_analysis(ANALYSIS, NEW_BODY)
    assert revision == "replaced"
    assert new.startswith(FOUR)
    assert "综合判定为 A 级线索" not in new
    assert new == FOUR + CONCLUSION_ANCHOR + "\n" + NEW_BODY


def test_anchor_missing_falls_back_to_append():
    """锚点缺失时退化为文末追加，原文完整保留，绝不失真也绝不失败。"""
    text = "该用户多次询价，综合判定为 A 级线索。"   # 模型未按格式输出段标题
    new, revision = _revise_analysis(text, NEW_BODY)
    assert revision == "appended"
    assert new.startswith(text)
    assert CONCLUSION_ANCHOR + "（复核修订）" in new
    assert new.endswith(NEW_BODY)


def test_empty_conclusion_leaves_text_untouched():
    """复核未给正文时文本一字不动，等级仍按复核结果改（由调用方负责）。"""
    for empty in (None, "", "   ", "\n"):
        new, revision = _revise_analysis(ANALYSIS, empty)
        assert (new, revision) == (ANALYSIS, "none")


def test_conclusion_carrying_its_own_heading_is_not_duplicated():
    """模型不听话、正文自带段标题时，不得出现重复标题。"""
    new, revision = _revise_analysis(
        ANALYSIS, CONCLUSION_ANCHOR + "\n" + NEW_BODY)
    assert revision == "replaced"
    assert new.count(CONCLUSION_ANCHOR) == 1
    assert new.endswith(NEW_BODY)


def test_duplicate_anchor_uses_last_occurrence():
    """总体评价是末段；前文引用到该标题时必须切在最后一次出现处。"""
    text = ("一、评论行为与用户身份\n详见下文五、总体评价。\n"
            + CONCLUSION_ANCHOR + "\n综合判定为 A 级线索。")
    new, revision = _revise_analysis(text, NEW_BODY)
    assert revision == "replaced"
    assert new == ("一、评论行为与用户身份\n详见下文五、总体评价。\n"
                   + CONCLUSION_ANCHOR + "\n" + NEW_BODY)


def test_empty_analysis_text_appends_without_leading_blank_lines():
    """定级节点未给 analysis_text 时，追加结果不应以空行开头。"""
    new, revision = _revise_analysis("", NEW_BODY)
    assert revision == "appended"
    assert new == CONCLUSION_ANCHOR + "（复核修订）\n" + NEW_BODY


PRELIM_ANALYSIS = ANALYSIS  # 五段齐全、第五段论证 A 级


def _lead_json(cid: str) -> str:
    return json.dumps({
        "lead_grade": "A", "is_valid_lead": True,
        "lead_summary": "关注同级车型，建议常规跟进",
        "purchase_stage": "积极对比",
        "target_brands": ["坦克"], "target_models": ["坦克300"],
        "core_needs": ["越野"], "main_concerns": ["落地价格"],
        "purchase_time": "近期", "usage_scenario": "越野出行",
        "recommended_entry_point": "从当地报价切入",
        "verification_questions": ["预算多少？"],
        "evidence_comment_ids": [cid],
        "analysis_text": PRELIM_ANALYSIS,
        "confidence": 0.9}, ensure_ascii=False)


REVIEW_UPGRADED_JSON = json.dumps({
    "review_action": "upgraded", "reviewed_grade": "H",
    "review_reason": "多条评论跨时间印证持续购车关注，初步评级偏保守",
    "revised_conclusion": NEW_BODY,
    "revised_lead_summary": "持续关注同级车型并多次表达换车意愿，建议优先联系。",
    "confidence": 0.9}, ensure_ascii=False)


async def test_upgrade_revises_narrative_and_keeps_first_four_sections(session):
    """复核上调后：等级、第五段、速读结论三者一致，前四段逐字保留。"""
    _, u1, _, c1, _ = _setup(session)
    provider = MockProvider()
    provider.queue(NOT_FILTERED_JSON, _lead_json(str(c1.id)),
                   REVIEW_UPGRADED_JSON,
                   _polish_echo(FOUR + CONCLUSION_ANCHOR + "\n" + NEW_BODY))
    await run_user_analysis(session, SkillExecutor(LLMGateway(provider)), u1.id)

    res = session.query(AnalysisResult).filter_by(
        target_type="user", target_id=str(u1.id)).one().result
    assert res["lead_grade"] == "H"
    assert res["pre_review_grade"] == "A"
    assert res["review_action"] == "upgraded"
    assert res["analysis_revision"] == "replaced"
    assert res["analysis_text"].startswith(FOUR)          # 前四段未动
    assert "综合判定为 A 级线索" not in res["analysis_text"]  # 旧结论已消失
    assert res["analysis_text"].endswith(NEW_BODY)
    assert res["lead_summary"] == "持续关注同级车型并多次表达换车意愿，建议优先联系。"
    assert res["analysis_polish"] == "polished"


async def test_confirmed_leaves_narrative_untouched(session):
    """复核确认时不动任何文本，也不产生修订痕迹。"""
    from tests.test_user_analysis import REVIEW_CONFIRMED_JSON
    _, u1, _, c1, _ = _setup(session)
    provider = MockProvider()
    provider.queue(NOT_FILTERED_JSON, _lead_json(str(c1.id)),
                   REVIEW_CONFIRMED_JSON, _polish_echo(PRELIM_ANALYSIS))
    await run_user_analysis(session, SkillExecutor(LLMGateway(provider)), u1.id)

    res = session.query(AnalysisResult).filter_by(
        target_type="user", target_id=str(u1.id)).one().result
    assert res["lead_grade"] == "A"
    assert res["review_action"] == "confirmed"
    assert res["analysis_revision"] == "none"
    assert res["analysis_text"] == PRELIM_ANALYSIS
    assert res["lead_summary"] == "关注同级车型，建议常规跟进"
    assert res["analysis_polish"] == "polished"


async def test_downgrade_also_revises_narrative(session):
    """降级与升级对称——文本论证 A、最终判 B 同样是矛盾。"""
    _, u1, _, c1, _ = _setup(session)
    down_body = "评论多为泛化的产品兴趣，缺乏明确购车表述，建议低优先级跟进。"
    review = json.dumps({
        "review_action": "downgraded", "reviewed_grade": "B",
        "review_reason": "初步评级偏激进，证据不足以支撑高价值判断",
        "revised_conclusion": down_body,
        "revised_lead_summary": "产品兴趣为主，暂无明确购车信号，建议低优先级跟进。",
        "confidence": 0.85}, ensure_ascii=False)
    provider = MockProvider()
    provider.queue(NOT_FILTERED_JSON, _lead_json(str(c1.id)), review,
                   _polish_echo(FOUR + CONCLUSION_ANCHOR + "\n" + down_body))
    await run_user_analysis(session, SkillExecutor(LLMGateway(provider)), u1.id)

    res = session.query(AnalysisResult).filter_by(
        target_type="user", target_id=str(u1.id)).one().result
    assert res["lead_grade"] == "B"
    assert res["analysis_revision"] == "replaced"
    assert res["analysis_text"].endswith(down_body)


async def test_review_failure_keeps_grade_and_narrative_together(session):
    """fail-open 原子性：复核调用失败时等级与文本双双保持初步值。"""
    _, u1, _, c1, _ = _setup(session)
    provider = MockProvider()
    provider.queue(NOT_FILTERED_JSON, _lead_json(str(c1.id)))  # 无复核响应
    await run_user_analysis(session, SkillExecutor(LLMGateway(provider)), u1.id)

    res = session.query(AnalysisResult).filter_by(
        target_type="user", target_id=str(u1.id)).one().result
    assert res["lead_grade"] == "A"              # 等级未改
    assert res["analysis_text"] == PRELIM_ANALYSIS  # 文本未改
    assert res["analysis_revision"] == "none"
    assert res["pre_review_grade"] is None       # 复核根本没跑完
    assert res["analysis_polish"] == "failed"    # 润色也失败，原文保留


async def test_filtered_user_skips_review_entirely(session):
    """被前置过滤的用户不进复核，合成 C 级结果不带修订痕迹。"""
    from tests.test_user_filter import FILTERED_JSON
    _, u1, _, c1, _ = _setup(session)
    provider = MockProvider()
    provider.queue(FILTERED_JSON)   # 只有过滤一跳
    await run_user_analysis(session, SkillExecutor(LLMGateway(provider)), u1.id)

    res = session.query(AnalysisResult).filter_by(
        target_type="user", target_id=str(u1.id)).one().result
    assert res["lead_grade"] == "C"
    assert res["analysis_revision"] == "none"
    assert res["pre_review_grade"] is None
    assert res["analysis_polish"] == "none"


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
