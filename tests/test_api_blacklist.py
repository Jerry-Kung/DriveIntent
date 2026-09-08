"""对外黑名单 API（/api/v1/blacklist）测试。

仿 tests/test_api_routes.py 夹具：内存 SQLite + StaticPool + API_KEYS，
dependency_overrides[get_db]，验证鉴权、分页/搜索、批量新增幂等、删除、中文 UTF-8。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.blacklist import blacklist_api_router
from app.api.routes import get_db
from app.db import Base


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("API_KEYS", "secret")
    from app.config import settings
    monkeypatch.setattr(settings, "api_keys", "secret")
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    import app.models  # noqa
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(blacklist_api_router)
    app.dependency_overrides[get_db] = lambda: Session()
    app.state.test_factory = Session
    return TestClient(app)


@pytest.fixture()
def session(client):
    yield client.app.state.test_factory()


_AUTH = {"Authorization": "Bearer secret"}


def _seed(session, *douyin_ids):
    from app.models import BlacklistedUser
    rows = [BlacklistedUser(douyin_id=uid) for uid in douyin_ids]
    session.add_all(rows)
    session.commit()
    return rows


# --------------------------------------------------------------------------- #
# 鉴权
# --------------------------------------------------------------------------- #

def test_requires_auth(client):
    """缺 Authorization / 错 key / 无 key 配置外 → 401。"""
    assert client.get("/api/v1/blacklist").status_code == 401
    assert client.post("/api/v1/blacklist", json={"douyin_ids": ["1"]}
                       ).status_code == 401
    assert client.delete("/api/v1/blacklist/1").status_code == 401
    r = client.get("/api/v1/blacklist",
                   headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# GET：分页 / 倒序 / 搜索 / total / 参数归一化
# --------------------------------------------------------------------------- #

def test_get_empty_list(client):
    r = client.get("/api/v1/blacklist", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_get_verified_created_at_east8(client, session):
    """created_at 应为东八区 ISO 8601（带 +08:00 偏移）。"""
    from datetime import datetime
    rows = _seed(session, "79373130119")
    rows[0].created_at = datetime(2026, 9, 8, 2, 0, 0)  # UTC
    session.commit()
    r = client.get("/api/v1/blacklist", headers=_AUTH)
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["created_at"] == "2026-09-08T10:00:00+08:00"


def test_get_paginated_newest_first(client, session):
    """倒序分页 + total 为全量（非本页条数）。"""
    _seed(session, "111111", "222222", "333333")
    r = client.get("/api/v1/blacklist?page=1&page_size=2", headers=_AUTH)
    body = r.json()
    assert body["total"] == 3
    assert body["page"] == 1 and body["page_size"] == 2
    assert len(body["items"]) == 2  # SQLite 按 id 升序但 created_at 相同，倒序按 id desc
    r2 = client.get("/api/v1/blacklist?page=2&page_size=2", headers=_AUTH)
    assert len(r2.json()["items"]) == 1


def test_get_pagination_normalized(client, session):
    """page<1 按 1；page_size>100 截断为 100；page_size<1 回默认。"""
    _seed(session, "111111", "222222")
    r = client.get("/api/v1/blacklist?page=0&page_size=999", headers=_AUTH)
    body = r.json()
    assert body["page"] == 1 and body["page_size"] == 100
    r2 = client.get("/api/v1/blacklist?page_size=0", headers=_AUTH)
    assert r2.json()["page_size"] == 20


def test_get_search_by_douyin_id_and_total(client, session):
    _seed(session, "79373130119", "79373130120", "999999")
    body = client.get("/api/v1/blacklist?q=7937", headers=_AUTH).json()
    assert body["total"] == 2
    assert {i["douyin_id"] for i in body["items"]} == {
        "79373130119", "79373130120"}
    assert client.get("/api/v1/blacklist?q=不存在", headers=_AUTH
                      ).json()["total"] == 0


def test_get_search_by_nickname_remark(client, session):
    from app.models import BlacklistedUser
    session.add(BlacklistedUser(douyin_id="111", nickname="东风用户"))
    session.add(BlacklistedUser(douyin_id="222", remark="越野爱好者"))
    session.commit()
    assert client.get("/api/v1/blacklist?q=东风", headers=_AUTH
                      ).json()["total"] == 1
    assert client.get("/api/v1/blacklist?q=越野", headers=_AUTH
                      ).json()["total"] == 1


# --------------------------------------------------------------------------- #
# POST：批量新增 / 幂等 / 非法计数 / 空数组 422
# --------------------------------------------------------------------------- #

def test_post_adds_with_nickname_remark(client, session):
    r = client.post("/api/v1/blacklist",
                    json={"douyin_ids": ["79373130119", "79373130120"],
                          "nickname": "批量昵称", "remark": "批量备注"},
                    headers=_AUTH)
    assert r.status_code == 200
    assert r.json() == {"added": 2, "skipped": 0, "invalid": 0}
    from app.models import BlacklistedUser
    rows = session.query(BlacklistedUser).all()
    assert len(rows) == 2
    assert all(row.nickname == "批量昵称" and row.remark == "批量备注"
               for row in rows)


def test_post_idempotent_and_invalid_count(client, session):
    """已存在重复计 skipped；非纯数字计 invalid。"""
    from app.models import BlacklistedUser
    session.add(BlacklistedUser(douyin_id="79373130119"))
    session.commit()
    r = client.post("/api/v1/blacklist",
                    json={"douyin_ids": ["79373130119", "abc", "", "12ab"]},
                    headers=_AUTH)
    assert r.status_code == 200
    assert r.json() == {"added": 0, "skipped": 1, "invalid": 3}
    # 非法项未入库
    assert session.query(BlacklistedUser).filter(
        BlacklistedUser.douyin_id.in_(["abc", "12ab"])).count() == 0


def test_post_empty_ids_422(client):
    r = client.post("/api/v1/blacklist", json={"douyin_ids": []},
                    headers=_AUTH)
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# DELETE：204 / 404
# --------------------------------------------------------------------------- #

def test_delete_hit_then_404(client, session):
    from app.models import BlacklistedUser
    row = BlacklistedUser(douyin_id="555000111")
    session.add(row)
    session.commit()
    r = client.delete(f"/api/v1/blacklist/{row.id}", headers=_AUTH)
    assert r.status_code == 204
    assert session.query(BlacklistedUser).filter_by(
        douyin_id="555000111").first() is None
    r2 = client.delete(f"/api/v1/blacklist/{row.id}", headers=_AUTH)
    assert r2.status_code == 404


# --------------------------------------------------------------------------- #
# 中文 UTF-8 往返
# --------------------------------------------------------------------------- #

def test_chinese_utf8_roundtrip(client, session):
    """中文 nickname/remark 经过库与响应往返后仍为预期内容（无 mojibake）。"""
    r = client.post("/api/v1/blacklist",
                    json={"douyin_ids": ["12345"], "remark": "不良广告号"},
                    headers=_AUTH)
    assert r.status_code == 200
    assert r.json() == {"added": 1, "skipped": 0, "invalid": 0}
    body = client.get("/api/v1/blacklist?q=不良", headers=_AUTH).json()
    assert body["total"] == 1
    assert body["items"][0]["remark"] == "不良广告号"
    assert body["items"][0]["douyin_id"] == "12345"
