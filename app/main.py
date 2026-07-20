import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import SessionLocal, init_db
from app.llm.gateway import build_gateway
from app.skills.executor import SkillExecutor
from app.web.routes import router
from app.workflow.tasks import reset_running
from app.workflow.worker import Worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as s:
        reset_running(s)
    stop_event = asyncio.Event()
    worker_task = None
    if settings.worker_enabled:
        gateway = build_gateway(session_factory=SessionLocal)
        worker = Worker(SessionLocal, SkillExecutor(gateway))
        worker_task = asyncio.create_task(worker.run_forever(stop_event))
    yield
    stop_event.set()
    if worker_task:
        worker_task.cancel()


app = FastAPI(title="DriveIntent", lifespan=lifespan)
app.include_router(router)
