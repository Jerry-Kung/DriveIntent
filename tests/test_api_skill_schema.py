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
    assert ctx.vehicle_category == []
    assert ctx.use_case == []


def test_video_context_v11_dump_contains_new_fields():
    from app.schemas.skills import VideoContextResult
    # vehicle_category 传单字符串：验证 V1.8.3 的 str→list 归一
    d = VideoContextResult(price_range_min=90000, price_range_max=110000,
                           vehicle_category="微型车",
                           use_case=["家用"]).model_dump()
    assert d["price_range_min"] == 90000
    assert d["vehicle_category"] == ["微型车"]


def test_video_context_v183_str_coerced_to_list():
    from app.schemas.skills import VideoContextResult
    # 历史单值形状（旧 LLM 输出/旧落库数据）归一为单元素数组
    ctx = VideoContextResult(brand="坦克", model="坦克300",
                             vehicle_category="越野", powertrain="燃油")
    assert ctx.brand == ["坦克"]
    assert ctx.model == ["坦克300"]
    assert ctx.vehicle_category == ["越野"]
    assert ctx.powertrain == ["燃油"]


def test_video_context_v183_none_and_blank_coerced_to_empty():
    from app.schemas.skills import VideoContextResult
    ctx = VideoContextResult(brand=None, model="  ", powertrain=None)
    assert ctx.brand == []
    assert ctx.model == []
    assert ctx.powertrain == []
    assert VideoContextResult().brand == []


def test_video_context_v183_list_passthrough():
    from app.schemas.skills import VideoContextResult
    # 线上真实事故：跨品牌对比视频，LLM 对四字段输出数组曾致整单作业失败
    ctx = VideoContextResult(
        brand=["小米", "吉利", "比亚迪", "长安", "奇瑞"],
        model=["小米SU7", "吉利星愿", "CS75 PLUS", "艾瑞泽"],
        vehicle_category=["轿车", "SUV"],
        powertrain=["纯电", "燃油"])
    assert ctx.brand == ["小米", "吉利", "比亚迪", "长安", "奇瑞"]
    assert ctx.vehicle_category == ["轿车", "SUV"]
    assert ctx.powertrain == ["纯电", "燃油"]


def test_video_context_v183_invalid_type_still_errors():
    from app.schemas.skills import VideoContextResult
    from pydantic import ValidationError
    try:
        VideoContextResult(brand=123)
    except ValidationError:
        return
    raise AssertionError("非 str/list/None 输入应仍触发校验错误")


def test_video_context_v17_price_float_coerced_to_int():
    from app.schemas.skills import VideoContextResult
    # 线上真实事故：LLM 输出 57.99 触发 int_from_float 使整单作业失败
    ctx = VideoContextResult(price_range_min=90000, price_range_max=57.99)
    assert ctx.price_range_max == 58
    assert isinstance(ctx.price_range_max, int)


def test_video_context_v17_price_numeric_string_coerced_to_int():
    from app.schemas.skills import VideoContextResult
    ctx = VideoContextResult(price_range_max="57.99")
    assert ctx.price_range_max == 58
    assert isinstance(ctx.price_range_max, int)


def test_video_context_v17_price_invalid_string_still_errors():
    from app.schemas.skills import VideoContextResult
    from pydantic import ValidationError
    try:
        VideoContextResult(price_range_max="not-a-number")
    except ValidationError:
        return
    raise AssertionError("无效价格字符串应仍触发校验错误")


def test_user_lead_result_v13_label_fields():
    out = UserLeadResult(lead_grade="A", is_car_owner=True,
                         has_purchase_intent=True)
    assert out.is_car_owner is True
    assert out.has_purchase_intent is True


def test_user_lead_result_v13_label_defaults():
    out = UserLeadResult(lead_grade="C")
    assert out.is_car_owner is False
    assert out.has_purchase_intent is False
