"""V1.6.4：analysis 润色节点。

定级+复核之后统一润色三个对外叙述字段，清除英文字段泄漏、消除与最终
定级的矛盾。fail-open：失败保留原文；只改文本不改级。
"""
import json


def test_v164_analysis_polish_result_defaults():
    from app.schemas.skills import AnalysisPolishResult
    r = AnalysisPolishResult()
    assert r.polished_analysis_text == ""
    assert r.polished_lead_summary == ""
    assert r.polished_profile_summary == ""
    assert r.confidence == 0.0


def test_v164_user_lead_result_analysis_polish_default():
    from app.schemas.skills import UserLeadResult
    assert UserLeadResult(lead_grade="C").analysis_polish == "none"


def test_v164_polish_config():
    from app.skills.executor import load_skill_config
    config = load_skill_config("user_analysis_polish")
    assert config.version == "1.6.4"
    assert config.prompt_file == "user_analysis_polish_v1.6.4.txt"
    assert config.prompt_version == "v1.6.4"
    assert config.multimodal is False


def test_v164_polish_prompt_renders_with_all_placeholders():
    """六个占位符齐全，正文无裸 $（Template.substitute 不抛错即证明）。"""
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("user_analysis_polish")
    text = render_prompt(config, {
        "lead_grade": "A", "review_action": "维持原级",
        "review_reason": "（无）", "analysis_text": "正文",
        "lead_summary": "速读", "profile_summary": "画像"})
    assert "正文" in text and "速读" in text and "画像" in text


def test_v164_polish_prompt_has_headings_and_bans():
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("user_analysis_polish")
    text = render_prompt(config, {
        "lead_grade": "A", "review_action": "维持原级",
        "review_reason": "（无）", "analysis_text": "a",
        "lead_summary": "b", "profile_summary": "c"})
    for heading in ("一、评论行为与用户身份", "二、购车阶段评估",
                    "三、目标车型与我方车型匹配度", "四、主页画像与调整结论",
                    "五、总体评价"):
        assert heading in text
    assert "is_car_owner" in text        # 禁令反例展示
    assert "严禁新增原文没有的事实" in text
    assert "最终评级为准" in text
    assert "JSON" in text


# —— 供本文件与其他测试文件复用的样例与 Mock 响应 ——
ORIG = "\n".join([
    "一、评论行为与用户身份", "用户多次询价，is_car_owner 为 false。",
    "二、购车阶段评估", "处于积极对比阶段。",
    "三、目标车型与我方车型匹配度", "匹配档位为 similar，未做调整。",
    "四、主页画像与调整结论", "主页画像无支持上调的直接证据。",
    "五、总体评价", "综合判定为 A 级线索，建议常规跟进。"])
POLISHED = (ORIG
            .replace("is_car_owner 为 false", "尚未拥有车辆")
            .replace("匹配档位为 similar，未做调整",
                     "目标车型与我方车型同处一个细分市场，未做评级调整"))
POLISH_OK_JSON = json.dumps({
    "polished_analysis_text": POLISHED,
    "polished_lead_summary": "润色后的速读结论。",
    "polished_profile_summary": "润色后的画像摘要。",
    "confidence": 0.9}, ensure_ascii=False)


def _lead():
    from app.schemas.skills import UserLeadResult
    return UserLeadResult(lead_grade="A", analysis_text=ORIG,
                          lead_summary="原速读结论", profile_summary="原画像摘要")


def _executor(*responses):
    from app.llm.gateway import LLMGateway
    from app.llm.mock import MockProvider
    from app.skills.executor import SkillExecutor
    provider = MockProvider()
    provider.queue(*responses)
    return SkillExecutor(LLMGateway(provider))


async def test_v164_apply_polish_replaces_all_three_fields():
    from app.skills.analysis_polish import apply_polish
    out = _lead()
    await apply_polish(_executor(POLISH_OK_JSON), out)
    assert out.analysis_polish == "polished"
    assert out.analysis_text == POLISHED
    assert out.lead_summary == "润色后的速读结论。"
    assert out.profile_summary == "润色后的画像摘要。"
    assert out.lead_grade == "A"            # 只改文本不改级


async def test_v164_apply_polish_llm_failure_fail_open():
    from app.skills.analysis_polish import apply_polish
    out = _lead()
    await apply_polish(_executor(), out)    # 空队列 → LLMError
    assert out.analysis_polish == "failed"
    assert out.analysis_text == ORIG        # 三字段原文保留
    assert out.lead_summary == "原速读结论"
    assert out.profile_summary == "原画像摘要"


async def test_v164_apply_polish_empty_text_fail_open():
    from app.skills.analysis_polish import apply_polish
    bad = json.dumps({"polished_analysis_text": "",
                      "polished_lead_summary": "新速读",
                      "polished_profile_summary": "新画像",
                      "confidence": 0.9}, ensure_ascii=False)
    out = _lead()
    await apply_polish(_executor(bad), out)
    assert out.analysis_polish == "failed"
    assert out.analysis_text == ORIG
    assert out.lead_summary == "原速读结论"
    assert out.profile_summary == "原画像摘要"


async def test_v164_apply_polish_missing_heading_fail_open():
    from app.skills.analysis_polish import apply_polish
    broken = ORIG.replace("五、总体评价", "总结")   # 丢一个段标题
    bad = json.dumps({"polished_analysis_text": broken,
                      "polished_lead_summary": "新速读",
                      "polished_profile_summary": "新画像",
                      "confidence": 0.9}, ensure_ascii=False)
    out = _lead()
    await apply_polish(_executor(bad), out)
    assert out.analysis_polish == "failed"
    assert out.analysis_text == ORIG


async def test_v164_apply_polish_empty_summaries_partial_apply():
    from app.skills.analysis_polish import apply_polish
    partial = json.dumps({"polished_analysis_text": POLISHED,
                          "polished_lead_summary": "",
                          "polished_profile_summary": "  ",
                          "confidence": 0.9}, ensure_ascii=False)
    out = _lead()
    await apply_polish(_executor(partial), out)
    assert out.analysis_polish == "polished"
    assert out.analysis_text == POLISHED
    assert out.lead_summary == "原速读结论"      # 单字段为空则保留原值
    assert out.profile_summary == "原画像摘要"
