"""
V1.10.1 补丁：把历史 api_job.result 回填到 lead_record 汇总表。

- 背景：线索列表页改读 lead_record（api_job.result 的物化派生表）。新增
  作业在终态落库时同事务写入，历史作业需本脚本回填一次。
- 幂等：以 (job_id, idx) 为主键做 upsert，可重复执行；中断后重跑会从
  头扫描但不会产生重复行，也不会覆盖已写入的正确数据。
- 可续跑：按作业 finished_at 升序分批处理；重复执行代价只是重扫一遍。
- 未回填期间列表仍可用：汇总表为空时服务自动回退原 JSON 展开路径，因此
  本脚本可在服务运行中执行，无需停机。
- **迁移期注意**：汇总表一旦有数据，服务即切换到汇总表路径。本脚本按
  finished_at 升序回填，因此**回填进行中列表是不完整的**（只含已回填的旧
  作业）。脚本结束时打印完备性自检结果；在自检通过前请勿把列表当作全量
  依据。全量回填实测约 3 分钟。
- 用法：
    python scripts/backfill_lead_records.py            # 全量回填
    python scripts/backfill_lead_records.py --limit 200 # 只处理最早 200 个作业
    python scripts/backfill_lead_records.py --dry-run   # 只统计不写库
- 数据库连接从 .env 读取。
"""
import argparse
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
    """写入就绪标记后立刻提交可见性；实际写入逻辑在应用服务层。

    标记只会在自检通过后出现，故服务不会读到"回填到一半却已就绪"的状态。
    复用服务层函数而非在此重复实现，避免两处路径口径分叉。
    """
    from app.services.lead_results import write_ready_marker as _write
    _write()
    print(f"就绪标记已写入：{Path(settings.lead_record_ready_marker).resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="回填 lead_record 汇总表")
    parser.add_argument("--batch", type=int, default=50,
                        help="每批处理的作业数（默认 50）")
    parser.add_argument("--limit", type=int, default=0,
                        help="最多处理多少个作业（0 表示不限）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只统计将写入的行数，不写库")
    args = parser.parse_args()

    import json as _json

    def dumps(value):
        return _json.dumps(value, ensure_ascii=False)

    conn = pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=DB_NAME,
        charset="utf8mb4",
    )

    placeholder = "(" + ", ".join(["%s"] * len(_COLUMNS)) + ")"
    # upsert：已存在的行按新值覆盖，保证重跑结果一致
    updates = ", ".join(f"`{c}`=VALUES(`{c}`)" for c in _COLUMNS
                        if c not in ("job_id", "idx"))
    insert_sql = (f"INSERT INTO lead_record ({', '.join('`' + c + '`' for c in _COLUMNS)}) "
                  f"VALUES {{values}} ON DUPLICATE KEY UPDATE {updates}")

    processed = jobs_done = rows_done = 0
    started = time.time()
    last_key = (None, None)       # (finished_at, id) 游标，保证分页不重不漏
    with conn:
        while True:
            take = args.batch
            if args.limit:
                take = min(take, args.limit - jobs_done)
                if take <= 0:
                    break
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
                batch = cur.fetchall()
            if not batch:
                break
            all_rows = []
            for job_id, result, lead_grades, finished_at in batch:
                if isinstance(result, (bytes, bytearray)):
                    result = _json.loads(result.decode("utf-8"))
                elif isinstance(result, str):
                    result = _json.loads(result)
                if isinstance(lead_grades, (bytes, bytearray, str)):
                    lead_grades = _json.loads(lead_grades)
                all_rows += build_rows(job_id, result, lead_grades, finished_at,
                                       dumps)
            last_key = (str(batch[-1][3]), batch[-1][0])
            jobs_done += len(batch)
            if not args.dry_run and all_rows:
                with conn.cursor() as cur:
                    # 单条语句行数过多会超出 max_allowed_packet，按 500 行切块
                    for i in range(0, len(all_rows), 500):
                        chunk = all_rows[i:i + 500]
                        cur.execute(
                            insert_sql.format(
                                values=", ".join([placeholder] * len(chunk))),
                            [v for row in chunk for v in row])
                conn.commit()
            rows_done += len(all_rows)
            processed += len(batch)
            elapsed = time.time() - started
            print(f"[{elapsed:6.1f}s] 作业 {jobs_done} 个，行 {rows_done} 条"
                  f"（最近处理：{batch[-1][3]}）", flush=True)
    print(f"完成：作业 {jobs_done} 个，行 {rows_done} 条，耗时 {time.time() - started:.1f}s"
          + ("（dry-run，未写库）" if args.dry_run else ""))
    if args.dry_run:
        return
    # 完备性自检：汇总表行数与 api_job 口径对比。回填期间新完成的作业会
    # 造成小幅正差（那部分由 worker 终态已写入汇总表），故允许汇总表略多。
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM lead_record")
        in_records = cur.fetchone()[0]
        cur.execute(f"SELECT COALESCE(SUM(JSON_LENGTH(result, '$.results')), 0) "
                    f"FROM api_job WHERE {_JOB_FILTER}")
        expected = int(cur.fetchone()[0])
    missing = expected - in_records
    if missing <= 0:
        print(f"自检通过：汇总表 {in_records} 行，api_job 口径 {expected} 行。")
        write_ready_marker()
        print("就绪标记已写入，列表页即刻切换到汇总表路径（快路径）。")
    else:
        print(f"[自检未通过] 汇总表 {in_records} 行，api_job 口径 {expected} 行，"
              f"缺 {missing} 行。")
        print("  中途失败时请重跑本脚本（幂等，会补齐缺失行）；"
              "在此之前列表页走回退路径，结果完整但较慢，请勿据此判断性能。")


if __name__ == "__main__":
    main()
