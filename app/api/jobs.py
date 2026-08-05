import uuid
from datetime import datetime, timedelta

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


def claim_next_job_detached(session: Session) -> dict | None:
    """认领一个作业并把执行所需数据取成普通 dict，随后不再需要该会话。

    V1.4.3：worker 不得在 LLM 调用期间持有连接。request_payload 是 deferred
    列，若延后访问会重新开启事务、把连接钉在池外整个 LLM 期间；故在此一次性
    读出，返回与 ORM 解耦的纯数据。
    """
    job = claim_next_job(session)
    if job is None:
        return None
    # 在会话仍可用时读出 deferred 列，之后调用方不再触碰 ORM 对象
    payload = job.request_payload
    data = {"id": job.id, "job_type": job.job_type, "payload": payload,
            "attempt_count": job.attempt_count}
    # 结束读取事务，归还连接
    session.commit()
    return data


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


def fail_stale_running_jobs(session: Session,
                            max_age_minutes: int) -> int:
    """把超时未更新的 running 作业直接判失败（不重试）。

    兜底场景：worker 认领后因进程崩溃/连接池异常等原因遗弃作业，
    作业永远停在 running。以 updated_at 判停滞（set_progress 会刷新
    该列，正常执行中的长作业不会被误杀）。
    """
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    stale = (session.query(ApiJob).filter(
        ApiJob.status == "running", ApiJob.updated_at < cutoff).all())
    for job in stale:
        job.status = "failed"
        job.error = f"作业停滞超过 {max_age_minutes} 分钟，已强制判定失败"
        job.finished_at = datetime.utcnow()
        _strip_screenshots(job)
    if stale:
        session.commit()
    return len(stale)


def reset_running_jobs(session: Session) -> int:
    n = (session.query(ApiJob).filter_by(status="running")
         .update({"status": "pending"}))
    session.commit()
    return n


def _stripped_payload(payload) -> dict | None:
    """返回清空截图后的 payload；无截图可清时返回 None（表示无需写回）。

    与 `_strip_screenshots` 同语义，但接收纯 dict、不触碰 ORM——供短会话
    路径在已持有 payload 时直接赋值，避免为剥离截图重新 SELECT 数 MB 大列。
    """
    if not isinstance(payload, dict):
        return None
    accounts = payload.get("accounts")
    if not isinstance(accounts, list):
        return None
    changed = False
    out_accounts = []
    for acc in accounts:
        if isinstance(acc, dict) and acc.get("account_homepage_screenshot"):
            acc = dict(acc, account_homepage_screenshot="")
            changed = True
        out_accounts.append(acc)
    if not changed:
        return None
    return dict(payload, accounts=out_accounts)


# --- V1.4.3：按 id 操作的短会话入口 -------------------------------------
# worker 在 LLM 期间不持有会话，状态更新时才临时开一个、用完立即关闭。
# 每个函数自行管理会话生命周期，调用方无需持有 session。

def set_progress_by_id(session_factory, job_id: str, done: int) -> None:
    with session_factory() as s:
        job = s.get(ApiJob, job_id)
        if job is not None:
            set_progress(s, job, done)


def finish_job_by_id(session_factory, job_id: str, *, result: dict | None,
                     status: str, error: str | None,
                     payload: dict | None = None) -> None:
    """落终态。传入 payload 时直接赋值已剥离版本，省去重读大列。"""
    with session_factory() as s:
        job = s.get(ApiJob, job_id)
        if job is None:
            return
        job.result = result
        job.status = status
        job.error = error
        job.finished_at = datetime.utcnow()
        if job.job_type == "profile_analysis":
            if payload is None:
                _strip_screenshots(job)          # 回退：自行加载后就地剥离
            else:
                stripped = _stripped_payload(payload)
                if stripped is not None:
                    job.request_payload = stripped
        s.commit()


def fail_or_retry_by_id(session_factory, job_id: str, error: str,
                        payload: dict | None = None) -> None:
    """失败重试/终态失败。终态时同样支持直接赋值已剥离 payload。"""
    with session_factory() as s:
        job = s.get(ApiJob, job_id)
        if job is None:
            return
        if job.attempt_count < job.max_attempts:
            job.status = "pending"
            job.error = error
            s.commit()
            return
        job.status = "failed"
        job.error = error
        job.finished_at = datetime.utcnow()
        if job.job_type == "profile_analysis":
            if payload is None:
                _strip_screenshots(job)
            else:
                stripped = _stripped_payload(payload)
                if stripped is not None:
                    job.request_payload = stripped
        s.commit()
