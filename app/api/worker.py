import asyncio
import logging

from app.api.agent1 import run_comment_screening
from app.api.agent2 import run_profile_analysis
from app.api.jobs import claim_next_job, fail_or_retry, finish_job, set_progress
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

    async def _execute(self, session, job) -> dict:
        def cb(done):
            set_progress(session, job, done)

        if job.job_type == "comment_screening":
            req = CommentScreeningRequest.model_validate(job.request_payload)
            return await run_comment_screening(self.executor, req,
                                               progress_cb=cb)
        if job.job_type == "profile_analysis":
            req = ProfileAnalysisRequest.model_validate(job.request_payload)
            return await run_profile_analysis(self.executor, self.gateway, req,
                                              progress_cb=cb)
        raise ValueError(f"未知作业类型: {job.job_type}")

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
        session = self.session_factory()
        try:
            job = claim_next_job(session)
            if job is None:
                return False
            logger.info("开始 API 作业 %s type=%s (第 %d 次)", job.id,
                        job.job_type, job.attempt_count)
            try:
                result = await self._execute(session, job)
            except Exception as e:
                session.rollback()
                logger.exception("API 作业 %s 执行失败", job.id)
                fail_or_retry(session, job, str(e)[:2000])
                await asyncio.sleep(self.poll_interval)
                return True
            status = self._status_for(result)
            if status == "failed":
                fail_or_retry(session, job, "全部条目处理失败")
            else:
                finish_job(session, job, result=result, status=status,
                           error=None)
            return True
        finally:
            session.close()

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

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        loops = [self._loop(stop_event)
                 for _ in range(settings.api_worker_concurrency)]
        await asyncio.gather(*loops)
