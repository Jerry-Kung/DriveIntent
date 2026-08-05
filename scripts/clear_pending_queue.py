"""清空 api_job 待处理队列（V1.4.4 存量处置，一次性运维脚本）。

背景：V1.4.4 生效前提交的 pending profile_analysis 作业全部带内联 base64
（595 行 / 约 7.5GB）。用户决策：不再逐个识图消费，直接清空待处理队列。

安全边界（严格遵守，勿放宽）：
  - 只处理 pending 行（含 pending 的 comment_screening）。
    running / success / partial / failed 一律不触碰。
  - pending 行不是业务终态，清空即丢弃其请求负载与排队资格；
    清空后 `/audit` 的任务量口径会缺少这批 pending（此前也未计入
    success/partial/failed 各桶，仅少计数 595 笔）。
  - 默认 dry-run，显式 --apply 才写入。
  - 不 ORDER BY（行可达 25MB，排序缓冲撑不住 1038）。

用法：
    python scripts/clear_pending_queue.py                # 预演
    python scripts/clear_pending_queue.py --apply        # 执行
    python scripts/clear_pending_queue.py --apply --batch 100

物理空间需 OPTIMIZE TABLE api_job 才能回收（会锁表，选业务低峰）。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="真正写入；缺省为 dry-run")
    ap.add_argument("--batch", type=int, default=200,
                    help="每批处理行数（默认 200）")
    args = ap.parse_args()

    engine = create_engine(settings.db_url, pool_size=2, max_overflow=0,
                           pool_pre_ping=True)
    Session = sessionmaker(bind=engine)

    mode = "执行" if args.apply else "预演（dry-run，不写入）"
    print("=" * 72)
    print(f"api_job 待处理队列清空 —— {mode}")
    print("-" * 72)

    with Session() as s:
        rows = s.execute(text("""
            SELECT job_type, COUNT(*) AS n,
                   ROUND(SUM(LENGTH(request_payload))/1024/1024) AS mb
            FROM api_job
            WHERE status = 'pending'
            GROUP BY job_type
        """)).fetchall()
        total = 0
        for jt, n, mb in rows:
            total += n
            print(f"  {jt:<20}{n:>6} 行  {mb or 0:>7}MB")
        print(f"  合计待清空 pending 行：{total}")

        if total == 0:
            print("  无待清空数据。")
            return 0

        ids = [r[0] for r in s.execute(text("""
            SELECT id FROM api_job WHERE status = 'pending'
        """)).fetchall()]

    deleted = 0
    for i in range(0, len(ids), args.batch):
        chunk = ids[i:i + args.batch]
        with Session() as s:
            if args.apply:
                s.execute(text(
                    "DELETE FROM api_job WHERE id IN :ids AND status='pending'"),
                    {"ids": chunk})
                s.commit()
            deleted += len(chunk)
        print(f"  进度 {min(i + args.batch, len(ids))}/{len(ids)}")

    print("-" * 72)
    print(f"完成：删除 {deleted} 行 pending 作业。")
    if not args.apply:
        print()
        print("这是预演，未写入任何数据。确认无误后加 --apply 执行。")
    else:
        print()
        print("物理空间需 OPTIMIZE TABLE 才能回收（会锁表，选业务低峰）：")
        print("    OPTIMIZE TABLE api_job;")
        print()
        print("提示：生产服务在另一台机器，若那台仍未部署 V1.4.4 的")
        print("Worker，本机清理后队列为空、后续新作业也不会被消费。")
    print("=" * 72)
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
