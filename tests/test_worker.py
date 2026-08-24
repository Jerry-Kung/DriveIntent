import asyncio
import json

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.models import AnalysisTask, Lead
from app.skills.executor import SkillExecutor
from app.workflow.pipeline import (SKILL_VERSIONS, VIDEO_CONTEXT_SKILL,
                                   advance, schedule_analysis)
from app.workflow.worker import Worker
from tests.test_analysis_polish import POLISH_OK_JSON
from tests.test_comment_screening import _item
from tests.test_user_analysis import LEAD_JSON, REVIEW_CONFIRMED_JSON
from tests.test_user_filter import NOT_FILTERED_JSON
from app.models import Comment, PlatformUser, Video
import app.workflow.worker as worker_module

CONTEXT_JSON = json.dumps({"brand": "坦克", "model": "坦克300",
                           "analysis_notes": ""}, ensure_ascii=False)


async def test_worker_full_pipeline(session):
    v = Video(platform="douyin", external_id="v1", title="t")
    u = PlatformUser(platform="douyin", external_id="u1", nickname="用户")
    session.add_all([v, u]); session.flush()
    c = Comment(platform="douyin", external_id="c1", video_id=v.id,
                user_id=u.id, content="落地多少钱")
    session.add(c); session.commit()

    provider = MockProvider()
    provider.queue(
        CONTEXT_JSON,
        json.dumps({"items": [_item(0)]}, ensure_ascii=False),
        NOT_FILTERED_JSON,
        LEAD_JSON.replace("__CID__", str(c.id)),
        REVIEW_CONFIRMED_JSON, POLISH_OK_JSON)
    worker = Worker(lambda: session,
                    SkillExecutor(LLMGateway(provider)))

    assert schedule_analysis(session) == 1        # 1 个视频语境任务
    while await worker.run_once():                # 逐个执行直到队列空
        pass

    assert session.query(AnalysisTask).filter_by(status="failed").count() == 0
    lead = session.query(Lead).one()
    assert lead.grade == "H" and lead.user_id == u.id

    from app.models import AnalysisResult
    res = session.query(AnalysisResult).filter_by(
        target_type="user", target_id=str(u.id)).one().result
    assert res["review_action"] == "confirmed"     # 复核真实走到
    assert res["analysis_polish"] == "polished"    # 润色真实走到


async def test_run_once_closes_session_on_every_path(session, monkeypatch):
    calls = []
    original_close = session.close

    def counting_close():
        calls.append(1)
        original_close()

    monkeypatch.setattr(session, "close", counting_close)
    worker = Worker(lambda: session, SkillExecutor(LLMGateway(MockProvider())))

    assert await worker.run_once() is False    # 无任务，也需 close
    assert len(calls) == 1


async def test_worker_rollback_on_db_error_and_session_stays_usable(
        session, monkeypatch):
    v = Video(platform="douyin", external_id="v1", title="t")
    session.add(v); session.commit()
    assert schedule_analysis(session) == 1     # 建 1 个语境任务

    async def bad_run_video_context(sess, executor, video_id):
        # 模拟 DB 层错误：flush 触发唯一约束冲突（撞上正在处理的任务自身）
        dup = AnalysisTask(task_type=VIDEO_CONTEXT_SKILL, target_type="video",
                           target_id=str(video_id),
                           skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL])
        sess.add(dup)
        sess.flush()

    monkeypatch.setattr(worker_module, "run_video_context",
                        bad_run_video_context)
    worker = Worker(lambda: session, SkillExecutor(LLMGateway(MockProvider())))

    assert await worker.run_once() is True
    task = session.query(AnalysisTask).filter_by(
        task_type=VIDEO_CONTEXT_SKILL).one()
    assert task.status == "pending"            # attempt 1 < max_attempts → 重试
    assert task.attempt_count == 1
    assert task.error is not None

    # rollback + close 之后 session 仍可用：再跑一轮不抛异常、任务继续被领取处理
    assert await worker.run_once() is True
    task = session.query(AnalysisTask).filter_by(
        task_type=VIDEO_CONTEXT_SKILL).one()
    assert task.status == "pending"
    assert task.attempt_count == 2


async def test_loop_survives_unexpected_exception():
    worker = Worker(lambda: None, None, poll_interval=0.01)
    calls = {"n": 0}

    async def flaky_run_once():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return False

    worker.run_once = flaky_run_once
    stop_event = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop_event.set()

    await asyncio.gather(worker._loop(stop_event), stopper())
    assert calls["n"] >= 2


async def test_advance_creates_batch_for_newly_imported_comments_on_screened_video(
        session):
    from app.services.results import save_result

    v = Video(platform="douyin", external_id="v1", title="t")
    u = PlatformUser(platform="douyin", external_id="u1", nickname="用户")
    session.add_all([v, u]); session.flush()
    c1 = Comment(platform="douyin", external_id="c1", video_id=v.id,
                user_id=u.id, content="评论1")
    c2 = Comment(platform="douyin", external_id="c2", video_id=v.id,
                user_id=u.id, content="评论2")
    session.add_all([c1, c2]); session.commit()

    save_result(session, target_type="video", target_id=str(v.id),
               skill_id=VIDEO_CONTEXT_SKILL,
               skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL],
               result={"brand": "坦克", "model": "坦克300"})

    assert advance(session) == 1     # 首次建批：覆盖 c1、c2
    batches = (session.query(AnalysisTask)
              .filter(AnalysisTask.task_type == "comment_lead_screening")
              .all())
    assert len(batches) == 1
    assert set(batches[0].payload["comment_ids"]) == {c1.id, c2.id}

    # 该视频已“筛选”（已建批）后，再导入 2 条新评论
    c3 = Comment(platform="douyin", external_id="c3", video_id=v.id,
                user_id=u.id, content="评论3")
    c4 = Comment(platform="douyin", external_id="c4", video_id=v.id,
                user_id=u.id, content="评论4")
    session.add_all([c3, c4]); session.commit()

    created = advance(session)
    assert created == 1

    batches = (session.query(AnalysisTask)
              .filter(AnalysisTask.task_type == "comment_lead_screening")
              .order_by(AnalysisTask.id).all())
    assert len(batches) == 2
    new_batch = batches[-1]
    assert set(new_batch.payload["comment_ids"]) == {c3.id, c4.id}
    assert new_batch.target_id == f"{v.id}:1"

    # 再跑一次 advance() 应保持幂等，不再新建
    assert advance(session) == 0
