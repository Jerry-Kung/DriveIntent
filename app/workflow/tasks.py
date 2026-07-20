from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AnalysisTask


def create_task(session: Session, *, task_type: str, target_type: str,
                target_id: str, skill_version: str,
                payload: dict | None = None) -> AnalysisTask | None:
    exists = (session.query(AnalysisTask)
              .filter_by(task_type=task_type, target_type=target_type,
                         target_id=target_id, skill_version=skill_version)
              .first())
    if exists:
        return None
    task = AnalysisTask(task_type=task_type, target_type=target_type,
                        target_id=target_id, skill_version=skill_version,
                        payload=payload)
    session.add(task)
    session.commit()
    return task


def claim_next(session: Session) -> AnalysisTask | None:
    task = (session.query(AnalysisTask)
            .filter_by(status="pending")
            .order_by(AnalysisTask.id).first())
    if task is None:
        return None
    task.status = "running"
    task.attempt_count += 1
    session.commit()
    return task


def finish_task(session: Session, task: AnalysisTask,
                error: str | None = None) -> None:
    if error is None:
        task.status = "success"
        task.error = None
    elif task.attempt_count < task.max_attempts:
        task.status = "pending"
        task.error = error
    else:
        task.status = "failed"
        task.error = error
    session.commit()


def reset_running(session: Session) -> int:
    n = (session.query(AnalysisTask)
         .filter_by(status="running")
         .update({"status": "pending"}))
    session.commit()
    return n


def retry_task(session: Session, task_id: int) -> bool:
    task = session.get(AnalysisTask, task_id)
    if task is None or task.status != "failed":
        return False
    task.status = "pending"
    task.attempt_count = 0
    task.error = None
    session.commit()
    return True


def task_counts(session: Session) -> dict:
    rows = (session.query(AnalysisTask.task_type, AnalysisTask.status,
                          func.count(AnalysisTask.id))
            .group_by(AnalysisTask.task_type, AnalysisTask.status).all())
    out: dict[str, dict[str, int]] = {}
    for task_type, status, count in rows:
        out.setdefault(task_type, {})[status] = count
    return out
