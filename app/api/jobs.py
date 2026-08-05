import uuid
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import ApiJob


def create_job(session: Session, job_type: str, payload: dict,
               total: int) -> ApiJob:
    job = ApiJob(id=str(uuid.uuid4()), job_type=job_type,
                 request_payload=payload, progress_total=total,
                 status="pending")
    session.add(job)
    session.commit()
    return job


def get_job(session: Session, job_id: str) -> ApiJob | None:
    return session.get(ApiJob, job_id)


def claim_next_job(session: Session) -> ApiJob | None:
    # FOR UPDATE SKIP LOCKED（需 MySQL 8.0+）：并发 worker 跳过已被
    # 他人锁定的行，避免重复认领同一作业；SQLite 会忽略该子句
    job = (session.query(ApiJob).filter_by(status="pending")
           .order_by(ApiJob.attempt_count.asc(), ApiJob.created_at.asc())
           .with_for_update(skip_locked=True).first())
    if job is None:
        return None
    job.status = "running"
    job.attempt_count += 1
    session.commit()
    return job


def set_progress(session: Session, job: ApiJob, done: int) -> None:
    job.progress_done = done
    session.commit()


def _strip_screenshots(job: ApiJob) -> None:
    """作业到达终态后清空 payload 中的 base64 截图，单行可从数 MB 降回 KB 级。

    截图仅在处理时需要；终态后保留会拖慢所有加载该行的查询与备份。
    只处理 profile_analysis 结构，其他 job_type 不触碰（也避免无谓触发
    deferred 列加载）。
    """
    if job.job_type != "profile_analysis":
        return
    payload = job.request_payload
    if not isinstance(payload, dict):
        return
    accounts = payload.get("accounts")
    if not isinstance(accounts, list):
        return
    changed = False
    for acc in accounts:
        if isinstance(acc, dict) and acc.get("account_homepage_screenshot"):
            acc["account_homepage_screenshot"] = ""
            changed = True
    if changed:
        # 就地修改 JSON 列不会被 ORM 感知，需显式标记
        flag_modified(job, "request_payload")


def finish_job(session: Session, job: ApiJob, *, result: dict | None,
               status: str, error: str | None) -> None:
    job.result = result
    job.status = status
    job.error = error
    job.finished_at = datetime.utcnow()
    _strip_screenshots(job)
    session.commit()


def fail_or_retry(session: Session, job: ApiJob, error: str) -> None:
    if job.attempt_count < job.max_attempts:
        job.status = "pending"
        job.error = error
    else:
        job.status = "failed"
        job.error = error
        job.finished_at = datetime.utcnow()
        _strip_screenshots(job)
    session.commit()


def reset_running_jobs(session: Session) -> int:
    n = (session.query(ApiJob).filter_by(status="running")
         .update({"status": "pending"}))
    session.commit()
    return n
