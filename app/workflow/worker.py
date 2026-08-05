import asyncio
import logging
import time

from app.config import settings
from app.skills.executor import SkillExecutor
from app.workflow.pipeline import (COMMENT_SCREENING_SKILL,
                                   USER_ANALYSIS_SKILL, VIDEO_CONTEXT_SKILL,
                                   advance, run_user_analysis,
                                   run_video_context, screen_comment_batch)
from app.workflow.tasks import claim_next, finish_task

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, session_factory, executor: SkillExecutor,
                 poll_interval: float | None = None):
        self.session_factory = session_factory
        self.executor = executor
        self.poll_interval = poll_interval or settings.worker_poll_interval

    async def run_once(self) -> bool:
        """认领 → 执行 → 落状态。

        V1.4.4：认领/落状态/推进三处离散的同步 DB 调用经 asyncio.to_thread
        执行。同步调用跑在事件循环里会冻结整个 loop，其余协程与 HTTP 请求
        在此期间全部停摆（`advance` 尤甚——它一次要跑多条查询）。
        注：pipeline 内部仍有同步 DB 调用，但其查询均为小结果集，且
        `scripts/diag_biz_worker_hold.py` 实测该路径 checkedout 峰值为 0。
        """
        session = self.session_factory()
        try:
            task = await asyncio.to_thread(claim_next, session)
            if task is None:
                return False
            logger.info("开始任务 #%s %s target=%s (第 %d 次尝试)",
                        task.id, task.task_type, task.target_id,
                        task.attempt_count)
            start = time.monotonic()
            error: str | None = None
            try:
                if task.task_type == VIDEO_CONTEXT_SKILL:
                    await run_video_context(session, self.executor,
                                            int(task.target_id))
                elif task.task_type == COMMENT_SCREENING_SKILL:
                    await screen_comment_batch(
                        session, self.executor,
                        int(task.payload["video_id"]),
                        list(task.payload["comment_ids"]))
                elif task.task_type == USER_ANALYSIS_SKILL:
                    await run_user_analysis(session, self.executor,
                                            int(task.target_id))
                else:
                    error = f"未知任务类型: {task.task_type}"
            except Exception as e:
                # 先 rollback 恢复 session 可用状态，再访问 task 属性（否则失败
                # 的 flush 会使 task 处于过期状态，此时任何查询都会因
                # PendingRollbackError 再次抛出，导致 rollback 永远执行不到）
                session.rollback()
                logger.exception("任务 %s 执行失败", task.id)
                error = str(e)[:2000]
            await asyncio.to_thread(finish_task, session, task, error)
            await asyncio.to_thread(advance, session)
            if error is not None:
                # 持久失败时节流，避免对故障中的 LLM/DB 热循环重试
                await asyncio.sleep(self.poll_interval)
            else:
                logger.info("任务 #%s 完成，耗时 %.1fs",
                            task.id, time.monotonic() - start)
            return True
        finally:
            session.close()

    async def _loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                worked = await self.run_once()
            except Exception:
                logger.exception("worker 循环出现未预期异常")
                await asyncio.sleep(self.poll_interval)
                continue
            if not worked:
                await asyncio.sleep(self.poll_interval)

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        loops = [self._loop(stop_event)
                 for _ in range(settings.worker_concurrency)]
        await asyncio.gather(*loops)
