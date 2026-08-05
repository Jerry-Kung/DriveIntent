"""诊断：确认"大 payload 认领 + 同步阻塞"如何抽干连接池并冻结事件循环。

真实测量（scripts/diag_db_truth.py + 远程读取实测）：
  - pending 队列 538 个 profile_analysis，payload 平均 12.98MB、最大 25MB
  - 远程 MySQL 读一条 22.7MB payload 实测耗时 3233ms
  - MySQL 侧 Max_used_connections=152 > max_connections=151（已打满）

链路推演（本脚本验证其中的可复现部分）：
  1. worker 认领作业时 claim_next_job_detached 必须整条读出 payload（12.98MB）
     —— 这是同步 IO，在事件循环里执行，耗时约 3s。
  2. 这 3s 内事件循环被**完全冻住**：其他 11 个 worker 协程、reaper、
     以及所有 HTTP 请求处理都无法推进（已由 diag_conn_per_request.py Q3 证实）。
  3. 12 个 worker 协程各自轮流做这件事 → 事件循环长期处于冻结状态。
  4. 冻结期间 FastAPI 线程池里的轮询请求持续取连接却得不到调度归还，
     连接堆积；worker 自己也抢不到连接 → QueuePool timeout。
  5. 超时是同步阻塞 30s，进一步冻住 loop → 报错呈现 30.00s 精确串行间隔。

本脚本量化步骤 1-2：同步大读取对事件循环的冻结时长。
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

from app.config import settings


async def main():
    engine = create_engine(settings.db_url, pool_size=3, max_overflow=0,
                           pool_pre_ping=True)

    # 找一条大 payload 作业
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT id FROM api_job WHERE LENGTH(request_payload) > 10000000 "
            "LIMIT 1")).fetchone()
        if row is None:
            print("库中无 >10MB payload，无法复现")
            return
        jid = row[0]
        size_mb = c.execute(text(
            "SELECT LENGTH(request_payload)/1024/1024 FROM api_job "
            "WHERE id=:i"), {"i": jid}).scalar()

    ticks = {"n": 0}
    gaps = []

    async def heartbeat():
        """事件循环健康探针：正常每 10ms 一跳。记录最大停顿。"""
        last = time.monotonic()
        try:
            while True:
                await asyncio.sleep(0.01)
                now = time.monotonic()
                gaps.append(now - last)
                last = now
                ticks["n"] += 1
        except asyncio.CancelledError:
            pass

    hb = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.3)
    base = ticks["n"]
    gaps.clear()

    print("=" * 74)
    print("同步读取大 payload 对事件循环的影响")
    print("-" * 74)
    print(f"目标作业 {jid[:8]}  payload = {size_mb:.1f}MB")
    print()

    # 模拟 worker 认领：在事件循环里做同步大读取
    t0 = time.monotonic()
    with engine.connect() as c:
        c.execute(text("SELECT request_payload FROM api_job WHERE id=:i"),
                  {"i": jid}).fetchone()
    blocked = time.monotonic() - t0

    await asyncio.sleep(0.05)
    hb.cancel()

    gained = ticks["n"] - base
    expected = int(blocked / 0.01)
    max_gap = max(gaps) if gaps else 0

    print(f"同步读取耗时          : {blocked * 1000:.0f}ms")
    print(f"该期间心跳实际次数    : {gained}")
    print(f"该期间心跳应有次数    : ~{expected}")
    print(f"事件循环最大单次停顿  : {max_gap * 1000:.0f}ms")
    print("-" * 74)
    if max_gap > blocked * 0.8:
        print("!! 事件循环在整个读取期间被完全冻住。")
        print()
        print("   API_WORKER_CONCURRENCY=6 + WORKER_CONCURRENCY=6 = 12 个协程，")
        print("   每个认领作业都要做一次这样的同步大读取。")
        print(f"   pending 队列有 538 个 profile_analysis（平均 12.98MB），")
        print("   事件循环因此长期处于冻结状态 —— 这解释了：")
        print("     · 07:33:33 后 LLM 调用完全归零")
        print("     · 报错呈 30.00s 精确串行间隔（超时也是同步阻塞）")
        print("     · 07:35:03 五个请求同一毫秒齐发（解冻瞬间集体恢复）")
    else:
        print("事件循环未被显著冻结，需重新审视假设")
    print("=" * 74)
    engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
