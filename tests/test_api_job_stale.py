"""卡死 running 作业兜底：超过阈值无更新的作业直接判失败，不重试。"""
from datetime import datetime, timedelta

import pytest

from app.api.jobs import (claim_next_job, create_job, fail_stale_running_jobs,
                          get_job)


def profile_payload() -> dict:
    return {"accounts": [
        {"account_uid": "u1", "account_name": "张三",
         "account_homepage_screenshot": "A" * 5000, "comment_history": []},
    ]}


def _backdate(session, job, minutes: int) -> None:
    """把 updated_at 回拨到 minutes 分钟前（绕过 onupdate 用底层 UPDATE）。"""
    from app.models import ApiJob
    session.query(ApiJob).filter_by(id=job.id).update(
        {"updated_at": datetime.utcnow() - timedelta(minutes=minutes)})
    session.commit()
    session.expire_all()


def test_stale_running_job_marked_failed_without_retry(session):
    job = create_job(session, "profile_analysis", profile_payload(), total=1)
    claim_next_job(session)
    assert job.attempt_count < job.max_attempts  # 仍有重试额度也不重试
    _backdate(session, job, minutes=31)

    n = fail_stale_running_jobs(session, max_age_minutes=30)

    assert n == 1
    row = get_job(session, job.id)
    assert row.status == "failed"
    assert row.error and "30" in row.error
    assert row.finished_at is not None
    # 终态同样剥离截图
    assert row.request_payload["accounts"][0][
        "account_homepage_screenshot"] == ""


def test_fresh_running_job_untouched(session):
    job = create_job(session, "profile_analysis", profile_payload(), total=1)
    claim_next_job(session)

    n = fail_stale_running_jobs(session, max_age_minutes=30)

    assert n == 0
    assert get_job(session, job.id).status == "running"


def test_stale_pending_job_untouched(session):
    job = create_job(session, "profile_analysis", profile_payload(), total=1)
    _backdate(session, job, minutes=120)

    n = fail_stale_running_jobs(session, max_age_minutes=30)

    assert n == 0
    assert get_job(session, job.id).status == "pending"


@pytest.mark.asyncio
async def test_worker_reap_once_fails_stale_job(session):
    from app.api.worker import ApiJobWorker
    from app.llm.gateway import LLMGateway
    from app.llm.mock import MockProvider
    from app.skills.executor import SkillExecutor

    job = create_job(session, "comment_screening",
                     {"comments": []}, total=0)
    claim_next_job(session)
    _backdate(session, job, minutes=31)

    provider = MockProvider()
    worker = ApiJobWorker(lambda: session,
                          SkillExecutor(LLMGateway(provider)),
                          LLMGateway(provider))
    n = await worker.reap_stale_once()

    assert n == 1
    assert get_job(session, job.id).status == "failed"
