import pandas as pd
from fastapi.testclient import TestClient

from app.main import app
from app.models import AnalysisTask, Comment, Video
from app.web.routes import get_db


def _client(session):
    def override():
        yield session
    app.dependency_overrides[get_db] = override
    return TestClient(app)          # 不用 with，避免触发 lifespan/MySQL


def _xlsx(tmp_path):
    df = pd.DataFrame([{
        "aweme_id": "1001", "title": "标题 #SUV", "desc": "文案",
        "cover_url": "http://x/1.jpg", "nickname": "小明",
        "sec_uid": "sec_1", "comment_id": "9001",
        "content": "落地多少钱", "create_time": 1783783725}])
    path = tmp_path / "t.xlsx"
    df.to_excel(path, index=False)
    return path


def test_import_and_start_analysis(tmp_path, session):
    client = _client(session)
    with open(_xlsx(tmp_path), "rb") as f:
        r = client.post("/api/import", files={"file": ("t.xlsx", f)})
    assert r.status_code == 200
    assert r.json()["videos_new"] == 1
    assert session.query(Video).count() == 1
    assert session.query(Comment).count() == 1

    r = client.post("/api/analysis/start")
    assert r.status_code == 200
    assert r.json()["created"] == 1
    assert session.query(AnalysisTask).count() == 1

    r = client.get("/api/analysis/progress")
    assert r.status_code == 200
    assert r.json()["video_context_analysis"]["pending"] == 1


def test_retry_endpoint_404_on_missing(session):
    client = _client(session)
    assert client.post("/api/tasks/999/retry").status_code == 404


def test_index_page(session):
    client = _client(session)
    r = client.get("/")
    assert r.status_code == 200
    assert "DriveIntent" in r.text
