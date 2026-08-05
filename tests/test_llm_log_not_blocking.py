"""LLM 调用日志落库不得冻结事件循环（V1.4.5 回归测试）。

根因（V1.4.5）：`LLMGateway._log` 是同步函数，却被 `async def chat` 直接在
事件循环里调用。它每次 LLM 调用都要 `session_factory()` 取连接、写一行
（input_digest 2000 字符 + output_text 8000 字符）、commit——全程同步。

危害有二：
  1. 连接池耗尽时，`pool.connect()` 会在事件循环里**同步阻塞满
     DB_POOL_TIMEOUT（30 秒）**，期间所有协程与 HTTP 请求全部停摆。
     生产日志中 30.0s / 90.1s / 120.0s / 150.1s 的成片静默正是其倍数。
  2. `except Exception: pass` 把 TimeoutError 吞掉，故该调用点**从不出现在
     任何 traceback 里**——报错全落在 get_job / set_progress_by_id 等受害者
     身上，掩盖了真正的阻塞源。

日志量级远超作业量级：实测 3 小时内 llm_call_log 写入 6703 行、API 作业仅
246 个（约 27 倍），故这是全系统最高频的一处同步 DB 调用。
"""
import asyncio
import time

import pytest

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider

# 单次日志落库的模拟耗时。连接池耗尽时真实阻塞可达 pool_timeout=30s，
# 此处取 0.3s 保持测试快速，量级差异不影响结论。
DB_LATENCY = 0.3
# 事件循环允许的最大单次停顿（心跳间隔 10ms，放宽以容忍 CI 抖动）
MAX_STALL = 0.2


class _SlowSession:
    """写日志时同步阻塞，模拟连接池耗尽/远程库慢写。"""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name in ("add", "commit", "query", "get", "execute"):
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
    """事件循环健康探针：正常每 10ms 跳一次。"""

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
        await asyncio.sleep(0.05)
        self.max_stall = 0.0
        self.ticks = 0
        self._start = time.monotonic()
        return self

    async def __aexit__(self, *exc):
        self.elapsed = time.monotonic() - self._start
        await asyncio.sleep(0.05)   # 结算：让冻结后的第一跳记进 max_stall
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        return False

    def assert_responsive(self, what: str) -> None:
        assert self.max_stall < MAX_STALL, (
            f"{what}：事件循环被冻结 {self.max_stall * 1000:.0f}ms（上限 "
            f"{MAX_STALL * 1000:.0f}ms）——LLM 日志落库未移出事件循环，"
            f"连接池耗尽时此处会同步阻塞满 pool_timeout（30s）")
        expected = int(self.elapsed / 0.01)
        assert self.ticks >= expected * 0.5, (
            f"{what}：{self.elapsed * 1000:.0f}ms 内仅心跳 {self.ticks} 次"
            f"（应约 {expected} 次）——事件循环被同步调用饿死")


@pytest.mark.asyncio
async def test_llm_log_does_not_block_event_loop(session):
    """gateway.chat 落日志期间，事件循环必须保持响应。"""
    provider = MockProvider()
    provider.queue("{}", "{}")
    gateway = LLMGateway(provider, session_factory=_SlowFactory(session))

    async with _Heartbeat() as hb:
        await gateway.chat([{"role": "user", "content": "hi"}],
                           skill_id="s", skill_version="1", prompt_version="1")

    hb.assert_responsive("gateway.chat 落 LLM 日志")


@pytest.mark.asyncio
async def test_llm_log_failure_still_swallowed(session):
    """落库失败仍不得影响主流程——日志是旁路，不能拖垮业务。"""
    class _Boom:
        def __call__(self):
            raise RuntimeError("连接池耗尽")

    provider = MockProvider()
    provider.queue("ok")
    gateway = LLMGateway(provider, session_factory=_Boom())

    resp = await gateway.chat([{"role": "user", "content": "hi"}])
    assert resp.text == "ok"
