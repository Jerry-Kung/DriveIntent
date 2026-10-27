import json

from app.matching.loader import (build_our_models_summary, load_our_models,
                                 normalize)
from app.matching.models import OurModelsConfig

_CFG = {
    "version": "1.0", "updated_at": "2026-07-27",
    "models": [{
        "model_id": "fz-x7", "brand": "方舟", "model_name": "方舟X7",
        "aliases": ["X7", "方舟 x7"], "price_min": 350000, "price_max": 420000,
        "vehicle_category": "越野", "powertrain": "PHEV",
        "use_case": ["越野", "家用"], "key_features": ["四驱", "大空间"],
        "target_audience": "30-45岁户外爱好者"}]}


def _write(tmp_path, data) -> str:
    p = tmp_path / "our_models.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_normalize_lower_and_strip_spaces():
    assert normalize("方舟 X7") == "方舟x7"
    assert normalize("  Tank 400 ") == "tank400"
    assert normalize("") == ""
    assert normalize("坦克-300") == "坦克300"
    assert normalize("坦克·300") == "坦克300"
    assert normalize("Model_Y") == "modely"


def test_load_valid_config(tmp_path):
    cfg = load_our_models(_write(tmp_path, _CFG))
    assert isinstance(cfg, OurModelsConfig)
    assert cfg.models[0].model_name == "方舟X7"
    assert cfg.models[0].price_min == 350000


def test_load_missing_file_returns_none(tmp_path):
    assert load_our_models(str(tmp_path / "nope.json")) is None


def test_load_invalid_json_returns_none(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{broken", encoding="utf-8")
    assert load_our_models(str(p)) is None


def test_load_schema_mismatch_returns_none(tmp_path):
    # models 元素缺少必填 price_min
    bad = {"models": [{"model_id": "a", "brand": "b", "model_name": "c",
                       "price_max": 1, "vehicle_category": "SUV"}]}
    assert load_our_models(_write(tmp_path, bad)) is None


def test_load_uses_default_settings_path(tmp_path, monkeypatch):
    from app.config import settings
    path = _write(tmp_path, _CFG)
    monkeypatch.setattr(settings, "our_models_config_path", path)
    cfg = load_our_models()
    assert cfg is not None and cfg.models[0].brand == "方舟"


def test_summary_contains_key_info(tmp_path):
    cfg = load_our_models(_write(tmp_path, _CFG))
    text = build_our_models_summary(cfg)
    assert "方舟X7" in text and "35" in text and "越野" in text


def test_summary_none_config():
    text = build_our_models_summary(None)
    assert "未配置" in text


def test_settings_new_fields_defaults():
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.our_models_config_path == "config/our_models.json"
    # V1.8.0：意向车型分类标准配置路径
    assert s.intent_categories_config_path == "config/intent_categories.json"


# —— V1.8.0：意向车型分类标准配置 ——

_CAT_CFG = {
    "version": "1.0", "updated_at": "2026-08-27",
    "categories": [
        {"code": "A", "rule": "“东风猛士”系列车型（与我方在售车型一致）"},
        {"code": "B", "rule": "越野车"},
        {"code": "C", "rule": "25-30万元价位的SUV"},
        {"code": "D", "rule": "其他车型，或无意向车型"}]}


def _write_cat(tmp_path, data) -> str:
    p = tmp_path / "intent_categories.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_load_intent_categories_valid(tmp_path):
    from app.matching.loader import load_intent_categories
    from app.matching.models import IntentCategoriesConfig
    cfg = load_intent_categories(_write_cat(tmp_path, _CAT_CFG))
    assert isinstance(cfg, IntentCategoriesConfig)
    assert [c.code for c in cfg.categories] == ["A", "B", "C", "D"]
    assert "越野车" in cfg.categories[1].rule


def test_load_intent_categories_missing_returns_none(tmp_path):
    from app.matching.loader import load_intent_categories
    assert load_intent_categories(str(tmp_path / "nope.json")) is None


def test_load_intent_categories_invalid_json_returns_none(tmp_path):
    from app.matching.loader import load_intent_categories
    p = tmp_path / "bad.json"
    p.write_text("{broken", encoding="utf-8")
    assert load_intent_categories(str(p)) is None


def test_load_intent_categories_schema_mismatch_returns_none(tmp_path):
    from app.matching.loader import load_intent_categories
    bad = {"categories": [{"code": "A"}]}  # 缺必填 rule
    assert load_intent_categories(_write_cat(tmp_path, bad)) is None


def test_load_intent_categories_default_settings_path(tmp_path, monkeypatch):
    from app.config import settings
    from app.matching.loader import load_intent_categories
    path = _write_cat(tmp_path, _CAT_CFG)
    monkeypatch.setattr(settings, "intent_categories_config_path", path)
    cfg = load_intent_categories()
    assert cfg is not None and cfg.categories[0].code == "A"


def test_intent_category_standard_text(tmp_path):
    from app.matching.loader import (build_intent_category_standard,
                                     load_intent_categories)
    cfg = load_intent_categories(_write_cat(tmp_path, _CAT_CFG))
    text = build_intent_category_standard(cfg)
    for kw in ("A", "越野车", "25-30万", "无意向车型"):
        assert kw in text


def test_intent_category_standard_none_config():
    from app.matching.loader import build_intent_category_standard
    text = build_intent_category_standard(None)
    assert "未配置" in text and "null" in text


def test_example_intent_categories_file_loads():
    """入库的模板文件必须可被 loader 正常解析。"""
    from app.matching.loader import load_intent_categories
    cfg = load_intent_categories("config/intent_categories.example.json")
    assert cfg is not None and len(cfg.categories) == 4
