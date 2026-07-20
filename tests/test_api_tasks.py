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


def test_import_missing_columns_returns_400(tmp_path, session):
    df = pd.DataFrame([{"aweme_id": "1001", "title": "标题A"}])
    path = tmp_path / "bad.xlsx"
    df.to_excel(path, index=False)
    client = _client(session)
    with open(path, "rb") as f:
        r = client.post("/api/import", files={"file": ("bad.xlsx", f)})
    assert r.status_code == 400
    assert "缺少必需列" in r.json()["detail"]


def test_failed_tasks_list_and_retry(session):
    task = AnalysisTask(task_type="video_context_analysis",
                        target_type="video", target_id="1",
                        skill_version="1.0", status="failed",
                        error="模拟失败原因" * 50, attempt_count=3)
    session.add(task); session.commit()
    client = _client(session)

    r = client.get("/api/tasks/failed")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == task.id
    assert data[0]["task_type"] == "video_context_analysis"
    assert data[0]["target_id"] == "1"
    assert data[0]["attempt_count"] == 3
    assert len(data[0]["error"]) <= 200

    r = client.post(f"/api/tasks/{task.id}/retry")
    assert r.status_code == 200
    session.refresh(task)
    assert task.status == "pending"

    assert client.get("/api/tasks/failed").json() == []


def test_index_page(session):
    client = _client(session)
    r = client.get("/")
    assert r.status_code == 200
    assert "DriveIntent" in r.text
