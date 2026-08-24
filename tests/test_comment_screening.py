import json

import pytest

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.models import Comment, PlatformUser, Video
from app.services.results import get_current_result, save_result
from app.skills.executor import SkillExecutor
from app.workflow.pipeline import (COMMENT_SCREENING_SKILL, SKILL_VERSIONS,
                                   VIDEO_CONTEXT_SKILL, screen_comment_batch)


def _setup(session, n_comments=2):
    v = Video(platform="douyin", external_id="v1", title="t")
    u = PlatformUser(platform="douyin", external_id="u1", nickname="n")
    session.add_all([v, u]); session.flush()
    comments = []
    for i in range(n_comments):
        c = Comment(platform="douyin", external_id=f"c{i}", video_id=v.id,
                    user_id=u.id, content=f"评论{i}")
        session.add(c); comments.append(c)
    session.flush()
    save_result(session, target_type="video", target_id=str(v.id),
                skill_id=VIDEO_CONTEXT_SKILL,
                skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL],
                result={"brand": "坦克", "model": "坦克300",
                        "analysis_notes": ""})
    return v, comments


def _item(idx, purchase=True):
    # V1.7.2：LLM 输出以批次内临时序号 index 定位评论，不再含 comment_id
    return {"index": idx, "is_meaningful": True,
            "is_automotive_related": True, "is_purchase_related": purchase,
            "is_suspected_marketing": False,
            "intent_signals": ["price_inquiry"] if purchase else [],
            "target_brand": "坦克", "target_model": "坦克300",
            "intent_strength": "high" if purchase else "none",
            # V1.3：与 is_purchase_related 同步，保证共享该 fixture 的
            # 流水线测试（e2e/worker/连接释放）在两标签判定下行为不变
            "has_purchase_intent": purchase,
            "reason": "询问价格", "confidence": 0.9}


async def test_screen_batch_saves_per_comment(session):
    v, comments = _setup(session)
    ids = [c.id for c in comments]
    provider = MockProvider()
    provider.queue(json.dumps(
        {"items": [_item(0), _item(1, purchase=False)]},
        ensure_ascii=False))
    executor = SkillExecutor(LLMGateway(provider))

    await screen_comment_batch(session, executor, v.id, ids)

    r0 = get_current_result(
        session, target_type="comment", target_id=str(ids[0]),
        skill_id=COMMENT_SCREENING_SKILL,
        skill_version=SKILL_VERSIONS[COMMENT_SCREENING_SKILL])
    assert r0.result["is_purchase_related"] is True
    assert r0.confidence == 0.9


async def test_screen_batch_splits_on_id_mismatch(session):
    v, comments = _setup(session, n_comments=2)
    ids = [c.id for c in comments]
    provider = MockProvider()
    # 整批返回错误 index（越界，3 次重试全失败）→ 拆成两个单条批次，各自成功
    bad = json.dumps({"items": [_item(999)]})
    provider.queue(bad, bad, bad,
                   json.dumps({"items": [_item(0)]}),
                   json.dumps({"items": [_item(0)]}))
    executor = SkillExecutor(LLMGateway(provider), max_retries=3)

    await screen_comment_batch(session, executor, v.id, ids)

    for cid in ids:
        assert get_current_result(
            session, target_type="comment", target_id=str(cid),
            skill_id=COMMENT_SCREENING_SKILL,
            skill_version=SKILL_VERSIONS[COMMENT_SCREENING_SKILL]) is not None


async def test_screen_batch_splits_on_duplicate_items(session):
    v, comments = _setup(session, n_comments=2)
    ids = [c.id for c in comments]
    provider = MockProvider()
    # 集合正确但条数错误（重复 index）：3 次重试全失败 → 拆成两个单条批次
    dup = json.dumps(
        {"items": [_item(0), _item(0), _item(1)]})
    provider.queue(dup, dup, dup,
                   json.dumps({"items": [_item(0)]}),
                   json.dumps({"items": [_item(0)]}))
    executor = SkillExecutor(LLMGateway(provider), max_retries=3)

    await screen_comment_batch(session, executor, v.id, ids)

    for cid in ids:
        assert get_current_result(
            session, target_type="comment", target_id=str(cid),
            skill_id=COMMENT_SCREENING_SKILL,
            skill_version=SKILL_VERSIONS[COMMENT_SCREENING_SKILL]) is not None


async def test_screen_batch_nonexistent_ids_returns_without_calling_llm(session):
    v, comments = _setup(session, n_comments=2)
    provider = MockProvider()
    provider.queue("sentinel-should-not-be-consumed")
    executor = SkillExecutor(LLMGateway(provider))

    await screen_comment_batch(session, executor, v.id, [999999])

    assert provider._responses == ["sentinel-should-not-be-consumed"]
