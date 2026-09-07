"""V1.9 黑名单管理页：录入表单 + 列表 + 删除（内部管理界面，与 /audit 同层）。"""
import logging
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response

from app.services.blacklist import add_blacklist, delete_blacklist, \
    list_blacklist
from app.web.routes import get_db, templates

logger = logging.getLogger(__name__)

blacklist_router = APIRouter()


def _parse_douyin_ids(text: str) -> list[str]:
    """按逗号/空白（含换行）切分，去空白、去重且保持顺序。

    仅做粗切分，合法性校验交由 service 层完成（非纯数字条目计入 invalid）。
    """
    seen: list[str] = []
    for token in re.split(r"[,\s]+", text.strip()):
        if token and token not in seen:
            seen.append(token)
    return seen


@blacklist_router.get("/blacklist")
def blacklist_page(request: Request, db=Depends(get_db)):
    rows = list_blacklist(db)
    return templates.TemplateResponse(request, "blacklist.html",
                                      {"rows": rows, "active": "blacklist"})


@blacklist_router.post("/api/blacklist")
def blacklist_add(douyin_ids: str = Form(...),
                  nickname: str = Form(""),
                  remark: str = Form(""),
                  db=Depends(get_db)):
    ids = _parse_douyin_ids(douyin_ids)
    result = add_blacklist(db, ids, nickname=nickname or None,
                           remark=remark or None)
    return {"added": result["added"],
            "skipped": result["skipped"],
            "invalid": result["invalid"]}


@blacklist_router.delete("/api/blacklist/{record_id}")
def blacklist_delete(record_id: int, db=Depends(get_db)):
    ok = delete_blacklist(db, record_id)
    if not ok:
        raise HTTPException(404, "黑名单记录不存在")
    return Response(status_code=204)
