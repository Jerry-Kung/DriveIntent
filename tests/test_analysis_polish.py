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
