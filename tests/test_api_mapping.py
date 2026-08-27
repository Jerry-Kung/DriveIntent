from app.api.mapping import map_screening_item, map_profile_result, now_iso
from app.schemas.skills import CommentScreeningItem, UserLeadResult


def test_now_iso_has_offset():
    assert "+08:00" in now_iso()


def test_map_screening_passed():
    item = CommentScreeningItem(comment_id="cm_1", is_meaningful=True,
                                is_suspected_marketing=False,
                                has_purchase_intent=True, reason="真实车主反馈")
    r = map_screening_item(item, "2026-07-19T15:30:00+08:00")
    assert r.passed is True and r.filter_reason is None
    assert "真实车主反馈" in r.analysis


def test_map_screening_marketing_filtered():
    item = CommentScreeningItem(comment_id="cm_2", is_meaningful=True,
                                is_suspected_marketing=True, reason="含微信号引流")
    r = map_screening_item(item, "t")
    assert r.passed is False
    assert r.filter_type == "marketing_account"
    assert r.filter_reason is None  # V1.1.1：枚举自解释，无需补充说明


def test_map_screening_meaningless_filtered():
    item = CommentScreeningItem(comment_id="cm_3", is_meaningful=False,
                                reason="纯数字刷屏")
    r = map_screening_item(item, "t")
    assert r.passed is False
    assert r.filter_type == "noise"
    assert r.filter_reason is None


def test_map_profile_high_to_gao():
    out = UserLeadResult(lead_grade="H", is_valid_lead=True, confidence=0.9,
                         profile_tags=["已购车主"], profile_summary="s",
                         analysis_text="a")
    r = map_profile_result(out, screenshot_available=True, has_comments=True,
                           processed_at="t")
    assert r.has_value is True
    assert (r.intent_level, r.intent_level_code) == ("高", "high")
    assert 85 <= r.value_score <= 100


def test_map_profile_c_grade_maps_low():
    # V1.7.3：C 映射为低(low)；valid C 现已产出价值，不再是 null
    out = UserLeadResult(lead_grade="C", is_valid_lead=True, confidence=0.5)
    r = map_profile_result(out, screenshot_available=True, has_comments=True,
                           processed_at="t")
    assert r.has_value is True
    assert (r.intent_level, r.intent_level_code) == ("低", "low")


def test_map_profile_c_grade_invalid_no_value():
    out = UserLeadResult(lead_grade="C", is_valid_lead=False, confidence=0.5)
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
    assert without.value_score >= 70  # 不得跌出 A 级(high) 下界 70（base 77）


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


def _item(**kw):
    from app.schemas.skills import CommentScreeningItem
    base = dict(comment_id="c", is_meaningful=True,
                is_suspected_marketing=False)
    base.update(kw)
    return CommentScreeningItem(**base)


def test_v13_rule1_actor_abnormal_wins():
    # 优先级1：actor 异常类优先于意向标签
    from app.api.mapping import resolve_filter_type
    item = _item(comment_actor="marketing_account",
                 has_purchase_intent=True, is_car_owner=True)
    assert resolve_filter_type(item) == "marketing_account"


def test_v13_rule2_intent_always_passes():
    # 优先级2：有购车意向必过筛（车主与否均然）
    from app.api.mapping import resolve_filter_type, map_screening_item
    for owner in (True, False):
        item = _item(has_purchase_intent=True, is_car_owner=owner)
        assert resolve_filter_type(item) == "genuine_user"
        assert map_screening_item(item, "t").passed is True


def test_v13_rule3_owner_without_intent_filtered():
    # 优先级3：无意向车主（纯讨论/吐槽）不过筛
    from app.api.mapping import map_screening_item
    item = _item(is_car_owner=True, has_purchase_intent=False,
                 positive_attitude=True, reason="我这台油耗8个")
    r = map_screening_item(item, "t")
    assert r.passed is False
    assert r.filter_type == "no_purchase_intent"
    assert r.filter_reason is None


def test_v13_rule4_non_owner_positive_passes():
    # 优先级4：无意向非车主有积极信号 → 过筛（B级弱线索）
    from app.api.mapping import map_screening_item
    item = _item(is_car_owner=False, has_purchase_intent=False,
                 positive_attitude=True, reason="内饰真好看")
    r = map_screening_item(item, "t")
    assert r.passed is True
    assert r.filter_type == "genuine_user"
    assert r.has_purchase_intent is False


def test_v13_rule5_non_owner_no_signal_filtered():
    # 优先级5：无意向非车主无积极信号 → 不过筛
    from app.api.mapping import map_screening_item
    item = _item(is_car_owner=False, has_purchase_intent=False,
                 positive_attitude=False)
    r = map_screening_item(item, "t")
    assert r.passed is False
    assert r.filter_type == "no_purchase_intent"


def test_v13_result_carries_labels():
    from app.api.mapping import map_screening_item
    item = _item(is_car_owner=True, has_purchase_intent=True)
    d = map_screening_item(item, "t").model_dump()
    assert d["is_car_owner"] is True
    assert d["has_purchase_intent"] is True
    assert "positive_attitude" not in d       # 内部信号不对外
    assert "owner_status" not in d


def test_v13_legacy_fallback_kept():
    # LLM 未输出 comment_actor 时回退 V1.0 判定（旧字段兜底）
    from app.api.mapping import resolve_filter_type
    marketing = _item(is_suspected_marketing=True, has_purchase_intent=True)
    noise = _item(is_meaningful=False)
    assert resolve_filter_type(marketing) == "marketing_account"
    assert resolve_filter_type(noise) == "noise"


def test_map_screening_off_topic():
    item = CommentScreeningItem(comment_id="c", comment_actor="off_topic")
    r = map_screening_item(item, "t")
    assert r.passed is False and r.filter_type == "off_topic"


def test_map_screening_no_legacy_fields():
    # V1.1.1：intent_strength / downgrade_applied / downgrade_reason 不再输出
    item = CommentScreeningItem(comment_id="c", is_meaningful=True,
                                intent_strength="high")
    d = map_screening_item(item, "t").model_dump()
    assert "intent_strength" not in d
    assert "downgrade_applied" not in d
    assert "downgrade_reason" not in d


def test_screening_dict_passed_v13_rules():
    from app.api.mapping import screening_dict_passed
    # 新数据（含 has_purchase_intent 键）走 V1.3 规则
    assert screening_dict_passed(
        {"comment_id": "c", "is_meaningful": True,
         "has_purchase_intent": True, "is_car_owner": True}) is True
    assert screening_dict_passed(
        {"comment_id": "c", "is_meaningful": True,
         "has_purchase_intent": False, "is_car_owner": True,
         "positive_attitude": True}) is False   # 无意向车主
    assert screening_dict_passed(
        {"comment_id": "c", "is_meaningful": True,
         "has_purchase_intent": False, "is_car_owner": False,
         "positive_attitude": True}) is True    # 非车主积极信号
    assert screening_dict_passed(
        {"comment_id": "c", "is_meaningful": True,
         "comment_actor": "marketing_account",
         "has_purchase_intent": True}) is False  # actor 异常优先


def test_screening_dict_passed_legacy_fallback():
    from app.api.mapping import screening_dict_passed
    # 历史数据（无 has_purchase_intent 键）回退旧口径
    assert screening_dict_passed(
        {"comment_id": "c", "is_purchase_related": True,
         "is_suspected_marketing": False}) is True
    assert screening_dict_passed(
        {"comment_id": "c", "is_purchase_related": False}) is False
    assert screening_dict_passed(
        {"comment_id": "c", "is_purchase_related": True,
         "is_suspected_marketing": True}) is False


def test_screened_out_category():
    from app.api.mapping import screened_out_category
    assert screened_out_category(
        {"comment_id": "c", "is_meaningful": True,
         "comment_actor": "marketing_account",
         "has_purchase_intent": False}) == "marketing"
    assert screened_out_category(
        {"comment_id": "c", "is_meaningful": True,
         "has_purchase_intent": False, "is_car_owner": True}) == "no_intent"
    assert screened_out_category(
        {"comment_id": "c", "is_meaningful": False,
         "has_purchase_intent": False}) == "unrelated"
    # 历史数据回退
    assert screened_out_category(
        {"comment_id": "c", "is_suspected_marketing": True}) == "marketing"
    assert screened_out_category(
        {"comment_id": "c", "is_purchase_related": False}) == "unrelated"


def test_screening_dict_passed_v11_data_falls_back():
    # V1.1~V1.2.1 落库数据：含 comment_actor 但无 has_purchase_intent，
    # 必须回退旧口径，不得因新字段缺省被误判为无购买意向
    from app.api.mapping import screened_out_category, screening_dict_passed
    legacy = {"comment_id": "c", "is_meaningful": True,
              "comment_actor": "genuine_user",
              "is_purchase_related": True, "is_suspected_marketing": False}
    assert screening_dict_passed(legacy) is True
    assert screened_out_category(
        {"comment_id": "c", "is_meaningful": True,
         "comment_actor": "genuine_user",
         "is_purchase_related": False}) == "unrelated"


def test_map_profile_carries_labels():
    out = UserLeadResult(lead_grade="H", is_valid_lead=True, confidence=0.9,
                         is_car_owner=True, has_purchase_intent=True)
    r = map_profile_result(out, screenshot_available=True, has_comments=True,
                           processed_at="t")
    assert r.is_car_owner is True
    assert r.has_purchase_intent is True


def test_map_profile_no_value_still_carries_labels():
    # has_value=false（如 C 级且 is_valid_lead=False）仍透出两标签
    out = UserLeadResult(lead_grade="C", is_valid_lead=False,
                         is_car_owner=True, has_purchase_intent=False)
    r = map_profile_result(out, screenshot_available=True, has_comments=True,
                           processed_at="t")
    assert r.has_value is False
    assert r.is_car_owner is True
    assert r.has_purchase_intent is False


def test_map_profile_carries_intent_fields():
    """V1.8.0：意向车型与分类透传对外契约（has_value 真/假两分支）。"""
    out = UserLeadResult(lead_grade="A", is_valid_lead=True,
                         intent_models=["坦克300", "猛士M817"],
                         intent_model_category="A")
    r = map_profile_result(out, screenshot_available=True, has_comments=True,
                           processed_at="t")
    assert r.intent_models == ["坦克300", "猛士M817"]
    assert r.intent_model_category == "A"


def test_map_profile_no_value_still_carries_intent_fields():
    out = UserLeadResult(lead_grade="C", is_valid_lead=False,
                         intent_models=["五菱宏光"],
                         intent_model_category="D")
    r = map_profile_result(out, screenshot_available=True, has_comments=True,
                           processed_at="t")
    assert r.has_value is False
    assert r.intent_models == ["五菱宏光"]
    assert r.intent_model_category == "D"


def test_map_profile_intent_defaults_when_absent():
    """历史/未识别输出：字段默认 [] 与 null，不报错。"""
    out = UserLeadResult(lead_grade="B")
    r = map_profile_result(out, screenshot_available=True, has_comments=True,
                           processed_at="t")
    assert r.intent_models == []
    assert r.intent_model_category is None
