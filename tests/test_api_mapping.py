from app.api.mapping import map_screening_item, map_profile_result, now_iso
from app.schemas.skills import CommentScreeningItem, UserLeadResult


def test_now_iso_has_offset():
    assert "+08:00" in now_iso()


def test_map_screening_passed():
    item = CommentScreeningItem(comment_id="cm_1", is_meaningful=True,
                                is_suspected_marketing=False,
                                is_purchase_related=True, reason="真实车主反馈")
    r = map_screening_item(item, "2026-07-19T15:30:00+08:00")
    assert r.passed is True and r.filter_reason is None
    assert "真实车主反馈" in r.analysis


def test_map_screening_marketing_filtered():
    item = CommentScreeningItem(comment_id="cm_2", is_meaningful=True,
                                is_suspected_marketing=True, reason="含微信号引流")
    r = map_screening_item(item, "t")
    assert r.passed is False
    assert r.filter_reason == "广告/引流类评论"


def test_map_screening_meaningless_filtered():
    item = CommentScreeningItem(comment_id="cm_3", is_meaningful=False,
                                reason="纯数字刷屏")
    r = map_screening_item(item, "t")
    assert r.passed is False
    assert r.filter_reason == "无实质内容"


def test_map_profile_high_to_gao():
    out = UserLeadResult(lead_grade="H", is_valid_lead=True, confidence=0.9,
                         profile_tags=["已购车主"], profile_summary="s",
                         analysis_text="a")
    r = map_profile_result(out, screenshot_available=True, has_comments=True,
                           processed_at="t")
    assert r.has_value is True
    assert (r.intent_level, r.intent_level_code) == ("高", "high")
    assert 85 <= r.value_score <= 100


def test_map_profile_c_grade_no_value():
    out = UserLeadResult(lead_grade="C", is_valid_lead=True, confidence=0.5)
    r = map_profile_result(out, screenshot_available=True, has_comments=True,
                           processed_at="t")
    assert r.has_value is False
    assert r.intent_level is None and r.value_score is None


def test_map_profile_screenshot_missing_lowers_score():
    out = UserLeadResult(lead_grade="A", is_valid_lead=True, confidence=0.8)
    with_shot = map_profile_result(out, screenshot_available=True,
                                   has_comments=True, processed_at="t")
    without = map_profile_result(out, screenshot_available=False,
                                 has_comments=True, processed_at="t")
    assert without.value_score < with_shot.value_score
    assert without.value_score >= 70  # 不得跌出 A 级(medium) 70-84 区间


def test_map_profile_screenshot_missing_high_grade_stays_in_range():
    out = UserLeadResult(lead_grade="H", is_valid_lead=True, confidence=0.9)
    without = map_profile_result(out, screenshot_available=False,
                                 has_comments=True, processed_at="t")
    assert without.value_score >= 85  # 不得跌出 H 级(high) 85-100 区间


def test_map_profile_no_comments():
    out = UserLeadResult(lead_grade="C", is_valid_lead=False, confidence=0.0)
    r = map_profile_result(out, screenshot_available=False, has_comments=False,
                           processed_at="t")
    assert r.has_value is False
