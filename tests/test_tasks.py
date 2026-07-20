from app.models import AnalysisTask
from app.workflow.tasks import (claim_next, create_task, finish_task,
                                reset_running, retry_task, task_counts)


def _mk(session, target_id="1"):
    return create_task(session, task_type="video_context_analysis",
                       target_type="video", target_id=target_id,
                       skill_version="1.0")


def test_create_task_idempotent(session):
    assert _mk(session) is not None
    assert _mk(session) is None
    assert session.query(AnalysisTask).count() == 1


def test_claim_and_finish_success(session):
    _mk(session)
    task = claim_next(session)
    assert task.status == "running" and task.attempt_count == 1
    assert claim_next(session) is None       # 没有第二个 pending
    finish_task(session, task)
    assert task.status == "success"


def test_finish_with_error_retries_then_fails(session):
    _mk(session)
    task = claim_next(session)
    finish_task(session, task, error="超时")      # attempt 1 < 3 → pending
    assert task.status == "pending"
    for _ in range(2):
        task = claim_next(session)
        finish_task(session, task, error="超时")
    assert task.status == "failed"               # attempt 3 == max → failed
    assert retry_task(session, task.id)
    assert task.status == "pending" and task.attempt_count == 0


def test_reset_running_and_counts(session):
    _mk(session, "1"); _mk(session, "2")
    claim_next(session)
    assert reset_running(session) == 1
    counts = task_counts(session)
    assert counts["video_context_analysis"]["pending"] == 2
