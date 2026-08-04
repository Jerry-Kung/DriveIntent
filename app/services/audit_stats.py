"""V1.4 后端审计：只读聚合统计服务。

数据源为业务既有落库的 api_job 与 llm_call_log 两表，本模块只查询、
不写库，业务模块不依赖本模块。时间口径：库内为 UTC 朴素时间，分桶按
东八区自然天/小时（+8 小时转换）。生产 MySQL、测试 SQLite，分桶表达
式按方言分派。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, text

from app.models import ApiJob, LlmCallLog

TZ8 = timezone(timedelta(hours=8))


def utc_range(granularity: str, span: int,
              now_utc: datetime | None = None) -> tuple[datetime, datetime]:
    """最近 span 个东八区自然天/小时（含当前所在桶）的 UTC 边界 [start, end)。"""
    now = (now_utc or datetime.utcnow()).replace(tzinfo=timezone.utc)
    local = now.astimezone(TZ8)
    if granularity == "day":
        end_local = (local + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        start_local = end_local - timedelta(days=span)
    else:
        end_local = local.replace(
            minute=0, second=0, microsecond=0) + timedelta(hours=1)
        start_local = end_local - timedelta(hours=span)

    def to_utc(d: datetime) -> datetime:
        return d.astimezone(timezone.utc).replace(tzinfo=None)

    return to_utc(start_local), to_utc(end_local)


def _bucket(db, col, granularity: str):
    """UTC 时间列 → 东八区天/小时桶标签的 SQL 表达式（按方言分派）。"""
    fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m-%d %H:00"
    if db.get_bind().dialect.name == "mysql":
        return func.date_format(
            func.date_add(col, text("INTERVAL 8 HOUR")), fmt)
    return func.strftime(fmt, func.datetime(col, "+8 hours"))
