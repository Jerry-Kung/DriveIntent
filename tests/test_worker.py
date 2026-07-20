import asyncio
import json

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.models import AnalysisTask, Lead
from app.skills.executor import SkillExecutor
from app.workflow.pipeline import (SKILL_VERSIONS, VIDEO_CONTEXT_SKILL,
                                   advance, schedule_analysis)
from app.workflow.worker import Worker
from tests.test_comment_screening import _item
from tests.test_user_analysis import LEAD_JSON
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
        json.dumps({"items": [_item(c.id)]}, ensure_ascii=False),
        LEAD_JSON.replace("__CID__", str(c.id)))
    worker = Worker(lambda: session,
                    SkillExecutor(LLMGateway(provider)))

    assert schedule_analysis(session) == 1        # 1 个视频语境任务
    while await worker.run_once():                # 逐个执行直到队列空
        pass

    assert session.query(AnalysisTask).filter_by(status="failed").count() == 0
    lead = session.query(Lead).one()
    assert lead.grade == "H" and lead.user_id == u.id


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
