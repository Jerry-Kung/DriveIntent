import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import SessionLocal, init_db
from app.llm.gateway import build_gateway
from app.skills.executor import SkillExecutor
from app.web.routes import router
from app.workflow.tasks import reset_running
from app.workflow.worker import Worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("数据库就绪: %s@%s:%s/%s", settings.db_user,
                settings.db_host, settings.db_port, settings.db_name)
    with SessionLocal() as s:
        reset_running(s)
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
    yield
    stop_event.set()
    if worker_task:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="DriveIntent", lifespan=lifespan)
app.include_router(router)
