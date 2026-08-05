import asyncio
import logging

from app.api import staging
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

    async def _execute(self, job_id: str, job_type: str, payload: dict,
                       vision_sink: dict | None = None) -> dict:
        """执行作业。只接纯数据，不持有会话，也不触碰 ORM 对象。

        V1.4.3：接收 ORM 对象会在访问 deferred 的 request_payload 时重新
        开启事务，把连接钉在池外整个 LLM 期间。
        V1.4.4：进度回调改 async，DB 写入经线程池，避免冻结事件循环；
        识图文本经 vision_sink 收集，终态写回 payload 替代 base64。
        """
        async def cb(done):
            await asyncio.to_thread(set_progress_by_id,
                                    self.session_factory, job_id, done)

        if job_type == "comment_screening":
            req = CommentScreeningRequest.model_validate(payload)
            return await run_comment_screening(self.executor, req,
                                               progress_cb=cb)
        if job_type == "profile_analysis":
            req = ProfileAnalysisRequest.model_validate(payload)
            return await run_profile_analysis(self.executor, self.gateway, req,
                                              progress_cb=cb,
                                              vision_sink=vision_sink)
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

        V1.4.4：三段会话全部经 asyncio.to_thread 执行。同步 DB 调用跑在
        事件循环里会冻结整个 loop（实测远程读 13MB payload 阻塞 3.2s，
        期间所有协程与 HTTP 请求停摆），是连接池耗尽的直接成因。
        """
        # 会话1：认领并取出执行所需数据，随即归还连接
        job = await asyncio.to_thread(self._claim)
        if job is None:
            return False

        job_id = job["id"]
        payload = job["payload"]
        logger.info("开始 API 作业 %s type=%s (第 %d 次)", job_id,
                    job["job_type"], job["attempt_count"])

        # 识图文本收集器：终态时写回 payload，替代 base64 截图
        vision: dict[str, str] = {}

        # 无连接持有：整个 LLM 调用期间不占用连接池
        try:
            result = await self._execute(job_id, job["job_type"], payload,
                                         vision_sink=vision)
        except Exception as e:
            logger.exception("API 作业 %s 执行失败", job_id)
            # 会话2：写失败状态
            await asyncio.to_thread(
                fail_or_retry_by_id, self.session_factory, job_id,
                str(e)[:2000], payload, vision)
            await asyncio.sleep(self.poll_interval)
            return True

        # 会话3：写终态。payload 已在内存中，直接传入以免为剥离截图重读大列
        status = self._status_for(result)
        if status == "failed":
            await asyncio.to_thread(
                fail_or_retry_by_id, self.session_factory, job_id,
                "全部条目处理失败", payload, vision)
        else:
            await asyncio.to_thread(
                self._finish, job_id, result, status, payload, vision)
        return True

    def _claim(self) -> dict | None:
        """会话1 的同步体，供 to_thread 调用。

        V1.4.4：认领后把暂存区的 base64 截图并回 payload 副本（仅内存，
        不落库）。存量作业 payload 内已内联截图，此时暂存为空、原样返回。
        """
        with self.session_factory() as session:
            job = claim_next_job_detached(session)
        if job is None:
            return None
        if job["job_type"] == "profile_analysis":
            shots = staging.load(job["id"])
            job["payload"] = staging.merge_into_payload(job["payload"], shots)
        return job

    def _finish(self, job_id: str, result: dict, status: str,
                payload: dict, vision: dict) -> None:
        """会话3 的同步体，供 to_thread 调用（关键字参数无法直接传给
        to_thread 的位置参数形式，故包一层）。"""
        finish_job_by_id(self.session_factory, job_id, result=result,
                         status=status, error=None, payload=payload,
                         vision_text=vision)

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
        return await asyncio.to_thread(self._reap_stale)

    def _reap_stale(self) -> int:
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
