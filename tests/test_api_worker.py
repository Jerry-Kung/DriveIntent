import json
import pytest

from app.api.jobs import create_job, get_job
from app.api.worker import ApiJobWorker
from app.llm.mock import MockProvider
from app.llm.gateway import LLMGateway
from app.skills.executor import SkillExecutor


class _Factory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self._session


@pytest.mark.asyncio
async def test_worker_runs_comment_job(session):
    ctx = json.dumps({"brand": "测试"})
    screening = json.dumps({"items": [
        {"comment_id": "cm_1", "is_meaningful": True,
         "is_suspected_marketing": False, "has_purchase_intent": True,
         "reason": "真实"}]})
    provider = MockProvider()
    provider.queue(ctx, screening)
    executor = SkillExecutor(LLMGateway(provider))
    gateway = LLMGateway(provider)

    payload = {"comments": [
        {"comment_id": "cm_1", "video_title": "试驾", "video_author": "@王",
         "video_author_fans": 1, "comment_content": "刚提车",
         "comment_author": "a", "comment_author_uid": "u1",
         "comment_time": "2026-07-19T14:23:00+08:00", "comment_like_count": 1}]}
    job = create_job(session, "comment_screening", payload, total=1)

    worker = ApiJobWorker(_Factory(session), executor, gateway)
    worked = await worker.run_once()
    assert worked is True
    row = get_job(session, job.id)
    assert row.status == "success"
    assert row.result["results"][0]["passed"] is True


@pytest.mark.asyncio
async def test_worker_no_job(session):
    provider = MockProvider()
    worker = ApiJobWorker(_Factory(session), SkillExecutor(LLMGateway(provider)),
                          LLMGateway(provider))
    assert await worker.run_once() is False
