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


def test_resolve_filter_type_priority_actor_over_owner():
    # 营销号 + 车主特征同时命中 → 归营销号
    from app.api.mapping import resolve_filter_type
    item = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                comment_actor="marketing_account",
                                owner_status="existing_owner")
    assert resolve_filter_type(item) == "marketing_account"


def test_resolve_filter_type_owner_values():
    from app.api.mapping import resolve_filter_type
    existing = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                    owner_status="existing_owner")
    ordered = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                   owner_status="ordered_owner")
    assert resolve_filter_type(existing) == "existing_owner"
    assert resolve_filter_type(ordered) == "ordered_owner"


def test_resolve_filter_type_legacy_fallback():
    # LLM 未输出新字段（默认值）时回退 V1.0 判定
    from app.api.mapping import resolve_filter_type
    marketing = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                     is_suspected_marketing=True)
    noise = CommentScreeningItem(comment_id="c", is_meaningful=False)
    ok = CommentScreeningItem(comment_id="c", is_meaningful=True)
    assert resolve_filter_type(marketing) == "marketing_account"
    assert resolve_filter_type(noise) == "noise"
    assert resolve_filter_type(ok) == "genuine_user"


def test_map_screening_owner_filtered_with_reason():
    item = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                owner_status="existing_owner",
                                intent_strength="low", reason="提车三个月")
    r = map_screening_item(item, "t")
    assert r.passed is False
    assert r.filter_type == "existing_owner"
    assert r.filter_reason == "已购车主评论"


def test_map_screening_ordered_owner_reason():
    item = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                owner_status="ordered_owner")
    r = map_screening_item(item, "t")
    assert r.filter_reason == "已下定车主评论"


def test_map_screening_off_topic_reason():
    item = CommentScreeningItem(comment_id="c", comment_actor="off_topic")
    r = map_screening_item(item, "t")
    assert r.passed is False
    assert r.filter_reason == "与汽车无关"


def test_map_screening_exposes_intent_and_downgrade():
    item = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                intent_strength="medium", reason="询价")
    r = map_screening_item(item, "t", downgrade_applied=True,
                           downgrade_reason="价位不匹配")
    assert r.passed is True and r.filter_type == "genuine_user"
    assert r.intent_strength == "medium"
    assert r.downgrade_applied is True
    assert r.downgrade_reason == "价位不匹配"


def test_map_screening_defaults_no_downgrade():
    item = CommentScreeningItem(comment_id="c", is_meaningful=True)
    r = map_screening_item(item, "t")
    assert r.downgrade_applied is False and r.downgrade_reason is None
