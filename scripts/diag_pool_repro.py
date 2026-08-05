#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""决定性实验：复现 QueuePool 耗尽。

假设 H1：FastAPI 同步端点跑在 anyio 默认 40 槽线程池中，每个请求经
get_db() 独占一条 DB 连接直到请求结束。连接池上限为
pool_size(15) + max_overflow(15) = 30 < 40。因此只要有 >30 个同步请求
同时在途（提交端点写 MB 级 payload 时每个都要占用连接数秒），线程池里
第 31 个及以后的请求就会阻塞在 pool.connect() 上，等满 30s 抛
TimeoutError；worker 协程此时去 claim_next 同样抢不到连接，于是抛出
用户看到的那条 worker 循环异常。

本实验用本地 SQLite + QueuePool 复现该竞争关系，不触碰生产库。
"""
import io
import sys
import threading
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

POOL_SIZE, MAX_OVERFLOW, POOL_TIMEOUT = 15, 15, 3   # 缩短 timeout 便于观察
THREADPOOL_SLOTS = 40                                # anyio 默认值

engine = create_engine(
    "sqlite:///file:memdb_diag?mode=memory&cache=shared&uri=true",
    poolclass=QueuePool,
    pool_size=POOL_SIZE, max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT, connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)

capacity = POOL_SIZE + MAX_OVERFLOW
print(f"连接池容量 = pool_size({POOL_SIZE}) + max_overflow({MAX_OVERFLOW})"
      f" = {capacity}")
print(f"并发同步请求上限（anyio 默认线程池）= {THREADPOOL_SLOTS}")
print(f"=> {THREADPOOL_SLOTS} > {capacity}，超出的 "
      f"{THREADPOOL_SLOTS - capacity} 个请求必然排队等连接\n")

HOLD = 5.0          # 模拟一次「写 MB 级 payload」占用连接的时长
results = {"ok": 0, "timeout": 0}
lock = threading.Lock()
barrier = threading.Barrier(THREADPOOL_SLOTS)


def request_worker(i: int):
    """模拟一个走 get_db() 的同步端点：整个请求期间独占一条连接。"""
    barrier.wait()                       # 让所有请求同时涌入
    try:
        s = Session()                    # get_db() 的 yield 之前
        try:
            s.execute(text("SELECT 1"))  # 此刻真正 checkout 连接
            time.sleep(HOLD)             # 模拟大 payload 写入耗时
        finally:
            s.close()                    # get_db() 的 finally
        with lock:
            results["ok"] += 1
    except SATimeoutError:
        with lock:
            results["timeout"] += 1


print(f"启动 {THREADPOOL_SLOTS} 个并发请求，每个持有连接 {HOLD}s "
      f"（pool_timeout={POOL_TIMEOUT}s）...")
threads = [threading.Thread(target=request_worker, args=(i,))
           for i in range(THREADPOOL_SLOTS)]
t0 = time.monotonic()
for t in threads:
    t.start()

# 请求涌入期间，模拟 worker 协程去 claim_next —— 它同样要抢连接
time.sleep(1.0)
worker_error = None
t_claim = time.monotonic()
try:
    ws = Session()
    try:
        ws.execute(text("SELECT 1"))
        print(f"\n[worker] claim_next 成功获取连接 "
              f"（等待 {time.monotonic()-t_claim:.1f}s）")
    finally:
        ws.close()
except SATimeoutError as e:
    worker_error = e
    print(f"\n[worker] claim_next 抢连接失败（等待 "
          f"{time.monotonic()-t_claim:.1f}s）:\n    {type(e).__name__}: "
          f"{str(e).splitlines()[0]}")

for t in threads:
    t.join()

print(f"\n总耗时 {time.monotonic()-t0:.1f}s")
print(f"请求结果: 成功 {results['ok']}, 连接超时 {results['timeout']}")
print("\n结论:")
if worker_error is not None or results["timeout"] > 0:
    print("  ✓ 复现成功——并发同步请求数超过连接池容量时，后到者（包括"
          "worker 的 claim_next）会阻塞至 pool_timeout 并抛 QueuePool "
          "TimeoutError，与生产日志一致。")
else:
    print("  ✗ 未复现，假设需修正。")
