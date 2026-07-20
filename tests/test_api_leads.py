from fastapi.testclient import TestClient

from app.main import app
from app.models import Lead, PlatformUser
from app.web.routes import get_db
from tests.test_aggregation import _setup


def _client(session):
    def override():
        yield session
    app.dependency_overrides[get_db] = override
    return TestClient(app)


def _mk_lead(session, grade="H", nickname="意向用户", brand="坦克",
            model="坦克300", confidence=0.9):
    u = PlatformUser(platform="douyin", external_id=f"u-{nickname}",
                     nickname=nickname)
    session.add(u); session.flush()
    lead = Lead(user_id=u.id, grade=grade, summary="询问落地价",
                target_brands=[brand], target_models=[model],
                core_needs=["越野"], main_concerns=["价格"],
                evidence=[{"comment_id": "1", "content": "落地多少钱"}],
                confidence=confidence, skill_version="1.0")
    session.add(lead); session.commit()
    return lead


def test_list_and_filter(session):
    _mk_lead(session, "H", "甲")
    _mk_lead(session, "B", "乙")
    client = _client(session)
    assert len(client.get("/api/leads").json()) == 2
    data = client.get("/api/leads", params={"grade": "H"}).json()
    assert len(data) == 1 and data[0]["nickname"] == "甲"


def test_review(session):
    lead = _mk_lead(session)
    client = _client(session)
    r = client.post(f"/api/leads/{lead.id}/review", json={
        "review_status": "valid", "review_tags": ["等级偏高"],
        "review_note": "ok"})
    assert r.status_code == 200
    session.refresh(lead)
    assert lead.review_status == "valid"
    assert lead.review_tags == ["等级偏高"]


def test_export_csv(session):
    _mk_lead(session)
    client = _client(session)
    r = client.get("/api/leads/export")
    assert r.status_code == 200
    assert r.text.lstrip("﻿").startswith("昵称,")
    assert "意向用户" in r.text


def test_pages_render(session):
    lead = _mk_lead(session)
    client = _client(session)
    assert "意向用户" in client.get("/leads").text
    assert "询问落地价" in client.get(f"/leads/{lead.id}").text


def test_brand_model_filter(session):
    _mk_lead(session, "H", "甲", brand="坦克", model="坦克300")
    _mk_lead(session, "B", "乙", brand="哈弗", model="H6")
    client = _client(session)
    data = client.get("/api/leads", params={"brand": "坦克"}).json()
    assert len(data) == 1 and data[0]["nickname"] == "甲"
    data = client.get("/api/leads", params={"model": "H6"}).json()
    assert len(data) == 1 and data[0]["nickname"] == "乙"


def test_sort_order(session):
    _mk_lead(session, "B", "丙", confidence=0.5)
    _mk_lead(session, "H", "甲", confidence=0.9)
    _mk_lead(session, "H", "乙", confidence=0.6)
    client = _client(session)
    data = client.get("/api/leads").json()
    assert [d["nickname"] for d in data] == ["甲", "乙", "丙"]


def test_export_csv_filtered(session):
    _mk_lead(session, "H", "甲")
    _mk_lead(session, "B", "乙")
    client = _client(session)
    r = client.get("/api/leads/export", params={"grade": "H"})
    assert r.status_code == 200
    assert "甲" in r.text
    assert "乙" not in r.text


def test_export_csv_escapes_formula_injection(session):
    _mk_lead(session, "H", "=cmd|'/c calc'!A1")
    client = _client(session)
    r = client.get("/api/leads/export")
    assert r.status_code == 200
    # 危险前缀被转义为文本，不会被 Excel 当公式执行
    assert "'=cmd|'/c calc'!A1" in r.text
    assert "\n=cmd" not in r.text and ",=cmd" not in r.text


def test_lead_detail_shows_evidence(session):
    v, u1, u2, c1, c2 = _setup(session)
    lead = Lead(user_id=u1.id, grade="H", summary="意向摘要",
                target_brands=["坦克"], target_models=["坦克300"],
                evidence=[{"comment_id": str(c1.id), "content": c1.content}],
                confidence=0.9, skill_version="1.0")
    session.add(lead); session.commit()
    client = _client(session)
    html = client.get(f"/leads/{lead.id}").text
    assert c1.content in html
    assert "high" in html
