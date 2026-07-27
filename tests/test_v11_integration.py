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

_OUR_MODELS = {
    "version": "1.0", "updated_at": "2026-07-27",
    "models": [{
        "model_id": "fz-x7", "brand": "方舟", "model_name": "方舟X7",
        "aliases": ["X7"], "price_min": 350000, "price_max": 420000,
        "vehicle_category": "越野", "powertrain": "PHEV",
        "use_case": ["越野", "家用"], "key_features": ["四驱"],
        "target_audience": "户外爱好者"}]}


@pytest.fixture()
def env(monkeypatch, tmp_path):
    from app.config import settings
    monkeypatch.setattr(settings, "api_keys", "secret")
    p = tmp_path / "our_models.json"
    p.write_text(json.dumps(_OUR_MODELS, ensure_ascii=False),
                 encoding="utf-8")
    monkeypatch.setattr(settings, "our_models_config_path", str(p))
    monkeypatch.setattr(settings, "intent_downgrade_enabled", True)
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
    return {"comments": [c("cm_1", "落地多少钱"), c("cm_2", "大定已下等提车"),
                         c("cm_3", "加V了解低息方案")]}


@pytest.mark.asyncio
async def test_v11_screening_end_to_end(env):
    app, Session = env
    client = TestClient(app)
    r = client.post("/api/v1/comment-screening", json=_payload(),
                    headers={"Authorization": "Bearer secret"})
    job_id = r.json()["job_id"]

    provider = MockProvider()
    provider.queue(
        json.dumps({"brand": "微光", "model": "微光mini",
                    "price_range_min": 90000, "price_range_max": 110000,
                    "vehicle_category": "微型车",
                    "use_case": ["家用", "通勤"]}),
        json.dumps({"items": [
            {"comment_id": "cm_1", "is_meaningful": True,
             "is_purchase_related": True, "comment_actor": "genuine_user",
             "owner_status": "none", "intent_strength": "high",
             "reason": "询问落地价"},
            {"comment_id": "cm_2", "is_meaningful": True,
             "comment_actor": "genuine_user",
             "owner_status": "ordered_owner", "intent_strength": "low",
             "reason": "已下定"},
            {"comment_id": "cm_3", "is_meaningful": True,
             "comment_actor": "marketing_account", "owner_status": "none",
             "intent_strength": "none", "reason": "引流广告"}]}))
    executor = SkillExecutor(LLMGateway(provider))
    worker = ApiJobWorker(lambda: Session(), executor, LLMGateway(provider))
    await worker.run_once()

    body = client.get(f"/api/v1/jobs/{job_id}",
                      headers={"Authorization": "Bearer secret"}).json()
    assert body["status"] == "success"
    r1, r2, r3 = body["result"]["results"]
    # cm_1：真实用户，10万微型车 vs 38万越野 → high 降两级（价位+品类）
    assert r1["passed"] is True
    assert r1["filter_type"] == "genuine_user"
    assert r1["intent_strength"] == "low"  # high 降两级（价位+品类）
    assert r1["downgrade_applied"] is True
    # cm_2：已下定车主 → 过滤
    assert r2["passed"] is False
    assert r2["filter_type"] == "ordered_owner"
    assert r2["filter_reason"] == "已下定车主评论"
    # cm_3：营销号 → 过滤
    assert r3["passed"] is False
    assert r3["filter_type"] == "marketing_account"
    assert r3["filter_reason"] == "广告/引流类评论"
