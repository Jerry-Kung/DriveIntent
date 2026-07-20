import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.templating import Jinja2Templates

from app.db import SessionLocal
from app.importer.core import import_bundle
from app.importer.excel import parse_excel
from app.workflow.pipeline import advance, schedule_analysis
from app.workflow.tasks import retry_task, task_counts

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
    return templates.TemplateResponse(request, "index.html", {})


@router.post("/api/import")
async def api_import(file: UploadFile, db=Depends(get_db)):
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        bundle = parse_excel(tmp_path)
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
    stats = import_bundle(db, bundle)
    return stats.model_dump()


@router.post("/api/analysis/start")
def api_start(db=Depends(get_db)):
    created = schedule_analysis(db)
    created += advance(db)
    return {"created": created}


@router.get("/api/analysis/progress")
def api_progress(db=Depends(get_db)):
    return task_counts(db)


@router.post("/api/tasks/{task_id}/retry")
def api_retry(task_id: int, db=Depends(get_db)):
    if not retry_task(db, task_id):
        raise HTTPException(404, "任务不存在或不是失败状态")
    return {"ok": True}
