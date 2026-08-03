from app.schemas.skills import UserLeadResult


def test_user_lead_result_has_profile_fields():
    out = UserLeadResult(lead_grade="H", profile_tags=["已购车主"],
                         profile_summary="账号画像摘要", analysis_text="分析过程")
    assert out.profile_tags == ["已购车主"]
    assert out.profile_summary == "账号画像摘要"
    assert out.analysis_text == "分析过程"


def test_user_lead_result_profile_fields_default_empty():
    out = UserLeadResult(lead_grade="C")
    assert out.profile_tags == []
    assert out.profile_summary == ""
    assert out.analysis_text == ""


def test_screening_item_v13_new_fields_defaults():
    from app.schemas.skills import CommentScreeningItem
    item = CommentScreeningItem(comment_id="c1")
    assert item.is_car_owner is False
    assert item.has_purchase_intent is False
    assert item.positive_attitude is False
    assert item.comment_actor == "genuine_user"


def test_screening_item_v13_owner_status_removed():
    from app.schemas.skills import CommentScreeningItem
    # 旧字段作为多余输入被忽略（历史 LLM 输出兼容），不再是模型字段
    item = CommentScreeningItem(comment_id="c1", owner_status="ordered_owner")
    assert "owner_status" not in item.model_dump()


def test_screening_item_v13_label_values():
    from app.schemas.skills import CommentScreeningItem
    item = CommentScreeningItem(comment_id="c1", is_car_owner=True,
                                has_purchase_intent=True)
    assert item.is_car_owner is True
    assert item.has_purchase_intent is True


def test_video_context_v11_new_fields_defaults():
    from app.schemas.skills import VideoContextResult
    ctx = VideoContextResult()
    assert ctx.price_range_min is None
    assert ctx.vehicle_category is None
    assert ctx.use_case == []


def test_video_context_v11_dump_contains_new_fields():
    from app.schemas.skills import VideoContextResult
    d = VideoContextResult(price_range_min=90000, price_range_max=110000,
                           vehicle_category="微型车",
                           use_case=["家用"]).model_dump()
    assert d["price_range_min"] == 90000
    assert d["vehicle_category"] == "微型车"


def test_user_lead_result_v13_label_fields():
    out = UserLeadResult(lead_grade="A", is_car_owner=True,
                         has_purchase_intent=True)
    assert out.is_car_owner is True
    assert out.has_purchase_intent is True


def test_user_lead_result_v13_label_defaults():
    out = UserLeadResult(lead_grade="C")
    assert out.is_car_owner is False
    assert out.has_purchase_intent is False
