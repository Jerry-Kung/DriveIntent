from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models import ApiJob, LlmCallLog
from app.web.routes import get_db


def _client(session):
    def override():
        yield session
    app.dependency_overrides[get_db] = override
    return TestClient(app)          # 不用 with，避免触发 lifespan/MySQL


def test_audit_page_renders_stats(session):
    now = datetime.utcnow()
    session.add_all([
        ApiJob(id="j1", job_type="comment_screening", status="success",
               created_at=now - timedelta(minutes=10),
               finished_at=now - timedelta(minutes=5)),
        LlmCallLog(skill_id="comment_lead_screening", model_name="m1",
                   prompt_tokens=123, completion_tokens=45,
                   duration_ms=600, created_at=now - timedelta(minutes=8)),
    ])
    session.commit()
    r = _client(session).get("/audit")
    assert r.status_code == 200
    assert "审计统计" in r.text
    assert "comment_lead_screening" in r.text
    assert "123" in r.text


def test_audit_page_empty_db(session):
    r = _client(session).get("/audit")
    assert r.status_code == 200
    assert "暂无数据" in r.text


def test_audit_range_non_numeric_falls_back(session):
    client = _client(session)
    r = client.get("/audit?range=abc")
    assert r.status_code == 200
    # 回退到 day 默认 7
    assert 'value="7"' in r.text
