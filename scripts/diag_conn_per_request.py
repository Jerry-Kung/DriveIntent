"""诊断：各类 HTTP 请求各消耗多少连接、持有多久。

用真实 FastAPI app + TestClient 打真实端点，用 pool 事件测量。
重点回答三个问题：
  Q1 401（无效 Key）的请求是否也会取走一条连接？
     —— compose.log 显示大量轮询方持有无效 Key；若 401 也吃连接，
        一波无效轮询就能抽干池子。
  Q2 200 轮询持有连接多久？result 是非 deferred 的 MB 级 JSON。
  Q3 事件循环里的同步 DB 调用会不会阻塞整个 loop？
     —— 这是 30 秒串行报错的直接解释。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("API_KEYS", "testkey")
os.environ.setdefault("WORKER_ENABLED", "false")
os.environ.setdefault("API_WORKER_ENABLED", "false")
os.environ.setdefault("LLM_PROVIDER", "mock")

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

DBFILE = "scripts/_diag_conn.sqlite"


def build():
    for suffix in ("", "-journal"):
        p = f"{DBFILE}{suffix}"
        if os.path.exists(p):
            os.remove(p)

    import app.db as appdb
    engine = create_engine(f"sqlite:///{DBFILE}", poolclass=QueuePool,
                           pool_size=5, max_overflow=0, pool_timeout=2,
                           connect_args={"check_same_thread": False})
    appdb.engine = engine
    appdb.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    import app.models  # noqa: F401
    appdb.Base.metadata.create_all(engine)
    return engine, appdb.SessionLocal


def main():
    engine, SessionLocal = build()

    # 让 routes 用上新的 SessionLocal
    import app.api.routes as routes
    routes.SessionLocal = SessionLocal

    events = []

    @event.listens_for(engine, "checkout")
    def _co(*a):
        events.append(("checkout", time.monotonic(), engine.pool.checkedout()))

    @event.listens_for(engine, "checkin")
    def _ci(*a):
        events.append(("checkin", time.monotonic(), engine.pool.checkedout()))

    from fastapi.testclient import TestClient

    from app.api.jobs import create_job
    from app.main import app

    # 造一个带大 result 的作业（模拟真实终态行）
    with SessionLocal() as s:
        job = create_job(s, "profile_analysis", {"accounts": []}, total=1)
        job.status = "success"
        job.result = {"results": [{"account_uid": f"u{i}",
                                   "analysis": "x" * 2000}
                                  for i in range(200)]}
        s.commit()
        job_id = job.id

    client = TestClient(app)

    def count(label, fn):
        events.clear()
        before = engine.pool.checkedout()
        r = fn()
        checkouts = sum(1 for e in events if e[0] == "checkout")
        after = engine.pool.checkedout()
        print(f"{label:<38} status={r.status_code:<4} "
              f"取连接次数={checkouts}  调用后未归还={after - before}")
        return checkouts

    print("=" * 74)
    print("Q1 / Q2：单请求的连接消耗")
    print("-" * 74)
    c_401 = count("GET /jobs/{id}  无效 Key (401)",
                  lambda: client.get(f"/api/v1/jobs/{job_id}",
                                     headers={"Authorization": "Bearer bad"}))
    count("GET /jobs/{id}  有效 Key (200)",
          lambda: client.get(f"/api/v1/jobs/{job_id}",
                             headers={"Authorization": "Bearer testkey"}))
    count("GET /health",
          lambda: client.get("/health"))
    count("HEAD /jobs/{id} 有效 Key",
          lambda: client.head(f"/api/v1/jobs/{job_id}",
                              headers={"Authorization": "Bearer testkey"}))

    print()
    print("=" * 74)
    print("Q1 结论")
    print("-" * 74)
    if c_401 > 0:
        print("!! 401 请求也会取走连接 —— 无效 Key 的轮询洪水可抽干连接池")
    else:
        print("OK 401 在取连接前被拦下，不消耗连接池")

    # Q3：事件循环阻塞
    print()
    print("=" * 74)
    print("Q3：事件循环里的同步 DB 调用是否阻塞整个 loop")
    print("-" * 74)

    import asyncio

    async def q3():
        # 占满池子
        held = [SessionLocal() for _ in range(5)]
        for h in held:
            h.execute(__import__("sqlalchemy").text("SELECT 1")).all()

        ticks = {"n": 0}

        async def heartbeat():
            """事件循环健康探针：正常应每 10ms 跳一次。"""
            try:
                while True:
                    await asyncio.sleep(0.01)
                    ticks["n"] += 1
            except asyncio.CancelledError:
                pass

        hb = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.1)
        base = ticks["n"]

        # 模拟 worker 的同步 DB 调用（set_progress_by_id 的行为）
        t0 = time.monotonic()
        try:
            with SessionLocal() as s:
                s.execute(__import__("sqlalchemy").text("SELECT 1")).all()
        except Exception as e:
            blocked = time.monotonic() - t0
            hb.cancel()
            gained = ticks["n"] - base
            print(f"同步 DB 调用阻塞时长 : {blocked:.2f}s "
                  f"(pool_timeout=2)")
            print(f"阻塞期间心跳次数     : {gained}  "
                  f"(正常应约 {int(blocked / 0.01)} 次)")
            if gained <= 1:
                print()
                print("!! 事件循环被完全冻住 —— 这正是 30 秒串行报错的成因：")
                print("   worker 协程的同步 DB 调用在等连接时阻塞整个 loop，")
                print("   其他协程连'尝试取连接'的机会都没有，只能排队挨个超时。")
            else:
                print("事件循环未被冻住")
            for h in held:
                h.close()
            return
        hb.cancel()
        for h in held:
            h.close()
        print("未触发超时，测试条件需调整")

    asyncio.run(q3())
    engine.dispose()


if __name__ == "__main__":
    main()
