"""诊断：业务 Worker（app/workflow/worker.py）在 LLM 期间是否持有连接。

V1.4.3 只改了 API Worker。业务 Worker 的 run_once 仍然全程持有同一
session（第 24 行创建，finally 才 close），中间穿插 await LLM。
pipeline 里虽有 session.commit() 提前结束事务，但 commit 只是结束事务、
归还连接——之后任何 ORM 属性访问都会重新取回连接并挂住。

本脚本用真实 Worker + 真实 pipeline 跑一遍，在 LLM 调用瞬间采样
pool.checkedout()，回答：业务 Worker 在 LLM 期间到底握不握连接。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("WORKER_ENABLED", "false")
os.environ.setdefault("API_WORKER_ENABLED", "false")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

DBFILE = "scripts/_diag_bizworker.sqlite"


def main():
    for suffix in ("", "-journal"):
        p = f"{DBFILE}{suffix}"
        if os.path.exists(p):
            os.remove(p)

    import app.db as appdb
    engine = create_engine(f"sqlite:///{DBFILE}", poolclass=QueuePool,
                           pool_size=10, max_overflow=0, pool_timeout=5,
                           connect_args={"check_same_thread": False})
    appdb.engine = engine
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    appdb.SessionLocal = SessionLocal
    import app.models  # noqa: F401
    appdb.Base.metadata.create_all(engine)

    from app.models import Comment, PlatformUser, Video
    from app.workflow.pipeline import schedule_analysis

    # 造数据：1 个视频 + 3 条评论（各属不同用户）
    with SessionLocal() as s:
        v = Video(platform="douyin", external_id="v1", title="测试视频",
                  author_name="@作者")
        s.add(v)
        s.commit()
        vid = v.id
        for i in range(3):
            u = PlatformUser(platform="douyin", external_id=f"uid{i}",
                             nickname=f"用户{i}")
            s.add(u)
            s.commit()
            s.add(Comment(platform="douyin", external_id=f"c{i}",
                          video_id=vid, user_id=u.id,
                          content=f"这车多少钱{i}"))
        s.commit()
        schedule_analysis(s)

    samples = []

    class SpyExecutor:
        """包住真实 executor，在每次 LLM 调用瞬间采样 checkedout。"""

        def __init__(self, inner):
            self.inner = inner

        async def run(self, skill_id, context, output_model):
            n = engine.pool.checkedout()
            samples.append((skill_id, n))
            print(f"  LLM 调用 skill={skill_id:<24} checkedout={n}")
            return await self.inner.run(skill_id, context, output_model)

    from app.llm.gateway import build_gateway
    from app.skills.executor import SkillExecutor
    from app.workflow.worker import Worker

    gateway = build_gateway(session_factory=SessionLocal)
    worker = Worker(SessionLocal, SpyExecutor(SkillExecutor(gateway)))

    print("=" * 66)
    print("业务 Worker 真实路径：LLM 调用期间的 pool.checkedout()")
    print("-" * 66)

    async def drive():
        for _ in range(12):
            worked = await worker.run_once()
            if not worked:
                break

    asyncio.run(drive())

    print("-" * 66)
    if not samples:
        print("未捕获到 LLM 调用，检查测试数据")
    else:
        peak = max(n for _, n in samples)
        print(f"LLM 期间 checkedout 峰值 = {peak}")
        print()
        if peak > 0:
            print("!! 业务 Worker 在 LLM 调用期间持有连接。")
            print("   WORKER_CONCURRENCY=6 → 稳态占用 6 条，")
            print("   叠加 API Worker 6 条 = 12 条被长期钉在池外。")
        else:
            print("OK 业务 Worker 在 LLM 期间不持有连接。")
    print("=" * 66)
    engine.dispose()


if __name__ == "__main__":
    main()
