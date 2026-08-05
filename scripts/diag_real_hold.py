"""用真实 ApiJobWorker 代码路径测量 LLM 期间的连接占用（不是模拟）。

把 app.db.engine 换成 SQLite QueuePool，注入一个会阻塞的假 gateway，
在"LLM 调用进行中"这一刻读 pool.checkedout()。
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DB_HOST"] = "127.0.0.1"      # 不会真连，下面整体换掉 engine

DB = Path(__file__).with_name("_diag_real.sqlite")
if DB.exists():
    DB.unlink()

import app.db as appdb
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

engine = create_engine(f"sqlite:///{DB}", poolclass=QueuePool,
                       pool_size=10, max_overflow=0)
appdb.engine = engine
appdb.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
SessionLocal = appdb.SessionLocal

import app.models  # noqa: E402
appdb.Base.metadata.create_all(engine)

from app.api.jobs import create_job  # noqa: E402
from app.api.worker import ApiJobWorker  # noqa: E402
from app.llm.base import LLMResponse  # noqa: E402
from app.llm.gateway import LLMGateway  # noqa: E402

PEAK = 0
SAMPLES = []


def sample(label):
    global PEAK
    n = engine.pool.checkedout()
    PEAK = max(PEAK, n)
    SAMPLES.append((label, n))
    return n


class SlowProvider:
    """模拟真实环境里数百秒的 LLM 调用（这里用 0.3s 代表）。"""

    async def chat(self, messages, *, model, temperature):
        sample("★ LLM 调用进行中（worker 是否还握着连接？）")
        await asyncio.sleep(0.3)
        return LLMResponse(text='{"results": []}', prompt_tokens=1,
                           completion_tokens=1)


async def main():
    payload = {"accounts": [{
        "account_uid": "u1", "account_name": "n1",
        "account_homepage_screenshot": "",
        "comment_history": [{"video_title": "t", "comment_content": "c",
                             "comment_time": "2026-08-05T10:00:00+08:00"}],
    }]}
    with SessionLocal() as s:
        create_job(s, "profile_analysis", payload, total=1)

    sample("基线（空闲）")

    gateway = LLMGateway(SlowProvider(), session_factory=SessionLocal)

    class Exec:
        """绕开 skill 配置文件，直接触发一次 gateway 调用。"""
        def __init__(self, gw):
            self.gateway = gw

        async def run(self, skill_id, ctx, model):
            await self.gateway.chat([{"role": "user", "content": "x"}],
                                    skill_id=skill_id)
            return model(lead_grade="C", is_valid_lead=False)

    worker = ApiJobWorker(SessionLocal, Exec(gateway), gateway)
    await worker.run_once()

    sample("作业结束后")

    print("采样序列：")
    for label, n in SAMPLES:
        print(f"  checkedout={n}   {label}")
    print()
    print(f"单个 API Worker 执行一次作业的连接峰值 = {PEAK}")
    print()
    print("按测试环境 .env 实配推算：")
    api_w = 3
    print(f"  API_WORKER_CONCURRENCY={api_w} → {api_w} × {PEAK} = {api_w * PEAK} 条被长期占用")
    print(f"  池容量 15+15=30，剩余可用 = {30 - api_w * PEAK} 条（供 Web + 业务 Worker + reaper）")


asyncio.run(main())
