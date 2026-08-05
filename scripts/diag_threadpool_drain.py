"""诊断：同步端点 + anyio 线程池是否会把连接池抽干。

背景（compose.log 证据）：
  1. 报错精确 30.00 秒串行排队（07:34:33 → 07:35:03 → 07:35:33 …）。
     若 12 个 worker 协程真在并发等连接，应几乎同时超时而非排队。
  2. 07:35:03.138/.140/.141/.142/.142 五个 LLM 请求同一毫秒齐发——
     被冻住的协程集体解冻的特征。
  3. 全日志 0 条 Web 访问日志：EndpointNoiseFilter 恰好过滤掉了
     /api/v1/jobs/ 的成功轮询，占满池的流量在日志里完全隐身。

假设：`GET /api/v1/jobs/{id}` 是同步 def，FastAPI 派往 anyio 线程池
（默认 40 线程），每线程经 get_db() 各持一条连接。40 > 池容量 30，
故轮询并发一上来就把池抽干，worker 与 reaper 全部饿死。

本脚本用真实 QueuePool（小容量便于观察）复现，并测量峰值 checkedout。
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

DB = "sqlite:///scripts/_diag_tpool.sqlite"
POOL_SIZE = 3
MAX_OVERFLOW = 2          # 容量 = 5
N_THREADS = 12            # 模拟 anyio 线程池并发（> 容量）
HOLD_SECONDS = 1.0        # 模拟大 JSON 序列化耗时


def main():
    for suffix in ("", "-journal"):
        p = f"scripts/_diag_tpool.sqlite{suffix}"
        if os.path.exists(p):
            os.remove(p)

    engine = create_engine(DB, poolclass=QueuePool, pool_size=POOL_SIZE,
                           max_overflow=MAX_OVERFLOW, pool_timeout=3,
                           connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)

    peak = {"v": 0}
    lock = threading.Lock()

    @event.listens_for(engine, "checkout")
    def _on_checkout(*a):
        with lock:
            n = engine.pool.checkedout()
            peak["v"] = max(peak["v"], n)

    results = {"ok": 0, "timeout": 0}

    def poll_request():
        """模拟一次 GET /api/v1/jobs/{id}：取连接 → 查询 → 序列化大 JSON。"""
        try:
            s = Session()
            try:
                s.execute(__import__("sqlalchemy").text("SELECT 1")).all()
                # 持有连接期间做「大 JSON 序列化」——同步端点的真实行为
                time.sleep(HOLD_SECONDS)
            finally:
                s.close()
            with lock:
                results["ok"] += 1
        except Exception as e:
            if "QueuePool limit" in str(e):
                with lock:
                    results["timeout"] += 1
            else:
                raise

    threads = [threading.Thread(target=poll_request) for _ in range(N_THREADS)]
    t0 = time.monotonic()
    for t in threads:
        t.start()

    # worker 在轮询压满期间尝试取连接（模拟 set_progress_by_id）
    time.sleep(0.3)
    worker_ok = None
    try:
        s = Session()
        s.execute(__import__("sqlalchemy").text("SELECT 1")).all()
        s.close()
        worker_ok = True
    except Exception as e:
        worker_ok = False if "QueuePool limit" in str(e) else None

    for t in threads:
        t.join()
    elapsed = time.monotonic() - t0

    print("=" * 60)
    print(f"pool_size={POOL_SIZE} max_overflow={MAX_OVERFLOW} "
          f"容量={POOL_SIZE + MAX_OVERFLOW}")
    print(f"并发轮询线程数={N_THREADS}（模拟 anyio 线程池）")
    print("-" * 60)
    print(f"峰值 checkedout      : {peak['v']}")
    print(f"轮询成功             : {results['ok']}")
    print(f"轮询被池超时拒绝     : {results['timeout']}")
    print(f"worker 能否取到连接  : {worker_ok}  <-- False 表示 worker 被饿死")
    print(f"总耗时               : {elapsed:.1f}s")
    print("=" * 60)
    if peak["v"] >= POOL_SIZE + MAX_OVERFLOW and worker_ok is False:
        print("结论：同步端点线程池确实抽干连接池，worker 饿死。假设成立。")
    else:
        print("结论：未复现，假设不成立，需另找根因。")

    engine.dispose()


if __name__ == "__main__":
    main()
