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
        {"index": 0, "is_meaningful": True,
         "is_suspected_marketing": False, "has_purchase_intent": True,
         "reason": "真实车主"},
        {"index": 1, "is_meaningful": False,
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
async def test_owner_without_intent_filtered():
    # V1.3：无购车意向的车主（纯讨论）不过筛，filter_type=no_purchase_intent
    screening = json.dumps({"items": [
        {"index": 0, "is_meaningful": True, "is_car_owner": True,
         "has_purchase_intent": False, "reason": "我这台开了2万公里，油耗8个"},
        {"index": 1, "is_meaningful": False, "reason": "刷屏"}]})
    out = await run_comment_screening(_executor(_CTX, screening), _req())
    r = out["results"][0]
    assert r["passed"] is False
    assert r["filter_type"] == "no_purchase_intent"
    assert r["is_car_owner"] is True
    assert r["has_purchase_intent"] is False


@pytest.mark.asyncio
async def test_owner_with_trade_in_intent_passes():
    # V1.3：车主表达增换购意向 → 必过筛（V1.1 时代恒被过滤，行为变更点）
    screening = json.dumps({"items": [
        {"index": 0, "is_meaningful": True, "is_car_owner": True,
         "has_purchase_intent": True, "intent_strength": "high",
         "reason": "开了5年想置换升级"},
        {"index": 1, "is_meaningful": False, "reason": "刷屏"}]})
    out = await run_comment_screening(_executor(_CTX, screening), _req())
    r = out["results"][0]
    assert r["passed"] is True
    assert r["filter_type"] == "genuine_user"
    assert r["is_car_owner"] is True
    assert r["has_purchase_intent"] is True


@pytest.mark.asyncio
async def test_failed_item_keys():
    # 只给语境响应，筛选批次 Mock 无响应 → 整批失败
    out = await run_comment_screening(_executor(_CTX), _req())
    r = out["results"][0]
    assert r["error"]
    assert r["filter_type"] is None
    assert r["filter_reason"] is None
    assert r["is_car_owner"] is None
    assert r["has_purchase_intent"] is None
    assert "intent_strength" not in r


def _req_with_empty():
    # 线上事故形状：3 条评论，第 1 条 content 为空（qwen 会丢弃它）
    return CommentScreeningRequest(comments=[
        {"comment_id": "cm_e0", "video_title": "试驾体验", "video_author": "@王",
         "video_author_fans": 100, "comment_content": "",
         "comment_author": "a", "comment_author_uid": "u0",
         "comment_time": "2026-07-19T14:23:00+08:00", "comment_like_count": 0},
        {"comment_id": "cm_e1", "video_title": "试驾体验", "video_author": "@王",
         "video_author_fans": 100, "comment_content": "凤尾？古斯特定价低很多吗",
         "comment_author": "b", "comment_author_uid": "u1",
         "comment_time": "2026-07-19T09:10:00+08:00", "comment_like_count": 0},
        {"comment_id": "cm_e2", "video_title": "试驾体验", "video_author": "@王",
         "video_author_fans": 100, "comment_content": "闭眼劳",
         "comment_author": "c", "comment_author_uid": "u2",
         "comment_time": "2026-07-19T09:10:00+08:00", "comment_like_count": 0},
    ])


@pytest.mark.asyncio
async def test_screening_empty_content_comment_not_failed():
    """V1.8.5：批内含空 content 评论不再使整批失败。

    线上事故：3 条评论含 1 条空 content，模型跳过它只回 index [0,1]，映射层
    集合校验失败 → 整单 3 次重试全败。修复后空 content 被代码层剔除并合成
    确定性结果，作业成功。
    """
    ctx = json.dumps({"brand": [], "model": [], "content_type": "互动/话题"})
    # LLM 输入侧只看到两条非空评论，故只需回 index 0、1
    screening = json.dumps({"items": [
        {"index": 0, "is_meaningful": True,
         "is_suspected_marketing": False, "has_purchase_intent": True,
         "reason": "对比询价"},
        {"index": 1, "is_meaningful": False,
         "reason": "情绪噪音"}]})
    # Mock 只预置一次 screening 响应：修复后应只用一次（不因重试烧 3 次）
    out = await run_comment_screening(_executor(ctx, screening),
                                      _req_with_empty())
    results = out["results"]
    assert [r["comment_id"] for r in results] == ["cm_e0", "cm_e1", "cm_e2"]
    # 空 content 评论：合成结果，不过筛
    assert results[0]["error"] is None
    assert results[0]["passed"] is False
    assert results[0]["filter_type"] == "off_topic"
    assert results[0]["has_purchase_intent"] is False
    # 两条非空评论恢复正常映射
    assert results[1]["error"] is None
    assert results[1]["passed"] is True
    assert results[2]["error"] is None
    assert results[2]["passed"] is False
