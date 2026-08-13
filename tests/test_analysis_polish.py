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
