"""V1.4 审计页面：任务量与 LLM 消耗统计（只读展示）。"""
import logging

from fastapi import APIRouter, Depends, Query, Request

from app.services.audit_stats import (job_stats, llm_stats, today_summary,
                                      utc_range)
from app.web.routes import get_db, templates

logger = logging.getLogger(__name__)

audit_router = APIRouter()

# granularity → (默认范围, 上限)
_LIMITS = {"day": (7, 90), "hour": (48, 168)}


@audit_router.get("/audit")
def audit_page(request: Request,
               granularity: str = "day",
               range_: str | None = Query(default=None, alias="range"),
               db=Depends(get_db)):
    if granularity not in _LIMITS:
        granularity = "day"
    default, cap = _LIMITS[granularity]
    try:
        range_int = int(range_)
    except (ValueError, TypeError):
        range_int = None
    span = min(range_int, cap) if range_int and range_int > 0 else default
    ctx = {"active": "audit", "granularity": granularity, "span": span,
           "error": None, "summary": None, "jobs": [], "llm": []}
    try:
        start_utc, end_utc = utc_range(granularity, span)
        ctx["summary"] = today_summary(db)
        ctx["jobs"] = job_stats(db, granularity, start_utc, end_utc)
        ctx["llm"] = llm_stats(db, granularity, start_utc, end_utc)
    except Exception:
        logger.exception("审计统计查询失败")
        ctx["error"] = "统计查询失败，请稍后重试或查看服务日志"
    return templates.TemplateResponse(request, "audit.html", ctx)
