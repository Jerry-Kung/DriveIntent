"""LLM 调用期间不得持有数据库事务（连接池耗尽回归测试）。

workflow worker 的会话若在 await LLM 时仍处于活动事务中，其底层连接会被
钉在连接池外长达整个 LLM 调用（重试+递归时可达数十分钟），并发下必然耗尽
连接池（QueuePool limit reached）。因此三个 pipeline 入口在发起 LLM 调用
时，会话必须已结束读取事务、归还连接。
"""
import json

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.models import Video
from app.skills.executor import SkillExecutor
from app.workflow.pipeline import (run_user_analysis, run_video_context,
                                   screen_comment_batch)
from tests.test_aggregation import _setup as _agg_setup
from tests.test_analysis_polish import POLISH_OK_JSON
from tests.test_comment_screening import _item
from tests.test_comment_screening import _setup as _screening_setup
from tests.test_user_analysis import LEAD_JSON
from tests.test_video_context import CONTEXT_JSON


class _TxnSpyExecutor:
    """包装 SkillExecutor，记录每次 LLM 调用时会话是否仍持有事务。"""

    def __init__(self, inner, session):
        self._inner = inner
        self._session = session
        self.in_txn_at_call: list[bool] = []

    async def run(self, skill_id, context, output_model):
        self.in_txn_at_call.append(self._session.in_transaction())
        return await self._inner.run(skill_id, context, output_model)


def _spy(session, *responses):
    provider = MockProvider()
    provider.queue(*responses)
    return _TxnSpyExecutor(SkillExecutor(LLMGateway(provider)), session)


async def test_run_video_context_releases_connection_during_llm(session):
    v = Video(platform="douyin", external_id="v1", title="t")
    session.add(v)
    session.commit()
    vid = v.id
    # 清空 identity map，确保 session.get 真正发出 SQL（模拟 worker 的新会话）
    session.expunge_all()
    spy = _spy(session, CONTEXT_JSON)

    await run_video_context(session, spy, vid)

    assert spy.in_txn_at_call == [False]


async def test_screen_comment_batch_releases_connection_during_llm(session):
    v, comments = _screening_setup(session)
    ids = [c.id for c in comments]
    spy = _spy(session, json.dumps(
        {"items": [_item(0), _item(1, purchase=False)]},
        ensure_ascii=False))

    await screen_comment_batch(session, spy, v.id, ids)

    assert spy.in_txn_at_call == [False]


async def test_run_user_analysis_releases_connection_during_llm(session):
    from tests.test_user_analysis import REVIEW_CONFIRMED_JSON
    from tests.test_user_filter import NOT_FILTERED_JSON
    _, u1, _, c1, _ = _agg_setup(session)
    spy = _spy(session, NOT_FILTERED_JSON,
               LEAD_JSON.replace("__CID__", str(c1.id)),
               REVIEW_CONFIRMED_JSON, POLISH_OK_JSON)

    await run_user_analysis(session, spy, u1.id)

    # 过滤、定级、复核、润色四跳均不持有事务
    assert spy.in_txn_at_call == [False, False, False, False]
