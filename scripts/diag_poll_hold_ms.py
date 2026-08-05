"""诊断：GET /api/v1/jobs/{id} 单次轮询持有连接多久。

get_db() 是 yield 依赖，连接在 finally 才 close——即在**整个响应
序列化完成之后**。而 ApiJob.result 是非 deferred 的 MB 级 JSON：
  SELECT 把整行搬进内存 → FastAPI/pydantic 序列化数 MB dict → 才归还连接

若序列化耗时可观，则每个轮询请求的连接持有时间远超"一次快查询"的直觉。
FastAPI 同步 def 端点跑在 anyio 线程池（40 线程）> 池容量 30。

本脚本测量：不同 result 体积下，单请求的连接持有时长与 CPU 占用。
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

DBFILE = "scripts/_diag_hold_ms.sqlite"


def main():
    for suffix in ("", "-journal"):
        p = f"{DBFILE}{suffix}"
        if os.path.exists(p):
            os.remove(p)

    import app.db as appdb
    engine = create_engine(f"sqlite:///{DBFILE}", poolclass=QueuePool,
                           pool_size=30, max_overflow=0, pool_timeout=5,
                           connect_args={"check_same_thread": False})
    appdb.engine = engine
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    appdb.SessionLocal = SessionLocal
    import app.models  # noqa: F401
    appdb.Base.metadata.create_all(engine)

    import app.api.routes as routes
    routes.SessionLocal = SessionLocal

    from fastapi.testclient import TestClient

    from app.api.jobs import create_job
    from app.main import app

    hold = {"out": None, "dur": None}

    @event.listens_for(engine, "checkout")
    def _co(*a):
        hold["out"] = time.monotonic()

    @event.listens_for(engine, "checkin")
    def _ci(*a):
        if hold["out"] is not None:
            hold["dur"] = time.monotonic() - hold["out"]

    client = TestClient(app)

    def make_job(n_results, text_len):
        with SessionLocal() as s:
            job = create_job(s, "comment_screening", {"comments": []},
                             total=n_results)
            job.status = "success"
            job.result = {"results": [
                {"comment_id": f"c{i}", "passed": True,
                 "filter_reason": "x" * text_len,
                 "analysis": "y" * text_len}
                for i in range(n_results)]}
            s.commit()
            return job.id

    print("=" * 72)
    print("单次 GET /api/v1/jobs/{id} 的连接持有时长")
    print("-" * 72)
    print(f"{'result 规模':<28}{'响应体积':>12}{'连接持有':>14}")
    print("-" * 72)

    rows = []
    for n, ln, label in [(10, 100, "10 条 × 100 字"),
                         (200, 500, "200 条 × 500 字"),
                         (1000, 500, "1000 条 × 500 字"),
                         (2000, 1000, "2000 条 × 1000 字")]:
        jid = make_job(n, ln)
        hold["dur"] = None
        r = client.get(f"/api/v1/jobs/{jid}",
                       headers={"Authorization": "Bearer testkey"})
        size = len(r.content) / 1024 / 1024
        dur = hold["dur"] or 0
        rows.append((label, size, dur))
        print(f"{label:<28}{size:>10.2f}MB{dur * 1000:>12.0f}ms")

    print("-" * 72)
    print()
    print("推算：连接容量 30，pool_timeout 30s")
    print("-" * 72)
    for label, size, dur in rows:
        if dur > 0:
            qps = 30 / dur
            print(f"{label:<28} 池可支撑约 {qps:>7.1f} QPS 的轮询")
    print()
    print("注：真实环境为远程 MySQL（118.145.238.55），网络往返 + 数 MB")
    print("    行传输会让持有时长显著高于本地 SQLite 的测量值。")
    print("=" * 72)
    engine.dispose()


if __name__ == "__main__":
    main()
