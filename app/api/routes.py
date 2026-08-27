from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException

from app.api import staging
from app.api.jobs import create_job, get_job
from app.api.schemas import CommentScreeningRequest, ProfileAnalysisRequest
from app.config import settings
from app.db import SessionLocal
from app.matching.loader import intent_category_label_map, load_intent_categories

_TZ8 = timezone(timedelta(hours=8))

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
    # V1.4.4：base64 截图不入库。抽到落盘暂存区，payload 中该字段置空后
    # 再落库（单行由 MB 级降到 KB 级），worker 认领时读回识图。
    payload = request.model_dump()
    shots = staging.extract_screenshots(payload)
    job = create_job(db, "profile_analysis", payload,
                     total=len(request.accounts))
    if shots:
        # 落库成功后再写暂存：反序会在建作业失败时留下孤儿文件
        staging.save(job.id, shots)
    return {"job_id": job.id, "status": job.status,
            "type": job.job_type}


def _apply_intent_category_labels(result: dict | None) -> dict | None:
    """对外返回前，把 profile_analysis 结果里的 intent_model_category 码值
    （A/B/C/D）按 config 转成中文正式内容。仅改返回数据，不改库——库内
    api_job.result 与 lead 表仍存码值，供内部审计/统计使用。

    仅处理 profile_analysis 结果；其他 job_type 原样透传。
    """
    if not isinstance(result, dict):
        return result
    results = result.get("results")
    if not isinstance(results, list):
        return result
    label_map = intent_category_label_map(load_intent_categories())
    for acct in results:
        if not isinstance(acct, dict):
            continue
        code = acct.get("intent_model_category")
        if code is None:
            continue
        acct["intent_model_category"] = label_map.get(code, code)
    return result


@api_router.get("/api/v1/jobs/{job_id}",
                dependencies=[Depends(require_api_key)])
def get_job_status(job_id: str, db=Depends(get_db)):
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="作业不存在")
    # 轮询响应是对外契约：返回前对 intent_model_category 做码值→中文映射
    return {
        "job_id": job.id, "type": job.job_type, "status": job.status,
        "progress": {"total": job.progress_total, "done": job.progress_done},
        "result": _apply_intent_category_labels(job.result),
        "error": job.error,
        "created_at": (job.created_at.replace(tzinfo=timezone.utc)
                       .astimezone(_TZ8).isoformat()
                       if job.created_at else None),
        "finished_at": (job.finished_at.replace(tzinfo=timezone.utc)
                        .astimezone(_TZ8).isoformat()
                        if job.finished_at else None),
    }
