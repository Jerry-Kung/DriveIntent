from fastapi import APIRouter, Depends, Header, HTTPException

from app.api.jobs import create_job, get_job
from app.api.schemas import CommentScreeningRequest, ProfileAnalysisRequest
from app.config import settings
from app.db import SessionLocal

api_router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_api_key(authorization: str = Header(default="")) -> None:
    keys = settings.api_keys_list
    if not keys:
        return  # 未配置 key 时不启用认证（本地/测试）
    token = authorization.removeprefix("Bearer ").strip()
    if token not in keys:
        raise HTTPException(status_code=401, detail="无效或缺失的 API Key")


@api_router.get("/health")
def health():
    return {"status": "ok"}


@api_router.post("/api/v1/comment-screening", status_code=202,
                 dependencies=[Depends(require_api_key)])
def submit_comment_screening(request: CommentScreeningRequest,
                             db=Depends(get_db)):
    job = create_job(db, "comment_screening", request.model_dump(),
                     total=len(request.comments))
    return {"job_id": job.id, "status": job.status,
            "type": job.job_type}


@api_router.post("/api/v1/profile-analysis", status_code=202,
                 dependencies=[Depends(require_api_key)])
def submit_profile_analysis(request: ProfileAnalysisRequest,
                            db=Depends(get_db)):
    job = create_job(db, "profile_analysis", request.model_dump(),
                     total=len(request.accounts))
    return {"job_id": job.id, "status": job.status,
            "type": job.job_type}


@api_router.get("/api/v1/jobs/{job_id}",
                dependencies=[Depends(require_api_key)])
def get_job_status(job_id: str, db=Depends(get_db)):
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="作业不存在")
    return {
        "job_id": job.id, "type": job.job_type, "status": job.status,
        "progress": {"total": job.progress_total, "done": job.progress_done},
        "result": job.result, "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": (job.finished_at.isoformat()
                        if job.finished_at else None),
    }
