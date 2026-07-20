from fastapi.testclient import TestClient

from app.main import app
from app.models import Lead, PlatformUser
from app.web.routes import get_db


def _client(session):
    def override():
        yield session
    app.dependency_overrides[get_db] = override
    return TestClient(app)


def _mk_lead(session, grade="H", nickname="意向用户"):
    u = PlatformUser(platform="douyin", external_id=f"u-{nickname}",
                     nickname=nickname)
    session.add(u); session.flush()
    lead = Lead(user_id=u.id, grade=grade, summary="询问落地价",
                target_brands=["坦克"], target_models=["坦克300"],
                core_needs=["越野"], main_concerns=["价格"],
                evidence=[{"comment_id": "1", "content": "落地多少钱"}],
                confidence=0.9, skill_version="1.0")
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
