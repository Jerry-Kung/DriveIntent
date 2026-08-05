"""诊断：直连测试环境 MySQL，查看连接占用真相与作业积压。

用户已授权访问 .env 中配置的测试库。只读查询，不做任何写操作。
服务器时间 GMT+0，数据库时间 GMT+8，注意换算。
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

from app.config import settings


def main():
    # 独立小连接池，避免干扰观测对象
    engine = create_engine(settings.db_url, pool_size=2, max_overflow=0,
                           pool_pre_ping=True)
    with engine.connect() as c:
        print("=" * 78)
        print("1) MySQL 连接上限与实际占用")
        print("-" * 78)
        for var in ("max_connections", "wait_timeout", "interactive_timeout"):
            v = c.execute(text(
                f"SHOW VARIABLES LIKE '{var}'")).fetchone()
            print(f"  {v[0]:<24} = {v[1]}")
        for st in ("Threads_connected", "Threads_running",
                   "Max_used_connections"):
            v = c.execute(text(f"SHOW STATUS LIKE '{st}'")).fetchone()
            print(f"  {v[0]:<24} = {v[1]}")

        print()
        print("=" * 78)
        print("2) 当前连接明细（按状态/命令分组）")
        print("-" * 78)
        rows = c.execute(text("""
            SELECT user, host, db, command, time, state, LEFT(info, 60)
            FROM information_schema.processlist
            ORDER BY time DESC
        """)).fetchall()
        print(f"  processlist 总行数 = {len(rows)}")
        by_cmd = Counter(r[3] for r in rows)
        print(f"  按 command 分组: {dict(by_cmd)}")
        by_user = Counter(r[0] for r in rows)
        print(f"  按 user 分组   : {dict(by_user)}")
        print()
        print("  最久的 12 条连接：")
        print(f"  {'user':<14}{'db':<24}{'cmd':<10}{'time(s)':>8}  state/info")
        for r in rows[:12]:
            info = (r[6] or "").replace("\n", " ")[:40]
            print(f"  {str(r[0]):<14}{str(r[2]):<24}{str(r[3]):<10}"
                  f"{r[4]:>8}  {str(r[5])[:18]} {info}")

        print()
        print("=" * 78)
        print("3) 长事务与锁等待")
        print("-" * 78)
        trx = c.execute(text("""
            SELECT trx_id, trx_state, trx_started,
                   TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS age_s,
                   trx_rows_locked, LEFT(trx_query, 50)
            FROM information_schema.innodb_trx
            ORDER BY trx_started
        """)).fetchall()
        if not trx:
            print("  无活跃事务")
        for t in trx:
            print(f"  trx={t[0]} state={t[1]} age={t[3]}s "
                  f"locked_rows={t[4]} q={t[5]}")

        print()
        print("=" * 78)
        print("4) api_job 作业状态分布（东八区口径）")
        print("-" * 78)
        rows = c.execute(text("""
            SELECT status, job_type, COUNT(*) AS n,
                   MIN(created_at) AS oldest, MAX(created_at) AS newest
            FROM api_job GROUP BY status, job_type ORDER BY n DESC
        """)).fetchall()
        print(f"  {'status':<12}{'type':<20}{'count':>8}  "
              f"{'oldest(UTC)':<21}{'newest(UTC)'}")
        for r in rows:
            print(f"  {r[0]:<12}{r[1]:<20}{r[2]:>8}  "
                  f"{str(r[3]):<21}{str(r[4])}")

        print()
        print("  running 作业的停滞情况：")
        rows = c.execute(text("""
            SELECT id, job_type, progress_done, progress_total,
                   TIMESTAMPDIFF(MINUTE, updated_at, UTC_TIMESTAMP())
                       AS stale_min
            FROM api_job WHERE status = 'running'
            ORDER BY updated_at LIMIT 15
        """)).fetchall()
        if not rows:
            print("    无 running 作业")
        for r in rows:
            print(f"    {r[0][:8]} {r[1]:<20} 进度={r[2]}/{r[3]} "
                  f"停滞={r[4]}min")

        print()
        print("=" * 78)
        print("5) 表体积与大 payload 残留")
        print("-" * 78)
        rows = c.execute(text("""
            SELECT table_name,
                   ROUND((data_length + index_length)/1024/1024) AS mb,
                   table_rows
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
            ORDER BY (data_length + index_length) DESC LIMIT 8
        """)).fetchall()
        for r in rows:
            print(f"  {r[0]:<28}{r[1]:>8} MB   ~{r[2]} 行")

        big = c.execute(text("""
            SELECT COUNT(*), ROUND(AVG(LENGTH(request_payload))/1024),
                   ROUND(MAX(LENGTH(request_payload))/1024/1024, 1)
            FROM api_job
            WHERE request_payload IS NOT NULL
              AND LENGTH(request_payload) > 512000
        """)).fetchone()
        print(f"\n  request_payload > 500KB 的行数 = {big[0]}"
              f"  平均 {big[1]}KB  最大 {big[2]}MB")

        big_r = c.execute(text("""
            SELECT COUNT(*), ROUND(AVG(LENGTH(result))/1024),
                   ROUND(MAX(LENGTH(result))/1024/1024, 1)
            FROM api_job WHERE result IS NOT NULL
        """)).fetchone()
        print(f"  result 非空行数 = {big_r[0]}"
              f"  平均 {big_r[1]}KB  最大 {big_r[2]}MB")

        print("=" * 78)
    engine.dispose()


if __name__ == "__main__":
    main()
