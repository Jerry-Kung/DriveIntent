"""V1.9.1 用户黑名单对外增删查 API（/api/v1/blacklist）。

外部前端对接黑名单机制：分页列表（可用关键字子串搜索）/ 批量幂等入库 / 逐条删除。
与既有 /api/v1/* 同层：走 Authorization: Bearer <API_KEY> 鉴权、JSON 输出、
时间戳统一东八区 ISO 8601。内部管理面 /api/blacklist（表单、无鉴权）不在此处。

复用 app.api.routes 的 get_db / require_api_key，避免鉴权与数据库会话逻辑重复。
"""
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.routes import get_db, require_api_key
from app.models import BlacklistedUser
from app.services.blacklist import (add_blacklist, count_blacklist,
                                    delete_blacklist, list_blacklist)

_TZ8 = timezone(timedelta(hours=8))
_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100

blacklist_api_router = APIRouter()


class BlacklistAddRequest(BaseModel):
    """批量入库请求体。douyin_ids 每项须为合法抖音号（纯数字）。"""
    douyin_ids: list[str]
    nickname: str | None = None
    remark: str | None = None


def _to_east8(dt) -> str:
    """把存储的 UTC naive 时间转东八区 ISO 8601 字符串（与 routes.py 一致）。"""
    return dt.replace(tzinfo=timezone.utc).astimezone(_TZ8).isoformat()


@blacklist_api_router.get("/api/v1/blacklist",
                          dependencies=[Depends(require_api_key)])
def list_blacklist_api(page: int = 1, page_size: int = _DEFAULT_PAGE_SIZE,
                       q: str = "", db=Depends(get_db)):
    """分页列出黑名单（created_at 倒序）；q 对 douyin_id/nickname/remark 子串搜索。"""
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = _DEFAULT_PAGE_SIZE
    elif page_size > _MAX_PAGE_SIZE:
        page_size = _MAX_PAGE_SIZE
    search = q.strip() or None
    total = count_blacklist(db, search=search)
    rows = list_blacklist(db, search=search,
                          offset=(page - 1) * page_size, limit=page_size)
    items = [{
        "blacklist_id": row.id,
        "douyin_id": row.douyin_id,
        "nickname": row.nickname,
        "remark": row.remark,
        "created_at": _to_east8(row.created_at),
    } for row in rows]
    return {"items": items, "total": total, "page": page,
            "page_size": page_size}


@blacklist_api_router.post("/api/v1/blacklist",
                           dependencies=[Depends(require_api_key)])
def add_blacklist_api(request: BlacklistAddRequest, db=Depends(get_db)):
    """批量幂等入库；返回 {added, skipped, invalid}。空数组返回 422。"""
    if not request.douyin_ids:
        raise HTTPException(status_code=422, detail="douyin_ids 不能为空")
    result = add_blacklist(db, request.douyin_ids,
                           nickname=request.nickname,
                           remark=request.remark)
    return {"added": result["added"], "skipped": result["skipped"],
            "invalid": result["invalid"]}


@blacklist_api_router.delete("/api/v1/blacklist/{blacklist_id}",
                             dependencies=[Depends(require_api_key)])
def delete_blacklist_api(blacklist_id: int, db=Depends(get_db)):
    """按 blacklist_id 删除一条；命中返回 204，未命中返回 404。"""
    ok = delete_blacklist(db, blacklist_id)
    if not ok:
        raise HTTPException(status_code=404, detail="黑名单记录不存在")
    return Response(status_code=204)
