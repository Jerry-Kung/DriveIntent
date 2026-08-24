"""V1.7.1 线索结果查询：从 api_job 扁平化精筛结果，支持分页/筛选/导出。

数据源为对外 API 异步路径落库的 api_job（job_type='profile_analysis'），
result.results[] 每账号一条，与 request_payload.accounts[] 顺序一致。
本模块只读 api_job 与 llm_call_log，不写库，业务模块不依赖本模块。
分页：无等级筛选走作业级游标（JSON_LENGTH 取账号数，只读覆盖当页的作业
result 大列）；有等级筛选退化为全量扁平化 + Python 过滤。时间口径：库内
finished_at/created_at 为 UTC 朴素时间，日期筛选按东八区自然日转换。
"""
import csv
import io
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, undefer

from app.models import ApiJob, LlmCallLog

TZ8 = timezone(timedelta(hours=8))

# 对外 intent_level_code → 内部等级；null/error/未知统一 C（口径同
# docs/20260813-14_精筛定级等级分布统计.md）。
# V1.7.3：前向映射已改多对一（H/A→high、B→medium、C→low），新数据不再依
# 赖本表反推——api_job.lead_grades 记录真实 HABC，见 grade_of()。本表仅作
# 旧数据（lead_grades 为 NULL）回退，旧映射一对一，反推仍准确。
_GRADE_FROM_CODE = {"high": "H", "medium": "A", "low": "B"}


def grade_of(acct: dict, internal_grade: str | None = None) -> str:
    """账号的内部 HABC 等级。

    internal_grade 非空（api_job.lead_grades 提供）时原样返回；为空/缺省
    时回退按对外 intent_level_code 反推（仅历史数据，旧映射一对一）。
    """
    if internal_grade:
        return internal_grade
    return _GRADE_FROM_CODE.get(acct.get("intent_level_code"), "C")


def _account_count(db):
    """SQL 表达式：result->'$.results' 数组长度，按方言分派。"""
    if db.get_bind().dialect.name == "mysql":
        return func.json_length(ApiJob.result, "$.results")
    return func.json_array_length(ApiJob.result, "$.results")


def _iso_utc8(dt):
    if dt is None:
        return None
    return (dt.replace(tzinfo=timezone.utc).astimezone(TZ8)
            .isoformat(timespec="seconds"))


def date_bounds(date_str: str) -> tuple[datetime, datetime] | None:
    """'YYYY-MM-DD' 东八区自然日 → UTC [start, end) 朴素时间边界；非法返回 None。"""
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    start_local = d.replace(tzinfo=TZ8)
    end_local = start_local + timedelta(days=1)
    return (start_local.astimezone(timezone.utc).replace(tzinfo=None),
            end_local.astimezone(timezone.utc).replace(tzinfo=None))


def _base_query(session: Session, *, date_from: str | None = None,
                date_to: str | None = None):
    q = (session.query(ApiJob)
         .filter(ApiJob.job_type == "profile_analysis",
                 ApiJob.result.isnot(None),
                 ApiJob.status.in_(["success", "partial"])))
    if date_from:
        b = date_bounds(date_from)
        if b:
            q = q.filter(ApiJob.finished_at >= b[0])
    if date_to:
        b = date_bounds(date_to)
        if b:
            q = q.filter(ApiJob.finished_at < b[1])
    return q.order_by(ApiJob.finished_at.desc(), ApiJob.id.desc())


def _to_row(job: ApiJob, idx: int, acct: dict) -> dict:
    # V1.7.3：优先读 lead_grades 真实 HABC；旧数据为 NULL，回退按 code 反推
    lead_grades = job.lead_grades or []
    internal_grade = (lead_grades[idx] if idx < len(lead_grades) else None)
    return {
        "job_id": job.id,
        "index": idx,
        "account_uid": acct.get("account_uid") or "",
        "grade": grade_of(acct, internal_grade),
        "value_score": acct.get("value_score"),
        "is_car_owner": acct.get("is_car_owner"),
        "has_purchase_intent": acct.get("has_purchase_intent"),
        "profile_summary": acct.get("profile_summary") or "",
        "profile_tags": acct.get("profile_tags") or [],
        "analysis": acct.get("analysis") or "",
        "processed_at": acct.get("processed_at"),
        "error": acct.get("error"),
        "finished_at": _iso_utc8(job.finished_at),
    }


def _flatten_job(job: ApiJob) -> list[dict]:
    results = (job.result or {}).get("results") or []
    return [_to_row(job, idx, acct)
            for idx, acct in enumerate(results) if isinstance(acct, dict)]


def _all_rows(session: Session, *, grade: str | None = None,
              date_from: str | None = None,
              date_to: str | None = None) -> list[dict]:
    rows = []
    for job in _base_query(session, date_from=date_from, date_to=date_to).all():
        for r in _flatten_job(job):
            if grade is None or r["grade"] == grade:
                rows.append(r)
    return rows


def query_lead_results(session: Session, *, grade: str | None = None,
                       date_from: str | None = None,
                       date_to: str | None = None,
                       page: int = 1, size: int = 20) -> dict:
    if grade:
        rows = _all_rows(session, grade=grade, date_from=date_from,
                         date_to=date_to)
        total = len(rows)
        return {"total": total, "page": page, "size": size,
                "rows": rows[(page - 1) * size: page * size]}

    base = _base_query(session, date_from=date_from, date_to=date_to)
    counts = base.with_entities(ApiJob.id, _account_count(session)).all()
    total = sum(n or 0 for _, n in counts)
    start = (page - 1) * size
    end = start + size
    cursor = 0
    selected: list[tuple[str, int, int]] = []
    for job_id, n in counts:
        n = n or 0
        if n == 0:
            continue
        job_start = cursor
        job_end = cursor + n
        cursor = job_end
        if job_end <= start or job_start >= end:
            continue
        selected.append((job_id, max(start - job_start, 0),
                         min(job_end, end) - job_start))
        if cursor >= end:
            break
    if not selected:
        return {"total": total, "page": page, "size": size, "rows": []}
    job_ids = [jid for jid, _, _ in selected]
    jobs = {j.id: j for j in session.query(ApiJob)
            .filter(ApiJob.id.in_(job_ids)).all()}
    rows = []
    for job_id, i0, i1 in selected:
        job = jobs.get(job_id)
        if job is None:
            continue
        results = (job.result or {}).get("results") or []
        for idx in range(i0, min(i1, len(results))):
            acct = results[idx]
            if isinstance(acct, dict):
                rows.append(_to_row(job, idx, acct))
    return {"total": total, "page": page, "size": size, "rows": rows}


def _call_dict(c) -> dict:
    return {"created_at": _iso_utc8(c.created_at), "skill_id": c.skill_id,
            "skill_version": c.skill_version,
            "prompt_version": c.prompt_version, "model_name": c.model_name,
            "prompt_tokens": c.prompt_tokens,
            "completion_tokens": c.completion_tokens,
            "duration_ms": c.duration_ms, "error": c.error}


def lead_detail_data(session: Session, job_id: str, index: int) -> dict | None:
    job = (session.query(ApiJob).options(undefer(ApiJob.request_payload))
           .filter(ApiJob.id == job_id).first())
    if job is None:
        return None
    results = (job.result or {}).get("results") or []
    if index < 0 or index >= len(results):
        return None
    acct = results[index]
    if not isinstance(acct, dict):
        return None
    payload = job.request_payload or {}
    accounts = payload.get("accounts") or []
    input_acct = (accounts[index]
                  if index < len(accounts) and isinstance(accounts[index], dict)
                  else {})

    # V1.7.1 精确关联：优先按 job_id + account_uid 匹配（V1.7.1 起落库
    # 写入），详情页只展示该账号自身的 3~5 次调用。历史数据回退时间窗近似。
    account_uid = acct.get("account_uid")
    calls = (session.query(LlmCallLog)
             .filter(LlmCallLog.job_id == job_id,
                     LlmCallLog.account_uid == account_uid)
             .order_by(LlmCallLog.created_at).all())
    if not calls:
        # 回退：旧日志无 job_id，按作业时间窗近似（多 worker 并发时不可靠）
        window_end = job.finished_at or datetime.utcnow()
        calls = (session.query(LlmCallLog)
                 .filter(LlmCallLog.created_at >= job.created_at,
                         LlmCallLog.created_at <= window_end)
                 .order_by(LlmCallLog.created_at).all())
    lead_grades = job.lead_grades or []
    internal_grade = (lead_grades[index] if index < len(lead_grades) else None)
    return {"job_id": job.id, "status": job.status,
            "created_at": _iso_utc8(job.created_at),
            "finished_at": _iso_utc8(job.finished_at),
            "progress_done": job.progress_done,
            "progress_total": job.progress_total,
            "acct": acct, "input": input_acct,
            "calls": [_call_dict(c) for c in calls],
            "grade": grade_of(acct, internal_grade)}


def _csv_safe(value):
    """防止 Excel/表格软件将以 =、+、-、@ 开头的单元格当公式执行。"""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def export_lead_results_csv(session: Session, *, grade: str | None = None,
                            date_from: str | None = None,
                            date_to: str | None = None) -> str:
    rows = _all_rows(session, grade=grade, date_from=date_from,
                     date_to=date_to)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["账号UID", "等级", "价值分", "车主", "购车意向",
                     "画像标签", "画像摘要", "分析文本", "处理时间", "作业ID"])
    for r in rows:
        writer.writerow([
            _csv_safe(r["account_uid"]), r["grade"], r["value_score"],
            r["is_car_owner"], r["has_purchase_intent"],
            _csv_safe("/".join(r["profile_tags"])),
            _csv_safe(r["profile_summary"]), _csv_safe(r["analysis"]),
            r["processed_at"], r["job_id"]])
    return buf.getvalue()
