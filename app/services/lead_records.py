"""V1.10.1 线索汇总表读写：api_job.result → lead_record 物化。

列表/筛选/导出改读 lead_record（普通列 + 索引），详情页仍读 api_job
的原始 JSON（那里需要完整账号字段，且是单作业一次性读取，本就很快）。

对外返回口径与 V1.7.3/V1.8.0 保持一致：等级优先取 api_job.lead_grades
按下标对齐的真实 HABC，缺失时按 intent_level_code 反推。
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import ApiJob, LeadRecord


def grade_of(acct: dict, internal_grade: str | None = None) -> str:
    """账号的内部 HABC 等级（与 services.lead_results.grade_of 同口径）。

    internal_grade 非空（api_job.lead_grades 提供）时原样返回；为空/缺省
    时回退按对外 intent_level_code 反推（仅历史数据，旧映射一对一）。
    """
    if internal_grade:
        return internal_grade
    return {"high": "H", "medium": "A", "low": "B"}.get(
        acct.get("intent_level_code"), "C")


def _as_int(value) -> int | None:
    """bool 是 int 的子类，须先排除，避免 True 被写成 1。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _as_bool(value) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    return None


def record_rows(job_id: str, acct: dict, index: int,
                internal_grade: str | None,
                finished_at: datetime | None) -> LeadRecord:
    """由单个账号结果构造一行 lead_record。"""
    return LeadRecord(
        job_id=job_id, idx=index,
        account_uid=str(acct.get("account_uid") or "")[:256],
        grade=grade_of(acct, internal_grade),
        value_score=_as_int(acct.get("value_score")),
        is_car_owner=_as_bool(acct.get("is_car_owner")),
        has_purchase_intent=_as_bool(acct.get("has_purchase_intent")),
        intent_models=acct.get("intent_models") or [],
        intent_model_category=acct.get("intent_model_category"),
        profile_summary=str(acct.get("profile_summary") or ""),
        profile_tags=acct.get("profile_tags") or [],
        analysis=str(acct.get("analysis") or ""),
        processed_at=acct.get("processed_at"),
        error=acct.get("error"),
        finished_at=finished_at,
    )


def replace_records(session: Session, job_id: str, result: dict | None,
                    lead_grades: list | None,
                    finished_at: datetime | None,
                    status: str | None = None) -> int:
    """用作业的最终结果整份替换该作业的汇总行，返回写入行数。

    幂等：先删除本作业既有行再插入，重试/重跑不会产生重复行。
    非 success/partial 终态（如整份失败）只清空不写入，避免列表里留下
    半截数据。调用方须与 api_job 终态写入处于同一事务。
    """
    session.query(LeadRecord).filter(LeadRecord.job_id == job_id).delete(
        synchronize_session=False)
    if status is not None and status not in ("success", "partial"):
        return 0
    results = (result or {}).get("results") or []
    grades = lead_grades or []
    n = 0
    for index, acct in enumerate(results):
        if not isinstance(acct, dict):
            continue
        internal_grade = grades[index] if index < len(grades) else None
        session.add(record_rows(job_id, acct, index, internal_grade,
                                finished_at))
        n += 1
    return n
