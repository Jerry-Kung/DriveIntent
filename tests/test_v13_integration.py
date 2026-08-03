import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import api_router, get_db
from app.api.worker import ApiJobWorker
from app.db import Base
from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.skills.executor import SkillExecutor


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


def _payload():
    def c(cid, content):
        return {"comment_id": cid, "video_title": "微光mini测评",
                "video_author": "@测评君", "video_author_fans": 10000,
                "comment_content": content, "comment_author": "a",
                "comment_author_uid": f"u_{cid}",
                "comment_time": "2026-07-27T10:00:00+08:00",
                "comment_like_count": 1}
    return {"comments": [c("cm_1", "落地多少钱"),
                         c("cm_2", "我这台开了2万公里，油耗8个"),
                         c("cm_3", "开了5年了，想置换升级"),
                         c("cm_4", "内饰真好看"),
                         c("cm_5", "加V了解低息方案")]}


@pytest.mark.asyncio
async def test_v13_screening_end_to_end(env):
    app, Session = env
    client = TestClient(app)
    r = client.post("/api/v1/comment-screening", json=_payload(),
                    headers={"Authorization": "Bearer secret"})
    job_id = r.json()["job_id"]

    provider = MockProvider()
    provider.queue(
        json.dumps({"brand": "微光", "model": "微光mini",
                    "vehicle_category": "微型车"}),
        json.dumps({"items": [
            {"comment_id": "cm_1", "is_meaningful": True,
             "comment_actor": "genuine_user", "is_car_owner": False,
             "has_purchase_intent": True, "intent_strength": "high",
             "reason": "询问落地价"},
            {"comment_id": "cm_2", "is_meaningful": True,
             "comment_actor": "genuine_user", "is_car_owner": True,
             "has_purchase_intent": False, "positive_attitude": False,
             "reason": "车主用车讨论，无购车意向"},
            {"comment_id": "cm_3", "is_meaningful": True,
             "comment_actor": "genuine_user", "is_car_owner": True,
             "has_purchase_intent": True, "intent_strength": "medium",
             "reason": "车主表达置换升级意向"},
            {"comment_id": "cm_4", "is_meaningful": True,
             "comment_actor": "genuine_user", "is_car_owner": False,
             "has_purchase_intent": False, "positive_attitude": True,
             "reason": "非车主表达产品兴趣"},
            {"comment_id": "cm_5", "is_meaningful": True,
             "comment_actor": "marketing_account", "is_car_owner": False,
             "has_purchase_intent": False, "reason": "引流广告"}]}))
    executor = SkillExecutor(LLMGateway(provider))
    worker = ApiJobWorker(lambda: Session(), executor, LLMGateway(provider))
    await worker.run_once()

    body = client.get(f"/api/v1/jobs/{job_id}",
                      headers={"Authorization": "Bearer secret"}).json()
    assert body["status"] == "success"
    r1, r2, r3, r4, r5 = body["result"]["results"]
    # cm_1：非车主有意向 → 过筛
    assert (r1["passed"], r1["filter_type"]) == (True, "genuine_user")
    assert (r1["is_car_owner"], r1["has_purchase_intent"]) == (False, True)
    # cm_2：车主无意向纯讨论 → 不过筛
    assert (r2["passed"], r2["filter_type"]) == (False, "no_purchase_intent")
    assert (r2["is_car_owner"], r2["has_purchase_intent"]) == (True, False)
    # cm_3：车主增换购意向 → 必过筛
    assert (r3["passed"], r3["filter_type"]) == (True, "genuine_user")
    # cm_4：非车主积极信号 → 过筛（B级弱线索）
    assert (r4["passed"], r4["filter_type"]) == (True, "genuine_user")
    assert r4["has_purchase_intent"] is False
    # cm_5：营销号 → 过滤；全部条目 filter_reason 恒 null、无内部信号泄漏
    assert (r5["passed"], r5["filter_type"]) == (False, "marketing_account")
    for item in (r1, r2, r3, r4, r5):
        assert item["filter_reason"] is None
        assert "positive_attitude" not in item
        assert "owner_status" not in item
