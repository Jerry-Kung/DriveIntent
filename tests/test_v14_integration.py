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


def test_audit_params_fallback_and_cap(session):
    client = _client(session)
    # 非法粒度回退 day；超上限截断；非正数回退默认——都不报 4xx
    assert client.get("/audit?granularity=bogus").status_code == 200
    assert client.get("/audit?granularity=hour&range=99999").status_code == 200
    assert client.get("/audit?range=-5").status_code == 200
    # 上限截断体现在回填的 range 输入框值
    r = client.get("/audit?granularity=hour&range=99999")
    assert 'value="168"' in r.text
    r = client.get("/audit?granularity=day&range=99999")
    assert 'value="90"' in r.text


def test_audit_hour_granularity_renders(session):
    now = datetime.utcnow()
    session.add(LlmCallLog(skill_id="user_lead_analysis", model_name="m2",
                           prompt_tokens=10, completion_tokens=5,
                           duration_ms=100,
                           created_at=now - timedelta(minutes=1)))
    session.commit()
    r = _client(session).get("/audit?granularity=hour")
    assert r.status_code == 200
    assert "user_lead_analysis" in r.text


def test_nav_contains_audit_link(session):
    r = _client(session).get("/")
    assert r.status_code == 200
    assert '/audit' in r.text


def test_business_endpoints_unchanged(session):
    client = _client(session)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/leads").status_code == 200
