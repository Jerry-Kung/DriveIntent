import asyncio
import logging
from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI

from app.api.jobs import reset_running_jobs
from app.api.routes import api_router
from app.api.worker import ApiJobWorker
from app.config import settings
from app.db import SessionLocal, init_db
from app.llm.gateway import build_gateway
from app.logging_filters import install_access_log_filter
from app.skills.executor import SkillExecutor
from app.web.audit import audit_router
from app.web.routes import router
from app.workflow.tasks import reset_running
from app.workflow.worker import Worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)
# 轮询/健康检查的成功访问日志会刷屏，仅保留出错记录
install_access_log_filter()


def _apply_threadpool_limit() -> None:
    """收敛 anyio 默认线程池，使并发同步请求数不超过连接池容量。

    FastAPI 的同步（def）端点在该线程池中执行，每个在途请求经 get_db()
    独占一条 DB 连接直到请求结束。anyio 默认 40 槽，而连接池容量为
    pool_size + max_overflow；两者失配时超出的请求会阻塞在 pool.connect()
    直到 pool_timeout 抛 QueuePool TimeoutError，并连带拖垮抢同一个池的
    worker（claim_next）。
    """
    capacity = settings.db_pool_size + settings.db_max_overflow
    slots = min(settings.web_threadpool_slots, capacity)
    anyio.to_thread.current_default_thread_limiter().total_tokens = slots
    if settings.web_threadpool_slots > capacity:
        logger.warning(
            "WEB_THREADPOOL_SLOTS=%d 超过连接池容量 %d，已下调至 %d",
            settings.web_threadpool_slots, capacity, slots)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _apply_threadpool_limit()
    init_db()
    logger.info("数据库就绪: %s@%s:%s/%s", settings.db_user,
                settings.db_host, settings.db_port, settings.db_name)
    logger.info("连接池: size=%d overflow=%d 容量=%d，Web 线程池槽位=%d",
                settings.db_pool_size, settings.db_max_overflow,
                settings.db_pool_size + settings.db_max_overflow,
                anyio.to_thread.current_default_thread_limiter().total_tokens)
    with SessionLocal() as s:
        reset_running(s)
        reset_running_jobs(s)
    stop_event = asyncio.Event()
    worker_task = None
    if settings.worker_enabled:
        gateway = build_gateway(session_factory=SessionLocal)
        worker = Worker(SessionLocal, SkillExecutor(gateway))
        worker_task = asyncio.create_task(worker.run_forever(stop_event))
        logger.info("Worker 已启动: provider=%s model=%s 并发=%d",
                    settings.llm_provider, settings.llm_model,
                    settings.worker_concurrency)
    else:
        logger.warning("Worker 未启用（WORKER_ENABLED=false），任务不会被执行")
    api_worker_task = None
    if settings.api_worker_enabled:
        api_gateway = build_gateway(session_factory=SessionLocal)
        api_worker = ApiJobWorker(
            SessionLocal, SkillExecutor(api_gateway), api_gateway)
        api_worker_task = asyncio.create_task(
            api_worker.run_forever(stop_event))
        logger.info("API Worker 已启动: 并发=%d",
                    settings.api_worker_concurrency)
    yield
    stop_event.set()
    for t in (worker_task, api_worker_task):
        if t:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass


app = FastAPI(title="DriveIntent", lifespan=lifespan)
app.include_router(router)
app.include_router(api_router)
app.include_router(audit_router)
