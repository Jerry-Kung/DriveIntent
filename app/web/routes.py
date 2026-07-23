import json
import logging
import tempfile
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.db import SessionLocal
from app.importer.core import import_bundle
from app.importer.excel import parse_excel
from app.importer.json_source import parse_json_source
from app.models import Lead, Video
from app.services.aggregation import build_user_evidence
from app.services.leads import (lead_to_dict, leads_to_csv, leads_to_dicts,
                                query_leads, query_screened_out_comments,
                                query_unclassified_users)
from app.workflow.pipeline import advance, schedule_analysis
from app.workflow.tasks import list_failed_tasks, retry_task, task_counts

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html",
                                      {"active": "index"})


# 同步端点：FastAPI 会放到线程池执行，解析与批量入库不会阻塞事件循环
@router.post("/api/import")
def api_import(file: UploadFile, db=Depends(get_db)):
    tmp_path = None
    try:
        raw_bytes = file.file.read()
        if (file.filename or "").endswith(".json"):
            bundle = parse_json_source(json.loads(raw_bytes.decode("utf-8")))
        else:
            with tempfile.NamedTemporaryFile(suffix=".xlsx",
                                             delete=False) as tmp:
                tmp_path = tmp.name
                tmp.write(raw_bytes)
            bundle = parse_excel(tmp_path)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, str(e))
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
    start = time.monotonic()
    stats = import_bundle(db, bundle)
    logger.info("导入耗时 %.1fs", time.monotonic() - start)
    return stats.model_dump()


@router.post("/api/analysis/start")
def api_start(db=Depends(get_db)):
    created = schedule_analysis(db)
    created += advance(db)
    video_count = db.query(Video).count()
    logger.info("启动分析: 新建任务 %d 个（库内视频 %d 个）", created, video_count)
    resp: dict = {"created": created}
    if video_count == 0:
        resp["message"] = "数据库中没有视频数据，请先导入 Excel"
    return resp


@router.get("/api/analysis/progress")
def api_progress(db=Depends(get_db)):
    return task_counts(db)


@router.get("/api/tasks/failed")
def api_failed_tasks(db=Depends(get_db)):
    return list_failed_tasks(db)


@router.post("/api/tasks/{task_id}/retry")
def api_retry(task_id: int, db=Depends(get_db)):
    if not retry_task(db, task_id):
        raise HTTPException(404, "任务不存在或不是失败状态")
    return {"ok": True}


class ReviewIn(BaseModel):
    review_status: str
    review_tags: list[str] = []
    review_note: str = ""


@router.get("/leads")
def leads_page(request: Request, grade: str | None = None,
               brand: str | None = None, model: str | None = None,
               review_status: str | None = None, db=Depends(get_db)):
    leads = query_leads(db, grade=grade, brand=brand, model=model,
                        review_status=review_status)
    rows = leads_to_dicts(db, leads)
    invalid_rows = query_unclassified_users(db)
    screened_out = query_screened_out_comments(db)
    return templates.TemplateResponse(
        request, "leads.html",
        {"rows": rows, "grade": grade or "", "brand": brand or "",
         "model": model or "", "review_status": review_status or "",
         "invalid_rows": invalid_rows, "screened_out": screened_out,
         "active": "leads"})


@router.get("/leads/{lead_id}")
def lead_detail_page(request: Request, lead_id: int, db=Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "线索不存在")
    d = lead_to_dict(db, lead)
    evidence_pack = build_user_evidence(db, lead.user_id)
    return templates.TemplateResponse(
        request, "lead_detail.html",
        {"lead": d, "pack": evidence_pack, "active": "leads"})


@router.get("/api/leads")
def api_leads(grade: str | None = None, brand: str | None = None,
              model: str | None = None, review_status: str | None = None,
              db=Depends(get_db)):
    leads = query_leads(db, grade=grade, brand=brand, model=model,
                        review_status=review_status)
    return leads_to_dicts(db, leads)


@router.get("/api/leads/export")
def api_leads_export(grade: str | None = None, brand: str | None = None,
                     model: str | None = None,
                     review_status: str | None = None, db=Depends(get_db)):
    leads = query_leads(db, grade=grade or None, brand=brand or None,
                        model=model or None,
                        review_status=review_status or None)
    csv_text = "﻿" + leads_to_csv(db, leads)
    return Response(csv_text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             'attachment; filename="leads.csv"'})


REVIEW_STATUS_NAMES = {"unreviewed": "未审核", "valid": "有效",
                       "invalid": "无效"}


@router.get("/api/leads/export/html")
def api_leads_export_html(grade: str | None = None, brand: str | None = None,
                          model: str | None = None,
                          review_status: str | None = None,
                          db=Depends(get_db)):
    leads = query_leads(db, grade=grade or None, brand=brand or None,
                        model=model or None,
                        review_status=review_status or None)
    rows = leads_to_dicts(db, leads)
    grade_counts: dict[str, int] = {}
    for r in rows:
        grade_counts[r["grade"]] = grade_counts.get(r["grade"], 0) + 1
    filters = [f"等级 {grade}" if grade else "",
               f"品牌 {brand}" if brand else "",
               f"车型 {model}" if model else "",
               ("审核状态 " + REVIEW_STATUS_NAMES.get(review_status,
                                                  review_status))
               if review_status else ""]
    filter_text = "；".join(x for x in filters if x) or "全部"
    html = templates.env.get_template("export_leads.html").render(
        rows=rows, grade_counts=grade_counts, filter_text=filter_text,
        invalid_rows=query_unclassified_users(db),
        screened_out=query_screened_out_comments(db),
        status_names=REVIEW_STATUS_NAMES,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
    return Response(html, media_type="text/html; charset=utf-8",
                    headers={"Content-Disposition":
                             'attachment; filename="leads.html"'})


@router.get("/api/leads/{lead_id}")
def api_lead_detail(lead_id: int, db=Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "线索不存在")
    return lead_to_dict(db, lead)


@router.post("/api/leads/{lead_id}/review")
def api_review(lead_id: int, body: ReviewIn, db=Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "线索不存在")
    lead.review_status = body.review_status
    lead.review_tags = body.review_tags
    lead.review_note = body.review_note
    db.commit()
    return {"ok": True}
