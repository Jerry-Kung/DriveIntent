import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.api.routes import api_router, get_db
from app.api.worker import ApiJobWorker
from app.llm.mock import MockProvider
from app.llm.gateway import LLMGateway
from app.skills.executor import SkillExecutor
from tests.test_analysis_polish import POLISH_OK_JSON, POLISHED
from tests.test_user_analysis import REVIEW_CONFIRMED_JSON
from tests.test_user_filter import NOT_FILTERED_JSON


@pytest.fixture()
def env(monkeypatch):
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
    return app, Session


@pytest.mark.asyncio
async def test_comment_screening_end_to_end(env):
    app, Session = env
    client = TestClient(app)
    payload = {"comments": [
        {"comment_id": "cm_1", "video_title": "试驾", "video_author": "@王",
         "video_author_fans": 1, "comment_content": "刚提这款车",
         "comment_author": "a", "comment_author_uid": "u1",
         "comment_time": "2026-07-19T14:23:00+08:00", "comment_like_count": 1}]}
    r = client.post("/api/v1/comment-screening", json=payload,
                    headers={"Authorization": "Bearer secret"})
    job_id = r.json()["job_id"]

    provider = MockProvider()
    provider.queue(json.dumps({"brand": "测试"}),
                   json.dumps({"items": [
                       {"index": 0, "is_meaningful": True,
                        "is_suspected_marketing": False,
                        "has_purchase_intent": True, "reason": "真实车主"}]}))
    executor = SkillExecutor(LLMGateway(provider))
    worker = ApiJobWorker(lambda: Session(), executor, LLMGateway(provider))
    await worker.run_once()

    poll = client.get(f"/api/v1/jobs/{job_id}",
                      headers={"Authorization": "Bearer secret"})
    body = poll.json()
    assert body["status"] == "success"
    assert body["result"]["results"][0]["passed"] is True


@pytest.mark.asyncio
async def test_profile_analysis_end_to_end_no_screenshot(env):
    app, Session = env
    client = TestClient(app)
    payload = {"accounts": [
        {"account_uid": "u1", "account_name": "用户",
         "account_homepage_screenshot": "",
         "comment_history": [
             {"video_title": "对比", "comment_content": "在纠结这两款",
              "comment_time": "2026-07-19T14:23:00+08:00",
              "comment_like_count": 5}]}]}
    r = client.post("/api/v1/profile-analysis", json=payload,
                    headers={"Authorization": "Bearer secret"})
    job_id = r.json()["job_id"]

    provider = MockProvider()
    provider.queue(NOT_FILTERED_JSON, json.dumps({
        "lead_grade": "A", "is_valid_lead": True, "lead_summary": "对比中",
        "evidence_comment_ids": ["u1:0"], "confidence": 0.8,
        "profile_tags": ["对比阶段"], "profile_summary": "画像",
        "analysis_text": "分析"}), REVIEW_CONFIRMED_JSON, POLISH_OK_JSON)
    executor = SkillExecutor(LLMGateway(provider))
    worker = ApiJobWorker(lambda: Session(), executor, LLMGateway(provider))
    await worker.run_once()

    body = client.get(f"/api/v1/jobs/{job_id}",
                      headers={"Authorization": "Bearer secret"}).json()
    assert body["status"] == "success"
    assert body["result"]["results"][0]["intent_level_code"] == "medium"
    # 复核+润色真实走完整个节点序列：响应体 analysis 变为润色后文本
    assert body["result"]["results"][0]["analysis"] == POLISHED
