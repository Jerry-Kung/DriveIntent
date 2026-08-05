"""验证 worker 真实路径落终态时不再重读大 payload。"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = Path(__file__).with_name("_diag_wpath.sqlite")
if DB.exists():
    DB.unlink()

import app.db as appdb
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

engine = create_engine(f"sqlite:///{DB}", poolclass=QueuePool,
                       pool_size=10, max_overflow=0)
appdb.engine = engine
appdb.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
SessionLocal = appdb.SessionLocal

import app.models  # noqa: E402
appdb.Base.metadata.create_all(engine)

from app.api.jobs import create_job, get_job  # noqa: E402
from app.api.worker import ApiJobWorker  # noqa: E402
from app.llm.base import LLMResponse  # noqa: E402
from app.llm.gateway import LLMGateway  # noqa: E402

PEAK = 0
STMTS = []


@event.listens_for(engine, "before_cursor_execute")
def cap(conn, cursor, statement, parameters, context, executemany):
    global PEAK
    PEAK = max(PEAK, engine.pool.checkedout())
    STMTS.append(statement.strip().replace("\n", " "))


class SlowProvider:
    async def chat(self, messages, *, model, temperature):
        global PEAK
        n = engine.pool.checkedout()
        PEAK = max(PEAK, n)
        print(f"  LLM 调用中 checkedout={n}")
        await asyncio.sleep(0.2)
        return LLMResponse(text='{}', prompt_tokens=1, completion_tokens=1)


async def main():
    payload = {"accounts": [{
        "account_uid": "u1", "account_name": "n1",
        "account_homepage_screenshot": "A" * 200000,
        "comment_history": [{"video_title": "t", "comment_content": "c",
                             "comment_time": "2026-08-05T10:00:00+08:00"}]}]}
    with SessionLocal() as s:
        jid = create_job(s, "profile_analysis", payload, total=1).id

    gateway = LLMGateway(SlowProvider(), session_factory=SessionLocal)

    class Exec:
        def __init__(self, gw):
            self.gateway = gw

        async def run(self, skill_id, ctx, model):
            await self.gateway.chat([{"role": "user", "content": "x"}],
                                    skill_id=skill_id)
            return model(lead_grade="C", is_valid_lead=False)

    STMTS.clear()
    worker = ApiJobWorker(SessionLocal, Exec(gateway), gateway)
    await worker.run_once()

    big_reads = [s for s in STMTS
                 if s.upper().startswith("SELECT") and "request_payload" in s]
    print(f"\n整个作业期间连接峰值 = {PEAK}")
    print(f"读取 request_payload 大列的 SELECT 次数 = {len(big_reads)}"
          f"   (认领时 1 次为必需)")

    with SessionLocal() as s:
        row = get_job(s, jid)
        shot = row.request_payload["accounts"][0]["account_homepage_screenshot"]
        print(f"终态 status={row.status}  截图已剥离={shot == ''}")


asyncio.run(main())
