import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.db import SessionLocal
from app.services.lead_results import (export_lead_results_csv, lead_detail_data,
                                       query_lead_results)

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
def index():
    return RedirectResponse("/leads", status_code=302)


@router.get("/leads")
def leads_page(request: Request, grade: str | None = None,
               date_from: str | None = None, date_to: str | None = None,
               page: int = 1, db=Depends(get_db)):
    if page < 1:
        page = 1
    data = query_lead_results(db, grade=grade or None,
                              date_from=date_from or None,
                              date_to=date_to or None, page=page, size=20)
    total_pages = max(1, (data["total"] + 19) // 20)
    return templates.TemplateResponse(request, "leads.html", {
        "rows": data["rows"], "total": data["total"], "page": page,
        "total_pages": total_pages, "grade": grade or "",
        "date_from": date_from or "", "date_to": date_to or "",
        "active": "leads"})


@router.get("/leads/{job_id}/{index}")
def lead_detail_page(request: Request, job_id: str, index: int,
                     db=Depends(get_db)):
    data = lead_detail_data(db, job_id, index)
    if data is None:
        raise HTTPException(404, "结果不存在")
    return templates.TemplateResponse(request, "lead_detail.html",
                                      {**data, "active": "leads"})


@router.get("/api/leads")
def api_leads(grade: str | None = None, date_from: str | None = None,
              date_to: str | None = None, page: int = 1, db=Depends(get_db)):
    return query_lead_results(db, grade=grade or None,
                              date_from=date_from or None,
                              date_to=date_to or None, page=page, size=20)


@router.get("/api/leads/export")
def api_leads_export(grade: str | None = None, date_from: str | None = None,
                     date_to: str | None = None, db=Depends(get_db)):
    csv_text = "﻿" + export_lead_results_csv(
        db, grade=grade or None, date_from=date_from or None,
        date_to=date_to or None)
    return Response(csv_text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             'attachment; filename="leads.csv"'})
