"""清理 api_job 存量大 payload（V1.4.4 阶段二）。

背景：`api_job` 表 6408MB / 10093 行，其中 request_payload 合计 9520MB，
result 仅 78MB——表体积的 99% 是 base64 截图。V1.4.4 起截图不再入库，本
脚本清理历史存量。

安全边界（严格遵守，勿放宽）：
  - **只处理终态行**（success / partial / failed）。pending / running 绝不触碰
    ——按"先跑完再清理"决策，pending 是待处理业务数据（560 个大 payload 行）。
  - 只清空 payload 中的 base64 截图字段，保留 accounts 其余结构。
  - **绝不触碰 result / status / 时间戳 / progress_***——/audit 页面依赖
    这些列做统计（10093 行，2026-07-24 起）。
  - 分批提交，避免长事务与主从延迟。
  - 默认 dry-run，显式 --apply 才写入。

用法：
    python scripts/cleanup_api_job_payload.py                # 预演
    python scripts/cleanup_api_job_payload.py --apply        # 执行
    python scripts/cleanup_api_job_payload.py --apply --batch 100

执行完成后另需回收物理空间（选业务低峰，会锁表）：
    OPTIMIZE TABLE api_job;
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings

TERMINAL = ("success", "partial", "failed")
SCREENSHOT_FIELD = "account_homepage_screenshot"
# 低于该体积的行清理收益不抵开销，跳过
MIN_BYTES = 100 * 1024


def _strip(payload: dict) -> tuple[dict, bool]:
    """清空 accounts 中的 base64 截图，返回（新 payload, 是否有变更）。"""
    accounts = payload.get("accounts")
    if not isinstance(accounts, list):
        return payload, False
    changed = False
    out = []
    for acc in accounts:
        if isinstance(acc, dict) and acc.get(SCREENSHOT_FIELD):
            acc = dict(acc, **{SCREENSHOT_FIELD: ""})
            changed = True
        out.append(acc)
    return dict(payload, accounts=out), changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="真正写入；缺省为 dry-run")
    ap.add_argument("--batch", type=int, default=200,
                    help="每批处理行数（默认 200）")
    ap.add_argument("--limit", type=int, default=0,
                    help="最多处理多少行，0 为不限")
    args = ap.parse_args()

    engine = create_engine(settings.db_url, pool_size=2, max_overflow=0,
                           pool_pre_ping=True)
    Session = sessionmaker(bind=engine)

    mode = "执行" if args.apply else "预演（dry-run，不写入）"
    print("=" * 72)
    print(f"api_job 存量 payload 清理 —— {mode}")
    print("-" * 72)

    with Session() as s:
        # 摸底：确认待清理规模，并确认 pending/running 不在范围内
        rows = s.execute(text("""
            SELECT status, COUNT(*), ROUND(SUM(LENGTH(request_payload))
                   /1024/1024) mb
            FROM api_job
            WHERE request_payload IS NOT NULL
              AND job_type = 'profile_analysis'
              AND LENGTH(request_payload) > :min_bytes
            GROUP BY status
        """), {"min_bytes": MIN_BYTES}).fetchall()
        print("（仅统计 profile_analysis；comment_screening 的大 payload "
              "是评论正文，属业务数据不清理）")
        print(f"{'status':<12}{'行数':>8}{'payload 合计':>14}   处理")
        total_target = 0
        for st, n, mb in rows:
            will = "清理" if st in TERMINAL else "跳过（业务数据）"
            if st in TERMINAL:
                total_target += n
            print(f"{st:<12}{n:>8}{mb or 0:>11} MB   {will}")
        print("-" * 72)
        print(f"待清理终态行：{total_target}")

        if total_target == 0:
            print("无待清理数据。")
            return 0

        # 不加 ORDER BY：测试库实测会触发 (1038, 'Out of sort memory')——
        # 该表单行可达 25MB，排序缓冲撑不住；清理顺序也无业务意义。
        # 限定 profile_analysis：只有它带 accounts[].截图，comment_screening
        # 的大 payload 是评论正文（业务数据，不清理）
        ids = [r[0] for r in s.execute(text("""
            SELECT id FROM api_job
            WHERE status IN :terminal
              AND job_type = 'profile_analysis'
              AND request_payload IS NOT NULL
              AND LENGTH(request_payload) > :min_bytes
        """), {"terminal": TERMINAL, "min_bytes": MIN_BYTES}).fetchall()]

    if args.limit:
        ids = ids[:args.limit]

    print()
    cleaned = skipped = 0
    freed = 0
    for i in range(0, len(ids), args.batch):
        chunk = ids[i:i + args.batch]
        with Session() as s:
            for jid in chunk:
                row = s.execute(text(
                    "SELECT request_payload, status FROM api_job WHERE id=:i"),
                    {"i": jid}).fetchone()
                if row is None:
                    continue
                payload, status = row
                # 二次确认状态：摸底与执行之间作业可能被 worker 改状态
                if status not in TERMINAL:
                    skipped += 1
                    continue
                # 原生 SQL 取 JSON 列得到的是字符串，需自行解析
                if isinstance(payload, (str, bytes)):
                    try:
                        payload = json.loads(payload)
                    except ValueError:
                        skipped += 1
                        continue
                if not isinstance(payload, dict):
                    skipped += 1
                    continue
                new_payload, changed = _strip(payload)
                if not changed:
                    skipped += 1
                    continue
                before = len(json.dumps(payload, ensure_ascii=False))
                after = json.dumps(new_payload, ensure_ascii=False)
                freed += before - len(after)
                cleaned += 1
                if args.apply:
                    s.execute(text(
                        "UPDATE api_job SET request_payload = :p "
                        "WHERE id = :i AND status IN :terminal"),
                        {"p": after, "i": jid, "terminal": TERMINAL})
            if args.apply:
                s.commit()
        print(f"  进度 {min(i + args.batch, len(ids))}/{len(ids)}  "
              f"已清理 {cleaned}  跳过 {skipped}  "
              f"释放约 {freed / 1024 / 1024:.0f}MB")

    print("-" * 72)
    print(f"完成：清理 {cleaned} 行，跳过 {skipped} 行，"
          f"释放约 {freed / 1024 / 1024:.0f}MB")
    if not args.apply:
        print()
        print("这是预演，未写入任何数据。确认无误后加 --apply 执行。")
    else:
        print()
        print("物理空间需 OPTIMIZE TABLE 才能回收（会锁表，选业务低峰）：")
        print("    OPTIMIZE TABLE api_job;")
    print("=" * 72)
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
