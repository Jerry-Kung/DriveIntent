"""黑名单管理页（web 路由 + 模板 + 导航）测试。

遵循 tests/test_api_routes.py 的 client 夹具模式：内存 SQLite + StaticPool，
dependency_overrides[get_db]。blacklist_router 无鉴权，无需 API_KEYS。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.web.blacklist import blacklist_router
from app.web.routes import get_db


@pytest.fixture()
def client():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    import app.models  # noqa 确保模型已注册
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(blacklist_router)
    app.dependency_overrides[get_db] = lambda: Session()
    app.state.test_factory = Session
    return TestClient(app)


@pytest.fixture()
def session(client):
    yield client.app.state.test_factory()


def test_page_empty(client):
    """空表：页面 200，含标题与录入表单标记。"""
    r = client.get("/blacklist")
    assert r.status_code == 200
    assert "黑名单" in r.text
    assert 'name="douyin_ids"' in r.text
    assert "暂无黑名单" in r.text


def test_page_seeded(client, session):
    """已种数据：页面 200，且出现对应抖音号。"""
    from app.models import BlacklistedUser
    session.add(BlacklistedUser(douyin_id="79373130119", nickname="张三",
                                remark="广告号"))
    session.commit()
    r = client.get("/blacklist")
    assert r.status_code == 200
    assert "79373130119" in r.text


def test_post_add_valid(client, session):
    """POST 全合法：新增两条，含昵称/备注，返回统计。"""
    r = client.post("/api/blacklist",
                    data={"douyin_ids": "79373130119, 1234567890",
                          "nickname": "张三", "remark": "广告号"})
    assert r.status_code == 200
    assert r.json() == {"added": 2, "skipped": 0, "invalid": 0}
    from app.models import BlacklistedUser
    rows = session.query(BlacklistedUser).all()
    assert len(rows) == 2
    assert {row.douyin_id for row in rows} == {"79373130119", "1234567890"}
    # nickname/remark 应用到了入库的每条记录
    assert all(row.nickname == "张三" and row.remark == "广告号" for row in rows)


def test_post_mix_skip_and_invalid(client, session):
    """POST 混合输入：已存在重复计 skipped，非数字计 invalid。"""
    from app.models import BlacklistedUser
    session.add(BlacklistedUser(douyin_id="79373130119"))
    session.commit()
    r = client.post("/api/blacklist",
                    data={"douyin_ids": "79373130119, abc, 79373130119"})
    assert r.status_code == 200
    assert r.json() == {"added": 0, "skipped": 1, "invalid": 1}


def test_delete_ok_then_404(client, session):
    """DELETE：命中返回 204 并删行；未命中返回 404。"""
    from app.models import BlacklistedUser
    row = BlacklistedUser(douyin_id="555000111")
    session.add(row)
    session.commit()
    rid = row.id
    r = client.delete(f"/api/blacklist/{rid}")
    assert r.status_code == 204
    # 直接按 douyin_id 重新查询，避免测试会话 identity map 缓存旧对象
    assert session.query(BlacklistedUser).filter_by(
        douyin_id="555000111").first() is None
    r2 = client.delete(f"/api/blacklist/{rid}")
    assert r2.status_code == 404


def test_post_result_chinese_utf8(client, session):
    """POST 结果含中文备注：返回 JSON 应正常解析、无乱码。"""
    r = client.post("/api/blacklist",
                    data={"douyin_ids": "12345",
                          "remark": "不良广告号"})
    assert r.status_code == 200
    body = r.json()
    assert body == {"added": 1, "skipped": 0, "invalid": 0}
    from app.models import BlacklistedUser
    row = session.query(BlacklistedUser).filter_by(douyin_id="12345").one()
    # 中文经库/响应往返后仍为预期内容（无 mojibake）
    assert row.remark == "不良广告号"


def test_post_json_422(client):
    """以 JSON 而非表单 POST：应返回 422（表单是预期路径）。"""
    r = client.post("/api/blacklist", json={"douyin_ids": "12345"})
    assert r.status_code == 422
