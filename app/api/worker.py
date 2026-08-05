import asyncio
import logging

from app.api.agent1 import run_comment_screening
from app.api.agent2 import run_profile_analysis
from app.api.jobs import (claim_next_job_detached, fail_or_retry_by_id,
                          fail_stale_running_jobs, finish_job_by_id,
                          set_progress_by_id)
from app.api.schemas import CommentScreeningRequest, ProfileAnalysisRequest
from app.config import settings

logger = logging.getLogger(__name__)


class ApiJobWorker:
    def __init__(self, session_factory, executor, gateway,
                 poll_interval: float | None = None):
        self.session_factory = session_factory
        self.executor = executor
        self.gateway = gateway
        self.poll_interval = poll_interval or settings.worker_poll_interval

    async def _execute(self, job_id: str, job_type: str,
                       payload: dict) -> dict:
        """执行作业。只接纯数据，不持有会话，也不触碰 ORM 对象。

        V1.4.3：接收 ORM 对象会在访问 deferred 的 request_payload 时重新
        开启事务，把连接钉在池外整个 LLM 期间。
        """
        def cb(done):
            set_progress_by_id(self.session_factory, job_id, done)

        if job_type == "comment_screening":
            req = CommentScreeningRequest.model_validate(payload)
            return await run_comment_screening(self.executor, req,
                                               progress_cb=cb)
        if job_type == "profile_analysis":
            req = ProfileAnalysisRequest.model_validate(payload)
            return await run_profile_analysis(self.executor, self.gateway, req,
                                              progress_cb=cb)
        raise ValueError(f"未知作业类型: {job_type}")

    @staticmethod
    def _status_for(result: dict) -> str:
        items = result.get("results", [])
        errored = sum(1 for r in items if r.get("error"))
        if errored == 0:
            return "success"
        if errored < len(items):
            return "partial"
        return "failed"

    async def run_once(self) -> bool:
        """认领 → 执行 → 落状态，三段各自使用独立短会话。

        V1.4.3：LLM 调用（实测可达数百秒）期间不持有任何数据库连接，
        连接占用与 API_WORKER_CONCURRENCY 解耦。代价是 claim 与 finish
        之间作业无事务保护，worker 崩溃会留下 running 孤儿——这由既有的
        fail_stale_running_jobs 兜底回收。
        """
        # 会话1：认领并取出执行所需数据，随即归还连接
        with self.session_factory() as session:
            job = claim_next_job_detached(session)
        if job is None:
            return False

        job_id = job["id"]
        payload = job["payload"]
        logger.info("开始 API 作业 %s type=%s (第 %d 次)", job_id,
                    job["job_type"], job["attempt_count"])

        # 无连接持有：整个 LLM 调用期间不占用连接池
        try:
            result = await self._execute(job_id, job["job_type"], payload)
        except Exception as e:
            logger.exception("API 作业 %s 执行失败", job_id)
            # 会话2：写失败状态
            fail_or_retry_by_id(self.session_factory, job_id, str(e)[:2000],
                                payload=payload)
            await asyncio.sleep(self.poll_interval)
            return True

        # 会话3：写终态。payload 已在内存中，直接传入以免为剥离截图重读大列
        status = self._status_for(result)
        if status == "failed":
            fail_or_retry_by_id(self.session_factory, job_id, "全部条目处理失败",
                                payload=payload)
        else:
            finish_job_by_id(self.session_factory, job_id, result=result,
                             status=status, error=None, payload=payload)
        return True

    async def _loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                worked = await self.run_once()
            except Exception:
                logger.exception("API worker 循环异常")
                await asyncio.sleep(self.poll_interval)
                continue
            if not worked:
                await asyncio.sleep(self.poll_interval)

    async def reap_stale_once(self) -> int:
        """回收停滞 running 作业：超时直接判失败（不重试）。"""
        session = self.session_factory()
        try:
            n = fail_stale_running_jobs(
                session, settings.api_job_stale_minutes)
            if n:
                logger.warning("回收停滞 running 作业 %d 个（超过 %d 分钟未更新）",
                               n, settings.api_job_stale_minutes)
            return n
        finally:
            session.close()

    async def _reaper_loop(self, stop_event: asyncio.Event) -> None:
        # 每分钟扫一次即可；阈值按 updated_at 判定，误差一分钟无影响
        while not stop_event.is_set():
            try:
                await self.reap_stale_once()
            except Exception:
                logger.exception("停滞作业回收循环异常")
            await asyncio.sleep(60)

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        loops = [self._loop(stop_event)
                 for _ in range(settings.api_worker_concurrency)]
        loops.append(self._reaper_loop(stop_event))
        await asyncio.gather(*loops)
