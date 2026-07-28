import json
import pytest

from app.api.agent1 import run_comment_screening
from app.api.schemas import CommentScreeningRequest
from app.llm.mock import MockProvider
from app.llm.gateway import LLMGateway
from app.skills.executor import SkillExecutor


def _req():
    return CommentScreeningRequest(comments=[
        {"comment_id": "cm_1", "video_title": "试驾体验", "video_author": "@王",
         "video_author_fans": 100, "comment_content": "刚提这款车",
         "comment_author": "a", "comment_author_uid": "u1",
         "comment_time": "2026-07-19T14:23:00+08:00", "comment_like_count": 10},
        {"comment_id": "cm_2", "video_title": "试驾体验", "video_author": "@王",
         "video_author_fans": 100, "comment_content": "666",
         "comment_author": "b", "comment_author_uid": "u2",
         "comment_time": "2026-07-19T09:10:00+08:00", "comment_like_count": 0},
    ])


def _executor(*responses):
    provider = MockProvider()
    provider.queue(*responses)
    return SkillExecutor(LLMGateway(provider))


@pytest.mark.asyncio
async def test_screening_maps_results():
    ctx = json.dumps({"brand": "测试", "content_type": "试驾"})
    screening = json.dumps({"items": [
        {"comment_id": "cm_1", "is_meaningful": True,
         "is_suspected_marketing": False, "is_purchase_related": True,
         "reason": "真实车主"},
        {"comment_id": "cm_2", "is_meaningful": False,
         "reason": "数字刷屏"}]})
    out = await run_comment_screening(_executor(ctx, screening), _req())
    results = out["results"]
    assert [r["comment_id"] for r in results] == ["cm_1", "cm_2"]
    assert results[0]["passed"] is True
    assert results[1]["passed"] is False
    assert results[1]["filter_type"] == "noise"
    assert results[1]["filter_reason"] is None


_OUR_MODELS = {
    "version": "1.0", "updated_at": "2026-07-27",
    "models": [{
        "model_id": "fz-x7", "brand": "方舟", "model_name": "方舟X7",
        "aliases": ["X7"], "price_min": 350000, "price_max": 420000,
        "vehicle_category": "越野", "powertrain": "PHEV",
        "use_case": ["越野", "家用"], "key_features": ["四驱"],
        "target_audience": "户外爱好者"}]}

# 视频语境：10万纯电微型车（与我方38万越野车双维度不匹配）
_CTX_MISMATCH = json.dumps({
    "brand": "微光", "model": "微光mini",
    "price_range_min": 90000, "price_range_max": 110000,
    "vehicle_category": "微型车", "use_case": ["家用", "通勤"]})

# 视频语境：我方车型
_CTX_OURS = json.dumps({"brand": "方舟", "model": "方舟X7",
                        "price_range_min": 350000,
                        "price_range_max": 420000,
                        "vehicle_category": "越野"})

_SCREEN_HIGH = json.dumps({"items": [
    {"comment_id": "cm_1", "is_meaningful": True,
     "is_purchase_related": True, "intent_strength": "high",
     "reason": "询问落地价"},
    {"comment_id": "cm_2", "is_meaningful": False, "reason": "刷屏"}]})


def _setup_config(tmp_path, monkeypatch, enabled=True):
    from app.config import settings
    p = tmp_path / "our_models.json"
    p.write_text(json.dumps(_OUR_MODELS, ensure_ascii=False),
                 encoding="utf-8")
    monkeypatch.setattr(settings, "our_models_config_path", str(p))
    monkeypatch.setattr(settings, "intent_downgrade_enabled", enabled)


@pytest.mark.asyncio
async def test_mismatch_marked_for_mismatched_video(tmp_path, monkeypatch):
    _setup_config(tmp_path, monkeypatch)
    out = await run_comment_screening(
        _executor(_CTX_MISMATCH, _SCREEN_HIGH), _req())
    r = out["results"][0]
    assert r["filter_type"] == "model_mismatch"  # 价位+品类两维度不匹配
    assert "价位" in r["filter_reason"]
    assert r["passed"] is True                   # 降级标记不影响 passed
    assert "intent_strength" not in r            # V1.1.1 不再输出
    assert "downgrade_applied" not in r


@pytest.mark.asyncio
async def test_no_mismatch_for_our_model_video(tmp_path, monkeypatch):
    _setup_config(tmp_path, monkeypatch)
    out = await run_comment_screening(
        _executor(_CTX_OURS, _SCREEN_HIGH), _req())
    r = out["results"][0]
    assert r["filter_type"] == "genuine_user"
    assert r["filter_reason"] is None


@pytest.mark.asyncio
async def test_no_mismatch_when_disabled(tmp_path, monkeypatch):
    _setup_config(tmp_path, monkeypatch, enabled=False)
    out = await run_comment_screening(
        _executor(_CTX_MISMATCH, _SCREEN_HIGH), _req())
    assert out["results"][0]["filter_type"] == "genuine_user"


@pytest.mark.asyncio
async def test_no_mismatch_when_config_missing(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "our_models_config_path",
                        str(tmp_path / "nope.json"))
    monkeypatch.setattr(settings, "intent_downgrade_enabled", True)
    out = await run_comment_screening(
        _executor(_CTX_MISMATCH, _SCREEN_HIGH), _req())
    assert out["results"][0]["filter_type"] == "genuine_user"


@pytest.mark.asyncio
async def test_owner_comment_filtered(tmp_path, monkeypatch):
    _setup_config(tmp_path, monkeypatch)
    screening = json.dumps({"items": [
        {"comment_id": "cm_1", "is_meaningful": True,
         "owner_status": "ordered_owner", "intent_strength": "low",
         "reason": "大定已下等提车"},
        {"comment_id": "cm_2", "is_meaningful": False, "reason": "刷屏"}]})
    out = await run_comment_screening(
        _executor(_CTX_OURS, screening), _req())
    r = out["results"][0]
    assert r["passed"] is False
    assert r["filter_type"] == "ordered_owner"
    assert r["filter_reason"] is None


@pytest.mark.asyncio
async def test_failed_item_keys(tmp_path, monkeypatch):
    _setup_config(tmp_path, monkeypatch)
    # 只给语境响应，筛选批次 Mock 无响应 → 整批失败
    out = await run_comment_screening(_executor(_CTX_MISMATCH), _req())
    r = out["results"][0]
    assert r["error"]
    assert r["filter_type"] is None
    assert r["filter_reason"] is None
    assert "intent_strength" not in r
