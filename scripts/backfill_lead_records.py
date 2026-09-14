"""
V1.10.1 补丁：把历史 api_job.result 回填到 lead_record 汇总表。

- 背景：线索列表页改读 lead_record（api_job.result 的物化派生表）。新增
  作业在终态落库时同事务写入，历史作业需本脚本回填一次。
- 幂等：以 (job_id, idx) 为主键做 upsert，可重复执行；中断后重跑会从
  头扫描但不会产生重复行，也不会覆盖已写入的正确数据。
- 可续跑：按作业 finished_at 升序分批处理；重复执行代价只是重扫一遍。
- 未回填期间列表仍可用：服务以就绪标记 data/lead_record_ready 为切换判据，
  标记不在时走原 JSON 展开路径，因此本脚本可在服务运行中执行，无需停机。
- 完备性自检：以"还有没有未被回填的作业"为判据（NOT EXISTS），不受回填
  期间新完成作业造成的行数漂移影响；通过后才写就绪标记。
- 长任务健壮性：连接在数分钟空闲后可能被中间链路回收（V1.10.1 实测：脚本
  跑到结尾自检时报 InterfaceError (0, '')，数据已全部写入，仅连接失效）。
  本脚本每次使用连接前探活，失效则重建并重放当批——写操作是幂等 upsert，
  重放安全，故单次链路中断不会让整个回填失败。
- 用法：
    python scripts/backfill_lead_records.py             # 全量回填
    python scripts/backfill_lead_records.py --limit 200 # 只处理最早 200 个作业
    python scripts/backfill_lead_records.py --dry-run   # 只统计不写库
    python scripts/backfill_lead_records.py --chunk 100 # 缩小单条 INSERT
- 数据库连接从 .env 读取。
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pymysql
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.services.lead_records import grade_of  # noqa: E402

load_dotenv()

DB_NAME = os.environ["DB_NAME"]

_JOB_FILTER = ("job_type='profile_analysis' AND result IS NOT NULL "
               "AND status IN ('success','partial')")

_COLUMNS = ["job_id", "idx", "account_uid", "grade", "value_score",
            "is_car_owner", "has_purchase_intent", "intent_models",
            "intent_model_category", "profile_summary", "profile_tags",
            "analysis", "processed_at", "error", "finished_at"]


def _as_bool(value):
    return value if isinstance(value, bool) else None


def _as_int(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def build_rows(job_id: str, result, lead_grades, finished_at,
               json_dumps) -> list[tuple]:
    """把单个作业的结果展开成待写入的行元组（与 lead_record 列一一对应）。"""
    if not isinstance(result, dict):
        return []
    results = result.get("results") or []
    if not isinstance(results, list):
        return []
    grades = lead_grades if isinstance(lead_grades, list) else []
    rows = []
    for index, acct in enumerate(results):
        if not isinstance(acct, dict):
            continue
        internal = grades[index] if index < len(grades) else None
        rows.append((
            job_id, index,
            str(acct.get("account_uid") or "")[:256],
            grade_of(acct, internal),
            _as_int(acct.get("value_score")),
            _as_bool(acct.get("is_car_owner")),
            _as_bool(acct.get("has_purchase_intent")),
            json_dumps(acct.get("intent_models") or []),
            acct.get("intent_model_category"),
            acct.get("profile_summary") or "",
            json_dumps(acct.get("profile_tags") or []),
            acct.get("analysis") or "",
            acct.get("processed_at"),
            acct.get("error"),
            finished_at,
        ))
    return rows


def write_ready_marker() -> None:
    """写入就绪标记；实际写入逻辑在应用服务层。

    标记只会在自检通过后出现，故服务不会读到"回填到一半却已就绪"的状态。
    复用服务层函数而非在此重复实现，避免两处路径口径分叉。
    """
    from app.services.lead_results import write_ready_marker as _write
    _write()
    print(f"就绪标记已写入：{Path(settings.lead_record_ready_marker).resolve()}")


def _connect():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=DB_NAME,
        charset="utf8mb4",
    )


def _ping(conn):
    """探活；连接已失效则抛出，由 _with_retry 重建。

    reconnect=False：pymysql 的自动重连会丢弃未提交事务且不让调用方感知，
    而本脚本要求写入边界显式可控，故一律由调用方重建连接。
    """
    conn.ping(reconnect=False)


def _with_retry(conn, action, what, attempts=3):
    """执行 action(conn)，返回 (结果, 可用的连接)。

    连接失效时重建并重试。失效的 connection 对象不可再用，故必须把新连接
    回传给调用方持有。写操作是幂等 upsert（主键 job_id+idx），重放同一批
    不会产生重复行，故重试安全。
    """
    for attempt in range(1, attempts + 1):
        try:
            _ping(conn)
            return action(conn), conn
        except pymysql.err.InterfaceError as e:
            if attempt >= attempts:
                raise
            print(f"  连接失效（{what}，第 {attempt} 次尝试），重连后重试… {e}",
                  flush=True)
            try:
                conn.close()
            except Exception:
                pass
            time.sleep(2 * attempt)
            conn = _connect()
    raise RuntimeError("unreachable")


def _fetch_batch(conn, last_key, take):
    """按键 (finished_at, id) 游标取一批作业，保证不重不漏。"""
    with conn.cursor() as cur:
        if last_key[0] is None:
            cur.execute(
                f"SELECT id, result, lead_grades, finished_at "
                f"FROM api_job WHERE {_JOB_FILTER} "
                f"ORDER BY finished_at, id LIMIT %s", (take,))
        else:
            cur.execute(
                f"SELECT id, result, lead_grades, finished_at "
                f"FROM api_job WHERE {_JOB_FILTER} "
                f"AND (finished_at, id) > (%s, %s) "
                f"ORDER BY finished_at, id LIMIT %s",
                (last_key[0], last_key[1], take))
        return cur.fetchall()


def _upsert(conn, insert_sql, placeholder, rows, chunk_size):
    """分块幂等写入。单条语句行数过多会让语句体积膨胀（实测 500 行最长分析
    文本约 3.4 MB，max_allowed_packet 一般 64 MB，风险不大但没必要）。"""
    with conn.cursor() as cur:
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i:i + chunk_size]
            cur.execute(
                insert_sql.format(values=", ".join([placeholder] * len(chunk))),
                [v for row in chunk for v in row])
    conn.commit()


def _self_check(conn):
    """完备性自检，返回 (汇总行数, 口径行数, 未被回填的作业数)。

    核心指标是"未被回填的作业数"而非行数差：行数口径会被回填/服务运行期间
    新完成的作业持续扰动（实测一次运行中漂移 178 行），而 NOT EXISTS 直接
    回答"还有没有漏掉的作业"，不受漂移影响。
    """
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM lead_record")
        in_records = cur.fetchone()[0]
        cur.execute(f"SELECT COALESCE(SUM(JSON_LENGTH(result, '$.results')), 0) "
                    f"FROM api_job WHERE {_JOB_FILTER}")
        expected = int(cur.fetchone()[0])
        cur.execute(
            f"SELECT COUNT(*) FROM api_job j WHERE {_JOB_FILTER} "
            f"AND NOT EXISTS (SELECT 1 FROM lead_record r WHERE r.job_id = j.id)")
        unfilled = cur.fetchone()[0]
    return in_records, expected, unfilled


def _decode(value):
    """JSON 列取回后可能是 str/bytes（取决于驱动与列类型），统一成对象。"""
    if isinstance(value, (bytes, bytearray)):
        return json.loads(value.decode("utf-8"))
    if isinstance(value, str):
        return json.loads(value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="回填 lead_record 汇总表")
    parser.add_argument("--batch", type=int, default=50,
                        help="每批处理的作业数（默认 50）")
    parser.add_argument("--chunk", type=int, default=200,
                        help="单条 INSERT 的语句行数上限（默认 200）")
    parser.add_argument("--limit", type=int, default=0,
                        help="最多处理多少个作业（0 表示不限）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只统计将写入的行数，不写库")
    args = parser.parse_args()

    def dumps(value):
        return json.dumps(value, ensure_ascii=False)

    placeholder = "(" + ", ".join(["%s"] * len(_COLUMNS)) + ")"
    # upsert：已存在的行按新值覆盖，保证重跑结果一致
    updates = ", ".join(f"`{c}`=VALUES(`{c}`)" for c in _COLUMNS
                        if c not in ("job_id", "idx"))
    insert_sql = (f"INSERT INTO lead_record ({', '.join('`' + c + '`' for c in _COLUMNS)}) "
                  f"VALUES {{values}} ON DUPLICATE KEY UPDATE {updates}")

    jobs_done = rows_done = 0
    started = time.time()
    last_key = (None, None)       # (finished_at, id) 游标
    conn = _connect()
    try:
        while True:
            take = args.batch
            if args.limit:
                take = min(take, args.limit - jobs_done)
                if take <= 0:
                    break
            batch, conn = _with_retry(
                conn, lambda c: _fetch_batch(c, last_key, take), "读取作业")
            if not batch:
                break
            all_rows = []
            for job_id, result, lead_grades, finished_at in batch:
                all_rows += build_rows(job_id, _decode(result),
                                       _decode(lead_grades), finished_at, dumps)
            last_key = (str(batch[-1][3]), batch[-1][0])
            jobs_done += len(batch)
            if not args.dry_run and all_rows:
                _, conn = _with_retry(
                    conn,
                    lambda c: _upsert(c, insert_sql, placeholder, all_rows,
                                      args.chunk),
                    "写入汇总行")
            rows_done += len(all_rows)
            elapsed = time.time() - started
            print(f"[{elapsed:6.1f}s] 作业 {jobs_done} 个，行 {rows_done} 条"
                  f"（最近处理：{batch[-1][3]}）", flush=True)

        print(f"完成：作业 {jobs_done} 个，行 {rows_done} 条，"
              f"耗时 {time.time() - started:.1f}s"
              + ("（dry-run，未写库）" if args.dry_run else ""))
        if args.dry_run:
            return
        # 完备性自检。判据是"还有没有未被回填的作业"：NOT EXISTS 不受回填
        # 期间新完成作业造成的行数漂移影响，也漏不掉任何作业。行数差仅作参考。
        (in_records, expected, unfilled), conn = _with_retry(
            conn, _self_check, "完备性自检")
        print(f"自检：汇总表 {in_records} 行，当前 api_job 口径 {expected} 行，"
              f"差 {expected - in_records} 行（负数表示汇总表多出，"
              f"属回填期间新写入的作业）；未被回填的作业 {unfilled} 个")
        if unfilled == 0:
            write_ready_marker()
            print("就绪标记已写入，列表页切换到汇总表路径（快路径）。")
        else:
            print(f"[自检未通过] 还有 {unfilled} 个作业未回填。")
            print("  这通常意味着回填中途失败。请重跑本脚本（幂等，会补齐缺失行）；"
                  "在此之前列表页走回退路径，结果完整但较慢。")
            sys.exit(1)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
