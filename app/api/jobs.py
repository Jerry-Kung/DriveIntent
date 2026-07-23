import uuid
from datetime import datetime

from sqlalchemy.orm import Session

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
    job = (session.query(ApiJob).filter_by(status="pending")
           .order_by(ApiJob.attempt_count.asc(), ApiJob.created_at.asc())
           .first())
    if job is None:
        return None
    job.status = "running"
    job.attempt_count += 1
    session.commit()
    return job


def set_progress(session: Session, job: ApiJob, done: int) -> None:
    job.progress_done = done
    session.commit()


def finish_job(session: Session, job: ApiJob, *, result: dict | None,
               status: str, error: str | None) -> None:
    job.result = result
    job.status = status
    job.error = error
    job.finished_at = datetime.utcnow()
    session.commit()


def fail_or_retry(session: Session, job: ApiJob, error: str) -> None:
    if job.attempt_count < job.max_attempts:
        job.status = "pending"
        job.error = error
    else:
        job.status = "failed"
        job.error = error
        job.finished_at = datetime.utcnow()
    session.commit()


def reset_running_jobs(session: Session) -> int:
    n = (session.query(ApiJob).filter_by(status="running")
         .update({"status": "pending"}))
    session.commit()
    return n
