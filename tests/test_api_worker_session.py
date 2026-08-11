"""API Worker 在 LLM 调用期间不得持有数据库连接（连接池耗尽回归测试）。

根因（V1.4.3）：`ApiJobWorker.run_once` 全程持有同一会话。`claim_next_job`
commit 后连接本已归还，但 `_execute` 中 `model_validate(job.request_payload)`
访问 deferred 列时会重新开启事务取走一条连接，并一直挂到 `finish_job`。
`LLM_TIMEOUT_SECONDS=600` 下这条连接被死握最长 10 分钟，抬高连接池基线水位，
最终 QueuePool limit reached。

与 tests/test_pipeline_connection_release.py 同源，覆盖 API 路径。
"""
import pytest

from app.api.jobs import create_job, get_job
from app.api.worker import ApiJobWorker
from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.skills.executor import SkillExecutor
from tests.test_user_filter import NOT_FILTERED_JSON


class _Factory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self._session


class _TxnSpyExecutor:
    """记录每次 LLM 调用发起时，worker 会话是否仍持有事务。"""

    def __init__(self, inner, session):
        self._inner = inner
        self._session = session
        self.in_txn_at_call: list[bool] = []

    async def run(self, skill_id, context, output_model):
        self.in_txn_at_call.append(self._session.in_transaction())
        return await self._inner.run(skill_id, context, output_model)


class _TxnSpyGateway:
    """识图走 gateway.chat 而非 executor.run，需单独探针。"""

    def __init__(self, inner, session):
        self._inner = inner
        self._session = session
        self.in_txn_at_call: list[bool] = []

    async def chat(self, messages, **kwargs):
        self.in_txn_at_call.append(self._session.in_transaction())
        return await self._inner.chat(messages, **kwargs)


COMMENT_PAYLOAD = {"comments": [
    {"comment_id": "cm_1", "video_title": "试驾", "video_author": "@王",
     "video_author_fans": 1, "comment_content": "刚提车",
     "comment_author": "a", "comment_author_uid": "u1",
     "comment_time": "2026-07-19T14:23:00+08:00", "comment_like_count": 1}]}

CTX_JSON = '{"brand": "测试"}'
SCREENING_JSON = ('{"items": [{"comment_id": "cm_1", "is_meaningful": true,'
                  ' "is_suspected_marketing": false,'
                  ' "has_purchase_intent": true, "reason": "真实"}]}')

PROFILE_PAYLOAD = {"accounts": [
    {"account_uid": "u1", "account_name": "昵称",
     "account_homepage_screenshot": "",
     "comment_history": [
         {"video_title": "试驾", "comment_content": "这车多少钱",
          "comment_time": "2026-07-19T14:23:00+08:00",
          "comment_like_count": 1}]}]}

LEAD_JSON = ('{"lead_grade": "H", "is_valid_lead": true,'
             ' "lead_summary": "s", "evidence_comment_ids": ["u1:0"],'
             ' "analysis_text": "a", "profile_summary": "p"}')


@pytest.mark.asyncio
async def test_comment_job_releases_connection_during_llm(session):
    provider = MockProvider()
    provider.queue(CTX_JSON, SCREENING_JSON)
    gateway = LLMGateway(provider)
    spy = _TxnSpyExecutor(SkillExecutor(gateway), session)
    create_job(session, "comment_screening", COMMENT_PAYLOAD, total=1)

    worker = ApiJobWorker(_Factory(session), spy, gateway)
    assert await worker.run_once() is True

    assert spy.in_txn_at_call, "未捕获到任何 LLM 调用"
    assert spy.in_txn_at_call == [False] * len(spy.in_txn_at_call), (
        "LLM 调用期间 worker 会话仍持有事务，连接被钉在池外")


@pytest.mark.asyncio
async def test_profile_job_releases_connection_during_llm(session):
    provider = MockProvider()
    provider.queue(LEAD_JSON)
    gateway = LLMGateway(provider)
    spy = _TxnSpyExecutor(SkillExecutor(gateway), session)
    create_job(session, "profile_analysis", PROFILE_PAYLOAD, total=1)

    worker = ApiJobWorker(_Factory(session), spy, gateway)
    assert await worker.run_once() is True

    assert spy.in_txn_at_call, "未捕获到任何 LLM 调用"
    assert spy.in_txn_at_call == [False] * len(spy.in_txn_at_call), (
        "LLM 调用期间 worker 会话仍持有事务，连接被钉在池外")


@pytest.mark.asyncio
async def test_profile_job_releases_connection_during_vision(session):
    """带截图时识图调用同样不得持有事务。"""
    provider = MockProvider()
    provider.queue('{"content_theme": "汽车"}', LEAD_JSON)
    inner = LLMGateway(provider)
    gw_spy = _TxnSpyGateway(inner, session)
    payload = {"accounts": [dict(PROFILE_PAYLOAD["accounts"][0],
                                 account_homepage_screenshot="https://x/a.png")]}
    create_job(session, "profile_analysis", payload, total=1)

    worker = ApiJobWorker(_Factory(session), SkillExecutor(inner), gw_spy)
    assert await worker.run_once() is True

    assert gw_spy.in_txn_at_call, "未捕获到识图调用"
    assert gw_spy.in_txn_at_call == [False] * len(gw_spy.in_txn_at_call), (
        "识图调用期间 worker 会话仍持有事务，连接被钉在池外")


# --- 短会话改造后，既有落库行为不得回归 -------------------------------

@pytest.mark.asyncio
async def test_worker_still_strips_screenshot_on_success(session):
    """终态剥离截图（V1.4 行为）经由 finish_job_by_id 仍须生效。"""
    provider = MockProvider()
    provider.queue('{"content_theme": "汽车"}', NOT_FILTERED_JSON, LEAD_JSON)
    gateway = LLMGateway(provider)
    payload = {"accounts": [dict(PROFILE_PAYLOAD["accounts"][0],
                                 account_homepage_screenshot="A" * 5000)]}
    job = create_job(session, "profile_analysis", payload, total=1)

    worker = ApiJobWorker(_Factory(session), SkillExecutor(gateway), gateway)
    assert await worker.run_once() is True

    session.expire_all()
    saved = get_job(session, job.id)
    assert saved.status in ("success", "partial")
    assert saved.request_payload["accounts"][0][
        "account_homepage_screenshot"] == ""
    assert saved.request_payload["accounts"][0]["account_uid"] == "u1"


@pytest.mark.asyncio
async def test_worker_failure_retries_and_preserves_payload(session):
    """执行失败且未耗尽重试时，回到 pending 且 payload 完整保留。"""
    class _Boom:
        async def run(self, *a, **kw):
            raise RuntimeError("boom")

    gateway = LLMGateway(MockProvider())
    payload = {"accounts": [dict(PROFILE_PAYLOAD["accounts"][0],
                                 account_homepage_screenshot="A" * 5000)]}
    job = create_job(session, "profile_analysis", payload, total=1)

    worker = ApiJobWorker(_Factory(session), _Boom(), gateway,
                          poll_interval=0.0)
    assert await worker.run_once() is True

    session.expire_all()
    saved = get_job(session, job.id)
    # 单账号失败被 run_profile_analysis 捕获为条目级 error → 整单 failed
    # 走 fail_or_retry_by_id；attempt=1 < max_attempts=3 故可重试
    assert saved.status == "pending"
    assert saved.attempt_count == 1
    assert saved.request_payload["accounts"][0][
        "account_homepage_screenshot"] == "A" * 5000


@pytest.mark.asyncio
async def test_progress_updates_land_in_db(session):
    """progress_cb 改为独立短会话后，进度仍须真实落库。"""
    provider = MockProvider()
    provider.queue(LEAD_JSON, LEAD_JSON)
    gateway = LLMGateway(provider)
    payload = {"accounts": [PROFILE_PAYLOAD["accounts"][0],
                            dict(PROFILE_PAYLOAD["accounts"][0],
                                 account_uid="u2")]}
    job = create_job(session, "profile_analysis", payload, total=2)

    worker = ApiJobWorker(_Factory(session), SkillExecutor(gateway), gateway)
    assert await worker.run_once() is True

    session.expire_all()
    assert get_job(session, job.id).progress_done == 2
