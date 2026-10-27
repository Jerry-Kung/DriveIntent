import json
import pytest

from app.api.jobs import create_job, get_job
from app.api.worker import ApiJobWorker
from app.llm.mock import MockProvider
from app.llm.gateway import LLMGateway
from app.models import BlacklistedUser
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
        {"index": 0, "is_meaningful": True,
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


@pytest.mark.asyncio
async def test_v19_worker_loads_blacklist_and_shortcircuits(session):
    """V1.9.0：worker 认领后作业级加载黑名单，命中账号零 LLM 短路为 C。

    使用未注入自定义 blacklist_loader 的默认加载器，命中内存 SQLite 黑名单表；
    provider 无预置响应，若错误实现触发 LLM 调用则会抛 LLMError 落入失败分支。
    """
    session.add(BlacklistedUser(douyin_id="79373130119"))
    session.commit()
    job = create_job(session, "profile_analysis", {"accounts": [{
        "account_uid": "u1", "account_name": "n",
        "account_douyin_id": "79373130119",
        "account_homepage_screenshot": "",
        "comment_history": [{"video_title": "t", "comment_content": "c",
                             "comment_time": "2026-07-19T14:23:00+08:00",
                             "comment_like_count": 1}]}]}, total=1)
    provider = MockProvider()  # 零响应：命中账号须零 LLM 调用
    gateway = LLMGateway(provider)
    worker = ApiJobWorker(_Factory(session), SkillExecutor(gateway), gateway)
    assert await worker.run_once() is True
    row = get_job(session, job.id)
    assert row.status == "success"
    assert row.result["results"][0]["has_value"] is False
    assert "黑名单" in row.result["results"][0]["analysis"]
