from app.matching.downgrade import (DowngradeDecision, apply_downgrade,
                                    evaluate_video_context)
from app.matching.models import OurModel, OurModelsConfig


def _config(**overrides) -> OurModelsConfig:
    base = dict(model_id="fz-x7", brand="方舟", model_name="方舟X7",
                aliases=["X7"], price_min=350000, price_max=420000,
                vehicle_category="越野", powertrain="PHEV",
                use_case=["越野", "家用"])
    base.update(overrides)
    return OurModelsConfig(models=[OurModel(**base)])


def _ctx(**overrides) -> dict:
    # 默认：10万纯电微型车 —— 与我方38万越野车双维度不匹配
    base = dict(brand="微光", model="微光mini",
                price_range_min=90000, price_range_max=110000,
                vehicle_category="微型车", use_case=["家用", "通勤"])
    base.update(overrides)
    return base


def test_apply_downgrade_ladder():
    assert apply_downgrade("high", 1) == "medium"
    assert apply_downgrade("high", 2) == "low"
    assert apply_downgrade("medium", 2) == "none"
    assert apply_downgrade("low", 1) == "none"


def test_apply_downgrade_floor_and_noop():
    assert apply_downgrade("none", 2) == "none"      # 不越界
    assert apply_downgrade("high", 0) == "high"      # 0 级不动
    assert apply_downgrade("unknown", 1) == "unknown"  # 非法值原样返回


def test_our_model_matched_by_name():
    d = evaluate_video_context(_ctx(brand="方舟", model="方舟X7"), _config())
    assert d.is_our_model is True and d.downgrade_levels == 0


def test_our_model_matched_by_alias_case_insensitive():
    d = evaluate_video_context(_ctx(brand="方舟", model="x7"), _config())
    assert d.is_our_model is True


def test_our_brand_other_model_no_downgrade():
    d = evaluate_video_context(_ctx(brand="方舟", model="方舟Z1"), _config())
    assert d.is_our_model is False and d.downgrade_levels == 0


def test_both_dimensions_mismatch_two_levels():
    d = evaluate_video_context(_ctx(), _config())
    assert d.downgrade_levels == 2
    assert d.reason and "价位" in d.reason and "品类" in d.reason


def test_price_only_mismatch_one_level():
    # 品类相同（越野），仅价格差距大
    d = evaluate_video_context(
        _ctx(vehicle_category="越野", use_case=["越野"]), _config())
    assert d.downgrade_levels == 1
    assert "价位" in d.reason


def test_category_only_mismatch_one_level():
    # 价格匹配（38万中值比 38.5万，比值≈0.99），仅品类不匹配
    d = evaluate_video_context(
        _ctx(price_range_min=360000, price_range_max=400000), _config())
    assert d.downgrade_levels == 1
    assert "品类" in d.reason


def test_price_ratio_boundaries():
    # 我方中值 385000；0.7 边界 → 269500；1.4 边界 → 539000
    ok_low = _ctx(price_range_min=269500, price_range_max=269500,
                  vehicle_category="越野", use_case=[])
    ok_high = _ctx(price_range_min=539000, price_range_max=539000,
                   vehicle_category="越野", use_case=[])
    assert evaluate_video_context(ok_low, _config()).downgrade_levels == 0
    assert evaluate_video_context(ok_high, _config()).downgrade_levels == 0


def test_suv_and_offroad_are_related():
    d = evaluate_video_context(
        _ctx(price_range_min=360000, price_range_max=400000,
             vehicle_category="SUV", use_case=[]), _config())
    assert d.downgrade_levels == 0


def test_missing_price_not_counted():
    d = evaluate_video_context(
        _ctx(price_range_min=None, price_range_max=None), _config())
    assert d.downgrade_levels == 1  # 只剩品类一个可判维度


def test_missing_category_not_counted():
    d = evaluate_video_context(
        _ctx(vehicle_category=None, use_case=[]), _config())
    assert d.downgrade_levels == 1  # 只剩价格一个可判维度


def test_all_missing_no_downgrade():
    d = evaluate_video_context(
        _ctx(price_range_min=None, price_range_max=None,
             vehicle_category=None, use_case=[]), _config())
    assert d.downgrade_levels == 0


def test_multi_models_take_most_lenient():
    cfg = OurModelsConfig(models=[
        _config().models[0],
        OurModel(model_id="fz-m1", brand="方舟", model_name="方舟M1",
                 aliases=[], price_min=90000, price_max=120000,
                 vehicle_category="微型车", use_case=["家用", "通勤"]),
    ])
    # 视频是10万微型车：与第二款车型两个维度都匹配 → 不降级
    d = evaluate_video_context(_ctx(), cfg)
    assert d.downgrade_levels == 0


def test_disabled_skips():
    d = evaluate_video_context(_ctx(), _config(), enabled=False)
    assert d == DowngradeDecision()


def test_none_config_skips():
    d = evaluate_video_context(_ctx(), None)
    assert d == DowngradeDecision()


def test_category_fallback_use_case_match():
    # vehicle_category 缺失，use_case 命中我方 use_case → 品类维度匹配
    d = evaluate_video_context(
        _ctx(price_range_min=360000, price_range_max=400000,
             vehicle_category=None, use_case=["越野"]), _config())
    assert d.downgrade_levels == 0


def test_category_fallback_use_case_mismatch():
    # vehicle_category 缺失，use_case 与我方无交集 → 品类不匹配计入
    d = evaluate_video_context(
        _ctx(vehicle_category=None, use_case=["商务"]), _config())
    assert d.downgrade_levels == 2  # 价格也不匹配

