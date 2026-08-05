"""事件循环不得被同步数据库调用冻结（V1.4.4 回归测试）。

根因（V1.4.4）：`claim_next_job_detached` 在事件循环里同步读出
`request_payload`。实测远程 MySQL 读一条 22.7MB payload 耗时 3233-3656ms，
期间事件循环心跳仅 5 次（应约 365 次），即 loop 被完全冻住：其余 worker
协程、reaper、以及所有 HTTP 请求处理全部无法推进。冻结期间线程池里的轮询
请求取走连接却得不到调度归还 → QueuePool limit reached。

本测试用心跳探针量化冻结时长：在事件循环中每 10ms 跳一次，同时驱动 worker
完成一个作业，断言最大单次停顿不超过阈值。DB 调用被 to_thread 移出循环后，
无论单次调用多慢，事件循环都应保持响应。
"""
import asyncio
import time

import pytest

from app.api.jobs import create_job
from app.api.worker import ApiJobWorker
from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.skills.executor import SkillExecutor

# 单次 DB 调用的模拟耗时。远程 MySQL 读 13MB payload 实测约 3.2s，
# 此处取 0.3s 以保持测试快速，量级差异不影响结论。
DB_LATENCY = 0.3
# 事件循环允许的最大单次停顿。心跳间隔 10ms，放宽到 200ms 以容忍
# CI 抖动；被同步 DB 调用冻结时停顿会达到 DB_LATENCY 量级。
MAX_STALL = 0.2

LEAD_JSON = ('{"lead_grade": "H", "is_valid_lead": true,'
             ' "lead_summary": "s", "evidence_comment_ids": ["u1:0"],'
             ' "analysis_text": "a", "profile_summary": "p"}')

ACCOUNT = {"account_uid": "u1", "account_name": "昵称",
           "account_homepage_screenshot": "",
           "comment_history": [
               {"video_title": "试驾", "comment_content": "这车多少钱",
                "comment_time": "2026-07-19T14:23:00+08:00",
                "comment_like_count": 1}]}


class _SlowSession:
    """包住真实会话，在每次 DB 交互处插入同步延迟，模拟远程大列读取。"""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name in ("query", "get", "commit", "execute"):
            def wrapped(*args, **kwargs):
                time.sleep(DB_LATENCY)   # 同步阻塞，正是生产中的行为
                return attr(*args, **kwargs)
            return wrapped
        return attr

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _SlowFactory:
    def __init__(self, session):
        self._session = _SlowSession(session)

    def __call__(self):
        return self._session


class _Heartbeat:
    """事件循环健康探针：正常每 10ms 跳一次。

    两个指标缺一不可：
      - max_stall：最大单次停顿。只有停顿**之后**的那一跳才能记录到它，
        故退出前必须留出结算时间，否则最后一次冻结会被漏记。
      - ticks vs expected：停顿期间的心跳缺口。即使 max_stall 因调度
        巧合被低估，缺口仍能暴露冻结。
    """

    def __init__(self):
        self.max_stall = 0.0
        self.ticks = 0
        self.elapsed = 0.0
        self._task = None
        self._start = 0.0

    async def _run(self):
        last = time.monotonic()
        try:
            while True:
                await asyncio.sleep(0.01)
                now = time.monotonic()
                self.max_stall = max(self.max_stall, now - last)
                last = now
                self.ticks += 1
        except asyncio.CancelledError:
            pass

    async def __aenter__(self):
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0.05)   # 让探针先稳定跑起来
        self.max_stall = 0.0
        self.ticks = 0
        self._start = time.monotonic()
        return self

    async def __aexit__(self, *exc):
        self.elapsed = time.monotonic() - self._start
        # 结算：让冻结后的第一跳跑完，把停顿记进 max_stall 再收尾
        await asyncio.sleep(0.05)
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        return False

    @property
    def expected_ticks(self) -> int:
        return int(self.elapsed / 0.01)

    def assert_responsive(self, what: str) -> None:
        assert self.max_stall < MAX_STALL, (
            f"{what}：事件循环被冻结 {self.max_stall * 1000:.0f}ms（上限 "
            f"{MAX_STALL * 1000:.0f}ms）——同步 DB 调用未移出事件循环，"
            f"其余协程与 HTTP 请求在此期间全部停摆")
        # 心跳缺口：允许一半余量以容忍 CI 调度抖动
        assert self.ticks >= self.expected_ticks * 0.5, (
            f"{what}：{self.elapsed * 1000:.0f}ms 内仅心跳 {self.ticks} 次"
            f"（应约 {self.expected_ticks} 次）——事件循环被同步调用饿死")


@pytest.mark.asyncio
async def test_event_loop_not_blocked_by_worker_db_calls(session):
    """worker 完整跑一个作业期间，事件循环必须保持响应。

    覆盖 run_once 的三段会话：认领（读 payload）、进度回调、落终态。
    """
    provider = MockProvider()
    provider.queue(LEAD_JSON, LEAD_JSON)
    gateway = LLMGateway(provider)
    payload = {"accounts": [ACCOUNT, dict(ACCOUNT, account_uid="u2")]}
    create_job(session, "profile_analysis", payload, total=2)

    worker = ApiJobWorker(_SlowFactory(session), SkillExecutor(gateway),
                          gateway)

    async with _Heartbeat() as hb:
        assert await worker.run_once() is True

    hb.assert_responsive("worker 跑完一个作业")


@pytest.mark.asyncio
async def test_event_loop_not_blocked_by_reaper(session):
    """停滞作业回收循环同样不得冻结事件循环。"""
    gateway = LLMGateway(MockProvider())
    worker = ApiJobWorker(_SlowFactory(session), SkillExecutor(gateway),
                          gateway)

    async with _Heartbeat() as hb:
        await worker.reap_stale_once()

    hb.assert_responsive("reaper 回收停滞作业")


@pytest.mark.asyncio
async def test_event_loop_not_blocked_when_queue_empty(session):
    """空队列轮询（最高频路径）也不得冻结事件循环。"""
    gateway = LLMGateway(MockProvider())
    worker = ApiJobWorker(_SlowFactory(session), SkillExecutor(gateway),
                          gateway)

    async with _Heartbeat() as hb:
        assert await worker.run_once() is False

    hb.assert_responsive("空队列认领")
