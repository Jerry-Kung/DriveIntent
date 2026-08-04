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


def _empty_job_row(bucket: str, job_type: str) -> dict:
    return {"bucket": bucket, "job_type": job_type,
            "received": 0, "success": 0, "partial": 0, "failed": 0}


def job_stats(db, granularity: str,
              start_utc: datetime, end_utc: datetime) -> list[dict]:
    """任务量明细：接收量按 created_at 分桶，完成量按 finished_at 分桶。"""
    rows: dict[tuple[str, str], dict] = {}
    created = _bucket(db, ApiJob.created_at, granularity)
    for bucket, job_type, n in (
            db.query(created, ApiJob.job_type, func.count())
            .filter(ApiJob.created_at >= start_utc,
                    ApiJob.created_at < end_utc)
            .group_by(created, ApiJob.job_type)):
        rows.setdefault((bucket, job_type),
                        _empty_job_row(bucket, job_type))["received"] = n
    finished = _bucket(db, ApiJob.finished_at, granularity)
    for bucket, job_type, status, n in (
            db.query(finished, ApiJob.job_type, ApiJob.status, func.count())
            .filter(ApiJob.finished_at.isnot(None),
                    ApiJob.finished_at >= start_utc,
                    ApiJob.finished_at < end_utc)
            .group_by(finished, ApiJob.job_type, ApiJob.status)):
        row = rows.setdefault((bucket, job_type),
                              _empty_job_row(bucket, job_type))
        if status in ("success", "partial", "failed"):
            row[status] = n
    return sorted(rows.values(),
                  key=lambda r: (r["bucket"], r["job_type"]), reverse=True)


def llm_stats(db, granularity: str,
              start_utc: datetime, end_utc: datetime) -> list[dict]:
    """LLM 消耗明细：每条 llm_call_log 为一次真实请求（含重试与失败）。"""
    bucket = _bucket(db, LlmCallLog.created_at, granularity)
    query = (
        db.query(bucket, LlmCallLog.skill_id, LlmCallLog.model_name,
                 func.count(),
                 func.count(LlmCallLog.error),  # COUNT(col) 只计非空 → 失败数
                 func.coalesce(func.sum(LlmCallLog.prompt_tokens), 0),
                 func.coalesce(func.sum(LlmCallLog.completion_tokens), 0),
                 func.avg(LlmCallLog.duration_ms))
        .filter(LlmCallLog.created_at >= start_utc,
                LlmCallLog.created_at < end_utc)
        .group_by(bucket, LlmCallLog.skill_id, LlmCallLog.model_name))
    rows = [
        {"bucket": b, "skill_id": skill, "model_name": model,
         "calls": calls, "errors": errors,
         "prompt_tokens": int(pt), "completion_tokens": int(ct),
         "avg_duration_ms": int(round(avg or 0))}
        for b, skill, model, calls, errors, pt, ct, avg in query]
    return sorted(rows, key=lambda r: (r["bucket"], r["skill_id"],
                                       r["model_name"]), reverse=True)
