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
    return TestClient(app)


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
