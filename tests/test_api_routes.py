import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.api.routes import api_router, get_db


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
    app.include_router(api_router)
    app.dependency_overrides[get_db] = lambda: Session()
    app.state.test_factory = Session
    return TestClient(app)


@pytest.fixture()
def session(client):
    yield client.app.state.test_factory()


def test_health_no_auth(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_missing_auth_401(client):
    r = client.post("/api/v1/comment-screening", json={"comments": []})
    assert r.status_code == 401


def test_submit_returns_job_id(client):
    r = client.post("/api/v1/comment-screening", json={"comments": []},
                    headers={"Authorization": "Bearer secret"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending" and "job_id" in body


def test_get_unknown_job_404(client):
    r = client.get("/api/v1/jobs/nope",
                   headers={"Authorization": "Bearer secret"})
    assert r.status_code == 404


def test_bad_payload_422(client):
    r = client.post("/api/v1/comment-screening",
                    json={"comments": [{"comment_id": "x"}]},
                    headers={"Authorization": "Bearer secret"})
    assert r.status_code == 422


def _write_cat_config(tmp_path):
    """V1.8.3：label 测试自建 tmp 配置，与未跟踪的实盘 config 解耦。"""
    import json
    cfg = {"version": "1.0", "categories": [
        {"code": "A", "label": "东风猛士系列", "rule": "东风猛士系列车型"},
        {"code": "B", "label": "越野车", "rule": "越野车"},
        {"code": "C", "label": "25-30万SUV", "rule": "25-30万元价位的SUV"},
        {"code": "D", "label": "其他", "rule": "其他车型，或无意向车型"}]}
    p = tmp_path / "intent_categories.json"
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_job_result_maps_intent_category_to_label(client, session, monkeypatch,
                                                  tmp_path):
    """对外轮询把 intent_model_category 码值映射为中文，库内仍存码值。"""
    from app.api.jobs import create_job, finish_job, get_job
    from app.config import settings
    monkeypatch.setattr(settings, "intent_categories_config_path",
                        _write_cat_config(tmp_path))
    job = create_job(session, "profile_analysis", {"accounts": []}, total=1)
    # 模拟 worker 落库：result 内存码值
    finish_job(session, job, status="success", error=None,
               result={"results": [{"account_uid": "u1", "has_value": True,
                                    "intent_models": ["坦克300"],
                                    "intent_model_category": "B"}]})
    body = client.get(f"/api/v1/jobs/{job.id}",
                      headers={"Authorization": "Bearer secret"}).json()
    # 对外返回中文正式内容
    assert body["result"]["results"][0]["intent_model_category"] == "越野车"
    # 库内仍是码值 B，供内部统计
    assert get_job(session, job.id).result["results"][0][
        "intent_model_category"] == "B"


def test_job_result_unknown_category_passthrough(client, session, monkeypatch,
                                                 tmp_path):
    """配置外码值原样透传；null 保持 null。"""
    from app.api.jobs import create_job, finish_job
    from app.config import settings
    monkeypatch.setattr(settings, "intent_categories_config_path",
                        _write_cat_config(tmp_path))
    job = create_job(session, "profile_analysis", {"accounts": []}, total=1)
    finish_job(session, job, status="success", error=None,
               result={"results": [
                   {"account_uid": "u2", "intent_model_category": "X"},
                   {"account_uid": "u3", "intent_model_category": None}]})
    body = client.get(f"/api/v1/jobs/{job.id}",
                      headers={"Authorization": "Bearer secret"}).json()
    assert body["result"]["results"][0]["intent_model_category"] == "X"
    assert body["result"]["results"][1]["intent_model_category"] is None
