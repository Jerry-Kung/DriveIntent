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


_CTX = json.dumps({"brand": "测试", "content_type": "试驾"})


@pytest.mark.asyncio
async def test_owner_comment_filtered():
    screening = json.dumps({"items": [
        {"comment_id": "cm_1", "is_meaningful": True,
         "owner_status": "ordered_owner", "intent_strength": "low",
         "reason": "大定已下等提车"},
        {"comment_id": "cm_2", "is_meaningful": False, "reason": "刷屏"}]})
    out = await run_comment_screening(_executor(_CTX, screening), _req())
    r = out["results"][0]
    assert r["passed"] is False
    assert r["filter_type"] == "ordered_owner"
    assert r["filter_reason"] is None


@pytest.mark.asyncio
async def test_failed_item_keys():
    # 只给语境响应，筛选批次 Mock 无响应 → 整批失败
    out = await run_comment_screening(_executor(_CTX), _req())
    r = out["results"][0]
    assert r["error"]
    assert r["filter_type"] is None
    assert r["filter_reason"] is None
    assert "intent_strength" not in r
