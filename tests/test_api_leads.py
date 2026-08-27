from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models import LlmCallLog
from app.web.routes import get_db
from tests.test_lead_results import _acct, _job


def _client(session):
    def override():
        yield session
    app.dependency_overrides[get_db] = override
    return TestClient(app)


def test_index_redirects(session):
    client = _client(session)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/leads"


def test_leads_page_renders(session):
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0),
         [_acct("u1", code="high")])
    client = _client(session)
    html = client.get("/leads").text
    assert "u1" in html
    assert "线索列表" in html


def test_leads_page_grade_filter(session):
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0),
         [_acct("u1", code="high"), _acct("u2", code="low")])
    client = _client(session)
    html = client.get("/leads", params={"grade": "H"}).text
    assert "u1" in html
    assert "u2" not in html


def test_detail_page_renders(session):
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0),
         [_acct("u1", code="high")],
         payload={"accounts": [{"account_name": "测试昵称",
                                "comment_history": [],
                                "homepage_vision_text": "识图文本"}]})
    client = _client(session)
    html = client.get("/leads/j1/0").text
    assert "u1" in html
    assert "作业信息" in html
    assert "测试昵称" in html


def test_detail_page_shows_entry_point(session):
    """详情页展示销售开场白；历史数据（无键）回退 "-"。"""
    acct = _acct("u1", code="high")
    acct["recommended_entry_point"] = "您关注的坦克300与我们的猛士M817同为硬派越野"
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0), [acct])
    client = _client(session)
    html = client.get("/leads/j1/0").text
    assert "销售开场白" in html
    assert "您关注的坦克300与我们的猛士M817同为硬派越野" in html

    _job(session, "j2", datetime(2026, 8, 14, 9, 0, 0), [_acct("u2")])
    html2 = client.get("/leads/j2/0").text
    assert "销售开场白" in html2  # 无键不报错，栏目仍在


def test_detail_page_shows_llm_calls(session):
    t = datetime(2026, 8, 14, 8, 0, 0)
    _job(session, "j1", t, [_acct("u1")])
    session.add(LlmCallLog(skill_id="user_lead_analysis",
                           skill_version="1.7.0", model_name="m",
                           job_id="j1", account_uid="u1",
                           created_at=t - timedelta(seconds=1)))
    session.commit()
    client = _client(session)
    html = client.get("/leads/j1/0").text
    assert "user_lead_analysis" in html
    assert "1.7.0" in html


def test_detail_page_404(session):
    client = _client(session)
    assert client.get("/leads/nope/0").status_code == 404


def test_api_leads_json(session):
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0),
         [_acct("u1", code="high")])
    client = _client(session)
    data = client.get("/api/leads").json()
    assert data["total"] == 1
    assert data["rows"][0]["account_uid"] == "u1"


def test_export_csv(session):
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0),
         [_acct("u1", code="high")])
    client = _client(session)
    r = client.get("/api/leads/export")
    assert r.status_code == 200
    assert "u1" in r.text


def test_removed_endpoints_gone(session):
    client = _client(session)
    for path in ["/api/import", "/api/analysis/start",
                 "/api/analysis/progress", "/api/tasks/failed",
                 "/api/leads/export/html"]:
        r = client.get(path, follow_redirects=False)
        assert r.status_code in (404, 405), path
