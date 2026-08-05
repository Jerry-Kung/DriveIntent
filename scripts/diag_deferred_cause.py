"""定位：LLM 期间那 1 条连接，究竟是被谁占住的？

对照实验：同一段代码，分别在 request_payload 为 deferred / 非 deferred 时
测量 LLM 调用期间的 checkedout。
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import Integer, JSON, String, create_engine
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column,
                            sessionmaker)
from sqlalchemy.pool import QueuePool


def build(deferred: bool, tag: str):
    class Base(DeclarativeBase):
        pass

    class Job(Base):
        __tablename__ = "job"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        status: Mapped[str] = mapped_column(String(16), default="pending")
        attempt_count: Mapped[int] = mapped_column(Integer, default=0)
        progress_done: Mapped[int] = mapped_column(Integer, default=0)
        request_payload: Mapped[dict | None] = mapped_column(
            JSON, deferred=deferred)

    db = Path(__file__).with_name(f"_diag_def_{tag}.sqlite")
    if db.exists():
        db.unlink()
    eng = create_engine(f"sqlite:///{db}", poolclass=QueuePool,
                        pool_size=10, max_overflow=0)
    Base.metadata.create_all(eng)
    SL = sessionmaker(bind=eng, expire_on_commit=False)
    with SL() as s:
        s.add(Job(id=1, request_payload={"a": "b" * 1000}))
        s.commit()
    return eng, SL, Job


async def scenario(deferred: bool, touch_payload: bool, tag: str):
    eng, SL, Job = build(deferred, tag)
    session = SL()
    try:
        # claim_next_job 等价逻辑
        job = (session.query(Job).filter_by(status="pending")
               .with_for_update(skip_locked=True).first())
        job.status = "running"
        job.attempt_count += 1
        session.commit()
        after_claim = eng.pool.checkedout()

        if touch_payload:
            _ = job.request_payload      # _execute 里的 model_validate

        during_llm = eng.pool.checkedout()
        await asyncio.sleep(0.05)        # LLM
        return after_claim, during_llm
    finally:
        session.close()
        eng.dispose()


async def main():
    print(f"{'场景':<44} {'claim后':>8} {'LLM期间':>8}")
    print("-" * 62)
    for deferred in (True, False):
        for touch in (True, False):
            tag = f"{deferred}_{touch}"
            a, b = await scenario(deferred, touch, tag)
            name = (f"deferred={str(deferred):<5} "
                    f"访问payload={str(touch):<5}")
            flag = "  ← 连接被握住" if b > 0 else ""
            print(f"{name:<44} {a:>8} {b:>8}{flag}")


asyncio.run(main())
