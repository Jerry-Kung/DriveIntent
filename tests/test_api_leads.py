import re
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


def test_detail_page_shows_v19_v110_fields(session):
    """V1.9/V1.10 精筛新增五字段（黑名单三 + 我方在售车型两）在详情页展示。

    注意这五个键只存在于 api_job.result.results[] 的账号对象里，详情页
    直接渲染该对象，不经 lead_record 汇总表（汇总表列不含它们）。
    """
    acct = _acct("u1", code="high")
    acct.update({"our_model_intent_level": "中",
                 "recommend_our_model": "猛士M817",
                 "is_blacklisted": True, "blacklist_type": "confirmed",
                 "blacklist_reason": "该抖音号已列入系统黑名单"})
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0), [acct])
    client = _client(session)
    html = client.get("/leads/j1/0").text
    for label in ["我方车型意向", "推荐我方车型", "黑名单"]:
        assert label in html
    assert "猛士M817" in html
    assert "确认黑名单" in html          # confirmed → 中文展示
    assert "该抖音号已列入系统黑名单" in html


def test_detail_page_shows_suspect_blacklist_type(session):
    """疑似黑名单（过滤节点判定）类型为中文枚举，原样展示且与 confirmed 区分。"""
    acct = _acct("u1", code="low")
    acct.update({"is_blacklisted": True, "blacklist_type": "营销号",
                 "blacklist_reason": "评论区反复导流至私域"})
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0), [acct])
    client = _client(session)
    html = client.get("/leads/j1/0").text
    assert "营销号" in html
    assert "确认黑名单" not in html
    assert "评论区反复导流至私域" in html


def test_detail_page_legacy_data_no_new_keys(session):
    """V1.9/V1.10 之前的历史数据无这五个键：栏目仍在，值回退 "-"，不报错。"""
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0), [_acct("u1")])
    client = _client(session)
    r = client.get("/leads/j1/0")
    assert r.status_code == 200
    html = r.text
    assert "我方车型意向" in html and "推荐我方车型" in html and "黑名单" in html
    assert "黑名单判定理由" not in html   # 未命中时不出现理由块


def test_detail_page_blacklisted_without_reason(session):
    """命中但理由为空：类型缺失时展示"是"，不出现"理由：None"。"""
    acct = _acct("u1", code="low")
    acct.update({"is_blacklisted": True, "blacklist_type": None,
                 "blacklist_reason": None})
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0), [acct])
    client = _client(session)
    html = client.get("/leads/j1/0").text
    assert "黑名单判定理由" not in html
    assert "None" not in html


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


def test_leads_page_uses_summary_table(session):
    """V1.10.1：列表页读汇总表，等级筛选与分页均走普通列。"""
    from app.models import LeadRecord
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0),
         [_acct("u1", code="high"), _acct("u2", code="low")])
    assert session.query(LeadRecord).count() == 2
    client = _client(session)
    html = client.get("/leads", params={"grade": "H"}).text
    assert "u1" in html
    assert "u2" not in html
    assert "共 1 条" in html


def test_leads_page_paging_matches_total(session):
    """翻页：页数提示与实际分页一致，页间不重不漏。

    列表固定 20 条/页，故造 45 条（3 个作业 × 15 账号）= 3 页。
    """
    base = datetime(2026, 8, 14, 8, 0, 0)
    for i in range(3):
        _job(session, f"j{i}", base + timedelta(minutes=i),
             [_acct(f"u{i}_{k}") for k in range(15)])
    client = _client(session)
    first = client.get("/leads").text
    assert "共 45 条" in first
    assert "第 1/3 页" in first
    seen = []
    for page in (1, 2, 3):
        html = client.get("/leads", params={"page": page}).text
        assert f"第 {page}/3 页" in html
        seen += re.findall(r'class="uid">([^<]+)<', html)
    assert len(seen) == 45
    assert len(set(seen)) == 45          # 页间不重复


def test_api_leads_grade_filter_json(session):
    _job(session, "j1", datetime(2026, 8, 14, 8, 0, 0),
         [_acct("u1", code="high"), _acct("u2", code="low"),
          _acct("u3", code="high")])
    client = _client(session)
    data = client.get("/api/leads", params={"grade": "H"}).json()
    assert data["total"] == 2
    assert [r["account_uid"] for r in data["rows"]] == ["u1", "u3"]


def test_export_csv_reads_summary_table(session):
    """导出走汇总表，仍是全量（不限当页）。"""
    base = datetime(2026, 8, 14, 8, 0, 0)
    for i in range(3):
        _job(session, f"j{i}", base + timedelta(minutes=i), [_acct(f"u{i}")])
    client = _client(session)
    r = client.get("/api/leads/export")
    assert r.status_code == 200
    for i in range(3):
        assert f"u{i}" in r.text
